"""
Tests de la auto-digitalizacion: segmentacion, hilos y pipeline completo.
"""

from pathlib import Path

import numpy as np
import pyembroidery as pe
import pytest
from PIL import Image, ImageDraw

from bordado.imagen import segmentar as seg
from bordado.imagen.digitalizar import (
    Region, _describir, decidir, digitalizar, elegir_tecnica,
    extraer_regiones, ordenar,
)
from bordado.imagen.hilos import catalogo, elegir
from bordado.parametros import AROS, ParamGlobales
from bordado.validador import validar

AZUL, CREMA, ROJO = (26, 62, 110), (240, 232, 210), (170, 40, 45)


@pytest.fixture
def logo(tmp_path):
    """Tres colores planos, con un anillo que deja un hueco real."""
    img = Image.new("RGB", (300, 300), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.ellipse([20, 20, 280, 280], fill=AZUL)
    d.ellipse([50, 50, 250, 250], fill=CREMA)
    d.ellipse([80, 80, 220, 220], fill=AZUL)      # -> el crema queda como anillo
    d.rectangle([120, 130, 180, 170], fill=ROJO)
    f = tmp_path / "logo.png"
    img.save(f)
    return f


# --------------------------------------------------------------- color

def test_lab_contra_valores_de_referencia():
    """Si esta conversion se desvia, todo el agrupamiento de color se corrompe."""
    esperado = {(255, 255, 255): (100.0, 0.0, 0.0),
                (0, 0, 0): (0.0, 0.0, 0.0),
                (255, 0, 0): (53.24, 80.09, 67.20),
                (0, 0, 255): (32.30, 79.19, -107.86)}
    for rgb, lab in esperado.items():
        assert seg.rgb_a_lab(np.array(rgb)) == pytest.approx(lab, abs=0.02)


def test_segmentacion_es_repetible(logo):
    """Misma imagen y misma semilla -> mismo resultado. k-means parte al azar."""
    rgb, fondo = seg.cargar(logo, 40.0, px_por_mm=4.0)
    a = seg.segmentar(rgb, fondo, 3, 4.0, semilla=7)
    b = seg.segmentar(rgb, fondo, 3, 4.0, semilla=7)
    assert np.array_equal(a.etiquetas, b.etiquetas)
    assert np.array_equal(a.colores, b.colores)


def test_detecta_y_recorta_el_fondo(logo):
    rgb, fondo = seg.cargar(logo, 40.0, px_por_mm=4.0)
    assert not fondo.any()                      # el PNG es opaco
    recortado = seg.detectar_fondo(rgb, fondo)
    assert recortado.any()                      # el blanco del borde se marca
    assert not recortado[recortado.shape[0] // 2, recortado.shape[1] // 2]


def test_transparencia_cuenta_como_fondo(tmp_path):
    img = Image.new("RGBA", (60, 60), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse([10, 10, 50, 50], fill=(200, 30, 30, 255))
    f = tmp_path / "t.png"
    img.save(f)
    _, fondo = seg.cargar(f, 30.0, px_por_mm=4.0)
    assert fondo[0, 0] and not fondo[fondo.shape[0] // 2, fondo.shape[1] // 2]


# --------------------------------------------------------------- hilos

def test_las_paletas_no_traen_huecos():
    """pyembroidery reserva posiciones con None; no son colores elegibles."""
    for fmt in ("jef", "pes", "hus"):
        marca, hilos = catalogo(fmt)
        assert hilos and all(h is not None for h in hilos)
        assert marca


@pytest.mark.parametrize("rgb", [(0, 0, 0), (255, 255, 255), (200, 20, 20),
                                 (30, 70, 160), (240, 200, 40), (90, 160, 70)])
def test_el_hilo_elegido_es_el_mas_cercano(rgb):
    """
    Se comprueba la propiedad, no el nombre comercial: ningun otro hilo del
    catalogo puede estar mas cerca en Lab. (Afirmar que el hilo de un rojo se
    llama "red" probaria como bautiza los colores el fabricante, no el codigo:
    el mas cercano a (200,20,20) resulta llamarse "Burnt Orange".)
    """
    elegido = elegir(rgb, "jef")
    _, hilos = catalogo("jef")
    objetivo = seg.rgb_a_lab(np.array(rgb, dtype=np.uint8))
    distancias = [
        float(seg.diferencia(
            seg.rgb_a_lab(np.array([h.get_red(), h.get_green(), h.get_blue()],
                                   dtype=np.uint8)), objetivo))
        for h in hilos]
    assert elegido.delta_e == pytest.approx(min(distancias), abs=1e-9)
    assert elegido.catalogo and elegido.marca == "Janome"


def test_un_color_exacto_se_marca_como_exacto():
    _, hilos = catalogo("jef")
    h = hilos[5]
    elegido = elegir((h.get_red(), h.get_green(), h.get_blue()), "jef")
    assert elegido.delta_e == pytest.approx(0.0, abs=1e-6) and elegido.exacto


# ------------------------------------------------------------- regiones

def test_extrae_regiones_con_huecos(logo):
    rgb, fondo = seg.cargar(logo, 60.0, px_por_mm=5.0)
    s = seg.segmentar(rgb, seg.detectar_fondo(rgb, fondo), 3, 5.0)
    regiones, _, _ = extraer_regiones(s)
    assert regiones
    # El anillo crema debe conservar su hueco: sin eso se cose el centro entero.
    assert any(r.huecos for r in regiones)
    assert all(r.area_mm2 > 0 and r.grosor_mm > 0 for r in regiones)


def test_el_grosor_distingue_franja_de_mancha():
    from bordado.imagen.digitalizar import _describir
    franja = _describir(0, [(0, 0), (60, 0), (60, 2), (0, 2)], [])
    mancha = _describir(0, [(0, 0), (30, 0), (30, 30), (0, 30)], [])
    assert franja.grosor_mm == pytest.approx(2.0, rel=0.05)
    assert mancha.grosor_mm == pytest.approx(15.0, rel=0.05)
    assert franja.elongacion > mancha.elongacion


def test_una_region_alargada_se_cose_a_lo_largo():
    from bordado.imagen.digitalizar import _describir
    franja = _describir(0, [(0, 0), (60, 0), (60, 3), (0, 3)], [])
    assert franja.elongacion > 1.8
    assert decidir(franja).angulo_grados == pytest.approx(franja.angulo, abs=1e-6)

    from bordado.imagen.digitalizar import Region
    compacta = _describir(0, [(0, 0), (20, 0), (20, 20), (0, 20)], [])
    assert decidir(compacta).angulo_grados == 45.0


def test_el_underlay_escala_con_el_area():
    from bordado.imagen.digitalizar import _describir
    grande = _describir(0, [(0, 0), (40, 0), (40, 40), (0, 40)], [])
    media = _describir(0, [(0, 0), (5, 0), (5, 5), (0, 5)], [])
    chica = _describir(0, [(0, 0), (2, 0), (2, 2), (0, 2)], [])
    assert decidir(grande).underlay == "tatami"
    assert decidir(media).underlay == "contorno"
    assert decidir(chica).underlay == "none"


def test_el_orden_agrupa_por_color(logo):
    rgb, fondo = seg.cargar(logo, 60.0, px_por_mm=5.0)
    s = seg.segmentar(rgb, seg.detectar_fondo(rgb, fondo), 3, 5.0)
    regiones, _, _ = extraer_regiones(s)
    colores = [r.color for r in ordenar(regiones)]
    # Cada color aparece en un unico bloque: un cambio de hilo por color.
    bloques = [c for i, c in enumerate(colores) if i == 0 or c != colores[i - 1]]
    assert len(bloques) == len(set(bloques))


# ------------------------------------------------------ pipeline completo

def test_pipeline_produce_una_matriz_valida(logo, tmp_path):
    g = ParamGlobales(aro=AROS["brother_5x7"])
    patron, d, _ = digitalizar(logo, ancho_mm=60, n_colores=3, g=g, px_por_mm=5.0)

    assert d.regiones and d.hilos_usados
    assert patron.stitches
    r = validar(patron, g)
    assert r.ok, r.errores                      # sin puntadas cortas ni fuera de aro
    assert 40 < float(r.metricas["Dimensiones (mm)"].split(" x ")[0]) < 62

    # Debe poder escribirse y releerse en los formatos de maquina.
    for ext in ("jef", "pes", "dst"):
        f = tmp_path / f"s.{ext}"
        pe.write(patron, str(f))
        assert pe.read(str(f)).stitches


def test_solo_se_reportan_los_hilos_que_se_cosen(logo):
    """Un grupo que se queda con el halo de antialias no es un carrete a comprar."""
    _, d, _ = digitalizar(logo, ancho_mm=60, n_colores=6, g=ParamGlobales(),
                          px_por_mm=5.0)
    usados = set(d.hilos_usados)
    assert usados == {r.color for r in d.regiones}
    assert len(usados) <= 6


def test_el_pipeline_es_repetible(logo):
    a, _, _ = digitalizar(logo, ancho_mm=50, n_colores=3, px_por_mm=4.0, semilla=3)
    b, _, _ = digitalizar(logo, ancho_mm=50, n_colores=3, px_por_mm=4.0, semilla=3)
    assert a.stitches == b.stitches


def test_una_imagen_vacia_da_un_error_claro(tmp_path):
    f = tmp_path / "vacia.png"
    Image.new("RGBA", (40, 40), (0, 0, 0, 0)).save(f)
    with pytest.raises(ValueError, match="bordar"):
        digitalizar(f, ancho_mm=40, n_colores=3, px_por_mm=4.0)


# --------------------------------------------------- detalle fino (corridas)
#
# Vienen de un caso real: la insignia de un colegio, 80 mm de ancho. El escudo
# salia bien pero el ano "1813" y el contorno fino desaparecian del bordado.
# El programa los estaba DESCARTANDO por finos, en vez de coserlos como lo
# hace cualquier digitalizador: con una corrida de puntadas sobre el trazo.

@pytest.fixture
def insignia(tmp_path: Path) -> Path:
    """Mancha gorda + un trazo fino de medio milimetro al lado."""
    img = Image.new("RGB", (400, 400), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([(40, 40), (360, 240)], fill=(26, 47, 92))   # mancha rellenable
    # A 60 mm de ancho y 8 px/mm, estos 3 px son ~0.45 mm: demasiado fino para
    # rellenar, perfectamente bordable como linea.
    d.rectangle([(60, 300), (340, 302)], fill=(26, 47, 92))  # trazo fino
    f = tmp_path / "insignia.png"
    img.save(f)
    return f


def franja(largo_mm: float, grosor_mm: float) -> Region:
    """Una franja recta de las medidas pedidas, como region."""
    h = grosor_mm / 2.0
    return _describir(0, [(0, -h), (largo_mm, -h), (largo_mm, h), (0, h)], [])


def test_un_trazo_fino_se_cose_como_corrida():
    """Medio milimetro no se rellena ni se hace satin, pero SI se borda."""
    assert elegir_tecnica(franja(20.0, 0.5)) == "corrida"


def test_una_franja_normal_sigue_yendo_a_satin():
    """La corrida es para lo que no cabe, no un atajo que degrade lo demas."""
    assert elegir_tecnica(franja(20.0, 2.5)) == "satin"


def test_una_mancha_se_sigue_rellenando():
    assert elegir_tecnica(_describir(0, [(0, 0), (20, 0), (20, 20), (0, 20)], [])) \
        == "relleno"


def test_el_ruido_de_antialiasing_no_se_cose():
    """
    Un borde difuso de 0.1 mm no es un trazo del dibujo: es el halo que deja
    reducir la imagen. Coserlo seria bordar basura.
    """
    assert elegir_tecnica(franja(20.0, 0.1)) == "descartar"


def test_una_mota_fina_y_corta_tampoco_se_cose():
    """Fina Y corta: no se leeria como linea ni aunque se cosiera."""
    assert elegir_tecnica(franja(1.0, 0.5)) == "descartar"


def test_el_trazo_fino_llega_hasta_la_matriz(insignia):
    """
    La prueba que importa: el detalle chico tiene que estar en el archivo.

    Se mide donde cae el trazo fino dentro del diseno y se comprueba que hay
    puntadas ahi. Antes no habia ninguna: la region se descartaba entera.
    """
    patron, d, _ = digitalizar(insignia, ancho_mm=60, n_colores=3, px_por_mm=8.0)
    assert d.descartadas == 0, "se siguio descartando detalle"
    assert any(elegir_tecnica(r) == "corrida" for r in d.regiones)

    # El trazo esta en el tercio inferior de la imagen; en el archivo, con Y
    # hacia abajo, eso es el tercio de Y mas alta.
    ys = [y for _, y, _ in patron.get_normalized_pattern().stitches]
    corte = min(ys) + 0.72 * (max(ys) - min(ys))
    assert sum(1 for y in ys if y > corte) > 20, (
        "no hay puntadas donde va el trazo fino")


def test_coser_el_detalle_fino_cuesta_poco(insignia):
    """
    Recuperar el detalle no puede salir caro: son lineas, no rellenos.

    Se compara contra el mismo diseno sin el trazo fino.
    """
    solo_mancha = insignia.with_name("solo_mancha.png")
    img = Image.new("RGB", (400, 400), "white")
    ImageDraw.Draw(img).rectangle([(40, 40), (360, 240)], fill=(26, 47, 92))
    img.save(solo_mancha)

    con, _, _ = digitalizar(insignia, ancho_mm=60, n_colores=3, px_por_mm=8.0)
    sin, _, _ = digitalizar(solo_mancha, ancho_mm=60, n_colores=3, px_por_mm=8.0)
    n_con = con.count_stitch_commands(pe.STITCH)
    n_sin = sin.count_stitch_commands(pe.STITCH)
    assert n_con > n_sin, "el trazo fino no agrego ni una puntada"
    assert n_con < n_sin * 1.5, (
        f"el detalle fino disparo las puntadas: {n_sin} -> {n_con}")
