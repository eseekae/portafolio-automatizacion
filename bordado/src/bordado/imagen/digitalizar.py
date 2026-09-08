"""
Auto-digitalizacion: imagen -> matriz de bordado.

Encadena las etapas y decide, para cada region, COMO coserla. Esa decision
es el 80% de la calidad final y es donde los digitalizadores automaticos
comerciales se quedan cortos.

    imagen
      -> segmentar   : k-means en Lab            (segmentar.py)
      -> vectorizar  : mascara -> anillos + RDP  (vectorizar.py)
      -> decidir     : tipo de puntada y angulo  (aqui)
      -> ordenar     : colores y recorrido       (aqui)
      -> hilos       : color -> carrete real     (hilos.py)
      -> patron      : Builder -> EmbPattern     (patron.py)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..aplique import ParamAplique, instrucciones
from ..aplique import secuencia as secuencia_aplique
from ..geometria import Polilinea, Punto, area_shoelace, longitud
from ..parametros import ParamGlobales, ParamRecta, ParamRelleno, ParamSatin
from ..patron import ConstructorPatron
from ..puntadas import puntada_recta, relleno_tatami, satin_de_region
from . import segmentar as seg
from .hilos import Hilo, elegir
from .vectorizar import separar_figuras, simplificar, trazar_anillos

# Por debajo de este grosor no hay puntada que quepa: la region se descarta
# en vez de generar basura que rompe agujas.
GROSOR_MINIMO_MM = 0.9

# Una franja mas ancha que esto deja el hilo flojo y se engancha: se rellena.
SATIN_ANCHO_MAX_MM = 6.0
# Y una region tiene que ser claramente alargada para que el satin la siga.
SATIN_ELONGACION_MIN = 2.5


@dataclass
class Region:
    """Una mancha de un color, ya en milimetros y lista para decidir."""
    color: int
    exterior: Polilinea
    huecos: list[Polilinea]
    area_mm2: float
    perimetro_mm: float
    angulo: float
    elongacion: float
    centro: Punto

    @property
    def grosor_mm(self) -> float:
        """
        Ancho tipico de la region: 2*area/perimetro.

        Es el radio hidraulico, y para una franja larga de ancho w da
        exactamente w. Sirve para distinguir "mancha gorda" de "linea fina"
        sin calcular el eje medial, que es caro y fragil.
        """
        return 2.0 * self.area_mm2 / self.perimetro_mm if self.perimetro_mm else 0.0


# Un retazo mas chico que esto es imposible de recortar a mano con prolijidad.
APLIQUE_AREA_MINIMA_MM2 = 300.0
# Y solo se propone si ahorra de verdad; si no, es complicarle la vida al
# bordador para nada.
APLIQUE_AHORRO_MINIMO = 0.30


def puntadas_estimadas(r: Region, densidad_mm: float,
                       p: ParamAplique | None = None) -> tuple[int, int]:
    """
    Estima el costo en puntadas de rellenar la region contra aplicarla.

    Relleno: N ~ area / (densidad * largo), mas el contorno de cierre.
    Aplique: no depende del area sino del PERIMETRO, porque solo se cosen los
    bordes. Son tres recorridos: posicion, fijacion y la columna satin de
    cobertura, que es la cara y lleva dos penetraciones por paso.
    """
    p = p or ParamAplique()
    perimetro = r.perimetro_mm or 1.0
    relleno = int(r.area_mm2 / (densidad_mm * 3.5) + perimetro / 1.8)
    aplique = int(perimetro / p.largo_posicion_mm
                  + perimetro / 2.0
                  + 2 * perimetro / p.densidad_cobertura_mm)
    return relleno, aplique


def elegir_tecnica(r: Region, densidad_mm: float = 0.40,
                   aplique: bool = False,
                   p_aplique: ParamAplique | None = None) -> str:
    """
    Decide COMO se cose cada region. Es donde se gana o se pierde la calidad.

    - "aplique" cuando de verdad sale mas barato que rellenar. El criterio NO
      es el area: es comparar los dos costos. Una mancha compacta y gorda se
      ahorra miles de puntadas; un anillo delgado tiene tanto borde que la
      cobertura satin cuesta MAS que el relleno que evita, y proponerlo seria
      hacerle recortar tela al bordador para terminar con mas hilo.
    - "satin" para franjas: el trazo de una letra, una hoja, una voluta. El
      satin las sigue y luce como bordado de verdad; el tatami en una franja
      angosta se ve como una trama pegada encima.
    - "relleno" para todo lo demas.
    """
    if aplique and r.area_mm2 >= APLIQUE_AREA_MINIMA_MM2:
        coste_relleno, coste_aplique = puntadas_estimadas(r, densidad_mm, p_aplique)
        if coste_aplique <= coste_relleno * (1.0 - APLIQUE_AHORRO_MINIMO):
            return "aplique"
    if (r.elongacion > SATIN_ELONGACION_MIN
            and GROSOR_MINIMO_MM <= r.grosor_mm <= SATIN_ANCHO_MAX_MM):
        return "satin"
    return "relleno"


@dataclass
class Digitalizacion:
    regiones: list[Region] = field(default_factory=list)
    hilos: dict[int, Hilo] = field(default_factory=dict)
    colores: np.ndarray | None = None
    descartadas: int = 0
    area_descartada_mm2: float = 0.0
    ancho_mm: float = 0.0
    alto_mm: float = 0.0
    colores_pedidos: int = 0
    paradas: int = 0
    notas: str = ""
    tecnicas: dict[str, int] = field(default_factory=dict)

    @property
    def hilos_usados(self) -> dict[int, Hilo]:
        """
        Solo los hilos que realmente se cosen.

        Un grupo de k-means puede quedarse con los pixeles del halo de
        antialias entre dos colores: existe, pero todas sus regiones son
        demasiado finas y se descartan. Anunciarlo como un carrete a comprar
        seria mentira.
        """
        usados = {r.color for r in self.regiones}
        return {i: h for i, h in sorted(self.hilos.items()) if i in usados}

    def resumen(self) -> str:
        usados = self.hilos_usados
        lineas = [f"Regiones cosidas: {len(self.regiones)}",
                  f"Descartadas por finas o diminutas: {self.descartadas}"
                  f" ({self.area_descartada_mm2:.1f} mm2)",
                  f"Tamano: {self.ancho_mm:.1f} x {self.alto_mm:.1f} mm"]
        if self.colores_pedidos and len(usados) < self.colores_pedidos:
            lineas.append(
                f"Colores: {len(usados)} efectivos de {self.colores_pedidos} "
                "pedidos (el resto quedo en bordes demasiado finos)")
        if self.tecnicas:
            lineas.append("Tecnicas: " + ", ".join(
                f"{n} {t}" for t, n in sorted(self.tecnicas.items())))
        lineas.append("Hilos a usar, en orden de bordado:")
        for orden, (i, h) in enumerate(usados.items(), start=1):
            n = sum(1 for r in self.regiones if r.color == i)
            area = sum(r.area_mm2 for r in self.regiones if r.color == i)
            aviso = "" if h.delta_e < 12 else "  (color aproximado)"
            lineas.append(f"  {orden}. {h.hex}  {h.nombre:<18} "
                          f"{h.marca} n.{h.catalogo:<5} "
                          f"{n:>3} region(es) {area:>7.1f} mm2{aviso}")
        return "\n".join(lineas)


# --------------------------------------------------------------------------
# Etapa 1-2: imagen -> regiones en milimetros
# --------------------------------------------------------------------------

def extraer_regiones(s: seg.Segmentacion, area_min_mm2: float = 1.0,
                     tolerancia_px: float = 0.7) -> tuple[list[Region], int, float]:
    """Traza y simplifica los contornos de cada color, ya convertidos a mm."""
    alto_px, ancho_px = s.etiquetas.shape
    ppmm = s.px_por_mm
    area_min_px = area_min_mm2 * ppmm * ppmm

    def a_mm(anillo: Polilinea) -> Polilinea:
        # La imagen tiene Y hacia abajo y el bordado hacia arriba: se invierte
        # aqui, una sola vez, y se centra el diseno en el origen.
        return [((x - ancho_px / 2) / ppmm, (alto_px / 2 - y) / ppmm)
                for x, y in anillo]

    regiones: list[Region] = []
    descartadas, area_descartada = 0, 0.0

    for color in range(s.n_colores):
        mascara = s.mascara(color)
        if not mascara.any():
            continue
        figuras = separar_figuras(trazar_anillos(mascara), area_min=area_min_px)
        for exterior_px, huecos_px in figuras:
            exterior = a_mm(simplificar(exterior_px, tolerancia_px))
            huecos = [a_mm(simplificar(h, tolerancia_px)) for h in huecos_px
                      if abs(area_shoelace(h)) >= area_min_px]
            if len(exterior) < 3:
                continue
            r = _describir(color, exterior, huecos)
            if r.grosor_mm < GROSOR_MINIMO_MM or r.area_mm2 < area_min_mm2:
                descartadas += 1
                area_descartada += r.area_mm2
                continue
            regiones.append(r)
    return regiones, descartadas, area_descartada


def _describir(color: int, exterior: Polilinea, huecos: list[Polilinea]) -> Region:
    """Calcula las medidas de la region y su eje principal."""
    area = abs(area_shoelace(exterior)) - sum(abs(area_shoelace(h)) for h in huecos)
    perimetro = longitud(exterior, cerrada=True) + sum(
        longitud(h, cerrada=True) for h in huecos)

    # Eje principal por analisis de componentes principales: la direccion en
    # que la region se estira. Rellenar a lo largo de ese eje sigue la forma
    # y evita el aspecto de trama pegada encima del dibujo.
    pts = np.asarray(exterior, dtype=float)
    centro = pts.mean(axis=0)
    cov = np.cov((pts - centro).T)
    valores, vectores = np.linalg.eigh(cov)
    principal = vectores[:, -1]
    angulo = math.degrees(math.atan2(principal[1], principal[0])) % 180.0
    elongacion = math.sqrt(max(valores[-1], 1e-12) / max(valores[0], 1e-12))

    return Region(color=color, exterior=exterior, huecos=huecos,
                  area_mm2=max(area, 0.0), perimetro_mm=perimetro,
                  angulo=angulo, elongacion=elongacion,
                  centro=(float(centro[0]), float(centro[1])))


# --------------------------------------------------------------------------
# Etapa 3: decidir como coser cada region
# --------------------------------------------------------------------------

def decidir(r: Region, densidad_mm: float = 0.40) -> ParamRelleno:
    """
    Elige parametros de relleno segun la forma. Reglas, no magia:

    - Region alargada (elongacion > 1.8): se cose a lo largo de su eje.
      Una hoja o una letra se ven mal con trama a 45 grados fija.
    - Region compacta: 45 grados, el angulo neutro que menos delata la trama.
    - El underlay se escala con el area: una mancha grande necesita base
      cruzada para no encogerse; una chica solo un contorno; una diminuta
      nada, porque el underlay pesaria mas que el relleno.
    """
    angulo = r.angulo if r.elongacion > 1.8 else 45.0
    if r.area_mm2 > 60.0:
        underlay = "tatami"
    elif r.area_mm2 > 12.0:
        underlay = "contorno"
    else:
        underlay = "none"
    # En regiones finas la trama larga cruza de lado a lado y se engancha.
    largo = 3.5 if r.grosor_mm > 3.0 else max(1.8, r.grosor_mm * 0.8)
    return ParamRelleno(densidad_mm=densidad_mm, largo_mm=largo,
                        angulo_grados=angulo, underlay=underlay)


# --------------------------------------------------------------------------
# Etapa 4: orden de colores y de recorrido
# --------------------------------------------------------------------------

def ordenar(regiones: list[Region]) -> list[Region]:
    """
    Ordena por color y, dentro de cada color, por cercania.

    Los colores van de mayor a menor superficie total: lo grande primero hace
    de fondo y lo pequeno queda encima, que es el orden en que se borda a
    mano. Dentro de un color se encadenan las regiones por vecino mas cercano
    (heuristica de viajante) para acortar los saltos de aguja.
    """
    por_color: dict[int, list[Region]] = {}
    for r in regiones:
        por_color.setdefault(r.color, []).append(r)

    orden_colores = sorted(por_color, key=lambda c: sum(
        r.area_mm2 for r in por_color[c]), reverse=True)

    salida: list[Region] = []
    actual: Punto = (0.0, 0.0)
    for color in orden_colores:
        pendientes = list(por_color[color])
        while pendientes:
            i = min(range(len(pendientes)),
                    key=lambda k: math.dist(actual, pendientes[k].centro))
            r = pendientes.pop(i)
            salida.append(r)
            actual = r.centro
    return salida


# --------------------------------------------------------------------------
# Orquestacion
# --------------------------------------------------------------------------

def digitalizar(ruta: Path, ancho_mm: float, n_colores: int = 5,
                formato_hilos: str = "jef", g: ParamGlobales | None = None,
                px_por_mm: float = 8.0, densidad_mm: float = 0.40,
                area_min_mm2: float = 1.0, suavizado: int = 3,
                quitar_fondo: bool = True, semilla: int = 0,
                aplique: bool = False,
                p_aplique: ParamAplique | None = None):
    """Devuelve (EmbPattern, Digitalizacion, Segmentacion)."""
    g = g or ParamGlobales()
    rgb, fondo = seg.cargar(ruta, ancho_mm, px_por_mm, suavizado)
    if quitar_fondo:
        fondo = seg.detectar_fondo(rgb, fondo)
    s = seg.segmentar(rgb, fondo, n_colores, px_por_mm, semilla)

    regiones, descartadas, area_desc = extraer_regiones(s, area_min_mm2)
    regiones = ordenar(regiones)

    alto_px, ancho_px = s.etiquetas.shape
    d = Digitalizacion(regiones=regiones, colores=s.colores,
                       descartadas=descartadas, area_descartada_mm2=area_desc,
                       ancho_mm=ancho_px / px_por_mm, alto_mm=alto_px / px_por_mm,
                       colores_pedidos=n_colores)
    for i in range(s.n_colores):
        d.hilos[i] = elegir(s.colores[i], formato_hilos)

    b = ConstructorPatron(g)
    tecnicas: dict[str, int] = {}
    bloques = 0
    color_previo: str | None = None
    notas: list[str] = []

    for r in regiones:
        h = d.hilos[r.color]
        catalogo = f"{h.marca} {h.catalogo} {h.nombre}".strip()
        tecnica = elegir_tecnica(r, densidad_mm, aplique, p_aplique)
        corridas: list[Polilinea] = []

        if tecnica == "aplique":
            pasos = secuencia_aplique(r.exterior, r.huecos, h.hex,
                                      p_aplique or ParamAplique())
            for paso in pasos:
                if not paso.corridas:
                    continue
                b.agregar(f"aplique{r.color}-{paso.orden}", paso.color,
                          paso.corridas, catalogo=paso.nombre,
                          forzar_bloque=True)
                bloques += 1
                color_previo = paso.color
            if not notas:
                notas.append(instrucciones(pasos))
            tecnicas["aplique"] = tecnicas.get("aplique", 0) + 1
            continue

        if tecnica == "satin":
            corridas = satin_de_region(
                r.exterior, ParamSatin(densidad_mm=max(0.30, densidad_mm - 0.05)),
                ancho_max_mm=SATIN_ANCHO_MAX_MM) or []
            if not corridas:
                tecnica = "relleno"      # no dio para satin: se rellena

        if tecnica == "relleno":
            p = decidir(r, densidad_mm)
            corridas = relleno_tatami(r.exterior, p, huecos=r.huecos)
            # Contorno de cierre: define el borde y tapa el dentado que deja el
            # relleno al terminar cada fila. Solo donde hay superficie que lo
            # justifique; en una mancha chica seria mas contorno que relleno.
            if r.area_mm2 > 15.0:
                corridas += puntada_recta(r.exterior, ParamRecta(largo_mm=1.8),
                                          cerrada=True)

        if corridas:
            if h.hex != color_previo:
                bloques += 1
                color_previo = h.hex
            b.agregar(f"c{r.color}", h.hex, corridas, catalogo=catalogo)
            tecnicas[tecnica] = tecnicas.get(tecnica, 0) + 1

    d.paradas = bloques
    d.notas = "\n\n".join(notas)
    d.tecnicas = tecnicas
    return b.construir(), d, s
