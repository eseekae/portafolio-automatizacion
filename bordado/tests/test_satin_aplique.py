"""
Tests del satin automatico y del aplique.

El aplique tiene una particularidad que domina su diseno: la PAUSA de la
maquina entre pasos es una instruccion para el operador, y si se pierde, la
maquina cose los tres pasos de corrido y arruina la pieza. Buena parte de
estos tests existen para proteger esa pausa.
"""

import math
import tempfile
from pathlib import Path

import pyembroidery as pe
import pytest

from bordado.aplique import ParamAplique, instrucciones, secuencia
from bordado.exportar import exportar
from bordado.geometria import circulo, longitud
from bordado.imagen.digitalizar import (
    APLIQUE_AREA_MINIMA_MM2, _describir, elegir_tecnica, puntadas_estimadas,
)
from bordado.parametros import AROS, ParamGlobales, ParamRelleno, ParamSatin
from bordado.patron import ConstructorPatron
from bordado.puntadas import relleno_tatami, rieles_desde_contorno, satin_de_region
from bordado.validador import PUNTADA_MIN_MM, validar

FORMATOS = ["jef", "pes", "dst", "exp", "vp3"]


def franja(largo: float, ancho: float, n: int = 40):
    """Rectangulo alargado, como el trazo de una letra."""
    sup = [(largo * i / n, ancho) for i in range(n + 1)]
    inf = [(largo * i / n, 0.0) for i in range(n, -1, -1)]
    return sup + inf


def franja_curva(radio: float, ancho: float, grados: float = 120, n: int = 40):
    ext, ins = [], []
    for i in range(n + 1):
        a = math.radians(grados * i / n)
        ext.append(((radio + ancho / 2) * math.cos(a), (radio + ancho / 2) * math.sin(a)))
        ins.append(((radio - ancho / 2) * math.cos(a), (radio - ancho / 2) * math.sin(a)))
    return ext + ins[::-1]


# ------------------------------------------------------------------ satin

def test_los_rieles_salen_de_los_dos_lados_largos():
    a, b = rieles_desde_contorno(franja(40, 3))
    # Los dos lados de una franja recta miden practicamente lo mismo.
    assert longitud(a) == pytest.approx(longitud(b), rel=0.05)
    assert longitud(a) == pytest.approx(40, rel=0.1)


def test_los_rieles_funcionan_con_la_franja_curvada():
    """El doble barrido no supone que la franja sea recta."""
    a, b = rieles_desde_contorno(franja_curva(20, 3))
    assert longitud(a) == pytest.approx(longitud(b), rel=0.2)


@pytest.mark.parametrize("figura", [franja(40, 3), franja_curva(20, 3)])
def test_el_satin_no_deja_puntadas_cortas(figura):
    corridas = satin_de_region(figura, ParamSatin())
    assert corridas
    for c in corridas:
        for i in range(len(c) - 1):
            assert math.dist(c[i], c[i + 1]) >= PUNTADA_MIN_MM * 0.9


def test_una_franja_ancha_no_va_en_satin():
    """Sobre el ancho maximo el hilo queda flojo: mejor rellenar."""
    assert satin_de_region(franja(40, 12), ParamSatin()) is None


def test_una_figura_que_no_es_franja_no_da_rieles_utiles():
    assert satin_de_region(circulo((0, 0), 15, 60), ParamSatin(),
                           ancho_max_mm=6.0) is None


def test_la_tecnica_elige_satin_para_una_franja():
    r = _describir(0, franja(40, 3), [])
    assert elegir_tecnica(r) == "satin"
    gorda = _describir(0, [(0, 0), (30, 0), (30, 30), (0, 30)], [])
    assert elegir_tecnica(gorda) == "relleno"


# ---------------------------------------------------------------- aplique

def test_la_secuencia_tiene_los_tres_pasos_en_orden():
    pasos = secuencia(circulo((0, 0), 30, 120), [], "#1B4F9C")
    assert [p.orden for p in pasos] == [1, 2, 3]
    assert [p.nombre for p in pasos] == ["Posicion", "Fijacion", "Cobertura"]
    assert all(p.corridas for p in pasos)
    # Solo hay pausa DESPUES de los dos primeros: el tercero termina la pieza.
    assert [p.pausa_despues for p in pasos] == [True, True, False]


def test_los_pasos_llevan_colores_distintos():
    """
    No es cosmetico: el escritor de .pes fusiona dos bloques contiguos del
    mismo color, y con ellos se pierde la parada de la maquina.
    """
    pasos = secuencia(circulo((0, 0), 30, 120), [], "#1B4F9C")
    colores = [p.color for p in pasos]
    assert len(set(colores)) == len(colores)


def test_la_cobertura_es_el_paso_caro():
    """El satin de cobertura es la cara visible; las guias son casi gratis."""
    pasos = secuencia(circulo((0, 0), 40, 160), [], "#1B4F9C")
    n = [sum(len(c) for c in p.corridas) for p in pasos]
    assert n[2] > n[0] + n[1]


def test_el_aplique_respeta_los_huecos():
    fuera, dentro = circulo((0, 0), 40, 160), circulo((0, 0), 18, 120)
    con = secuencia(fuera, [dentro], "#1B4F9C")
    sin = secuencia(fuera, [], "#1B4F9C")
    for i in range(3):
        assert (sum(len(c) for c in con[i].corridas)
                > sum(len(c) for c in sin[i].corridas))


def test_las_instrucciones_nombran_los_pasos_y_las_pausas():
    texto = instrucciones(secuencia(circulo((0, 0), 30, 120), [], "#1B4F9C"))
    for palabra in ("POSICION", "FIJACION", "COBERTURA", "recorta", "detiene"):
        assert palabra in texto


# -------------------------------------------------- cuando conviene aplicar

def test_el_aplique_solo_gana_en_manchas_grandes():
    """
    El criterio no es el area sino comparar costos. Una mancha chica tiene
    poco relleno que ahorrar y el mismo borde que coser.
    """
    chica = _describir(0, circulo((0, 0), 10, 80), [])
    grande = _describir(0, circulo((0, 0), 50, 200), [])
    assert elegir_tecnica(chica, aplique=True) != "aplique"
    assert elegir_tecnica(grande, aplique=True) == "aplique"

    r_chica, a_chica = puntadas_estimadas(chica, 0.40)
    r_grande, a_grande = puntadas_estimadas(grande, 0.40)
    assert a_chica > r_chica          # aplicar una mancha chica cuesta MAS
    assert a_grande < r_grande * 0.6  # y una grande ahorra de sobra


def test_un_anillo_no_se_aplica_aunque_sea_grande():
    """
    Mucho borde para poca superficie: la cobertura satin costaria mas que el
    relleno que evita. Es el caso que un umbral por area habria elegido mal.
    """
    anillo = _describir(0, circulo((0, 0), 45, 200), [circulo((0, 0), 38, 200)])
    assert anillo.area_mm2 > APLIQUE_AREA_MINIMA_MM2
    assert elegir_tecnica(anillo, aplique=True) == "relleno"


def test_el_aplique_ahorra_de_verdad_frente_al_relleno():
    disco = circulo((0, 0), 50, 200)
    apl = sum(len(c) for p in secuencia(disco, [], "#1B4F9C") for c in p.corridas)
    rel = sum(len(c) for c in relleno_tatami(disco, ParamRelleno()))
    assert apl < rel * 0.5


# ------------------------------------------------- la pausa debe sobrevivir

def _patron_aplique(colores_guia=("#FF00FF", "#00C853")):
    p = ParamAplique(color_posicion=colores_guia[0], color_fijacion=colores_guia[1])
    pasos = secuencia(circulo((0, 0), 30, 120), [], "#1B4F9C", p)
    b = ConstructorPatron(ParamGlobales(aro=AROS["brother_5x7"]))
    for paso in pasos:
        b.agregar(paso.nombre, paso.color, paso.corridas, forzar_bloque=True)
    return b.construir(), len(pasos)


@pytest.mark.parametrize("formato", FORMATOS)
def test_la_pausa_sobrevive_en_cada_formato(formato, tmp_path):
    patron, esperadas = _patron_aplique()
    f = tmp_path / f"a.{formato}"
    pe.write(patron, str(f))
    assert pe.read(str(f)).count_color_changes() + 1 == esperadas, formato


def test_el_validador_exige_las_paradas():
    patron, esperadas = _patron_aplique()
    g = ParamGlobales(aro=AROS["brother_5x7"])
    assert validar(patron, g, paradas_esperadas=esperadas).ok
    r = validar(patron, g, paradas_esperadas=esperadas + 1)
    assert not r.ok and "parada" in r.errores[0]


def test_la_exportacion_caza_una_pausa_perdida(tmp_path):
    """
    Con las guias del mismo color que la cobertura, el escritor de .pes
    fusiona bloques y una parada desaparece. Tiene que ser un ERROR: un
    archivo asi cose los tres pasos de corrido y arruina la pieza.
    """
    g = ParamGlobales(aro=AROS["brother_5x7"])
    bueno, esperadas = _patron_aplique()
    r, _ = exportar(bueno, "ok", tmp_path / "ok", g, formatos=FORMATOS,
                    comprimir=False, paradas_esperadas=esperadas)
    assert r.ok, r.errores

    malo, esperadas = _patron_aplique(colores_guia=("#1B4F9C", "#1B4F9C"))
    r, _ = exportar(malo, "malo", tmp_path / "malo", g, formatos=FORMATOS,
                    comprimir=False, paradas_esperadas=esperadas)
    assert not r.ok
    assert any("perdio paradas" in e for e in r.errores)


def test_forzar_bloque_mantiene_la_parada_con_el_mismo_color():
    """Sin `forzar_bloque` dos objetos del mismo color se funden en uno."""
    g = ParamGlobales()
    corridas = [circulo((0, 0), 10, 40)]
    sin = ConstructorPatron(g)
    sin.agregar("a", "#123456", corridas).agregar("b", "#123456", corridas)
    con = ConstructorPatron(g)
    con.agregar("a", "#123456", corridas, forzar_bloque=True)
    con.agregar("b", "#123456", corridas, forzar_bloque=True)
    assert sin.construir().count_color_changes() == 0
    assert con.construir().count_color_changes() == 1
