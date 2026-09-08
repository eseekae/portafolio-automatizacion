"""
Tests del importador de SVG.

Todo se comprueba contra AREAS CONOCIDAS: es la unica forma de saber que un
parser de curvas y transformaciones esta bien. "Se ve parecido" no es un test.
"""

import math

import pytest

from bordado.geometria import area_shoelace
from bordado.imagen.svg import cargar, leer_path, separar

CABECERA = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'


@pytest.fixture
def svg(tmp_path):
    contador = {"n": 0}

    def crear(cuerpo: str):
        contador["n"] += 1
        f = tmp_path / f"t{contador['n']}.svg"
        f.write_text(f"{CABECERA}{cuerpo}</svg>")
        return f
    return crear


def area_de(ruta, ancho=100.0):
    """Areas de todas las formas del archivo, en el orden en que se dibujan."""
    return [abs(area_shoelace(t)) for _, trozos in cargar(ruta, ancho) for t in trozos]


# --------------------------------------------------------------- formas

@pytest.mark.parametrize("cuerpo,esperada", [
    ('<rect x="10" y="10" width="40" height="30" fill="#f00"/>', 1200),
    ('<circle cx="50" cy="50" r="20" fill="#f00"/>', math.pi * 400),
    ('<ellipse cx="50" cy="50" rx="30" ry="15" fill="#f00"/>', math.pi * 450),
    ('<polygon points="10,10 90,10 50,80" fill="#f00"/>', 2800),
    ('<path d="M10 10 L90 10 L90 60 L10 60 Z" fill="#f00"/>', 4000),
    ('<path d="m10 10 l80 0 l0 50 z" fill="#f00"/>', 2000),
    ('<path d="M10 10 H90 V60 H10 Z" fill="#f00"/>', 4000),
    # Arco: medio circulo de radio 20 cerrado por la cuerda.
    ('<path d="M30 50 A20 20 0 1 0 70 50 Z" fill="#f00"/>', math.pi * 400 / 2),
])
def test_las_formas_dan_su_area_exacta(svg, cuerpo, esperada):
    assert area_de(svg(cuerpo))[0] == pytest.approx(esperada, rel=0.03)


def test_las_curvas_de_bezier_se_aplanan_bien(svg):
    """Cuatro cubicas aproximando un circulo de radio 40."""
    k = 40 * 0.5523
    d = (f"M50 10 C{50+k} 10 90 {50-k} 90 50 C90 {50+k} {50+k} 90 50 90 "
         f"C{50-k} 90 10 {50+k} 10 50 C10 {50-k} {50-k} 10 50 10 Z")
    assert area_de(svg(f'<path d="{d}" fill="#f00"/>'))[0] == \
        pytest.approx(math.pi * 1600, rel=0.02)


def test_un_path_vacio_no_rompe():
    assert leer_path("") == []
    assert leer_path("M10 10") == []          # un punto no es una forma


# -------------------------------------------------------- transformaciones

@pytest.mark.parametrize("transform,esperada", [
    ('translate(20,20)', 900),
    ('scale(2)', 3600),
    ('scale(2,3)', 5400),
    ('rotate(45 50 50)', 900),                 # rotar no cambia el area
    ('matrix(2 0 0 3 5 5)', 5400),
])
def test_las_transformaciones_se_aplican(svg, transform, esperada):
    cuerpo = (f'<g transform="{transform}">'
              '<rect x="5" y="5" width="30" height="30" fill="#f00"/></g>')
    assert area_de(svg(cuerpo))[0] == pytest.approx(esperada, rel=0.03)


def test_las_transformaciones_anidadas_se_componen(svg):
    cuerpo = ('<g transform="translate(10,10)"><g transform="scale(2)">'
              '<rect width="10" height="10" fill="#f00"/></g></g>')
    assert area_de(svg(cuerpo))[0] == pytest.approx(400, rel=0.02)


# ------------------------------------------------------------------ color

@pytest.mark.parametrize("relleno,esperado", [
    ('fill="#1B4F9C"', (0x1B, 0x4F, 0x9C)),
    ('fill="#f00"', (255, 0, 0)),
    ('fill="rgb(10,20,30)"', (10, 20, 30)),
    ('fill="blue"', (0, 0, 255)),
    ('style="fill:#123456"', (0x12, 0x34, 0x56)),
])
def test_se_lee_el_color_de_relleno(svg, relleno, esperado):
    f = svg(f'<rect width="20" height="20" {relleno}/>')
    assert cargar(f, 100.0)[0][0] == esperado


@pytest.mark.parametrize("relleno", ['fill="none"', 'fill="url(#grad)"', ''])
def test_lo_que_no_tiene_relleno_se_ignora(svg, relleno):
    """Un trazo sin relleno no se puede bordar, y un degradado tampoco."""
    assert cargar(svg(f'<rect width="20" height="20" {relleno}/>'), 100.0) == []


def test_el_color_se_hereda_del_grupo(svg):
    cuerpo = '<g fill="#00ff00"><circle cx="50" cy="50" r="20"/></g>'
    assert cargar(svg(cuerpo), 100.0)[0][0] == (0, 255, 0)


def test_el_texto_sin_convertir_se_ignora(svg):
    """Bordar texto exige convertirlo a curvas antes de exportar."""
    assert cargar(svg('<text x="10" y="10" fill="#000">hola</text>'), 100.0) == []


# ------------------------------------------------------------------ huecos

def test_los_subtrazados_de_un_path_forman_huecos(svg):
    """Es como el SVG expresa la contra de una "o": dos anillos en un path."""
    d = ('M50 10 A40 40 0 1 0 50 90 A40 40 0 1 0 50 10 Z '
         'M50 30 A20 20 0 1 1 50 70 A20 20 0 1 1 50 30 Z')
    figuras = separar(cargar(svg(f'<path d="{d}" fill="#f00"/>'), 100.0))
    assert len(figuras) == 1
    _, exterior, huecos = figuras[0]
    assert len(huecos) == 1
    neta = abs(area_shoelace(exterior)) - abs(area_shoelace(huecos[0]))
    assert neta == pytest.approx(math.pi * (1600 - 400), rel=0.04)


# --------------------------------------------- apilado (modelo del pintor)

def test_lo_que_queda_tapado_no_se_cose(svg):
    """
    Tres discos concentricos de colores alternos. Bordados tal cual serian
    tres discos completos superpuestos: el triple de hilo y los colores
    mezclandose. Cada uno debe coserse solo donde queda a la vista.
    """
    cuerpo = ('<circle cx="50" cy="50" r="40" fill="#1a3e6e"/>'
              '<circle cx="50" cy="50" r="30" fill="#f0e8d2"/>'
              '<circle cx="50" cy="50" r="20" fill="#1a3e6e"/>')
    figuras = separar(cargar(svg(cuerpo), 100.0))
    assert len(figuras) == 3
    cosida = sum(abs(area_shoelace(e)) - sum(abs(area_shoelace(h)) for h in hs)
                 for _, e, hs in figuras)
    # La superficie total cosida es la del disco mayor: ni un mm2 repetido.
    assert cosida == pytest.approx(math.pi * 1600, rel=0.03)
    assert len(figuras[0][2]) == 1 and len(figuras[1][2]) == 1


def test_solo_se_resta_lo_contenido_por_completo(svg):
    """
    Dos formas que se cruzan a medias no se pueden restar sin recorte de
    poligonos de verdad. Se cosen enteras (con solape) en vez de recortar mal.
    """
    cuerpo = ('<rect x="10" y="10" width="40" height="40" fill="#f00"/>'
              '<rect x="30" y="30" width="40" height="40" fill="#0f0"/>')
    figuras = separar(cargar(svg(cuerpo), 100.0))
    assert len(figuras) == 2
    assert figuras[0][2] == [] and figuras[1][2] == []


def test_lo_anidado_se_asigna_a_su_dueno_inmediato(svg):
    """
    Con A dentro de B dentro de C, restarle A a C ademas de a B volveria a
    rellenar ese hueco por la regla par-impar.
    """
    cuerpo = ('<rect x="0" y="0" width="90" height="90" fill="#100000"/>'
              '<rect x="20" y="20" width="50" height="50" fill="#200000"/>'
              '<rect x="35" y="35" width="20" height="20" fill="#300000"/>')
    figuras = separar(cargar(svg(cuerpo), 100.0))
    assert [len(h) for _, _, h in figuras] == [1, 1, 0]


# --------------------------------------------------------------- escalado

def test_el_dibujo_se_lleva_al_ancho_pedido(svg):
    f = svg('<rect x="0" y="0" width="100" height="50" fill="#f00"/>')
    pts = cargar(f, 80.0)[0][1][0]
    xs = [p[0] for p in pts]
    assert max(xs) - min(xs) == pytest.approx(80.0, rel=0.01)


def test_el_eje_y_queda_hacia_arriba(svg):
    """El SVG tiene Y hacia abajo y el bordado hacia arriba."""
    f = svg('<rect x="0" y="0" width="20" height="20" fill="#f00"/>')
    ys = [p[1] for p in cargar(f, 100.0)[0][1][0]]
    # Un rectangulo pegado al borde superior del SVG queda ARRIBA en el bordado.
    assert min(ys) > 0


# --------------------------------------------------------- pipeline entero

def test_un_svg_produce_una_matriz_valida(svg, tmp_path):
    import pyembroidery as pe

    from bordado.imagen.digitalizar import digitalizar
    from bordado.parametros import AROS, ParamGlobales
    from bordado.validador import validar

    cuerpo = ('<circle cx="50" cy="50" r="40" fill="#1a3e6e"/>'
              '<circle cx="50" cy="50" r="25" fill="#f0e8d2"/>')
    g = ParamGlobales(aro=AROS["brother_5x7"])
    patron, d, s = digitalizar(svg(cuerpo), ancho_mm=70, g=g)

    assert s is None                       # no hubo segmentacion: era vectorial
    assert len(d.regiones) == 2
    assert len(d.hilos_usados) == 2
    assert validar(patron, g).ok
    f = tmp_path / "s.jef"
    pe.write(patron, str(f))
    assert pe.read(str(f)).stitches


def test_un_svg_sin_formas_rellenas_avisa(svg):
    from bordado.imagen.digitalizar import digitalizar
    with pytest.raises(ValueError, match="relleno"):
        digitalizar(svg('<rect width="20" height="20" fill="none"/>'),
                    ancho_mm=50)
