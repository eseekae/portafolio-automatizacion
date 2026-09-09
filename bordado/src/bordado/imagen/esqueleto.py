"""
Descomposicion de una figura en sus TRAZOS, para bordar detalle chico.

EL PROBLEMA QUE RESUELVE
    Un numero de 3 mm de alto tiene trazos de medio milimetro de ancho. Si se
    cose recorriendo su contorno, hay que muestrear ese contorno cada 0.7 mm
    -la puntada mas corta que admite la maquina- y un digito de 2 mm de ancho
    se convierte en un garabato de doce puntos. Rellenarlo con trama tampoco
    sirve: los giros de fin de fila caen a 0.35 mm y el filtro de puntadas
    cortas los elimina.

    Se probaron las dos y las dos fallan. Estan documentadas aqui para que
    nadie las vuelva a intentar creyendo que son el camino facil.

LA SOLUCION, QUE ES LA QUE USA LA INDUSTRIA
    Una COLUMNA SATIN. Dos perforaciones seguidas caen en lados OPUESTOS del
    trazo: la puntada mide el ANCHO del trazo -0.6 mm, legal- mientras que el
    avance a lo largo del trazo es de apenas 0.35 mm. Es decir, la columna
    satin DESACOPLA el largo de la puntada de la resolucion del dibujo, y por
    eso se pueden bordar letras mas finas que la puntada minima.

    Para armar la columna hacen falta los dos bordes del trazo. Y para
    encontrarlos hace falta saber por donde pasa el trazo: su EJE MEDIAL.

COMO SE OBTIENE EL EJE
    1. Se rasteriza la region a una rejilla fina.
    2. Se adelgaza la mancha hasta dejarla de un pixel de ancho
       (Zhang-Suen), lo que da el esqueleto.
    3. Se mide, en cada punto del esqueleto, la distancia al borde mas
       cercano: ese es el semiancho del trazo ahi.
    4. El esqueleto se corta en RAMAS por sus bifurcaciones. Cada rama es un
       trazo de la letra: el palo del "1", cada lobulo del "8".

    Sin scipy ni skimage: el proyecto se distribuye como un ejecutable y cada
    dependencia son decenas de megabytes. Son unas cien lineas de numpy.
"""

from __future__ import annotations

import math

import numpy as np

from ..geometria import Polilinea, Punto, cruces_scanline_anillos

# Resolucion de la rejilla. Con 24 px/mm un trazo de 0.5 mm son 12 pixeles:
# suficiente para que el adelgazado encuentre el centro sin ambiguedad.
PX_POR_MM = 24.0

# Una rama mas corta que esto no es un trazo de la figura: es una espina que
# deja el adelgazado en una esquina.
RAMA_MINIMA_MM = 0.6

# Tope de pixeles por region. Sin el, una figura grande cuesta segundos.
PIXELES_MAX = 400_000


def rasterizar(exterior: Polilinea, huecos: list[Polilinea],
               px_por_mm: float = PX_POR_MM
               ) -> tuple[np.ndarray, float, float, float]:
    """
    Pinta la region en una rejilla booleana.

    Devuelve (mascara, x0, y0, px_por_mm) para poder volver a milimetros.
    Se usa la misma regla par-impar que el relleno, asi que los huecos -la
    contra de un "8"- quedan vacios sin tratarlos aparte.
    """
    anillos = [exterior, *huecos]
    xs = [q[0] for a in anillos for q in a]
    ys = [q[1] for a in anillos for q in a]
    # La distancia al borde recorre la rejilla pixel a pixel, asi que el
    # costo va con el AREA. Una figura larga -el contorno de un escudo
    # entero- desbordaria el presupuesto de tiempo, y para medir su ancho no
    # hace falta tanto detalle: se baja la resolucion antes que tardar.
    lados = (max(xs) - min(xs) + 1e-6) * (max(ys) - min(ys) + 1e-6)
    if lados * px_por_mm * px_por_mm > PIXELES_MAX:
        # El piso es bajo a proposito: una figura tan grande tiene trazos
        # igual de grandes, asi que no necesita el detalle fino.
        px_por_mm = max(4.0, math.sqrt(PIXELES_MAX / lados))
    # Un pixel de margen a cada lado: el adelgazado necesita que la mancha no
    # toque el borde de la rejilla, o la trata como si siguiera hacia afuera.
    margen = 2.0 / px_por_mm
    x0, y0 = min(xs) - margen, min(ys) - margen
    x1, y1 = max(xs) + margen, max(ys) + margen
    ancho = max(3, int(math.ceil((x1 - x0) * px_por_mm)))
    alto = max(3, int(math.ceil((y1 - y0) * px_por_mm)))

    m = np.zeros((alto, ancho), dtype=bool)
    for j in range(alto):
        y = y0 + (j + 0.5) / px_por_mm
        cruces = cruces_scanline_anillos(anillos, y)
        for k in range(0, len(cruces) - 1, 2):
            a = int(math.ceil((cruces[k] - x0) * px_por_mm - 0.5))
            b = int(math.floor((cruces[k + 1] - x0) * px_por_mm - 0.5))
            if b >= a:
                m[j, max(a, 0):b + 1] = True
    return m, x0, y0, px_por_mm


def distancia_al_borde(m: np.ndarray) -> np.ndarray:
    """
    Distancia de cada pixel de la mancha al fondo mas cercano, en pixeles.

    Chamfer 3-4 en dos pasadas. No es la distancia euclidea exacta -se
    equivoca hasta un 6%- pero aqui solo se usa para medir el ancho de un
    trazo, donde ese error es de centesimas de milimetro.
    """
    INF = 1e9
    d = np.where(m, INF, 0.0)
    alto, ancho = d.shape
    A, B = 3.0, 4.0                    # costo recto y diagonal

    for j in range(alto):              # ida: arriba-izquierda -> abajo-derecha
        for i in range(ancho):
            if d[j, i] == 0.0:
                continue
            v = d[j, i]
            if j > 0:
                v = min(v, d[j - 1, i] + A)
                if i > 0:
                    v = min(v, d[j - 1, i - 1] + B)
                if i < ancho - 1:
                    v = min(v, d[j - 1, i + 1] + B)
            if i > 0:
                v = min(v, d[j, i - 1] + A)
            d[j, i] = v

    for j in range(alto - 1, -1, -1):  # vuelta
        for i in range(ancho - 1, -1, -1):
            if d[j, i] == 0.0:
                continue
            v = d[j, i]
            if j < alto - 1:
                v = min(v, d[j + 1, i] + A)
                if i > 0:
                    v = min(v, d[j + 1, i - 1] + B)
                if i < ancho - 1:
                    v = min(v, d[j + 1, i + 1] + B)
            if i < ancho - 1:
                v = min(v, d[j, i + 1] + A)
            d[j, i] = v

    return d / A                       # a unidades de pixel


def adelgazar(m: np.ndarray) -> np.ndarray:
    """
    Esqueleto de la mancha: la reduce a lineas de un pixel de ancho.

    Algoritmo de Zhang-Suen (1984), el clasico. Cada iteracion tiene dos
    subpasadas que borran pixeles del borde solo si quitarlos no parte la
    figura en dos ni acorta un extremo. Se repite hasta que no cambia nada.

    Se implementa con operaciones sobre el array completo, no pixel por
    pixel: sobre una rejilla de un numero chico son milisegundos.
    """
    img = m.copy()

    def vecinos(a: np.ndarray) -> list[np.ndarray]:
        """P2..P9 en el orden del articulo: N, NE, E, SE, S, SO, O, NO."""
        d = np.zeros_like(a)
        salida = []
        for dy, dx in ((-1, 0), (-1, 1), (0, 1), (1, 1),
                       (1, 0), (1, -1), (0, -1), (-1, -1)):
            v = d.copy()
            v[max(0, -dy):a.shape[0] - max(0, dy),
              max(0, -dx):a.shape[1] - max(0, dx)] = \
                a[max(0, dy):a.shape[0] + min(0, dy),
                  max(0, dx):a.shape[1] + min(0, dx)]
            salida.append(v)
        return salida

    for _ in range(200):               # tope de seguridad; converge en pocas
        cambio = False
        for paso in (0, 1):
            p = vecinos(img)
            b = sum(x.astype(np.int16) for x in p)          # vecinos vivos
            # Transiciones 0->1 recorriendo P2..P9 en circulo.
            a = np.zeros(img.shape, dtype=np.int16)
            for k in range(8):
                a += (~p[k] & p[(k + 1) % 8]).astype(np.int16)

            if paso == 0:
                c1 = ~(p[0] & p[2] & p[4])                  # N,E,S
                c2 = ~(p[2] & p[4] & p[6])                  # E,S,O
            else:
                c1 = ~(p[0] & p[2] & p[6])                  # N,E,O
                c2 = ~(p[0] & p[4] & p[6])                  # N,S,O

            borrar = img & (b >= 2) & (b <= 6) & (a == 1) & c1 & c2
            if borrar.any():
                img &= ~borrar
                cambio = True
        if not cambio:
            break
    return img


def _grados(esq: np.ndarray) -> np.ndarray:
    """Cuantos vecinos vivos tiene cada pixel del esqueleto."""
    g = np.zeros(esq.shape, dtype=np.int8)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == 0 and dx == 0:
                continue
            v = np.zeros_like(esq)
            v[max(0, -dy):esq.shape[0] - max(0, dy),
              max(0, -dx):esq.shape[1] - max(0, dx)] = \
                esq[max(0, dy):esq.shape[0] + min(0, dy),
                    max(0, dx):esq.shape[1] + min(0, dx)]
            g += v.astype(np.int8)
    return g * esq


def ramas(esq: np.ndarray) -> list[list[tuple[int, int]]]:
    """
    Corta el esqueleto en ramas: los tramos entre extremos y bifurcaciones.

    Cada rama es un trazo del dibujo. En un "8" son los dos lobulos; en un
    "1", el palo, la bandera y la base. Se cosen por separado porque cada uno
    tiene su propia direccion y su propio ancho.
    """
    g = _grados(esq)
    vivos = {(int(j), int(i)) for j, i in zip(*np.nonzero(esq))}
    nodo = {p for p in vivos if g[p] != 2}      # extremos y bifurcaciones

    def alrededor(p):
        j, i = p
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy or dx:
                    q = (j + dy, i + dx)
                    if q in vivos:
                        yield q

    salida: list[list[tuple[int, int]]] = []
    usados: set[frozenset] = set()

    def recorrer(inicio, siguiente):
        camino = [inicio, siguiente]
        previo, actual = inicio, siguiente
        while actual not in nodo:
            paso = [q for q in alrededor(actual) if q != previo]
            if not paso:
                break
            previo, actual = actual, paso[0]
            camino.append(actual)
        return camino

    for p in nodo:
        for q in alrededor(p):
            arista = frozenset((p, q))
            if arista in usados:
                continue
            camino = recorrer(p, q)
            for k in range(len(camino) - 1):
                usados.add(frozenset((camino[k], camino[k + 1])))
            if len(camino) >= 2:
                salida.append(camino)

    if not salida and vivos:
        # Un anillo cerrado no tiene ni extremos ni bifurcaciones: se parte
        # por cualquier punto para poder recorrerlo.
        inicio = min(vivos)
        vecino = next(iter(alrededor(inicio)), None)
        if vecino is not None:
            camino = [inicio, vecino]
            previo, actual = inicio, vecino
            while actual != inicio:
                paso = [q for q in alrededor(actual) if q != previo]
                if not paso:
                    break
                previo, actual = actual, paso[0]
                camino.append(actual)
            salida.append(camino)
    return salida


def _podar(caminos: list[list[tuple[int, int]]], dist: np.ndarray,
           factor: float = 1.2) -> list[list[tuple[int, int]]]:
    """
    Quita las espinas: ramas cortas que salen de una bifurcacion y no van a
    ninguna parte.

    Adelgazar una figura con esquinas -y las letras son casi solo esquinas-
    deja siempre estos apendices. No son trazos del dibujo, son un artefacto
    del algoritmo, y cosidos por separado fragmentan la letra en parches. Es
    el post-proceso estandar de un eje medial y sin el no sirve para bordar.

    El criterio es relativo al grosor local: una espina mas corta que el
    ancho del propio trazo no puede ser un trazo.
    """
    grado: dict[tuple[int, int], int] = {}
    for c in caminos:
        for extremo in (c[0], c[-1]):
            grado[extremo] = grado.get(extremo, 0) + 1

    salida = []
    for c in caminos:
        libres = sum(1 for extremo in (c[0], c[-1]) if grado.get(extremo, 0) <= 1)
        if libres == 0:
            salida.append(c)                     # une dos bifurcaciones
            continue
        largo = sum(math.dist(c[k], c[k + 1]) for k in range(len(c) - 1))
        ancho = max(float(dist[j, i]) for j, i in c) * 2.0
        if libres == 2 or largo >= ancho * factor:
            salida.append(c)
    return salida or caminos


def _alargar(puntos: Polilinea, semi: list[float]) -> tuple[Polilinea, list[float]]:
    """
    Estira el trazo por sus dos puntas.

    El adelgazado se detiene aproximadamente medio ancho antes del borde de
    la figura, asi que la columna satin nacida del esqueleto deja las puntas
    del trazo sin cubrir. En una letra eso se ve como palos cortados.
    """
    if len(puntos) < 2:
        return puntos, semi

    def estirar(a: Punto, b: Punto, d: float) -> Punto:
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy) or 1.0
        return (b[0] + dx / L * d, b[1] + dy / L * d)

    p0 = estirar(puntos[1], puntos[0], semi[0])
    p1 = estirar(puntos[-2], puntos[-1], semi[-1])
    return [p0, *puntos, p1], [semi[0], *semi, semi[-1]]


def trazos_de_region(exterior: Polilinea, huecos: list[Polilinea],
                     px_por_mm: float = PX_POR_MM,
                     rama_minima_mm: float = RAMA_MINIMA_MM
                     ) -> list[tuple[Polilinea, list[float]]]:
    """
    Descompone la region en trazos: [(puntos en mm, semianchos en mm), ...].

    Es todo lo que hace falta para coser cada trazo como columna satin.
    """
    m, x0, y0, ppmm = rasterizar(exterior, huecos, px_por_mm)
    if not m.any():
        return []
    dist = distancia_al_borde(m)
    esq = adelgazar(m)
    if not esq.any():
        return []

    salida: list[tuple[Polilinea, list[float]]] = []
    for camino in _podar(ramas(esq), dist):
        puntos = [(x0 + (i + 0.5) / ppmm, y0 + (j + 0.5) / ppmm)
                  for j, i in camino]
        largo = sum(math.dist(puntos[k], puntos[k + 1])
                    for k in range(len(puntos) - 1))
        if largo < rama_minima_mm:
            continue
        semi = [float(dist[j, i]) / ppmm for j, i in camino]
        salida.append(_alargar(puntos, semi))
    return salida


def suavizar(puntos: Polilinea, ventana: int = 5) -> Polilinea:
    """
    Media movil sobre el camino.

    El esqueleto avanza por pixeles, asi que zigzaguea un pixel arriba y
    abajo. Cosido tal cual, ese temblor se ve en la tela como un borde
    dentado. Los extremos se dejan intactos para no acortar el trazo.
    """
    n = len(puntos)
    if n <= ventana or ventana < 3:
        return list(puntos)
    r = ventana // 2
    salida = list(puntos)
    for k in range(r, n - r):
        xs = [puntos[k + t][0] for t in range(-r, r + 1)]
        ys = [puntos[k + t][1] for t in range(-r, r + 1)]
        salida[k] = (sum(xs) / len(xs), sum(ys) / len(ys))
    return salida
