"""
Analisis de una matriz: donde se van las puntadas, el hilo y el tiempo.

POR QUE HACE FALTA
    "Se demora 25 minutos" no se arregla adivinando. Un archivo de bordado no
    dice como fue digitalizado, pero lo que la maquina va a hacer si esta todo
    ahi: cuantas perforaciones, cuanto hilo, cuantos cortes y cuanta superficie
    cubre. De eso salen las palancas concretas para bajar el tiempo.

SOBRE EL TIEMPO
    La cuenta ingenua "puntadas / velocidad" se queda corta y por eso la
    estimacion nunca cuadra con el reloj. Cada corte de hilo detiene la
    maquina alrededor de un segundo y medio, y cada cambio de color son
    decenas de segundos de la persona reenhebrando. En un diseno con muchos
    cortes eso son minutos, no ruido.

LO QUE NO SE MIDE
    La separacion entre pasadas no se puede recuperar de forma fiable desde
    las puntadas: se probaron varios estimadores y todos fallaban por mas del
    doble segun el desfase de filas del relleno. Se informa en cambio la
    densidad en puntadas por cm2, que es exacta y es la medida que usa el
    oficio.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pyembroidery as pe

UNIDADES_POR_MM = 10.0
CELDA_MM = 0.5          # rejilla para estimar la superficie cubierta

# Bandas de referencia en puntadas por cm2, calibradas midiendo rellenos de
# separacion conocida sobre un disco de area conocida:
#     0.25 mm (demasiado denso) -> 151      0.45 mm (abierto, valido) ->  77
#     0.35 mm (denso, valido)   -> 101      0.55 mm (se ve la tela)   ->  57
#     0.40 mm (estandar)        ->  91
DENSIDAD_ALTA = 125.0   # por encima: mas hilo del necesario, tela acartonada
DENSIDAD_BAJA = 60.0    # por debajo: se empieza a ver la tela


@dataclass
class Analisis:
    puntadas: int = 0
    saltos: int = 0
    recorrido_mm: float = 0.0
    cortes: int = 0
    colores: int = 0
    ancho_mm: float = 0.0
    alto_mm: float = 0.0
    hilo_m: float = 0.0
    area_cubierta_cm2: float = 0.0
    largo_medio_mm: float = 0.0
    largo_max_mm: float = 0.0
    cortas: int = 0
    largas: int = 0
    minutos_puntadas: float = 0.0
    minutos_cortes: float = 0.0
    minutos_colores: float = 0.0
    sugerencias: list[str] = field(default_factory=list)

    @property
    def minutos(self) -> float:
        return self.minutos_puntadas + self.minutos_cortes + self.minutos_colores

    @property
    def densidad_punt_cm2(self) -> float:
        return self.puntadas / self.area_cubierta_cm2 if self.area_cubierta_cm2 else 0.0

    def texto(self) -> str:
        lineas = [
            "=" * 62, " ANALISIS DE LA MATRIZ", "=" * 62,
            f"  {'Puntadas':.<34} {self.puntadas:,}",
            f"  {'Tamano (mm)':.<34} {self.ancho_mm:.1f} x {self.alto_mm:.1f}",
            f"  {'Superficie cubierta (cm2)':.<34} {self.area_cubierta_cm2:.1f}",
            f"  {'Densidad (puntadas/cm2)':.<34} {self.densidad_punt_cm2:.0f}",
            f"  {'Hilo (m)':.<34} {self.hilo_m:.1f}",
            f"  {'Largo medio de puntada (mm)':.<34} {self.largo_medio_mm:.2f}",
            f"  {'Cortes de hilo':.<34} {self.cortes:,}",
            f"  {'Saltos (aguja en vacio)':.<34} {self.saltos:,}"
            f"  ·  {self.recorrido_mm / 10:.0f} cm de recorrido",
            f"  {'Cambios de color':.<34} {self.colores}",
            "-" * 62,
            " TIEMPO ESTIMADO",
            f"  {'Cosiendo':.<34} {self.minutos_puntadas:>5.1f} min",
            f"  {'Cortes de hilo':.<34} {self.minutos_cortes:>5.1f} min",
            f"  {'Cambios de color':.<34} {self.minutos_colores:>5.1f} min",
            f"  {'TOTAL':.<34} {self.minutos:>5.1f} min",
            "-" * 62,
        ]
        if self.sugerencias:
            lineas.append(" COMO BAJARLO")
            for s in self.sugerencias:
                lineas.append(f"  - {s}")
        else:
            lineas.append("  El diseno ya esta bien aprovechado.")
        lineas.append("=" * 62)
        return "\n".join(lineas)


def analizar(patron: pe.EmbPattern, velocidad_ppm: int = 700,
             segundos_por_corte: float = 1.5,
             segundos_por_color: float = 25.0) -> Analisis:
    """Mide un patron ya codificado y propone donde recortar tiempo."""
    a = Analisis()
    norm = patron.get_normalized_pattern()
    a.puntadas = norm.count_stitch_commands(pe.STITCH)
    a.colores = norm.count_color_changes()
    if not a.puntadas:
        return a

    x0, y0, x1, y1 = norm.bounds()
    a.ancho_mm = (x1 - x0) / UNIDADES_POR_MM
    a.alto_mm = (y1 - y0) / UNIDADES_POR_MM

    segmentos: list[tuple[tuple[float, float], tuple[float, float]]] = []
    largos: list[float] = []
    # Dos posiciones distintas: la ultima PUNTADA (para medir largos, que se
    # interrumpe al cortar) y la ultima posicion FISICA de la aguja (para medir
    # recorrido, que no se interrumpe: el cabezal se mueve igual).
    previo = None
    aguja = None
    for x, y, cmd in norm.stitches:
        base = cmd & pe.COMMAND_MASK
        if base == pe.STITCH:
            if previo is not None:
                d = math.hypot(x - previo[0], y - previo[1]) / UNIDADES_POR_MM
                largos.append(d)
                segmentos.append((previo, (x, y)))
            elif aguja is not None:
                a.recorrido_mm += math.hypot(x - aguja[0],
                                             y - aguja[1]) / UNIDADES_POR_MM
            previo = aguja = (x, y)
        elif base == pe.JUMP:
            a.saltos += 1
            if aguja is not None:
                a.recorrido_mm += math.hypot(x - aguja[0],
                                             y - aguja[1]) / UNIDADES_POR_MM
            # Tras el salto la aguja baja en el destino: esa es la primera
            # perforacion del tramo, no una puntada de largo cero.
            previo = None
            aguja = (x, y)
        else:
            if base == pe.TRIM:
                a.cortes += 1
            previo = None

    if largos:
        a.hilo_m = sum(largos) / 1000.0
        a.largo_medio_mm = sum(largos) / len(largos)
        a.largo_max_mm = max(largos)
        a.cortas = sum(1 for d in largos if d < 0.6)
        a.largas = sum(1 for d in largos if d > 12.1)

    a.area_cubierta_cm2 = _superficie_cubierta(segmentos)

    a.minutos_puntadas = a.puntadas / max(velocidad_ppm, 1)
    a.minutos_cortes = a.cortes * segundos_por_corte / 60.0
    a.minutos_colores = a.colores * segundos_por_color / 60.0
    a.sugerencias = _sugerir(a, velocidad_ppm)
    return a


def _superficie_cubierta(segmentos: list, celda_mm: float = CELDA_MM) -> float:
    """
    Superficie que el hilo llega a tapar, en cm2.

    Se marcan en una rejilla las celdas por las que pasa el hilo. Es una
    estimacion, no una medida exacta: sirve para comparar la densidad contra
    las bandas de referencia, no para calcular tela.
    """
    if not segmentos:
        return 0.0
    u = celda_mm * UNIDADES_POR_MM
    ocupadas: set[tuple[int, int]] = set()
    for (ax, ay), (bx, by) in segmentos:
        pasos = int(math.hypot(bx - ax, by - ay) / u) + 1
        for k in range(pasos + 1):
            t = k / pasos
            ocupadas.add((int((ax + (bx - ax) * t) // u),
                          int((ay + (by - ay) * t) // u)))
    return len(ocupadas) * celda_mm * celda_mm / 100.0


def _sugerir(a: Analisis, velocidad_ppm: int) -> list[str]:
    """Palancas concretas, con el ahorro en puntadas y minutos."""
    salida: list[str] = []
    densidad = a.densidad_punt_cm2

    def ahorro(fraccion: float) -> str:
        n = int(a.puntadas * fraccion)
        return f"{n:,} puntadas y ~{n / max(velocidad_ppm, 1):.1f} min"

    if densidad > DENSIDAD_ALTA:
        salida.append(
            f"La densidad ({densidad:.0f} punt/cm2) esta por encima de lo "
            f"habitual ({DENSIDAD_ALTA:.0f}). Re-digitalizando el original con "
            f"separacion 0.45 en vez de 0.40 ahorras del orden de {ahorro(0.09)}.")
    elif densidad < DENSIDAD_BAJA:
        salida.append(
            f"La densidad ({densidad:.0f} punt/cm2) es baja: puede que se vea "
            "la tela entre pasadas. Aqui no hay tiempo que recortar.")

    # El umbral es bajo a proposito: un diseno con muchas zonas finas tiene
    # media baja de forma legitima, porque ahi la puntada NO puede alargarse.
    if a.largo_medio_mm < 2.5 and a.puntadas > 2000:
        salida.append(
            f"El largo medio de puntada es {a.largo_medio_mm:.2f} mm, corto. "
            "En areas grandes se puede subir a 3.5-4.0 mm sin que se note: "
            f"eso ronda {ahorro(0.10)}.")

    if a.recorrido_mm > 20 * math.sqrt(max(a.area_cubierta_cm2, 1)) * 10:
        salida.append(
            f"La aguja recorre {a.recorrido_mm / 10:.0f} cm en vacio para un "
            f"diseno de {a.area_cubierta_cm2:.0f} cm2. Es mucho ir y venir: "
            "el diseno se cose salteado en vez de por zonas.")

    # Un corte cada 300 puntadas ya es mucho picoteo; por debajo es normal.
    if a.cortes > a.puntadas / 300 and a.minutos_cortes > 0.5:
        salida.append(
            f"{a.cortes:,} cortes de hilo suman ~{a.minutos_cortes:.1f} min, "
            f"un {100 * a.minutos_cortes / max(a.minutos, 1e-9):.0f}% del "
            "total. Son muchos para el tamano: el diseno esta partido en "
            "demasiados trozos sueltos.")

    if a.colores >= 8:
        salida.append(
            f"{a.colores} cambios de color suman ~{a.minutos_colores:.1f} min "
            "de reenhebrado, ademas de la molestia.")

    if a.area_cubierta_cm2 > 25 and densidad > DENSIDAD_BAJA:
        salida.append(
            f"Son {a.area_cubierta_cm2:.0f} cm2 de relleno. Si el diseno tiene "
            "manchas grandes de un color, en aplique se cosen solo los bordes: "
            "ahi el ahorro es del 60-70%, no del 10%.")

    if not salida:
        return []
    salida.append(
        "Nada de esto se puede aplicar sobre el archivo ya bordado: no guarda "
        "las regiones, solo las perforaciones. Hay que volver al original "
        "(imagen o SVG) y re-digitalizarlo con `matriz digitalizar "
        "--calidad rapida`.")
    return salida
