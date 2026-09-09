"""
Utilidades geometricas puras (mm). No conoce nada de formatos de bordado.

Mantener esta capa "tonta" es lo que permite testearla sin maquina de bordar
y reutilizarla si manana cambias pyembroidery por otro backend.
"""

from __future__ import annotations

import math
from typing import Iterable

import numpy as np

Punto = tuple[float, float]
Polilinea = list[Punto]


# --------------------------------------------------------------------------
# Metricas basicas
# --------------------------------------------------------------------------

def bbox(puntos: Iterable[Punto]) -> tuple[float, float, float, float]:
    """Caja contenedora -> (xmin, ymin, xmax, ymax)."""
    xs = [p[0] for p in puntos]
    ys = [p[1] for p in puntos]
    return min(xs), min(ys), max(xs), max(ys)


def area_shoelace(poligono: Polilinea) -> float:
    """
    Area con signo (formula del zapatero / shoelace).
    Signo positivo = orientacion antihoraria. Usamos el valor absoluto para
    estimar cantidad de puntadas de un relleno.
    """
    n = len(poligono)
    s = 0.0
    for i in range(n):
        x1, y1 = poligono[i]
        x2, y2 = poligono[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return s / 2.0


def longitud(polilinea: Polilinea, cerrada: bool = False) -> float:
    """Largo total recorrido de una polilinea."""
    pts = polilinea + [polilinea[0]] if cerrada else polilinea
    return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


# --------------------------------------------------------------------------
# Transformaciones
# --------------------------------------------------------------------------

def rotar(puntos: Polilinea, grados: float, centro: Punto = (0.0, 0.0)) -> Polilinea:
    """Rotacion rigida alrededor de `centro`."""
    a = math.radians(grados)
    ca, sa = math.cos(a), math.sin(a)
    cx, cy = centro
    return [
        (cx + (x - cx) * ca - (y - cy) * sa,
         cy + (x - cx) * sa + (y - cy) * ca)
        for x, y in puntos
    ]


def trasladar(puntos: Polilinea, dx: float, dy: float) -> Polilinea:
    return [(x + dx, y + dy) for x, y in puntos]


def centroide(poligono: Polilinea) -> Punto:
    xs = [p[0] for p in poligono]
    ys = [p[1] for p in poligono]
    return sum(xs) / len(xs), sum(ys) / len(ys)


# --------------------------------------------------------------------------
# Remuestreo: convertir geometria continua en puntos de penetracion de aguja
# --------------------------------------------------------------------------

def remuestrear(polilinea: Polilinea, paso_mm: float,
                cerrada: bool = False) -> Polilinea:
    """
    Devuelve puntos equiespaciados cada `paso_mm` a lo largo de la polilinea.

    Este es el corazon de cualquier digitalizador: la maquina no dibuja curvas,
    solo perfora puntos y tensa hilo recto entre ellos. Todo se reduce a
    elegir DONDE perforar.
    """
    pts = list(polilinea)
    if cerrada and pts[0] != pts[-1]:
        pts.append(pts[0])
    if len(pts) < 2:
        return pts

    salida: Polilinea = [pts[0]]
    resto = paso_mm
    for i in range(len(pts) - 1):
        p0, p1 = pts[i], pts[i + 1]
        seg = math.dist(p0, p1)
        if seg == 0:
            continue
        ux, uy = (p1[0] - p0[0]) / seg, (p1[1] - p0[1]) / seg
        avance = resto
        while avance <= seg:
            salida.append((p0[0] + ux * avance, p0[1] + uy * avance))
            avance += paso_mm
        resto = avance - seg
    # El ultimo punto real siempre se cose, para que la forma cierre. Pero si
    # el paso no cabe un numero entero de veces, agregarlo dejaria una astilla
    # de decimas de milimetro: por debajo de medio paso se REEMPLAZA el ultimo
    # punto en vez de anadir otro.
    final = pts[-1]
    if math.dist(salida[-1], final) > 1e-6:
        if len(salida) > 1 and math.dist(salida[-1], final) < paso_mm * 0.5:
            salida[-1] = final
        else:
            salida.append(final)
    return salida


def desplazar_trazo(trazo: Polilinea, dist_mm: float) -> Polilinea:
    """
    Offset de una polilinea ABIERTA: la corre `dist_mm` a un lado.

    Sirve para convertir el trazo de un SVG (una linea con grosor) en los dos
    rieles de una columna satin: uno a +ancho/2 y otro a -ancho/2.

    A diferencia de `desplazar_contorno`, los extremos no tienen vecino por un
    lado, asi que ahi se usa la normal de la unica arista que hay.

    Misma limitacion que su hermana: es un offset por normales promediadas.
    Con los desplazamientos de los que se trata aqui -medio milimetro, el
    grosor de un contorno- no alcanza a auto-intersectarse ni en una esquina
    aguda. Con offsets grandes si podria.
    """
    n = len(trazo)
    if n < 2:
        return list(trazo)

    def normal(a: Punto, b: Punto) -> Punto:
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy) or 1.0
        return (-dy / L, dx / L)          # a la izquierda del avance

    salida: Polilinea = []
    for i in range(n):
        if i == 0:
            nx, ny = normal(trazo[0], trazo[1])
        elif i == n - 1:
            nx, ny = normal(trazo[-2], trazo[-1])
        else:
            ax, ay = normal(trazo[i - 1], trazo[i])
            bx, by = normal(trazo[i], trazo[i + 1])
            nx, ny = ax + bx, ay + by
            L = math.hypot(nx, ny)
            if L < 1e-9:                  # giro de 180 grados
                nx, ny = ax, ay
            else:
                # Se alarga para que el ancho del offset se mantenga en la
                # esquina y no se estreche por el coseno del angulo.
                escala = min(4.0, 1.0 / max(L / 2.0, 0.25))
                nx, ny = nx / L * escala, ny / L * escala
        salida.append((trazo[i][0] + nx * dist_mm, trazo[i][1] + ny * dist_mm))
    return salida


def desplazar_contorno(poligono: Polilinea, dist_mm: float) -> Polilinea:
    """
    Offset aproximado de un poligono cerrado por normales promediadas.

    LIMITACION CONOCIDA: es un offset "ingenuo". Funciona bien en formas
    convexas o suaves (que es el 90% de una matriz comercial) y puede
    auto-intersectarse en concavidades agudas con offsets grandes.
    Para produccion seria, reemplazar por Shapely (`poly.buffer(-d)`).
    Se deja explicito para no vender humo.
    """
    n = len(poligono)
    salida: Polilinea = []
    for i in range(n):
        prev = poligono[(i - 1) % n]
        cur = poligono[i]
        nxt = poligono[(i + 1) % n]

        # Normal exterior de cada arista adyacente (asume orden antihorario).
        def normal(a: Punto, b: Punto) -> Punto:
            dx, dy = b[0] - a[0], b[1] - a[1]
            L = math.hypot(dx, dy) or 1.0
            return (dy / L, -dx / L)

        n1, n2 = normal(prev, cur), normal(cur, nxt)
        nx, ny = n1[0] + n2[0], n1[1] + n2[1]
        L = math.hypot(nx, ny) or 1.0
        salida.append((cur[0] + nx / L * dist_mm, cur[1] + ny / L * dist_mm))
    return salida


# --------------------------------------------------------------------------
# Scanline: base del relleno tatami
# --------------------------------------------------------------------------

def cruces_scanline(poligono: Polilinea, y: float) -> list[float]:
    """
    Coordenadas X donde la recta horizontal `y` corta el poligono.

    Regla par-impar (even-odd): ordenados, los cruces se toman de a pares
    (entra / sale). Es el algoritmo clasico de relleno de poligonos.
    """
    return cruces_scanline_anillos([poligono], y)


def cruces_scanline_anillos(anillos: list[Polilinea], y: float) -> list[float]:
    """
    Igual que `cruces_scanline`, pero sobre varios anillos a la vez.

    Es lo que permite rellenar figuras CON HUECOS (una dona, la contra de una
    letra "o"): la regla par-impar sale gratis. Un rayo que entra al contorno
    exterior y luego entra al hueco acumula dos cruces, asi que el tramo
    dentro del hueco queda fuera de los pares y no se cose.
    """
    a = _aristas(anillos)
    if a is None:
        return []
    x1, y1, x2, y2 = a
    # Intervalo semiabierto [min, max) para no contar dos veces los vertices.
    corta = (np.minimum(y1, y2) <= y) & (y < np.maximum(y1, y2))
    if not corta.any():
        return []
    yy1 = y1[corta]
    t = (y - yy1) / (y2[corta] - yy1)
    return sorted((x1[corta] + t * (x2[corta] - x1[corta])).tolist())


# Las aristas de un contorno se recalculan una vez por FILA del relleno, y un
# diseno tiene miles de filas. Construirlas en Python cada vez era el trabajo
# mas caro de todo el programa; se guardan y se reutilizan.
_CACHE_ARISTAS: dict[int, tuple] = {}


def _aristas(anillos: list[Polilinea]):
    """Arrays (x1, y1, x2, y2) con todas las aristas, sin las horizontales."""
    clave = id(anillos)
    guardado = _CACHE_ARISTAS.get(clave)
    if guardado is not None and guardado[0] is anillos:
        return guardado[1]

    trozos = []
    for anillo in anillos:
        if len(anillo) < 2:
            continue
        p = np.asarray(anillo, dtype=float)
        q = np.roll(p, -1, axis=0)
        vivo = p[:, 1] != q[:, 1]          # las horizontales no aportan cruce
        if vivo.any():
            trozos.append((p[vivo], q[vivo]))
    if not trozos:
        salida = None
    else:
        pa = np.concatenate([t[0] for t in trozos])
        qa = np.concatenate([t[1] for t in trozos])
        salida = (pa[:, 0], pa[:, 1], qa[:, 0], qa[:, 1])

    if len(_CACHE_ARISTAS) > 64:           # no crecer sin limite
        _CACHE_ARISTAS.clear()
    _CACHE_ARISTAS[clave] = (anillos, salida)
    return salida


# --------------------------------------------------------------------------
# Primitivas de forma (utiles para armar disenos de prueba)
# --------------------------------------------------------------------------

def circulo(centro: Punto, radio_mm: float, segmentos: int = 96) -> Polilinea:
    cx, cy = centro
    return [
        (cx + radio_mm * math.cos(2 * math.pi * i / segmentos),
         cy + radio_mm * math.sin(2 * math.pi * i / segmentos))
        for i in range(segmentos)
    ]


def rectangulo_redondeado(x: float, y: float, w: float, h: float,
                          r: float, segmentos: int = 16) -> Polilinea:
    """Rectangulo con esquinas redondeadas, en orden antihorario."""
    r = min(r, w / 2, h / 2)
    pts: Polilinea = []
    esquinas = [
        (x + w - r, y + r, -90.0),   # inferior derecha
        (x + w - r, y + h - r, 0.0),  # superior derecha
        (x + r, y + h - r, 90.0),     # superior izquierda
        (x + r, y + r, 180.0),        # inferior izquierda
    ]
    for cx, cy, a0 in esquinas:
        for i in range(segmentos + 1):
            a = math.radians(a0 + 90.0 * i / segmentos)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts
