"""
Tests del simulador de bordado.

El simulador es una herramienta de DIAGNOSTICO: si el guion miente, el
diagnostico miente. Por eso lo que se prueba aqui no es que "se vea bonito",
sino que cada trazo corresponda de verdad a lo que hace la maquina:

  - que una puntada sea una puntada y un salto sea un salto,
  - que el corte de hilo quede anclado en el trazo correcto,
  - que el eje Y quede dado vuelta (el bordado mira hacia arriba, el
    lienzo del navegador hacia abajo),
  - y que el HTML sea autonomo, porque se manda por correo a gente que no
    tiene el programa instalado ni necesariamente internet.
"""

import json
import math
import re

import pyembroidery as pe
import pytest

from bordado.geometria import circulo
from bordado.parametros import PERFILES, ParamGlobales, ParamRelleno
from bordado.patron import ConstructorPatron
from bordado.puntadas import relleno_tatami
from bordado.simular import (
    PUNTADA_MIN_MM, UNIDADES_POR_MM, Guion, Trazo, escribir_html, guionizar,
    simular,
)


def hilo(rgb: tuple[int, int, int], nombre: str) -> pe.EmbThread:
    h = pe.EmbThread()
    h.set_color(*rgb)
    h.description = nombre
    return h


def construir(comandos, hilos=((200, 10, 10, "Rojo"),)) -> pe.EmbPattern:
    """Patron crudo: (comando, x_mm, y_mm) en milimetros."""
    p = pe.EmbPattern()
    for r, g, b, nombre in hilos:
        p.add_thread(hilo((r, g, b), nombre))
    for cmd, x, y in comandos:
        p.add_stitch_absolute(cmd, x * UNIDADES_POR_MM, y * UNIDADES_POR_MM)
    p.end()
    return p


# ------------------------------------------------------------- puntadas

def test_una_corrida_da_un_trazo_menos_que_puntadas():
    """Tres perforaciones son dos tramos de hilo, no tres."""
    g = guionizar(construir([(pe.STITCH, 0, 0), (pe.STITCH, 3, 0),
                             (pe.STITCH, 6, 0)]))
    assert len(g.trazos) == 2
    assert all(t.tipo == "puntada" for t in g.trazos)


def test_los_trazos_van_encadenados():
    """El final de un trazo es el principio del siguiente: la aguja no teletransporta."""
    g = guionizar(construir([(pe.STITCH, 0, 0), (pe.STITCH, 3, 0),
                             (pe.STITCH, 3, 4)]))
    a, b = g.trazos
    assert (a.x2, a.y2) == (b.x1, b.y1)


def test_el_eje_y_queda_dado_vuelta():
    """
    En el bordado Y crece hacia arriba; en el lienzo del navegador, hacia
    abajo. Si no se invierte, la vista previa sale espejada y el diagnostico
    apunta al lado equivocado de la tela.
    """
    g = guionizar(construir([(pe.STITCH, 0, 0), (pe.STITCH, 0, 10)]))
    t = g.trazos[0]
    assert t.y1 == pytest.approx(0.0)
    assert t.y2 == pytest.approx(-10.0)


def test_las_medidas_estan_en_milimetros():
    g = guionizar(construir([(pe.STITCH, 0, 0), (pe.STITCH, 40, 0),
                             (pe.STITCH, 40, 25)]))
    assert g.ancho_mm == pytest.approx(40.0)
    assert g.alto_mm == pytest.approx(25.0)


# ---------------------------------------------------------------- saltos

def test_el_salto_se_dibuja_desde_donde_quedo_la_aguja():
    g = guionizar(construir([(pe.STITCH, 0, 0), (pe.STITCH, 3, 0),
                             (pe.JUMP, 50, 0), (pe.STITCH, 50, 0),
                             (pe.STITCH, 53, 0)]))
    saltos = [t for t in g.trazos if t.tipo == "salto"]
    assert len(saltos) == 1
    assert (saltos[0].x1, saltos[0].x2) == (3.0, 50.0)


def test_tras_un_salto_no_se_inventa_una_puntada():
    """
    El tramo entre la ultima costura y el nuevo punto ya es el salto. Si
    ademas se contara como puntada, el simulador dibujaria hilo donde no lo hay.
    """
    g = guionizar(construir([(pe.STITCH, 0, 0), (pe.STITCH, 3, 0),
                             (pe.JUMP, 50, 0), (pe.STITCH, 50, 0),
                             (pe.STITCH, 53, 0)]))
    puntadas = [t for t in g.trazos if t.tipo == "puntada"]
    assert len(puntadas) == 2                    # 0-3 y 50-53
    assert not any(t.x1 == 3.0 and t.tipo == "puntada" and t.x2 == 50.0
                   for t in g.trazos)


def test_salto_largo_queda_avisado():
    g = guionizar(construir([(pe.STITCH, 0, 0), (pe.STITCH, 3, 0),
                             (pe.JUMP, 60, 0), (pe.STITCH, 60, 0),
                             (pe.STITCH, 63, 0)]), salto_largo_mm=12.0)
    salto = next(t for t in g.trazos if t.tipo == "salto")
    assert salto.aviso == "salto_largo"


def test_salto_corto_no_queda_avisado():
    g = guionizar(construir([(pe.STITCH, 0, 0), (pe.STITCH, 3, 0),
                             (pe.JUMP, 8, 0), (pe.STITCH, 8, 0),
                             (pe.STITCH, 11, 0)]), salto_largo_mm=12.0)
    salto = next(t for t in g.trazos if t.tipo == "salto")
    assert salto.aviso == ""


# ---------------------------------------------------------------- cortes

def test_el_corte_apunta_al_trazo_donde_ocurre():
    g = guionizar(construir([(pe.STITCH, 0, 0), (pe.STITCH, 3, 0),
                             (pe.TRIM, 3, 0),
                             (pe.JUMP, 50, 0), (pe.STITCH, 50, 0),
                             (pe.STITCH, 53, 0)]))
    assert g.cortes == [1]
    # El trazo 1 es justamente el salto que sigue al corte.
    assert g.trazos[1].tipo == "salto"


def test_el_corte_rompe_la_continuidad_de_la_costura():
    """Despues de cortar no puede quedar un hilo uniendo las dos zonas."""
    g = guionizar(construir([(pe.STITCH, 0, 0), (pe.STITCH, 3, 0),
                             (pe.TRIM, 3, 0),
                             (pe.STITCH, 40, 0), (pe.STITCH, 43, 0)]))
    assert all(t.tipo != "puntada" or abs(t.x2 - t.x1) < 10 for t in g.trazos)
    assert len(g.trazos) == 2                     # 0-3 y 40-43


def test_sin_cortes_la_lista_queda_vacia():
    g = guionizar(construir([(pe.STITCH, 0, 0), (pe.STITCH, 3, 0)]))
    assert g.cortes == []


# --------------------------------------------------------------- colores

def test_el_cambio_de_color_avanza_el_indice():
    g = guionizar(construir(
        [(pe.STITCH, 0, 0), (pe.STITCH, 3, 0),
         (pe.COLOR_CHANGE, 3, 0),
         (pe.STITCH, 3, 10), (pe.STITCH, 6, 10)],
        hilos=((200, 10, 10, "Rojo"), (10, 10, 200, "Azul"))))
    assert [t.color for t in g.trazos] == [0, 1]


def test_los_colores_salen_del_patron():
    """
    Se toman los hilos que el patron declara. Ojo: la normalizacion de
    pyembroidery deja solo los hilos que se usan de verdad, asi que para
    ver dos colores tiene que haber dos bloques cosidos.
    """
    g = guionizar(construir(
        [(pe.STITCH, 0, 0), (pe.STITCH, 3, 0),
         (pe.COLOR_CHANGE, 3, 0), (pe.STITCH, 3, 10), (pe.STITCH, 6, 10)],
        hilos=((200, 10, 10, "Rojo"), (10, 10, 200, "Azul"))))
    assert g.colores == ["#C80A0A", "#0A0AC8"]
    assert g.nombres == ["Rojo", "Azul"]


def test_sin_hilos_hay_un_color_por_defecto():
    """Un archivo sin paleta igual se tiene que poder mirar."""
    p = pe.EmbPattern()
    p.add_stitch_absolute(pe.STITCH, 0, 0)
    p.add_stitch_absolute(pe.STITCH, 30, 0)
    p.end()
    g = guionizar(p)
    assert len(g.colores) == 1 and g.colores[0].startswith("#")
    assert len(g.nombres) == 1


def test_el_color_nunca_se_pasa_de_la_paleta():
    """Un cambio de color de mas no puede romper la reproduccion."""
    g = guionizar(construir(
        [(pe.STITCH, 0, 0), (pe.STITCH, 3, 0),
         (pe.COLOR_CHANGE, 3, 0), (pe.STITCH, 3, 10), (pe.STITCH, 6, 10),
         (pe.COLOR_CHANGE, 6, 10), (pe.STITCH, 6, 20), (pe.STITCH, 9, 20)],
        hilos=((200, 10, 10, "Rojo"), (10, 10, 200, "Azul"))))
    assert max(t.color for t in g.trazos) == len(g.colores) - 1


# ---------------------------------------------------------------- avisos

def test_puntada_corta_queda_avisada():
    """Bajo el minimo la maquina puede saltarsela o romper la aguja."""
    corta = PUNTADA_MIN_MM / 2
    g = guionizar(construir([(pe.STITCH, 0, 0), (pe.STITCH, corta, 0)]))
    assert g.trazos[0].aviso == "corta"


def test_puntada_larga_queda_avisada():
    """Sobre 12.1 mm el formato no la puede representar."""
    g = guionizar(construir([(pe.STITCH, 0, 0), (pe.STITCH, 20, 0)]))
    assert g.trazos[0].aviso == "larga"


def test_puntada_normal_no_queda_avisada():
    g = guionizar(construir([(pe.STITCH, 0, 0), (pe.STITCH, 3.5, 0)]))
    assert g.trazos[0].aviso == ""


# ------------------------------------------------------------------ json

def test_el_json_conserva_todos_los_trazos():
    g = guionizar(construir([(pe.STITCH, 0, 0), (pe.STITCH, 3, 0),
                             (pe.JUMP, 50, 0), (pe.STITCH, 50, 0),
                             (pe.STITCH, 53, 0)]))
    d = json.loads(g.a_json())
    assert len(d["trazos"]) == len(g.trazos)
    assert d["ancho"] == pytest.approx(g.ancho_mm, abs=0.01)


def test_el_json_codifica_el_tipo_como_numero():
    """0 = puntada, 1 = salto. Se abrevia porque son miles de trazos."""
    g = guionizar(construir([(pe.STITCH, 0, 0), (pe.STITCH, 3, 0),
                             (pe.JUMP, 50, 0), (pe.STITCH, 50, 0),
                             (pe.STITCH, 53, 0)]))
    tipos = [t[4] for t in json.loads(g.a_json())["trazos"]]
    assert tipos == [0 if t.tipo == "puntada" else 1 for t in g.trazos]


def test_el_json_es_valido_aunque_no_haya_nada():
    d = json.loads(Guion().a_json())
    assert d["trazos"] == [] and d["cortes"] == []


# ------------------------------------------------------------------ html

def test_el_html_se_escribe_y_lleva_el_titulo(tmp_path):
    g = guionizar(construir([(pe.STITCH, 0, 0), (pe.STITCH, 3, 0)]))
    destino = escribir_html(g, tmp_path / "sub" / "vista.html", "Dragon 7x13")
    assert destino.exists()
    texto = destino.read_text(encoding="utf-8")
    assert "Dragon 7x13" in texto
    assert "__TITULO__" not in texto and "__DATOS__" not in texto


def test_el_html_es_autonomo(tmp_path):
    """
    Se manda por correo a clientes: no puede pedir internet ni archivos
    sueltos al lado. Todo el CSS y el JS van dentro.
    """
    g = guionizar(construir([(pe.STITCH, 0, 0), (pe.STITCH, 3, 0)]))
    texto = escribir_html(g, tmp_path / "v.html").read_text(encoding="utf-8")
    assert not re.search(r'src\s*=\s*["\']https?://', texto)
    assert not re.search(r'<link[^>]+href\s*=\s*["\']https?://', texto)
    assert not re.search(r'<script[^>]+src\s*=', texto)


def test_el_html_lleva_los_datos_adentro(tmp_path):
    g = guionizar(construir([(pe.STITCH, 0, 0), (pe.STITCH, 3, 0),
                             (pe.STITCH, 6, 0)]))
    texto = escribir_html(g, tmp_path / "v.html").read_text(encoding="utf-8")
    crudo = re.search(r"const D = (\{.*?\});", texto, re.S).group(1)
    assert len(json.loads(crudo)["trazos"]) == 2


def test_simular_devuelve_ruta_y_guion(tmp_path):
    p = construir([(pe.STITCH, 0, 0), (pe.STITCH, 3, 0)])
    destino, g = simular(p, tmp_path / "v.html", "Prueba")
    assert destino.exists() and len(g.trazos) == 1


# ------------------------------------------------- sobre un diseno de verdad

@pytest.fixture(scope="module")
def patron_disco() -> pe.EmbPattern:
    """Un disco relleno: el caso donde de verdad se buscan fallas."""
    corridas = relleno_tatami(circulo((0, 0), 20, 120), ParamRelleno())
    c = ConstructorPatron(ParamGlobales())
    c.agregar("disco", "#1B4F9C", corridas)
    return c.construir()


def test_el_guion_de_un_diseno_real_tiene_de_todo(patron_disco):
    g = guionizar(patron_disco)
    assert len(g.trazos) > 100
    assert any(t.tipo == "puntada" for t in g.trazos)


def test_los_cortes_apuntan_dentro_del_guion(patron_disco):
    g = guionizar(patron_disco)
    assert all(0 <= i <= len(g.trazos) for i in g.cortes)


def test_el_recorrido_del_guion_coincide_con_el_patron(patron_disco):
    """
    El largo total de hilo del guion tiene que ser el mismo que sale de
    recorrer el patron a mano. Si no coincide, el simulador esta dibujando
    tramos que la maquina no cose.
    """
    g = guionizar(patron_disco)
    del_guion = sum(math.dist((t.x1, t.y1), (t.x2, t.y2))
                    for t in g.trazos if t.tipo == "puntada")

    total, previo = 0.0, None
    for x, y, cmd in patron_disco.get_normalized_pattern().stitches:
        base = cmd & pe.COMMAND_MASK
        punto = (x / UNIDADES_POR_MM, y / UNIDADES_POR_MM)
        if base == pe.STITCH:
            if previo is not None:
                total += math.dist(previo, punto)
            previo = punto
        else:
            previo = None
    assert del_guion == pytest.approx(total, rel=1e-6)


def test_ningun_trazo_se_sale_del_bastidor(patron_disco):
    """Las coordenadas del guion tienen que caer dentro de la caja declarada."""
    g = guionizar(patron_disco)
    xs = [v for t in g.trazos for v in (t.x1, t.x2)]
    ys = [v for t in g.trazos for v in (t.y1, t.y2)]
    assert max(xs) - min(xs) == pytest.approx(g.ancho_mm, abs=0.05)
    assert max(ys) - min(ys) == pytest.approx(g.alto_mm, abs=0.05)
