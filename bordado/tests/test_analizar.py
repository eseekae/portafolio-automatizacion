"""
Tests del analisis de eficiencia y de los perfiles de calidad.

La pregunta que responde este modulo es concreta: "mi matriz tarda 25 minutos,
donde se van". Asi que lo que se prueba es que las medidas sean fieles y que
las sugerencias solo aparezcan cuando corresponde.
"""

import math

import pyembroidery as pe
import pytest

from bordado.analizar import (
    DENSIDAD_ALTA, DENSIDAD_BAJA, analizar,
)
from bordado.geometria import area_shoelace, circulo
from bordado.imagen.digitalizar import decidir, _describir
from bordado.parametros import (
    PERFILES, ParamGlobales, ParamRelleno,
)
from bordado.patron import ConstructorPatron
from bordado.puntadas import relleno_tatami
from bordado.validador import _minutos


DISCO = circulo((0, 0), 38, 200)
AREA_CM2 = abs(area_shoelace(DISCO)) / 100.0


def patron_de(**kw):
    b = ConstructorPatron(ParamGlobales())
    b.agregar("x", "#000000", relleno_tatami(DISCO, ParamRelleno(**kw)))
    return b.construir()


# ------------------------------------------------------------- medidas

def test_la_superficie_cubierta_se_acerca_a_la_real():
    """
    Se estima marcando en una rejilla por donde pasa el hilo. Sobre un disco
    de area conocida tiene que dar practicamente esa area.
    """
    a = analizar(patron_de())
    assert a.area_cubierta_cm2 == pytest.approx(AREA_CM2, rel=0.06)


def test_el_hilo_y_las_puntadas_cuadran():
    a = analizar(patron_de())
    assert a.puntadas > 1000
    # Largo medio por cantidad de puntadas tiene que dar el hilo total.
    assert a.hilo_m == pytest.approx(a.largo_medio_mm * a.puntadas / 1000, rel=0.05)


def test_la_densidad_sube_al_cerrar_la_separacion():
    """Mas juntas las pasadas, mas puntadas por cm2. Es la relacion clave."""
    densidades = [analizar(patron_de(densidad_mm=d)).densidad_punt_cm2
                  for d in (0.30, 0.40, 0.50)]
    assert densidades[0] > densidades[1] > densidades[2]


def test_las_bandas_de_referencia_estan_calibradas():
    """
    Un relleno estandar (0.40) tiene que caer DENTRO de la banda normal, y uno
    exagerado (0.25) por encima. Si no, el analisis daria avisos falsos.
    """
    normal = analizar(patron_de(densidad_mm=0.40)).densidad_punt_cm2
    denso = analizar(patron_de(densidad_mm=0.25, largo_mm=3.0)).densidad_punt_cm2
    abierto = analizar(patron_de(densidad_mm=0.55, largo_mm=4.0,
                                 underlay="none")).densidad_punt_cm2
    assert DENSIDAD_BAJA < normal < DENSIDAD_ALTA
    assert denso > DENSIDAD_ALTA
    assert abierto < normal


def test_un_patron_vacio_no_rompe():
    a = analizar(pe.EmbPattern())
    assert a.puntadas == 0 and a.minutos == 0.0


# --------------------------------------------------------------- tiempo

def test_el_tiempo_incluye_cortes_y_colores():
    """
    Contar solo puntadas subestima siempre: los cortes detienen la maquina y
    los cambios de color detienen tambien a la persona.
    """
    g = ParamGlobales(velocidad_ppm=600, segundos_por_corte=1.5,
                      segundos_por_color=25.0)
    solo_puntadas = _minutos(6000, 0, 1, g)
    con_cortes = _minutos(6000, 40, 1, g)
    con_colores = _minutos(6000, 40, 5, g)
    assert solo_puntadas == pytest.approx(10.0)
    assert con_cortes == pytest.approx(10.0 + 40 * 1.5 / 60)
    assert con_colores > con_cortes
    # Cuatro cambios de color son casi dos minutos: no es ruido.
    assert con_colores - con_cortes == pytest.approx(4 * 25 / 60, rel=0.01)


def test_el_desglose_del_tiempo_suma_el_total():
    a = analizar(patron_de(), velocidad_ppm=500)
    assert a.minutos == pytest.approx(
        a.minutos_puntadas + a.minutos_cortes + a.minutos_colores)


def test_la_velocidad_de_la_maquina_cambia_la_cuenta():
    lento = analizar(patron_de(), velocidad_ppm=400).minutos
    rapido = analizar(patron_de(), velocidad_ppm=800).minutos
    assert lento > rapido * 1.8


# ---------------------------------------------------------- sugerencias

def test_avisa_cuando_esta_demasiado_denso():
    a = analizar(patron_de(densidad_mm=0.25, largo_mm=3.0))
    assert any("densidad" in s.lower() for s in a.sugerencias)
    assert any("re-digitalizar" in s for s in a.sugerencias)


def test_no_avisa_de_densidad_en_un_diseno_normal():
    """El aviso falso es peor que no avisar: lleva a empeorar un diseno sano."""
    a = analizar(patron_de(densidad_mm=0.40))
    assert not any("por encima de lo habitual" in s for s in a.sugerencias)


def test_avisa_cuando_hay_demasiados_cortes():
    p = pe.EmbPattern()
    p.add_thread({"hex": "#000000"})
    for bloque in range(60):          # 60 trocitos sueltos: mucho picoteo
        p.trim()
        p.move_abs(bloque * 40, 0)
        for i in range(20):
            p.stitch_abs(bloque * 40 + i * 15, 0)
    p.end()
    a = analizar(p)
    assert any("cortes de hilo" in s for s in a.sugerencias)


def test_el_informe_se_lee():
    texto = analizar(patron_de(densidad_mm=0.25, largo_mm=3.0)).texto()
    for palabra in ("Puntadas", "Densidad", "TIEMPO", "TOTAL", "COMO BAJARLO"):
        assert palabra in texto


# ------------------------------------------------------------- perfiles

def test_los_perfiles_van_de_mas_a_menos_trabajo():
    alta, equilibrada, rapida = (PERFILES[n] for n in
                                 ("alta", "equilibrada", "rapida"))
    assert alta.densidad_mm < equilibrada.densidad_mm < rapida.densidad_mm
    assert alta.largo_mm < equilibrada.largo_mm < rapida.largo_mm
    # Menos underlay: el umbral para ponerlo pleno sube.
    assert (alta.area_underlay_tatami_mm2 < equilibrada.area_underlay_tatami_mm2
            < rapida.area_underlay_tatami_mm2)


def test_el_perfil_rapido_pone_menos_underlay():
    """Una region mediana lleva base cruzada en alta y solo contorno en rapida."""
    r = _describir(0, circulo((0, 0), 6, 60), [])       # ~113 mm2
    assert decidir(r, perfil=PERFILES["alta"]).underlay == "tatami"
    assert decidir(r, perfil=PERFILES["rapida"]).underlay == "contorno"


def test_el_perfil_rapido_ahorra_de_verdad():
    def puntadas(perfil):
        p = decidir(_describir(0, DISCO, []), perfil.densidad_mm, perfil)
        b = ConstructorPatron(ParamGlobales())
        b.agregar("x", "#000000", relleno_tatami(DISCO, p))
        return b.construir().count_stitch_commands(pe.STITCH)

    alta = puntadas(PERFILES["alta"])
    rapida = puntadas(PERFILES["rapida"])
    assert rapida < alta * 0.80          # al menos un 20% menos


def test_el_perfil_llega_hasta_la_matriz(tmp_path):
    from PIL import Image, ImageDraw

    from bordado.imagen.digitalizar import digitalizar

    f = tmp_path / "x.png"
    img = Image.new("RGB", (300, 300), (255, 255, 255))
    ImageDraw.Draw(img).ellipse([20, 20, 280, 280], fill=(20, 20, 20))
    img.save(f)

    n = {}
    for nombre in ("alta", "equilibrada", "rapida"):
        patron, _, _ = digitalizar(f, ancho_mm=70, n_colores=2, px_por_mm=5.0,
                                   perfil=nombre)
        n[nombre] = patron.count_stitch_commands(pe.STITCH)
    assert n["rapida"] < n["equilibrada"] < n["alta"]
