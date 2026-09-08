"""
Generadores de puntada (patron de diseno: STRATEGY).

Cada generador recibe geometria en mm + sus parametros, y devuelve
`list[Polilinea]`: una lista de "corridas" continuas de puntadas.
Una corrida = secuencia de perforaciones sin levantar la aguja.
Entre corridas puede haber salto (JUMP) o corte (TRIM); eso lo decide
la capa superior (`patron.py`), no el generador.

Contrato unico -> los generadores son intercambiables y testeables solos.
"""

from __future__ import annotations

import math

from .geometria import (
    Polilinea, Punto, centroide, cruces_scanline_anillos, desplazar_contorno,
    longitud, remuestrear, rotar,
)
from .parametros import ParamRecta, ParamRelleno, ParamSatin

# Largo maximo que los formatos DST/PES codifican en una puntada. Por encima,
# la maquina la parte sola y el hilo queda flotando.
CRUCE_MAX_MM = 10.0


# --------------------------------------------------------------------------
# 1. Puntada corrida (running stitch)
# --------------------------------------------------------------------------

def puntada_recta(trazo: Polilinea, p: ParamRecta,
                  cerrada: bool = False) -> list[Polilinea]:
    """Contornos finos, detalles, tallos, y underlay de eje."""
    return [remuestrear(trazo, p.largo_mm, cerrada=cerrada)]


def puntada_triple(trazo: Polilinea, p: ParamRecta,
                   cerrada: bool = False) -> list[Polilinea]:
    """
    Bean stitch / triple: ida-vuelta-ida sobre el mismo camino.
    Triplica el grosor visual sin cambiar de hilo. Muy usada en line art.
    """
    base = remuestrear(trazo, p.largo_mm, cerrada=cerrada)
    return [base + base[::-1] + base]


# --------------------------------------------------------------------------
# 2. Columna satin
# --------------------------------------------------------------------------

def columna_satin(riel_a: Polilinea, riel_b: Polilinea,
                  p: ParamSatin) -> list[Polilinea]:
    """
    Zigzag denso entre dos rieles.

    Pasos:
      1. Se calcula cuantos zigzags caben:  n = L_promedio / densidad
      2. Se remuestrean AMBOS rieles a n puntos (asi quedan sincronizados
         aunque tengan largos distintos: es lo que hace que el satin siga
         curvas sin abrirse).
      3. Pull compensation: se separan los rieles `compensacion_mm` hacia
         afuera. El hilo, al tensarse, encoge la columna a lo ancho; si no
         compensas, aparece la tela entre el borde y el relleno.
    """
    L = (longitud(riel_a) + longitud(riel_b)) / 2.0
    n = max(2, int(L / p.densidad_mm))

    a = _remuestrear_a_n(riel_a, n)
    b = _remuestrear_a_n(riel_b, n)

    corridas: list[Polilinea] = []

    # --- Underlay: estabiliza la tela antes de poner el satin encima ---
    if p.underlay == "center":
        eje = [((a[i][0] + b[i][0]) / 2, (a[i][1] + b[i][1]) / 2) for i in range(n)]
        corridas.append(remuestrear(eje, 2.0))
    elif p.underlay == "zigzag":
        # Zigzag de baja densidad (~4x mas abierto que el satin final).
        paso = max(1, int(p.densidad_mm * 4 / p.densidad_mm))
        corridas.append([a[i] if i % 2 == 0 else b[i] for i in range(0, n, max(1, paso * 4))])

    # --- Satin propiamente tal, con compensacion ---
    zig: Polilinea = []
    for i in range(n):
        ax, ay = a[i]
        bx, by = b[i]
        dx, dy = bx - ax, by - ay
        d = math.hypot(dx, dy) or 1.0
        ux, uy = dx / d, dy / d
        c = p.compensacion_mm
        pa = (ax - ux * c, ay - uy * c)
        pb = (bx + ux * c, by + uy * c)
        # Secuencia correcta: a0, b0, a1, b1, ...
        # Cada puntada CRUZA la columna (largo = ancho), y el avance entre
        # penetraciones del mismo riel es exactamente `densidad_mm`.
        # (Alternar el orden por fila genera puntadas de largo = densidad,
        #  o sea < 0.5 mm: rompe agujas. Es el error clasico del satin.)
        zig.extend([pa, pb])
    corridas.append(zig)
    return corridas


def satin_desde_eje(eje: Polilinea, ancho_mm: float,
                    p: ParamSatin) -> list[Polilinea]:
    """Construye los dos rieles desplazando un eje +-ancho/2 por la normal."""
    a, b = [], []
    n = len(eje)
    for i in range(n):
        p0 = eje[max(0, i - 1)]
        p1 = eje[min(n - 1, i + 1)]
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        d = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / d, dx / d          # normal unitaria
        h = ancho_mm / 2.0
        a.append((eje[i][0] + nx * h, eje[i][1] + ny * h))
        b.append((eje[i][0] - nx * h, eje[i][1] - ny * h))
    return columna_satin(a, b, p)


def _remuestrear_a_n(linea: Polilinea, n: int) -> Polilinea:
    """Remuestrea a exactamente n puntos distribuidos por longitud de arco."""
    if len(linea) < 2:
        return linea * n
    acum = [0.0]
    for i in range(len(linea) - 1):
        acum.append(acum[-1] + math.dist(linea[i], linea[i + 1]))
    total = acum[-1] or 1.0
    salida: Polilinea = []
    j = 0
    for k in range(n):
        objetivo = total * k / (n - 1)
        while j < len(acum) - 2 and acum[j + 1] < objetivo:
            j += 1
        seg = (acum[j + 1] - acum[j]) or 1.0
        t = (objetivo - acum[j]) / seg
        x = linea[j][0] + t * (linea[j + 1][0] - linea[j][0])
        y = linea[j][1] + t * (linea[j + 1][1] - linea[j][1])
        salida.append((x, y))
    return salida


# --------------------------------------------------------------------------
# 3. Relleno tatami
# --------------------------------------------------------------------------

def relleno_tatami(poligono: Polilinea, p: ParamRelleno,
                   huecos: list[Polilinea] | None = None) -> list[Polilinea]:
    """
    Relleno por barrido (scanline) en serpentina.

    `huecos` son anillos interiores que NO se cosen: la contra de una letra
    "o", el centro de una dona. Se resuelven con la regla par-impar del
    scanline, sin logica adicional.

    Se rota el poligono -angulo, se rellena con lineas HORIZONTALES (mucho
    mas simple y estable numericamente), y se rota de vuelta.

    El `desfase_mm` corre el inicio de las perforaciones fila a fila. Sin el,
    todos los puntos de penetracion quedan alineados y se forma una linea
    visible que parte el bordado: el "efecto cremallera" (zipper effect).
    """
    corridas: list[Polilinea] = []
    cen = centroide(poligono)
    huecos = huecos or []
    anillos = [poligono, *huecos]

    # --- Underlay ---
    if p.underlay == "contorno":
        corridas.append(remuestrear(desplazar_contorno(poligono, -0.8), 2.0, cerrada=True))
    elif p.underlay == "tatami":
        corridas.append(remuestrear(desplazar_contorno(poligono, -0.8), 2.5, cerrada=True))
        base = ParamRelleno(
            densidad_mm=p.densidad_underlay_mm,
            largo_mm=4.0,
            angulo_grados=p.angulo_grados + 90.0,  # cruzado al relleno final
            desfase_mm=0.0,
            underlay="none",
        )
        # El underlay se encoge hacia adentro; los huecos se agrandan, que es
        # el mismo desplazamiento pero con el signo invertido.
        corridas.extend(_barrido(
            [desplazar_contorno(poligono, -0.5)]
            + [desplazar_contorno(h, 0.5) for h in huecos], base, cen))

    corridas.extend(_barrido(anillos, p, cen))
    return corridas


def _barrido(anillos: list[Polilinea], p: ParamRelleno,
             centro: Punto) -> list[Polilinea]:
    """
    Motor del tatami: descomposicion en celdas (boustrophedon) + serpentina.

    El barrido ingenuo cose fila por fila y corta el hilo cada vez que una
    fila viene partida. En un anillo, TODAS las filas vienen partidas por el
    hueco: 91 corridas y 91 cortes de hilo, cuando bastan 2.

    La descomposicion correcta agrupa los tramos en CELDAS: dos tramos de
    filas consecutivas pertenecen a la misma celda si se solapan en X. Una
    celda es una franja continua que se puede recorrer en serpentina de una
    sola pasada. Un anillo se descompone en 2 celdas (el lado izquierdo y el
    derecho); una figura con tres lobulos, en 3.

    Es el mismo algoritmo que se usa para planificar la cobertura de un
    terreno con un robot: recorrer todo sin levantar la herramienta.
    """
    rot = [rotar(a, -p.angulo_grados, centro) for a in anillos]
    ys = [q[1] for a in rot for q in a]
    if not ys:
        return []

    # --- Barrido: tramos rellenables por fila ---------------------------
    filas: list[tuple[float, list[tuple[float, float]]]] = []
    y = min(ys) + p.densidad_mm / 2.0
    y_fin = max(ys)
    while y <= y_fin:
        xs = cruces_scanline_anillos(rot, y)
        tramos = [(xs[i], xs[i + 1]) for i in range(0, len(xs) - 1, 2)
                  if xs[i + 1] - xs[i] >= p.largo_mm * 0.4]
        if tramos:
            filas.append((y, tramos))
        y += p.densidad_mm

    # --- Agrupamiento en celdas conectadas ------------------------------
    celdas: list[list[tuple[float, float, float]]] = []
    activas: list[list[tuple[float, float, float]]] = []
    for y, tramos in filas:
        siguientes: list[list[tuple[float, float, float]]] = []
        for x0, x1 in tramos:
            elegida = None
            for celda in activas:
                if celda in siguientes:
                    continue          # una celda solo continua en un tramo
                _, cx0, cx1 = celda[-1]
                if min(x1, cx1) > max(x0, cx0):   # se solapan en X
                    elegida = celda
                    break
            if elegida is None:
                elegida = []
                celdas.append(elegida)
            elegida.append((y, x0, x1))
            siguientes.append(elegida)
        activas = siguientes

    # --- Serpentina dentro de cada celda --------------------------------
    # Al pasar de una fila a la siguiente, la serpentina cruza la diferencia
    # de ancho entre ambas. Donde la figura se ensancha de golpe (la punta de
    # una estrella) ese cruce puede superar el largo maximo de puntada que la
    # maquina codifica: 12.1 mm. Ahi se corta la corrida en vez de dejar un
    # hilo largo que se engancha.
    corridas: list[Polilinea] = []
    for celda in celdas:
        if len(celda) < 2:
            continue      # una sola fila: no alcanza para coser nada util
        corrida: Polilinea = []
        for fila, (y, x0, x1) in enumerate(celda):
            ini, fin = (x0, x1) if fila % 2 == 0 else (x1, x0)
            if corrida and math.dist(corrida[-1], (ini, y)) > CRUCE_MAX_MM:
                if len(corrida) >= 2:
                    corridas.append(rotar(corrida, p.angulo_grados, centro))
                corrida = []
            corrida.extend(_puntos_de_fila(ini, fin, y, fila, p))
        if len(corrida) >= 2:
            corridas.append(rotar(corrida, p.angulo_grados, centro))
    return corridas


def _puntos_de_fila(x_ini: float, x_fin: float, y: float, fila: int,
                    p: ParamRelleno) -> Polilinea:
    """Divide un tramo en puntadas, con el desfase de fila aplicado."""
    largo = abs(x_fin - x_ini)
    signo = 1.0 if x_fin >= x_ini else -1.0
    # Desfase de fila: rompe la alineacion de las perforaciones y evita la
    # linea visible que parte el bordado ("efecto cremallera").
    off = (fila * p.desfase_mm) % p.largo_mm if p.largo_mm else 0.0
    puntos: Polilinea = [(x_ini, y)]
    d = p.largo_mm - off if off else p.largo_mm
    while d < largo:
        puntos.append((x_ini + signo * d, y))
        d += p.largo_mm
    if len(puntos) > 1 and abs(largo - (d - p.largo_mm)) < p.largo_mm * 0.4:
        puntos[-1] = (x_fin, y)      # evita una astilla de decimas de mm
    else:
        puntos.append((x_fin, y))
    return puntos
