"""
Tests del pipeline. Se pueden correr en CI para que nunca se publique una
matriz defectuosa: si el QA falla, falla el build.

    pytest -q
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pyembroidery as pe

from bordado.geometria import (
    area_shoelace, circulo, cruces_scanline, longitud, remuestrear,
)
from bordado.parametros import AROS, ParamGlobales, ParamRelleno, ParamSatin
from bordado.patron import ConstructorPatron
from bordado.puntadas import columna_satin, relleno_tatami
from bordado.validador import PUNTADA_MIN_MM, validar


# ---------------------------------------------------------------- geometria

def test_area_circulo():
    """Shoelace sobre un poligono de 256 lados debe converger a pi*r^2."""
    a = abs(area_shoelace(circulo((0, 0), 10, segmentos=256)))
    assert math.isclose(a, math.pi * 100, rel_tol=1e-3)


def test_remuestreo_respeta_el_paso():
    pts = remuestrear([(0, 0), (100, 0)], 2.0)
    dists = [math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    assert all(d <= 2.0 + 1e-6 for d in dists)


def test_scanline_par_impar():
    """Un anillo (poligono en 8) o forma concava debe dar cruces pares."""
    assert len(cruces_scanline(circulo((0, 0), 5), 0.0)) == 2


# ----------------------------------------------------------------- puntadas

def test_satin_sin_puntadas_cortas():
    """
    Regresion del bug clasico: alternar el orden del zigzag genera puntadas
    del largo de la densidad (~0.4 mm) que quiebran agujas.
    """
    ext, ins = circulo((0, 0), 20, segmentos=200), circulo((0, 0), 17, segmentos=200)
    corridas = columna_satin(ext, ins, ParamSatin())
    zig = corridas[-1]
    cortas = sum(1 for i in range(len(zig) - 1)
                 if math.dist(zig[i], zig[i + 1]) < PUNTADA_MIN_MM)
    assert cortas == 0


def test_densidad_de_relleno_es_coherente():
    """
    N ~= A / (d * l).  Se acepta +-40% porque el underlay y los bordes suman.
    """
    poly = circulo((0, 0), 15, segmentos=120)
    p = ParamRelleno(densidad_mm=0.4, largo_mm=3.5, underlay="none")
    n = sum(len(c) for c in relleno_tatami(poly, p))
    esperado = abs(area_shoelace(poly)) / (p.densidad_mm * p.largo_mm)
    assert 0.6 * esperado < n < 1.4 * esperado


def test_relleno_no_cruza_huecos():
    """Un poligono concavo no debe generar puntadas que crucen el vacio."""
    concavo = [(-20, 0), (-5, 20), (0, 0), (5, 20), (20, 0)]
    for corrida in relleno_tatami(concavo, ParamRelleno(underlay="none")):
        for i in range(len(corrida) - 1):
            assert math.dist(corrida[i], corrida[i + 1]) < 12.1


# ---------------------------------------------------- patron y exportacion

def _patron_demo():
    g = ParamGlobales(aro=AROS["brother_4x4"])
    b = ConstructorPatron(g)
    b.agregar("fondo", "#1B4F9C", relleno_tatami(circulo((0, 0), 20), ParamRelleno()))
    return b.construir(), g


def test_qa_aprueba_un_diseno_sano():
    patron, g = _patron_demo()
    assert validar(patron, g).ok


def test_qa_rechaza_diseno_fuera_del_aro():
    """Un diseno de 200 mm no cabe en un aro de 100x100: debe ser ERROR."""
    g = ParamGlobales(aro=AROS["brother_4x4"])
    b = ConstructorPatron(g)
    b.agregar("gigante", "#000000", relleno_tatami(circulo((0, 0), 100), ParamRelleno()))
    r = validar(b.construir(), g)
    assert not r.ok and "No cabe" in r.errores[0]


def test_ida_y_vuelta_pes_jef_dst(tmp_path):
    """
    Escribir y volver a leer: si el binario estuviera corrupto, la cantidad
    de puntadas o las dimensiones no calzarian.
    """
    patron, _ = _patron_demo()
    original = patron.get_normalized_pattern().count_stitch_commands(pe.STITCH)
    for ext in ("pes", "jef", "dst", "exp", "vp3"):
        f = tmp_path / f"t.{ext}"
        pe.write(patron, str(f))
        leido = pe.read(str(f))
        assert abs(leido.count_stitch_commands(pe.STITCH) - original) <= 2, ext
        x0, y0, x1, y1 = leido.bounds()
        assert math.isclose((x1 - x0) / 10, 40.0, abs_tol=1.5), ext
