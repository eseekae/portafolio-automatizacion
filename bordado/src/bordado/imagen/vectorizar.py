"""
Trazado de contornos: mascara de pixeles -> anillos poligonales.

No se usa OpenCV a proposito. Agregaria ~60 MB al ejecutable para resolver
un problema que, sobre mascaras binarias, tiene una solucion exacta y corta.

IDEA
    El borde de un conjunto de pixeles es un poligono RECTILINEO: cada pixel
    del frente aporta una arista unitaria por cada vecino que sea fondo. Si
    esas aristas se emiten siempre con el interior al mismo lado y luego se
    encadenan por sus extremos, salen anillos cerrados sin ambiguedad.

    Esto da contornos exactos (no aproximados) y, de regalo, separa contornos
    exteriores de huecos por el signo del area.

AMBIGUEDAD DIAGONAL
    Cuando dos pixeles del frente se tocan solo por una esquina, el vertice
    comun tiene dos aristas de salida. Se elige siempre la que gira mas a la
    derecha, lo que equivale a tratar el frente como 4-conexo: dos manchas
    que se tocan en diagonal quedan como dos regiones distintas. Es lo que
    conviene al bordar, porque un puente de un pixel no se puede coser.
"""

from __future__ import annotations

import numpy as np

from ..geometria import Polilinea, area_shoelace

# Aristas que aporta un pixel del frente segun que vecino sea fondo.
# Coordenadas de imagen: x a la derecha, y hacia ABAJO. El orden de cada
# arista mantiene el interior siempre del mismo lado.
_ARISTAS = {
    "arriba": ((1, 0), (0, 0)),
    "izquierda": ((0, 0), (0, 1)),
    "abajo": ((0, 1), (1, 1)),
    "derecha": ((1, 1), (1, 0)),
}


def trazar_anillos(mascara: np.ndarray) -> list[Polilinea]:
    """
    Devuelve todos los anillos cerrados del borde de `mascara` (bool 2D),
    en coordenadas de pixel (esquinas, no centros).

    El signo del area distingue contorno exterior de hueco; la clasificacion
    la hace `separar_figuras`.
    """
    m = np.asarray(mascara, dtype=bool)
    if not m.any():
        return []
    # Marco de fondo: garantiza que ninguna region toque el borde del arreglo
    # y que todo contorno quede cerrado.
    m = np.pad(m, 1, constant_values=False)

    vecinos = {
        "arriba": np.roll(m, 1, axis=0),
        "abajo": np.roll(m, -1, axis=0),
        "izquierda": np.roll(m, 1, axis=1),
        "derecha": np.roll(m, -1, axis=1),
    }

    # salidas[vertice] -> lista de vertices alcanzables por una arista
    salidas: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for lado, (d_ini, d_fin) in _ARISTAS.items():
        borde = m & ~vecinos[lado]
        for fila, col in np.argwhere(borde):
            ini = (int(col) + d_ini[0], int(fila) + d_ini[1])
            fin = (int(col) + d_fin[0], int(fila) + d_fin[1])
            salidas.setdefault(ini, []).append(fin)

    anillos: list[Polilinea] = []
    for arranque in list(salidas):
        while salidas.get(arranque):
            anillo = _seguir(salidas, arranque)
            if len(anillo) >= 4:
                # Se descuenta el marco agregado al principio.
                anillos.append([(x - 1.0, y - 1.0) for x, y in anillo])
    return anillos


def _seguir(salidas: dict, arranque: tuple[int, int]) -> list[tuple[int, int]]:
    """Camina las aristas consumiendolas hasta volver al punto de partida."""
    anillo = [arranque]
    actual = arranque
    direccion = None
    while True:
        candidatos = salidas.get(actual)
        if not candidatos:
            return anillo
        siguiente = _elegir(candidatos, actual, direccion)
        candidatos.remove(siguiente)
        if not candidatos:
            salidas.pop(actual, None)
        direccion = (siguiente[0] - actual[0], siguiente[1] - actual[1])
        actual = siguiente
        if actual == arranque:
            return anillo
        anillo.append(actual)


def _elegir(candidatos: list, actual: tuple, direccion) -> tuple:
    """
    Con varias aristas de salida (toque diagonal), se toma la que gira mas a
    la derecha. Eso separa las manchas que solo comparten una esquina.
    """
    if len(candidatos) == 1 or direccion is None:
        return candidatos[0]
    dx, dy = direccion

    def giro(destino):
        vx, vy = destino[0] - actual[0], destino[1] - actual[1]
        cruz = dx * vy - dy * vx          # <0 derecha, 0 recto, >0 izquierda
        punto = dx * vx + dy * vy         # <0 es retroceder: lo peor
        return (cruz, -punto)

    return min(candidatos, key=giro)


# --------------------------------------------------------------------------
# Clasificacion y simplificacion
# --------------------------------------------------------------------------

def separar_figuras(anillos: list[Polilinea],
                    area_min: float = 0.0) -> list[tuple[Polilinea, list[Polilinea]]]:
    """
    Agrupa cada contorno exterior con los huecos que lo contienen.

    Devuelve [(exterior, [huecos...]), ...]. Los anillos con area menor a
    `area_min` se descartan: en una imagen real son ruido de compresion, y
    una mancha de 1 mm2 no se puede bordar.
    """
    exteriores: list[Polilinea] = []
    huecos: list[Polilinea] = []
    for anillo in anillos:
        a = area_shoelace(anillo)
        if abs(a) < area_min:
            continue
        # En coordenadas de imagen (Y hacia abajo) el exterior sale negativo.
        (exteriores if a < 0 else huecos).append(anillo)

    figuras: list[tuple[Polilinea, list[Polilinea]]] = []
    # De mayor a menor: un hueco se asigna al exterior mas pequeno que lo
    # contenga, que es su verdadero dueno cuando hay figuras anidadas.
    orden = sorted(range(len(exteriores)),
                   key=lambda i: abs(area_shoelace(exteriores[i])))
    asignados: dict[int, list[Polilinea]] = {i: [] for i in orden}
    for h in huecos:
        px, py = h[0]
        for i in orden:
            if _dentro(exteriores[i], px, py):
                asignados[i].append(h)
                break
    for i, ext in enumerate(exteriores):
        figuras.append((ext, asignados[i]))
    figuras.sort(key=lambda f: abs(area_shoelace(f[0])), reverse=True)
    return figuras


def _dentro(anillo: Polilinea, x: float, y: float) -> bool:
    """Punto en poligono por conteo de cruces (ray casting)."""
    dentro = False
    n = len(anillo)
    for i in range(n):
        x1, y1 = anillo[i]
        x2, y2 = anillo[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xc = x1 + (y - y1) / (y2 - y1) * (x2 - x1)
            if x < xc:
                dentro = not dentro
    return dentro


def simplificar(anillo: Polilinea, tolerancia: float) -> Polilinea:
    """
    Ramer-Douglas-Peucker sobre un anillo cerrado.

    Un contorno rectilineo de pixeles tiene un vertice por pixel de borde:
    miles de puntos en escalera. Sin simplificar, cada escalon se convierte
    en una puntada y el bordado sale con el borde dentado. La tolerancia se
    expresa en las mismas unidades del anillo.
    """
    if len(anillo) < 4:
        return anillo
    # Se parte el anillo en dos cadenas por los dos puntos mas separados, para
    # que RDP (que trabaja sobre cadenas abiertas) no colapse el cierre.
    i = max(range(len(anillo)),
            key=lambda k: (anillo[k][0] - anillo[0][0]) ** 2
            + (anillo[k][1] - anillo[0][1]) ** 2)
    a = _rdp(anillo[:i + 1], tolerancia)
    b = _rdp(anillo[i:] + [anillo[0]], tolerancia)
    salida = a[:-1] + b[:-1]
    return salida if len(salida) >= 3 else anillo


def _rdp(puntos: Polilinea, tol: float) -> Polilinea:
    if len(puntos) < 3:
        return list(puntos)
    x0, y0 = puntos[0]
    x1, y1 = puntos[-1]
    dx, dy = x1 - x0, y1 - y0
    norma = (dx * dx + dy * dy) ** 0.5
    peor, indice = -1.0, 0
    for k in range(1, len(puntos) - 1):
        px, py = puntos[k]
        if norma == 0:
            d = ((px - x0) ** 2 + (py - y0) ** 2) ** 0.5
        else:
            d = abs(dy * px - dx * py + x1 * y0 - y1 * x0) / norma
        if d > peor:
            peor, indice = d, k
    if peor <= tol:
        return [puntos[0], puntos[-1]]
    return _rdp(puntos[:indice + 1], tol)[:-1] + _rdp(puntos[indice:], tol)
