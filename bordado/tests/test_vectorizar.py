"""
Tests del trazado de contornos.

Se comprueba contra figuras de area conocida: es la unica forma de saber que
un trazador de contornos esta bien, porque "se ve parecido" no es un test.
"""

import math

import numpy as np
import pytest

from bordado.geometria import area_shoelace
from bordado.imagen.vectorizar import (
    separar_figuras, simplificar, trazar_anillos,
)


def area(anillo) -> float:
    return abs(area_shoelace(anillo))


def _disco(lado: int, cx: int, cy: int, r: int) -> np.ndarray:
    yy, xx = np.mgrid[0:lado, 0:lado]
    return ((xx - cx) ** 2 + (yy - cy) ** 2) <= r * r


# ------------------------------------------------------------ exactitud

def test_cuadrado_area_exacta():
    """Un rectangulo de pixeles tiene borde rectilineo: el area debe ser exacta."""
    m = np.zeros((30, 30), bool)
    m[5:15, 5:20] = True
    anillos = trazar_anillos(m)
    assert len(anillos) == 1
    assert area(anillos[0]) == pytest.approx(150.0)


def test_circulo_area_aproximada():
    anillos = trazar_anillos(_disco(80, 40, 40, 30))
    assert len(anillos) == 1
    assert area(anillos[0]) == pytest.approx(math.pi * 900, rel=0.01)


def test_dona_da_dos_anillos_y_un_hueco():
    m = _disco(80, 40, 40, 30) & ~_disco(80, 40, 40, 12)
    anillos = trazar_anillos(m)
    assert len(anillos) == 2

    figuras = separar_figuras(anillos)
    assert len(figuras) == 1
    exterior, huecos = figuras[0]
    assert len(huecos) == 1
    neta = area(exterior) - area(huecos[0])
    assert neta == pytest.approx(math.pi * (900 - 144), rel=0.02)


def test_manchas_que_solo_se_tocan_en_diagonal_quedan_separadas():
    """
    Un puente de una esquina no se puede coser. El trazador trata el frente
    como 4-conexo, asi que devuelve dos regiones y no una con cintura cero.
    """
    m = np.zeros((10, 10), bool)
    m[3, 3] = True
    m[4, 4] = True
    anillos = trazar_anillos(m)
    assert len(anillos) == 2
    assert all(area(a) == pytest.approx(1.0) for a in anillos)


def test_dos_manchas_separadas():
    m = np.zeros((40, 40), bool)
    m[5:12, 5:12] = True
    m[25:35, 25:35] = True
    figuras = separar_figuras(trazar_anillos(m))
    assert len(figuras) == 2
    # Se devuelven de mayor a menor superficie.
    assert area(figuras[0][0]) > area(figuras[1][0])


def test_mascara_vacia():
    assert trazar_anillos(np.zeros((10, 10), bool)) == []


def test_region_que_toca_el_borde_del_arreglo():
    """El marco interno debe cerrar el contorno igual, sin salirse de rango."""
    m = np.ones((12, 12), bool)
    anillos = trazar_anillos(m)
    assert len(anillos) == 1
    assert area(anillos[0]) == pytest.approx(144.0)


# -------------------------------------------------------- simplificacion

def test_simplificar_reduce_puntos_conservando_el_area():
    anillo = trazar_anillos(_disco(80, 40, 40, 30))[0]
    simple = simplificar(anillo, 0.6)
    assert len(simple) < len(anillo) / 2
    assert area(simple) == pytest.approx(area(anillo), rel=0.03)


def test_simplificar_no_rompe_figuras_minimas():
    triangulo = [(0.0, 0.0), (5.0, 0.0), (0.0, 5.0)]
    assert len(simplificar(triangulo, 1.0)) >= 3


def test_area_minima_descarta_el_ruido():
    """Un pixel suelto es ruido de compresion, no un elemento del diseno."""
    m = np.zeros((40, 40), bool)
    m[5:20, 5:20] = True
    m[30, 30] = True                      # mota de 1 px
    assert len(trazar_anillos(m)) == 2
    assert len(separar_figuras(trazar_anillos(m), area_min=4.0)) == 1
