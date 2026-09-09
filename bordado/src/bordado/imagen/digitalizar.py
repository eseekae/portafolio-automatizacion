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
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np

from ..aplique import ParamAplique, instrucciones
from ..aplique import secuencia as secuencia_aplique
from ..geometria import Polilinea, Punto, area_shoelace, longitud
from ..parametros import (
    PERFIL_POR_DEFECTO, PERFILES, ParamGlobales, ParamRecta, ParamRelleno,
    ParamSatin, Perfil,
)
from ..patron import ConstructorPatron
from ..puntadas import (
    ordenar_corridas, puntada_recta, puntada_triple, relleno_tatami,
    satin_de_region,
)
from . import segmentar as seg
from .hilos import Hilo, elegir
from .vectorizar import separar_figuras, simplificar, trazar_anillos

# Por debajo de este grosor no cabe ni un relleno ni una columna satin: la
# aguja no tiene donde entrar y salir sin repicar el mismo agujero.
#
# Pero "no se puede RELLENAR" no es lo mismo que "no se puede BORDAR". Un
# trazo de medio milimetro -el numero de un ano, el contorno fino de un
# escudo, la contra de una letra- se borda como los borda cualquier
# digitalizador profesional: con una CORRIDA de puntadas siguiendo la forma.
# El hilo mide unos 0.4 mm de ancho, asi que una linea de hilo ES el trazo.
#
# Antes estas regiones se descartaban y el detalle chico simplemente
# desaparecia del bordado.
GROSOR_MINIMO_MM = 0.9

# Por debajo de esto ya no es un trazo del dibujo: es el borde difuso que deja
# el antialiasing al reducir la imagen. Coserlo seria bordar ruido.
GROSOR_CORRIDA_MIN_MM = 0.25

# Y tiene que tener LARGO suficiente para que se vea como una linea. El largo
# de una franja delgada es aproximadamente la mitad de su perimetro.
LARGO_CORRIDA_MIN_MM = 2.5

def ordenar_corridas_enlazadas(corridas: list[Polilinea], desde: Punto
                               ) -> tuple[list[Polilinea], Punto]:
    """
    Elige por cual de las corridas empezar segun donde quedo la aguja, sin
    romper el orden de fases.

    Las corridas de una region llegan en el orden correcto (underlay, relleno,
    contorno). Solo se decide si conviene dar vuelta la PRIMERA, que es lo
    unico que se puede tocar sin alterar ese orden.
    """
    if not corridas:
        return corridas, desde
    primera = corridas[0]
    if math.dist(desde, primera[-1]) < math.dist(desde, primera[0]):
        corridas = [primera[::-1]] + corridas[1:]
    return corridas, corridas[-1][-1]


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
    if r.grosor_mm < GROSOR_MINIMO_MM:
        # Demasiado fina para rellenar: se cose como linea o no se cose.
        return "corrida" if es_corrida(r) else "descartar"
    return "relleno"


def es_corrida(r: Region) -> bool:
    """
    Si una region demasiado fina para rellenar se puede coser como linea.

    Pide dos cosas: que sea un trazo del dibujo y no ruido de antialiasing, y
    que tenga largo suficiente para leerse como una linea y no como una mota.
    """
    return (r.grosor_mm >= GROSOR_CORRIDA_MIN_MM
            and r.perimetro_mm / 2.0 >= LARGO_CORRIDA_MIN_MM)


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
            # Una region fina ya no se tira: si da para coserse como linea,
            # sigue viva y `elegir_tecnica` la mandara a "corrida". Solo se
            # descarta lo que no se puede bordar de ninguna forma.
            if r.grosor_mm < GROSOR_MINIMO_MM and not es_corrida(r):
                descartadas += 1
                area_descartada += r.area_mm2
                continue
            if r.area_mm2 < area_min_mm2 and r.grosor_mm >= GROSOR_MINIMO_MM:
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

def decidir(r: Region, densidad_mm: float = 0.40,
            perfil: Perfil | None = None) -> ParamRelleno:
    """
    Elige parametros de relleno segun la forma. Reglas, no magia:

    - Region alargada (elongacion > 1.8): se cose a lo largo de su eje.
      Una hoja o una letra se ven mal con trama a 45 grados fija.
    - Region compacta: 45 grados, el angulo neutro que menos delata la trama.
    - El underlay se escala con el area: una mancha grande necesita base
      cruzada para no encogerse; una chica solo un contorno; una diminuta
      nada, porque el underlay pesaria mas que el relleno.

    El `perfil` mueve los umbrales de una sola vez. Es la palanca de tiempo:
    subir la separacion, alargar la puntada y poner menos underlay son las
    tres cosas que de verdad bajan los minutos de maquina.
    """
    perfil = perfil or PERFILES[PERFIL_POR_DEFECTO]
    angulo = r.angulo if r.elongacion > 1.8 else 45.0
    if r.area_mm2 > perfil.area_underlay_tatami_mm2:
        underlay = "tatami"
    elif r.area_mm2 > perfil.area_underlay_contorno_mm2:
        underlay = "contorno"
    else:
        underlay = "none"
    # En regiones finas la trama larga cruza de lado a lado y se engancha.
    largo = perfil.largo_mm if r.grosor_mm > 3.0 else max(1.8, r.grosor_mm * 0.8)
    return ParamRelleno(densidad_mm=densidad_mm, largo_mm=largo,
                        angulo_grados=angulo, underlay=underlay)


# --------------------------------------------------------------------------
# Etapa 4: orden de colores y de recorrido
# --------------------------------------------------------------------------

def agrupar_por_color(regiones: list[Region]) -> list[list[Region]]:
    """
    Agrupa las regiones por color, de mayor a menor superficie total.

    Lo grande primero hace de fondo y lo pequeno queda encima, que es el orden
    en que se borda a mano. El recorrido DENTRO de cada color no se decide
    aqui: depende de donde quede la aguja al terminar cada region, y eso solo
    se sabe al ir generando las puntadas.
    """
    por_color: dict[int, list[Region]] = {}
    for r in regiones:
        por_color.setdefault(r.color, []).append(r)
    orden = sorted(por_color, key=lambda c: sum(
        r.area_mm2 for r in por_color[c]), reverse=True)
    return [por_color[c] for c in orden]


def mas_cercana(regiones: list[Region], desde: Punto) -> int:
    """
    Indice de la region cuyo borde queda mas cerca de `desde`.

    Se mide contra el CONTORNO, no contra el centro: la aguja llega al borde
    de la region, no a su centro, y en formas alargadas la diferencia entre
    una medida y otra es de centimetros.
    """
    def distancia(r: Region) -> float:
        paso = max(1, len(r.exterior) // 24)
        return min(math.dist(desde, q) for q in r.exterior[::paso])

    return min(range(len(regiones)), key=lambda k: distancia(regiones[k]))


def ordenar(regiones: list[Region]) -> list[Region]:
    """Orden de referencia, sin conocer el recorrido real de la aguja."""
    salida: list[Region] = []
    actual: Punto = (0.0, 0.0)
    for grupo in agrupar_por_color(regiones):
        pendientes = list(grupo)
        while pendientes:
            i = mas_cercana(pendientes, actual)
            r = pendientes.pop(i)
            salida.append(r)
            actual = r.centro
    return salida


# --------------------------------------------------------------------------
# Orquestacion
# --------------------------------------------------------------------------

def regiones_desde_svg(ruta: Path, ancho_mm: float, area_min_mm2: float = 1.0
                       ) -> tuple[list[Region], "np.ndarray", None, int, float]:
    """
    Lee un SVG y devuelve (regiones, colores, None, descartadas, area) listo
    para el resto del pipeline. Sin segmentar, sin rasterizar: los contornos
    vienen del archivo.
    """
    import numpy as np

    from .svg import cargar as cargar_svg
    from .svg import separar as separar_svg

    figuras = separar_svg(cargar_svg(ruta, ancho_mm), area_min_mm2)
    if not figuras:
        raise ValueError(
            "El SVG no tiene ninguna forma con relleno que se pueda bordar. "
            "Revisa que no sean solo trazos, y convierte el texto a curvas "
            "antes de exportar.")

    colores: list[tuple[int, int, int]] = []
    indice: dict[tuple[int, int, int], int] = {}
    regiones: list[Region] = []
    descartadas, area_descartada = 0, 0.0
    for color, exterior, huecos in figuras:
        if color not in indice:
            indice[color] = len(colores)
            colores.append(color)
        r = _describir(indice[color], exterior, huecos)
        # Mismo criterio que en la via de imagen: lo fino se cose como linea,
        # no se tira. Un SVG de un logo trae justamente los detalles chicos
        # (numeros, contornos, la contra de una letra) en formas delgadas.
        if r.grosor_mm < GROSOR_MINIMO_MM:
            if es_corrida(r):
                regiones.append(r)
            else:
                descartadas += 1
                area_descartada += r.area_mm2
        elif r.area_mm2 < area_min_mm2:
            descartadas += 1
            area_descartada += r.area_mm2
        else:
            regiones.append(r)
    return (regiones, np.array(colores, dtype=np.uint8), None,
            descartadas, area_descartada)


def digitalizar(ruta: Path, ancho_mm: float, n_colores: int = 5,
                formato_hilos: str = "jef", g: ParamGlobales | None = None,
                px_por_mm: float = 8.0, densidad_mm: float = 0.40,
                area_min_mm2: float = 1.0, suavizado: int = 3,
                quitar_fondo: bool = True, semilla: int = 0,
                aplique: bool = False,
                p_aplique: ParamAplique | None = None,
                perfil: str = PERFIL_POR_DEFECTO):
    """
    Devuelve (EmbPattern, Digitalizacion, Segmentacion|None).

    Si `ruta` es un SVG se salta la segmentacion por completo: el arte ya es
    vectorial, los contornos exactos estan en el archivo y rasterizarlos para
    volver a trazarlos seria perder precision a cambio de nada.
    """
    perfil_obj = PERFILES.get(perfil, PERFILES[PERFIL_POR_DEFECTO])
    if densidad_mm == 0.40:
        densidad_mm = perfil_obj.densidad_mm     # solo si no se pidio otra
    g = g or ParamGlobales()
    # Menos cortes de hilo: cada uno detiene la maquina alrededor de 1.5 s.
    g = replace(g, salto_max_sin_corte_mm=perfil_obj.salto_max_sin_corte_mm)
    ruta = Path(ruta)

    if ruta.suffix.lower() == ".svg":
        regiones, colores, s, descartadas, area_desc = regiones_desde_svg(
            ruta, ancho_mm, area_min_mm2)
        n_pedidos = len(colores)
    else:
        rgb, fondo = seg.cargar(ruta, ancho_mm, px_por_mm, suavizado)
        if quitar_fondo:
            fondo = seg.detectar_fondo(rgb, fondo)
        s = seg.segmentar(rgb, fondo, n_colores, px_por_mm, semilla)
        regiones, descartadas, area_desc = extraer_regiones(s, area_min_mm2)
        colores = s.colores
        n_pedidos = n_colores

    regiones = ordenar(regiones)
    if regiones:
        xs = [q[0] for r in regiones for q in r.exterior]
        ys = [q[1] for r in regiones for q in r.exterior]
        ancho_total, alto_total = max(xs) - min(xs), max(ys) - min(ys)
    else:
        ancho_total = alto_total = 0.0

    d = Digitalizacion(regiones=regiones, colores=colores,
                       descartadas=descartadas, area_descartada_mm2=area_desc,
                       ancho_mm=ancho_total, alto_mm=alto_total,
                       colores_pedidos=n_pedidos)
    for i in range(len(colores)):
        d.hilos[i] = elegir(colores[i], formato_hilos)

    b = ConstructorPatron(g)
    tecnicas: dict[str, int] = {}
    bloques = 0
    color_previo: str | None = None
    notas: list[str] = []

    # La region siguiente se elige por donde quedo la aguja de verdad, no por
    # el centro de la anterior. Ordenar de antemano obliga a suponer la
    # posicion final, y en formas alargadas esa suposicion se equivoca por
    # centimetros: son saltos largos, y cada salto largo obliga a cortar.
    aguja: Punto = (0.0, 0.0)
    secuencia: list[Region] = []
    for grupo in agrupar_por_color(regiones):
        pendientes = list(grupo)
        while pendientes:
            r = pendientes.pop(mas_cercana(pendientes, aguja))
            secuencia.append(r)
            aguja = r.centro          # provisional; se corrige al generarla
    regiones = secuencia
    d.regiones = regiones

    aguja = (0.0, 0.0)
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

        if tecnica == "descartar":
            # Llego hasta aqui por el camino del SVG, que no filtra antes.
            d.descartadas += 1
            d.area_descartada_mm2 += r.area_mm2
            continue

        if tecnica == "corrida":
            # Se sigue el CONTORNO de la region, no un eje medial calculado.
            # En una franja de medio milimetro los dos bordes distan menos que
            # el ancho del propio hilo, asi que recorrerlos deja exactamente la
            # linea que se busca, sin la fragilidad de estimar un eje.
            #
            # Triple (bean stitch) y no corrida simple: una sola pasada de hilo
            # sobre un trazo fino se ve desvaida, y es lo que se usa en la
            # industria para numeros y contornos chicos.
            pr = ParamRecta(largo_mm=min(2.0, max(1.0, r.grosor_mm * 3)))
            for anillo in [r.exterior, *r.huecos]:
                corridas += puntada_triple(anillo, pr, cerrada=True)

        if tecnica == "satin":
            corridas = satin_de_region(
                r.exterior, ParamSatin(densidad_mm=max(0.30, densidad_mm - 0.05)),
                ancho_max_mm=SATIN_ANCHO_MAX_MM) or []
            if not corridas:
                tecnica = "relleno"      # no dio para satin: se rellena

        if tecnica == "relleno":
            p = decidir(r, densidad_mm, perfil_obj)
            corridas = relleno_tatami(r.exterior, p, huecos=r.huecos)
            # Contorno de cierre: define el borde y tapa el dentado que deja el
            # relleno al terminar cada fila. Solo donde hay superficie que lo
            # justifique; en una mancha chica seria mas contorno que relleno.
            if r.area_mm2 > 15.0:
                corridas += puntada_recta(r.exterior, ParamRecta(largo_mm=1.8),
                                          cerrada=True)

        if corridas:
            # Se enlaza con lo anterior: la primera corrida de esta region es
            # la que quede mas cerca de donde solto la aguja.
            corridas, aguja = ordenar_corridas_enlazadas(corridas, aguja)
            if h.hex != color_previo:
                bloques += 1
                color_previo = h.hex
            b.agregar(f"c{r.color}", h.hex, corridas, catalogo=catalogo)
            tecnicas[tecnica] = tecnicas.get(tecnica, 0) + 1

    d.paradas = bloques
    d.notas = "\n\n".join(notas)
    d.tecnicas = tecnicas
    return b.construir(), d, s
