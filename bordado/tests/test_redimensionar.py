"""
Tests del redimensionado.

La regla que sostiene el modulo: escalar puntadas multiplica la separacion
entre pasadas del relleno por el mismo factor, y eso NO se puede recalcular
sin conocer las regiones. Por eso el modulo hace bien los cambios chicos y
RECHAZA los grandes, en vez de entregar en silencio un archivo inservible.
"""

import math

import pyembroidery as pe
import pytest

from bordado.convertir import convertir_archivo
from bordado.geometria import circulo
from bordado.parametros import ParamGlobales, ParamRelleno
from bordado.patron import ConstructorPatron
from bordado.puntadas import relleno_tatami
from bordado.redimensionar import (
    FACTOR_SEGURO_MAX, FACTOR_SEGURO_MIN, PUNTADA_MAX_MM, PUNTADA_MIN_MM,
    factor_para, reescalar,
)


@pytest.fixture
def patron():
    b = ConstructorPatron(ParamGlobales())
    b.agregar("x", "#1B4F9C", relleno_tatami(circulo((0, 0), 25, 120),
                                             ParamRelleno()))
    return b.construir()


def largos_mm(p) -> list[float]:
    """Largo de cada puntada real, saltandose los desplazamientos."""
    salida, previo = [], None
    for x, y, cmd in p.stitches:
        base = cmd & pe.COMMAND_MASK
        if base == pe.STITCH:
            if previo is not None:
                salida.append(math.hypot(x - previo[0], y - previo[1]) / 10.0)
            previo = (x, y)
        elif base == pe.JUMP:
            previo = (x, y)
        else:
            previo = None
    return salida


# ------------------------------------------------------------ rango seguro

@pytest.mark.parametrize("factor", [0.90, 0.95, 1.0, 1.05, 1.10])
def test_los_cambios_chicos_se_aceptan(patron, factor):
    nuevo, r = reescalar(patron, factor)
    assert nuevo is not None and r.seguro
    assert r.ancho_despues == pytest.approx(r.ancho_antes * factor, rel=0.02)


@pytest.mark.parametrize("factor", [0.5, 0.7, 1.3, 2.0])
def test_los_cambios_grandes_se_rechazan(patron, factor):
    nuevo, r = reescalar(patron, factor)
    assert nuevo is None and not r.seguro
    # El aviso tiene que decir QUE pasaria y COMO resolverlo.
    texto = " ".join(r.avisos)
    assert "separacion" in texto and "digitalizar" in texto


def test_el_rechazo_igual_informa_el_tamano(patron):
    """Saber a que tamano habria quedado es justo lo que el usuario pregunta."""
    _, r = reescalar(patron, 2.0)
    assert r.ancho_despues == pytest.approx(r.ancho_antes * 2.0, rel=0.01)
    assert r.puntadas_antes > 0


def test_forzar_deja_pasar_pero_lo_dice(patron):
    nuevo, r = reescalar(patron, 1.6, forzar=True)
    assert nuevo is not None and not r.seguro
    assert any("--forzar" in a for a in r.avisos)


def test_un_factor_invalido_se_rechaza(patron):
    nuevo, r = reescalar(patron, 0.0)
    assert nuevo is None and not r.seguro


def test_los_limites_del_rango_son_los_declarados(patron):
    assert reescalar(patron, FACTOR_SEGURO_MIN)[0] is not None
    assert reescalar(patron, FACTOR_SEGURO_MAX)[0] is not None
    assert reescalar(patron, FACTOR_SEGURO_MIN - 0.01)[0] is None
    assert reescalar(patron, FACTOR_SEGURO_MAX + 0.01)[0] is None


# ------------------------------------------------- correccion de los largos

def _patron_con_largos(*largos_mm_lista):
    p = pe.EmbPattern()
    p.add_thread({"hex": "#000000"})
    for fila, largo in enumerate(largos_mm_lista):
        p.trim()
        p.move_abs(0, fila * 300)
        for i in range(1, 13):
            p.stitch_abs(i * largo * 10, fila * 300)
    p.end()
    return p


@pytest.mark.parametrize("factor", [0.88, 1.0, 1.12])
def test_ninguna_puntada_queda_fuera_de_rango(factor):
    """
    Al agrandar aparecen puntadas demasiado largas (se enganchan) y al achicar
    demasiado cortas (rompen agujas). Las dos se corrigen.
    """
    nuevo, _ = reescalar(_patron_con_largos(9.0, 0.4, 3.5), factor)
    d = largos_mm(nuevo)
    assert min(d) >= PUNTADA_MIN_MM - 1e-6
    assert max(d) <= PUNTADA_MAX_MM + 1e-6


def test_las_puntadas_largas_se_parten():
    nuevo, r = reescalar(_patron_con_largos(9.0), 1.12, forzar=True)
    assert r.divididas > 0
    assert max(largos_mm(nuevo)) <= PUNTADA_MAX_MM + 1e-6


def test_las_puntadas_cortas_se_fusionan():
    nuevo, r = reescalar(_patron_con_largos(0.4), 0.88)
    assert r.fusionadas > 0
    assert min(largos_mm(nuevo)) >= PUNTADA_MIN_MM - 1e-6


def test_un_diseno_sano_no_se_toca(patron):
    """Sin cambio de escala no hay nada que corregir."""
    _, r = reescalar(patron, 1.0)
    assert (r.divididas, r.fusionadas) == (0, 0)
    assert r.puntadas_despues == r.puntadas_antes


def test_no_se_pierde_el_ultimo_punto_de_cada_tramo():
    """Ese punto cierra la forma: se corre, no se descarta."""
    nuevo, _ = reescalar(_patron_con_largos(0.4, 0.4), 0.88)
    assert nuevo.count_stitch_commands(pe.TRIM) >= 2
    assert nuevo.count_stitch_commands(pe.STITCH) > 0


# ------------------------------------------------------------- factor_para

def test_factor_para_calcula_el_factor_del_ancho_pedido(patron):
    x0, _, x1, _ = patron.bounds()
    ancho = (x1 - x0) / 10.0
    assert factor_para(patron, ancho_mm=ancho * 1.1) == pytest.approx(1.1, rel=0.01)
    assert factor_para(patron) == 1.0


# ------------------------------------------------- integrado en el conversor

def test_el_conversor_redimensiona(patron, tmp_path):
    origen = tmp_path / "o.pes"
    pe.write(patron, str(origen), {"version": 1})
    r = convertir_archivo(origen, tmp_path / "d.jef", "jef", escala=1.10)
    assert r.ok and r.escala == 1.10
    leido = pe.read(str(tmp_path / "d.jef"))
    x0, _, x1, _ = leido.bounds()
    assert (x1 - x0) / 10.0 == pytest.approx(r.ancho_mm, rel=0.03)


def test_el_conversor_rechaza_una_escala_insegura(patron, tmp_path):
    origen = tmp_path / "o.pes"
    pe.write(patron, str(origen), {"version": 1})
    r = convertir_archivo(origen, tmp_path / "d.jef", "jef", escala=1.8)
    assert r.estado == "error" and "separacion" in r.detalle
    assert not (tmp_path / "d.jef").exists()

    r = convertir_archivo(origen, tmp_path / "f.jef", "jef", escala=1.8,
                          forzar_escala=True)
    assert r.ok and (tmp_path / "f.jef").exists()


def test_el_informe_se_lee(patron):
    _, r = reescalar(patron, 1.5)
    texto = r.texto()
    for palabra in ("Factor", "Tamano", "Separacion", "digitalizar"):
        assert palabra in texto
