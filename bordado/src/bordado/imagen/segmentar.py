"""
Segmentacion de color: imagen -> N regiones planas de color.

Bordar no admite degradados: cada color es un carrete de hilo. El primer
paso es siempre reducir la imagen a un numero PEQUENO de colores planos.

POR QUE EN ESPACIO LAB Y NO EN RGB
    RGB no es perceptualmente uniforme: la misma distancia numerica se ve
    como una diferencia enorme entre verdes y como casi nada entre azules
    oscuros. Agrupar en RGB junta colores que el ojo distingue y separa
    colores que el ojo ve iguales. Lab si es (aproximadamente) uniforme, asi
    que agrupar ahi produce las divisiones que una persona haria a mano.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

# Blanco de referencia D65, el iluminante estandar para pantallas (sRGB).
_BLANCO_D65 = np.array([0.95047, 1.00000, 1.08883])


@dataclass
class Segmentacion:
    etiquetas: np.ndarray      # (alto, ancho) int: indice de color por pixel
    colores: np.ndarray        # (n, 3) uint8: color RGB de cada grupo
    fondo: np.ndarray          # (alto, ancho) bool: True donde NO se borda
    px_por_mm: float

    @property
    def n_colores(self) -> int:
        return len(self.colores)

    def mascara(self, indice: int) -> np.ndarray:
        return (self.etiquetas == indice) & ~self.fondo

    def cuenta(self, indice: int) -> int:
        return int(self.mascara(indice).sum())


# --------------------------------------------------------------------------
# Conversion de color
# --------------------------------------------------------------------------

def rgb_a_lab(rgb: np.ndarray) -> np.ndarray:
    """sRGB (0-255) -> CIE L*a*b*. Acepta cualquier forma con 3 canales al final."""
    x = np.asarray(rgb, dtype=np.float64) / 255.0
    # Deshace la curva de gamma de sRGB: los valores del archivo no son
    # proporcionales a la luz emitida.
    lineal = np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124564, 0.3575761, 0.1804375],
                  [0.2126729, 0.7151522, 0.0721750],
                  [0.0193339, 0.1191920, 0.9503041]])
    xyz = lineal @ m.T / _BLANCO_D65
    d = 6.0 / 29.0
    f = np.where(xyz > d ** 3, np.cbrt(xyz), xyz / (3 * d * d) + 4.0 / 29.0)
    fx, fy, fz = f[..., 0], f[..., 1], f[..., 2]
    return np.stack([116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)], axis=-1)


def diferencia(lab_a: np.ndarray, lab_b: np.ndarray) -> np.ndarray:
    """Delta E 76: distancia euclidiana en Lab. Suficiente para elegir hilo."""
    return np.linalg.norm(np.asarray(lab_a) - np.asarray(lab_b), axis=-1)


# --------------------------------------------------------------------------
# Carga
# --------------------------------------------------------------------------

def cargar(ruta: Path, ancho_mm: float, px_por_mm: float = 8.0,
           suavizado: int = 3) -> tuple[np.ndarray, np.ndarray]:
    """
    Abre la imagen y la lleva a la resolucion de trabajo.

    `px_por_mm` fija el detalle maximo alcanzable: con 8 px/mm, un pixel mide
    0.125 mm, muy por debajo de la puntada mas corta que una maquina admite
    (0.6 mm). Subirlo no mejora el bordado y solo hace todo mas lento.

    Devuelve (rgb, fondo) donde `fondo` marca los pixeles transparentes.
    """
    img = Image.open(ruta)
    img = img.convert("RGBA")

    ancho_px = max(16, int(round(ancho_mm * px_por_mm)))
    alto_px = max(16, int(round(ancho_px * img.height / img.width)))
    img = img.resize((ancho_px, alto_px), Image.LANCZOS)

    if suavizado >= 3 and suavizado % 2 == 1:
        # Filtro de mediana: aplana el ruido de JPEG y las tramas de semitono
        # sin desdibujar los bordes, que es justo lo contrario de un desenfoque.
        img = img.filter(ImageFilter.MedianFilter(size=suavizado))

    datos = np.asarray(img, dtype=np.uint8)
    rgb = datos[..., :3].copy()
    fondo = datos[..., 3] < 128
    # Un pixel transparente puede traer basura de color debajo; se neutraliza
    # para que no arrastre los centroides al agrupar.
    rgb[fondo] = 255
    return rgb, fondo


def detectar_fondo(rgb: np.ndarray, fondo: np.ndarray,
                   tolerancia: float = 12.0) -> np.ndarray:
    """
    Marca como fondo el color que domina el BORDE de la imagen.

    Casi todo logo o dibujo viene sobre un fondo plano que no se borda.

    OJO CON LA CONECTIVIDAD, que es donde estuvo el error
        No basta con borrar todos los pixeles de ese color: hay que borrar
        solo los que se pueden alcanzar DESDE EL BORDE sin cruzar el dibujo.

        Un escudo blanco sobre fondo blanco tiene las dos cosas del mismo
        color, y son cosas distintas: lo de afuera es fondo y lo de adentro
        es dibujo. Borrando por color se iban tambien el monograma blanco, el
        interior de una cinta y cualquier contra de una letra. En el bordado
        eso no es "nada": es hilo blanco, que sobre una polera de color es
        justamente lo que se ve.

        Por eso se rellena desde el borde hacia adentro y se para en el
        dibujo. Lo que queda encerrado se borda.
    """
    if fondo.all():
        return fondo
    marco = np.concatenate([rgb[0, :], rgb[-1, :], rgb[:, 0], rgb[:, -1]])
    colores, cuentas = np.unique(marco.reshape(-1, 3), axis=0, return_counts=True)
    dominante = colores[cuentas.argmax()]
    if cuentas.max() < 0.5 * len(marco):
        return fondo   # borde heterogeneo: probablemente no hay fondo plano
    d = diferencia(rgb_a_lab(rgb), rgb_a_lab(dominante))
    # Los transparentes tambien dejan pasar: un logo recortado tiene el fondo
    # en alfa y el color plano solo en los bordes del recorte.
    candidato = (d < tolerancia) | fondo
    return fondo | _alcanzable_desde_el_borde(candidato)


def _alcanzable_desde_el_borde(candidato: np.ndarray) -> np.ndarray:
    """
    Que parte de `candidato` se toca con el borde de la imagen.

    Relleno por inundacion con barrido de FILAS, no pixel a pixel: se avanza
    por tramos horizontales completos. En una imagen de un millon de pixeles
    la diferencia es entre decimas de segundo y varios segundos.
    """
    alto, ancho = candidato.shape
    visto = np.zeros_like(candidato)
    pila: list[tuple[int, int]] = []

    for j in (0, alto - 1):
        pila += [(j, i) for i in range(ancho) if candidato[j, i]]
    for i in (0, ancho - 1):
        pila += [(j, i) for j in range(alto) if candidato[j, i]]

    while pila:
        j, i = pila.pop()
        if visto[j, i] or not candidato[j, i]:
            continue
        # Se estira el tramo hacia los dos lados hasta topar con el dibujo.
        izq = i
        while izq > 0 and candidato[j, izq - 1] and not visto[j, izq - 1]:
            izq -= 1
        der = i
        while der < ancho - 1 and candidato[j, der + 1] and not visto[j, der + 1]:
            der += 1
        visto[j, izq:der + 1] = True
        # Y se siembran los tramos de arriba y de abajo.
        for jj in (j - 1, j + 1):
            if 0 <= jj < alto:
                fila = candidato[jj, izq:der + 1] & ~visto[jj, izq:der + 1]
                dentro = False
                for k, v in enumerate(fila):
                    if v and not dentro:
                        pila.append((jj, izq + k))
                        dentro = True
                    elif not v:
                        dentro = False
    return visto


# --------------------------------------------------------------------------
# Agrupamiento
# --------------------------------------------------------------------------

def segmentar(rgb: np.ndarray, fondo: np.ndarray, n_colores: int,
              px_por_mm: float = 8.0, semilla: int = 0,
              limpieza: int = 2) -> Segmentacion:
    """Reduce la imagen a `n_colores` colores planos mediante k-means en Lab."""
    lab = rgb_a_lab(rgb)
    utiles = ~fondo
    muestras = lab[utiles]
    if len(muestras) == 0:
        raise ValueError("La imagen no tiene pixeles que bordar.")

    n_colores = max(1, min(n_colores, len(np.unique(muestras, axis=0))))
    centros = _kmeans(muestras, n_colores, semilla)

    etiquetas = np.argmin(
        ((lab[:, :, None, :] - centros[None, None, :, :]) ** 2).sum(-1), axis=-1)
    etiquetas = etiquetas.astype(np.int32)

    for _ in range(limpieza):
        etiquetas = _voto_mayoritario(etiquetas, fondo)

    # El color que se muestra es el promedio REAL de los pixeles de cada
    # grupo, no el centroide en Lab: asi la vista previa se parece al original.
    colores = np.zeros((n_colores, 3), dtype=np.uint8)
    for i in range(n_colores):
        m = (etiquetas == i) & utiles
        colores[i] = rgb[m].mean(axis=0).round() if m.any() else (128, 128, 128)

    return Segmentacion(etiquetas, colores, fondo, px_por_mm)


def _kmeans(datos: np.ndarray, k: int, semilla: int,
            iteraciones: int = 24, muestra_max: int = 40000) -> np.ndarray:
    """
    k-means con inicializacion k-means++ y semilla fija (resultado repetible).

    Sobre imagenes grandes se trabaja con una muestra: 40 000 pixeles bastan
    para ubicar los centroides y evitan que el costo crezca con el tamano.
    """
    rng = np.random.default_rng(semilla)
    x = datos
    if len(x) > muestra_max:
        x = x[rng.choice(len(x), muestra_max, replace=False)]

    # k-means++: cada centro nuevo se elige lejos de los ya elegidos, lo que
    # evita el clasico resultado malo de dos centros pegados.
    centros = [x[rng.integers(len(x))]]
    for _ in range(k - 1):
        d = np.min(((x[:, None, :] - np.array(centros)[None]) ** 2).sum(-1), axis=1)
        total = d.sum()
        idx = rng.integers(len(x)) if total <= 0 else \
            int(np.searchsorted(np.cumsum(d / total), rng.random()))
        centros.append(x[min(idx, len(x) - 1)])
    centros = np.array(centros, dtype=np.float64)

    for _ in range(iteraciones):
        asign = np.argmin(((x[:, None, :] - centros[None]) ** 2).sum(-1), axis=1)
        nuevos = np.array([x[asign == i].mean(axis=0) if (asign == i).any()
                           else centros[i] for i in range(k)])
        if np.allclose(nuevos, centros, atol=1e-4):
            break
        centros = nuevos
    return centros


def _voto_mayoritario(etiquetas: np.ndarray, fondo: np.ndarray) -> np.ndarray:
    """
    Filtro de moda 3x3: cada pixel toma la etiqueta mas frecuente entre sus
    vecinos. Borra los pixeles sueltos que k-means deja en los bordes y que
    se convertirian en regiones de 1 px imposibles de bordar.
    """
    n = int(etiquetas.max()) + 1
    cuentas = np.zeros((n,) + etiquetas.shape, dtype=np.int16)
    for i in range(n):
        cap = ((etiquetas == i) & ~fondo).astype(np.int16)
        acumulado = np.zeros_like(cap)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                acumulado += np.roll(np.roll(cap, dy, axis=0), dx, axis=1)
        cuentas[i] = acumulado
    salida = np.argmax(cuentas, axis=0).astype(np.int32)
    return np.where(fondo, etiquetas, salida)
