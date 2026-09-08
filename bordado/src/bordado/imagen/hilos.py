"""
Mapeo de colores a hilos reales.

No se inventan codigos de catalogo: se usan las paletas que pyembroidery ya
trae, que son las de las propias maquinas. Tienen nombre y numero reales, y
son las que el bordador vera en la pantalla de su maquina al abrir el
archivo, asi que son mas utiles que una referencia generica.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pyembroidery as pe

from .segmentar import diferencia, rgb_a_lab

# Paleta por formato de destino. Cada maquina muestra los nombres de la suya.
PALETAS = {
    "jef": ("Janome", pe.EmbThreadJef),
    "sew": ("Janome", pe.EmbThreadSew),
    "pes": ("Brother", pe.EmbThreadPec),
    "pec": ("Brother", pe.EmbThreadPec),
    "hus": ("Husqvarna", pe.EmbThreadHus),
    "shv": ("Husqvarna", pe.EmbThreadShv),
}
PALETA_POR_DEFECTO = "jef"


@dataclass(frozen=True)
class Hilo:
    hex: str
    nombre: str
    catalogo: str
    marca: str
    delta_e: float          # que tan lejos quedo del color pedido

    @property
    def exacto(self) -> bool:
        # Delta E < 2.3 es el umbral clasico de "diferencia apenas perceptible".
        return self.delta_e < 2.3


def catalogo(formato: str = PALETA_POR_DEFECTO) -> tuple[str, list]:
    """
    Paleta de la maquina, sin los huecos.

    Las listas de pyembroidery reservan posiciones con None (el indice 0 suele
    significar "sin hilo"). Se descartan: no son colores elegibles.
    """
    marca, clase = PALETAS.get(formato.lower(), PALETAS[PALETA_POR_DEFECTO])
    return marca, [h for h in clase.get_thread_set() if h is not None]


def elegir(rgb, formato: str = PALETA_POR_DEFECTO) -> Hilo:
    """Devuelve el hilo del catalogo mas cercano al color pedido, en Lab."""
    marca, hilos = catalogo(formato)
    objetivo = rgb_a_lab(np.array(rgb, dtype=np.uint8))
    paleta = rgb_a_lab(np.array(
        [[h.get_red(), h.get_green(), h.get_blue()] for h in hilos], dtype=np.uint8))
    d = diferencia(paleta, objetivo)
    i = int(np.argmin(d))
    h = hilos[i]
    return Hilo(
        hex=f"#{h.get_red():02X}{h.get_green():02X}{h.get_blue():02X}",
        nombre=(h.description or "").strip() or "sin nombre",
        catalogo=(h.catalog_number or "").strip(),
        marca=marca,
        delta_e=float(d[i]),
    )
