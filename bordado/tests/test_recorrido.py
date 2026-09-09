"""
Tests del recorrido de la aguja.

Vienen de un sintoma reportado desde la maquina: un diseno de UN SOLO COLOR
que se detenia una y otra vez. No eran cambios de color ni comandos STOP (se
verifico que no se emite ninguno): eran CORTES DE HILO, y los cortes salian de
que la aguja viajaba lejos entre corrida y corrida.

Reordenar no cambia ni una puntada, solo en que secuencia se cosen.
"""

import math

import pyembroidery as pe
import pytest

from bordado.analizar import analizar
from bordado.geometria import circulo
from bordado.parametros import (
    PERFILES, AROS, ParamGlobales, ParamRelleno, ParamSatin,
)
from bordado.patron import ConstructorPatron
from bordado.puntadas import ordenar_corridas, relleno_tatami, satin_de_region


def recorrido(corridas, desde=(0.0, 0.0)) -> float:
    """Camino que hace la aguja en vacio entre corrida y corrida."""
    total, pos = 0.0, desde
    for c in corridas:
        total += math.dist(pos, c[0])
        pos = c[-1]
    return total


# ------------------------------------------------------- ordenar_corridas

def test_ordenar_acorta_el_recorrido():
    lejanas = [[(0, 0), (10, 0)], [(200, 200), (210, 200)],
               [(12, 0), (22, 0)], [(212, 200), (222, 200)]]
    ordenadas, _ = ordenar_corridas(lejanas)
    assert recorrido(ordenadas) < recorrido(lejanas) / 2


def test_ordenar_da_vuelta_la_corrida_si_conviene():
    """Una corrida se puede coser en cualquier sentido: se elige el mas corto."""
    corridas = [[(0, 0), (5, 0)], [(100, 0), (6, 0)]]
    ordenadas, final = ordenar_corridas(corridas)
    # La segunda se cose al reves, empezando por el extremo cercano.
    assert ordenadas[1][0] == (6, 0)
    assert final == (100, 0)


def test_ordenar_conserva_todas_las_corridas():
    corridas = [[(0, 0), (10, 0)], [(50, 50), (60, 50)], [(5, 30), (15, 30)]]
    ordenadas, _ = ordenar_corridas(corridas)
    assert len(ordenadas) == 3
    # Mismos extremos, en algun orden y quiza dados vuelta.
    extremos = {frozenset((c[0], c[-1])) for c in ordenadas}
    assert extremos == {frozenset((c[0], c[-1])) for c in corridas}


def test_ordenar_descarta_lo_que_no_es_corrida():
    assert ordenar_corridas([[(0, 0)], []])[0] == []


def test_ordenar_arranca_donde_quedo_la_aguja():
    corridas = [[(100, 0), (110, 0)], [(5, 0), (15, 0)]]
    ordenadas, _ = ordenar_corridas(corridas, desde=(0.0, 0.0))
    assert ordenadas[0][0] == (5, 0)


# ------------------------------------------------ el underlay va primero

def test_el_underlay_no_se_mezcla_con_el_relleno():
    """
    El orden dentro de cada fase es libre, pero el underlay tiene que coserse
    ANTES del relleno que sostiene. Si se reordenara todo junto, la base
    podria terminar encima.
    """
    poly = circulo((0, 0), 25, 120)
    con = relleno_tatami(poly, ParamRelleno(underlay="tatami"))
    sin = relleno_tatami(poly, ParamRelleno(underlay="none"))

    # Las ultimas corridas de `con` son exactamente el relleno de `sin`.
    cola = con[-len(sin):]
    assert sum(len(c) for c in cola) == sum(len(c) for c in sin)
    assert len(con) > len(sin)          # y antes hay corridas de underlay


def test_ordenar_no_cambia_las_puntadas():
    """La cantidad y el largo de las puntadas quedan igual: solo el orden."""
    poly = circulo((0, 0), 25, 120)
    corridas = relleno_tatami(poly, ParamRelleno())
    ordenadas, _ = ordenar_corridas(corridas)
    assert sum(len(c) for c in ordenadas) == sum(len(c) for c in corridas)


def test_el_satin_conserva_su_columna_al_final():
    franja = ([(x, 3.0) for x in range(0, 41, 1)]
              + [(x, 0.0) for x in range(40, -1, -1)])
    corridas = satin_de_region(franja, ParamSatin())
    assert corridas
    # La ultima corrida es la columna: la mas larga con diferencia.
    assert len(corridas[-1]) == max(len(c) for c in corridas)


# --------------------------------------------- el sintoma que se reporto

def _dragon(tmp_path):
    from PIL import Image, ImageDraw
    f = tmp_path / "d.png"
    img = Image.new("RGB", (400, 700), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.ellipse([40, 40, 360, 300], fill=(20, 20, 20))
    d.polygon([(200, 300), (150, 660), (250, 660)], fill=(20, 20, 20))
    d.ellipse([30, 380, 130, 480], fill=(20, 20, 20))
    d.ellipse([270, 380, 370, 480], fill=(20, 20, 20))
    img.save(f)
    return f


def test_un_diseno_de_un_color_no_lleva_ninguna_parada(tmp_path):
    """
    Ni COLOR_CHANGE ni STOP: si la maquina se detiene en un diseno de un solo
    color, no es porque el archivo se lo pida.
    """
    from bordado.imagen.digitalizar import digitalizar

    patron, d, _ = digitalizar(_dragon(tmp_path), ancho_mm=70, n_colores=2,
                               px_por_mm=5.0)
    assert len(d.hilos_usados) == 1
    for x, y, cmd in patron.get_normalized_pattern().stitches:
        assert (cmd & pe.COMMAND_MASK) not in (pe.COLOR_CHANGE, pe.STOP,
                                               pe.NEEDLE_SET)


@pytest.mark.parametrize("formato", ["jef", "pes", "dst", "vp3", "exp"])
def test_tampoco_aparecen_paradas_al_guardar(tmp_path, formato):
    """Ningun escritor debe INVENTAR una parada donde no la habia."""
    from bordado.imagen.digitalizar import digitalizar

    patron, _, _ = digitalizar(_dragon(tmp_path), ancho_mm=70, n_colores=2,
                               px_por_mm=5.0)
    f = tmp_path / f"d.{formato}"
    pe.write(patron, str(f))
    leido = pe.read(str(f))
    assert leido.count_color_changes() == 0
    assert sum(1 for s in leido.stitches
               if (s[2] & pe.COMMAND_MASK) == pe.STOP) == 0


def test_los_perfiles_ordenan_de_mas_a_menos_paradas():
    """
    Cortar detiene la maquina; saltar no, pero deja un hilo suelto. El perfil
    elige ese compromiso, y tiene que ser monotono.
    """
    assert (PERFILES["alta"].salto_max_sin_corte_mm
            < PERFILES["equilibrada"].salto_max_sin_corte_mm
            < PERFILES["rapida"].salto_max_sin_corte_mm)


def test_menos_cortes_con_el_umbral_alto(tmp_path):
    from bordado.imagen.digitalizar import digitalizar

    cortes = {}
    for perfil in ("alta", "rapida"):
        patron, _, _ = digitalizar(_dragon(tmp_path), ancho_mm=70, n_colores=2,
                                   px_por_mm=5.0, perfil=perfil)
        cortes[perfil] = analizar(patron).cortes
    assert cortes["rapida"] <= cortes["alta"]


def test_el_recorrido_se_mide_tambien_a_traves_de_los_cortes():
    """
    El cabezal se mueve igual despues de cortar. Si no se contara ese tramo,
    el recorrido informado saldria mucho menor que el real.
    """
    p = pe.EmbPattern()
    p.add_thread({"hex": "#000000"})
    p.move_abs(0, 0)
    p.stitch_abs(100, 0)
    p.trim()
    p.move_abs(1000, 0)          # 90 mm de viaje despues del corte
    p.stitch_abs(1100, 0)
    p.end()
    a = analizar(p)
    assert a.recorrido_mm > 80
