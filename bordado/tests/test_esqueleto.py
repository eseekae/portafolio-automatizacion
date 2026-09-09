"""
Tests de la descomposicion en trazos.

Este modulo existe por una razon concreta y medida: los numeros chicos de una
insignia salian como garabatos. Se probaron dos caminos que NO funcionan y
estan documentados en el codigo para que nadie los repita:

  - recorrer el contorno: la puntada y el avance son lo mismo, asi que para
    respetar la puntada minima hay que muestrear cada 0.7 mm, y un digito de
    2 mm queda reducido a doce puntos;
  - rellenar con trama: los giros de fin de fila caen a 0.35 mm y el filtro de
    puntadas cortas los borra.

Lo que si funciona es la columna satin sobre el eje del trazo. Por eso lo que
se prueba aqui es que el eje sea fiel: si el eje miente, la letra sale mal.
"""

import math

import pytest

from bordado.geometria import circulo
from bordado.imagen.esqueleto import (
    PIXELES_MAX, PX_POR_MM, adelgazar, medir_ancho, ramas, rasterizar,
    suavizar, trazos_de_region,
)
from bordado.parametros import ParamSatin
from bordado.puntadas import satin_por_eje


def franja(largo: float, ancho: float) -> list[tuple[float, float]]:
    return [(0, 0), (largo, 0), (largo, ancho), (0, ancho)]


def largo_de(puntos) -> float:
    return sum(math.dist(puntos[k], puntos[k + 1]) for k in range(len(puntos) - 1))


# ------------------------------------------------------------ rasterizado

def test_la_mascara_cubre_la_figura():
    m, x0, y0, ppmm = rasterizar(franja(10.0, 2.0), [])
    # Area en pixeles / ppmm^2 tiene que dar el area en mm2, con el margen
    # de un pixel por el redondeo del borde.
    area = m.sum() / (ppmm * ppmm)
    assert area == pytest.approx(20.0, rel=0.05)


def test_los_huecos_quedan_vacios():
    """La contra de un '8' no se cose: la regla par-impar sale gratis."""
    m, _, _, ppmm = rasterizar(circulo((0, 0), 3.0, 60), [circulo((0, 0), 1.5, 60)])
    area = m.sum() / (ppmm * ppmm)
    esperada = math.pi * (3.0 ** 2 - 1.5 ** 2)
    assert area == pytest.approx(esperada, rel=0.05)


def test_una_figura_grande_baja_la_resolucion():
    """El costo va con el area: sin tope, una figura larga tarda segundos."""
    m, _, _, ppmm = rasterizar(franja(400.0, 40.0), [])
    assert m.size <= PIXELES_MAX * 1.2
    assert ppmm >= 4.0
    # Y una figura normal conserva la resolucion completa.
    _, _, _, fina = rasterizar(franja(12.0, 1.0), [])
    assert fina == PX_POR_MM


# ------------------------------------------------ distancia y adelgazado

def test_el_ancho_se_mide_perpendicular_al_trazo():
    """
    Se mide el ANCHO del trazo, no la distancia al borde mas cercano.

    La distancia al borde puede salirse por una punta y subestimar; el ancho
    perpendicular es lo que de verdad tiene que cubrir la columna satin.
    """
    m, _, _, ppmm = rasterizar(franja(20.0, 2.0), [])
    alto, ancho = m.shape
    # En el medio de la franja, avanzando en horizontal.
    semi = medir_ancho(m, alto // 2, ancho // 2, 0, 1) / ppmm
    assert semi == pytest.approx(1.0, abs=0.15)             # semiancho = 1 mm


def test_el_adelgazado_deja_una_linea():
    m, _, _, _ = rasterizar(franja(20.0, 2.0), [])
    esq = adelgazar(m)
    assert esq.any()
    assert esq.sum() < m.sum() / 5          # mucho mas fino que la mancha
    # Y cae dentro de la figura, no fuera.
    assert not (esq & ~m).any()


def test_el_adelgazado_no_parte_la_figura():
    """Zhang-Suen solo borra pixeles que no desconectan: una franja sigue
    siendo una sola linea."""
    m, _, _, _ = rasterizar(franja(20.0, 2.0), [])
    esq = adelgazar(m)
    assert len(ramas(esq)) == 1


# -------------------------------------------------------------- trazos

def test_una_franja_da_un_trazo_por_su_medio():
    tr = trazos_de_region(franja(20.0, 0.6), [])
    assert len(tr) == 1
    puntos, semi = tr[0]
    assert largo_de(puntos) == pytest.approx(20.0, rel=0.15)
    assert sum(semi) / len(semi) == pytest.approx(0.30, abs=0.06)


def test_el_semiancho_sigue_al_trazo():
    """Un trazo que se ensancha tiene que dar semianchos crecientes."""
    cuna = [(0, 0), (20, 0), (20, 3.0), (0, 0.6)]
    tr = trazos_de_region(cuna, [])
    assert tr
    puntos, semi = max(tr, key=lambda t: largo_de(t[0]))
    # Se compara el semiancho al principio y al final del trazo.
    if puntos[0][0] > puntos[-1][0]:
        semi = semi[::-1]
    assert semi[-1] > semi[0]


def test_una_ele_da_dos_trazos():
    """Cada brazo es un trazo con su propia direccion: se cosen aparte."""
    L = [(0, 0), (0.8, 0), (0.8, 5.2), (6, 5.2), (6, 6), (0, 6)]
    assert len(trazos_de_region(L, [])) == 2


def test_un_anillo_se_recorre_entero():
    """La contra de un '8': el eje tiene que dar la vuelta completa."""
    tr = trazos_de_region(circulo((0, 0), 2.0, 60), [circulo((0, 0), 1.4, 60)])
    assert tr
    total = sum(largo_de(p) for p, _ in tr)
    assert total == pytest.approx(2 * math.pi * 1.7, rel=0.25)


def test_las_espinas_no_se_cosen():
    """
    Adelgazar una figura con esquinas deja apendices que no son trazos del
    dibujo. Cosidos aparte fragmentan la letra en parches.
    """
    # Un rectangulo gordo: su esqueleto ideal es UNA linea; las esquinas
    # generan espinas hacia los vertices.
    tr = trazos_de_region(franja(12.0, 2.0), [])
    assert len(tr) <= 2, f"quedaron {len(tr)} trazos: no se podaron las espinas"


def test_el_trazo_llega_hasta_las_puntas():
    """
    El adelgazado se detiene antes del borde. Sin alargar, la columna satin
    deja las puntas sin cubrir y en una letra eso se ve como un palo cortado.
    """
    largo = 20.0
    puntos, _ = trazos_de_region(franja(largo, 1.0), [])[0]
    assert largo_de(puntos) > largo * 0.9


def test_una_figura_vacia_no_revienta():
    assert trazos_de_region([(0, 0), (0, 0), (0, 0)], []) == []


# ------------------------------------------------------------ suavizado

def test_el_suavizado_quita_el_temblor_sin_acortar():
    """El esqueleto avanza por pixeles y zigzaguea; eso se ve en la tela."""
    tembloroso = [(i * 0.5, 0.1 if i % 2 else -0.1) for i in range(20)]
    suave = suavizar(tembloroso)
    desvio = lambda ps: sum(abs(p[1]) for p in ps) / len(ps)
    assert desvio(suave) < desvio(tembloroso) / 2
    assert suave[0] == tembloroso[0] and suave[-1] == tembloroso[-1]


def test_un_trazo_corto_no_se_suaviza():
    corto = [(0, 0), (1, 0)]
    assert suavizar(corto) == corto


# ------------------------------------------- lo que hace posible todo esto

def test_la_columna_satin_supera_la_puntada_minima():
    """
    LA razon de ser del modulo.

    En una columna satin dos perforaciones seguidas caen en lados OPUESTOS
    del trazo, asi que la puntada mide el ANCHO del trazo mientras que el
    avance a lo largo es de solo 0.35 mm. Por eso se puede bordar detalle mas
    fino que la puntada mas corta que admite la maquina.
    """
    eje = [(x * 0.5, 0.0) for x in range(20)]
    semi = [0.3] * len(eje)             # trazo de 0.6 mm: bajo el minimo
    p = ParamSatin(densidad_mm=0.35, compensacion_mm=0.05, underlay="none")
    corridas = satin_por_eje(eje, semi, p, ancho_minimo_mm=0.7)
    assert corridas
    puntos = corridas[0]
    largos = [math.dist(puntos[i], puntos[i + 1]) for i in range(len(puntos) - 1)]
    assert min(largos) >= 0.7, "hay puntadas bajo el minimo: el filtro las borraria"

    # Y aun asi el dibujo se resuelve cada 0.35 mm.
    de_un_riel = puntos[0::2]
    avance = [math.dist(de_un_riel[i], de_un_riel[i + 1])
              for i in range(len(de_un_riel) - 1)]
    assert sum(avance) / len(avance) == pytest.approx(0.35, abs=0.1)


def test_el_satin_no_deja_dos_penetraciones_seguidas_en_el_mismo_riel():
    """
    Alternar el orden de los rieles (a,b / b,a) parece mas elegante y es un
    error: deja dos perforaciones seguidas del mismo lado, separadas solo por
    el avance. Ya se cometio una vez en este proyecto.
    """
    eje = [(x * 0.5, 0.0) for x in range(12)]
    p = ParamSatin(densidad_mm=0.4, compensacion_mm=0.0, underlay="none")
    puntos = satin_por_eje(eje, [0.5] * len(eje), p)[0]
    lados = [1 if q[1] > 0 else -1 for q in puntos]
    assert all(lados[i] != lados[i + 1] for i in range(len(lados) - 1))


def test_el_satin_ensancha_lo_que_es_mas_fino_que_la_puntada():
    """Pull compensation: sin esto, un trazo de 0.4 mm no se coseria."""
    eje = [(x * 0.5, 0.0) for x in range(10)]
    p = ParamSatin(densidad_mm=0.4, compensacion_mm=0.0, underlay="none")
    puntos = satin_por_eje(eje, [0.2] * len(eje), p, ancho_minimo_mm=0.8)[0]
    ancho = max(q[1] for q in puntos) - min(q[1] for q in puntos)
    assert ancho == pytest.approx(0.8, abs=0.05)


def test_sin_eje_no_hay_satin():
    p = ParamSatin()
    assert satin_por_eje([], [], p) == []
    assert satin_por_eje([(0, 0)], [0.3], p) == []
    assert satin_por_eje([(0, 0), (1, 0)], [0.3], p) == []   # largos distintos


# --------------------------------------------- pelos: mas finos que la puntada

def test_un_pelo_no_se_engorda_hasta_la_puntada_minima():
    """
    Un trazo de 0.4 mm ensanchado a 0.7 deja de parecerse a la letra: en un
    "8" o un "3" se cierran los huecos. Por eso, cuando el trazo es mas fino
    que la puntada minima, se cose una corrida triple POR EL EJE en vez de una
    columna satin: deja una linea del grosor del hilo, que es justo lo que
    mide el trazo.

    Ojo, POR EL EJE. Recorrer el contorno es otra cosa y no funciona: ahi la
    puntada y el avance son lo mismo.
    """
    from bordado.parametros import ParamRecta
    from bordado.puntadas import puntada_triple
    eje = [(x * 0.5, 0.0) for x in range(20)]
    corridas = puntada_triple(eje, ParamRecta(largo_mm=1.2))
    assert corridas
    puntos = corridas[0]
    largos = [math.dist(puntos[i], puntos[i + 1]) for i in range(len(puntos) - 1)]
    # La puntada avanza a lo largo del trazo, asi que puede ser larga. El cero
    # es el punto donde la triple da la vuelta; el constructor lo filtra.
    assert min(x for x in largos if x > 1e-9) >= 0.6
    # Y no se sale de la linea: el ancho cubierto es el del hilo, no mas.
    assert max(abs(q[1]) for q in puntos) < 1e-6


# --------------------------------------------------- contornos: dos orillas

def test_el_contorno_se_cose_de_una_sola_pasada():
    """
    LA solucion al borde punteado.

    Por el eje medial, un contorno de 15 cm salia partido en unos 160 tramos
    -el adelgazado inventa una bifurcacion en cada irregularidad del borde- y
    cada union dejaba una muesca. Entre las dos orillas es UNA sola columna
    que da la vuelta completa: no puede tener muescas.
    """
    from bordado.geometria import circulo
    from bordado.puntadas import satin_de_anillo
    corridas = satin_de_anillo(circulo((0, 0), 20, 200), circulo((0, 0), 19, 200),
                               ParamSatin(densidad_mm=0.4, compensacion_mm=0.0))
    assert len(corridas) == 1, "el contorno tiene que ser una sola corrida"


def test_los_rieles_del_contorno_son_sus_propias_orillas():
    """No se calcula nada intermedio: los dos rieles ya existen."""
    from bordado.geometria import circulo
    from bordado.puntadas import satin_de_anillo
    puntos = satin_de_anillo(circulo((0, 0), 20, 200), circulo((0, 0), 19, 200),
                             ParamSatin(densidad_mm=0.4, compensacion_mm=0.0))[0]
    radios = [math.hypot(*q) for q in puntos]
    assert min(radios) == pytest.approx(19.0, abs=0.05)
    assert max(radios) == pytest.approx(20.0, abs=0.05)


def test_la_puntada_del_contorno_cruza_la_columna():
    """Cada puntada mide el ANCHO del contorno, no el avance."""
    from bordado.geometria import circulo
    from bordado.puntadas import satin_de_anillo
    puntos = satin_de_anillo(circulo((0, 0), 20, 200), circulo((0, 0), 19, 200),
                             ParamSatin(densidad_mm=0.4, compensacion_mm=0.0))[0]
    largos = [math.dist(puntos[i], puntos[i + 1]) for i in range(len(puntos) - 1)]
    assert min(largos) >= 0.9


def test_un_contorno_al_reves_igual_se_empareja():
    """
    El hueco suele venir con el giro contrario. Sin orientarlo igual, la
    columna cruza la figura en diagonal y sale un ovillo.
    """
    from bordado.geometria import circulo
    from bordado.puntadas import satin_de_anillo
    hueco_al_reves = circulo((0, 0), 19, 200)[::-1]
    puntos = satin_de_anillo(circulo((0, 0), 20, 200), hueco_al_reves,
                             ParamSatin(densidad_mm=0.4, compensacion_mm=0.0))[0]
    largos = [math.dist(puntos[i], puntos[i + 1]) for i in range(len(puntos) - 1)]
    # Si el emparejamiento fallara, habria puntadas que cruzan el circulo.
    assert max(largos) < 3.0


def test_un_contorno_finisimo_se_ensancha_hasta_la_puntada_minima():
    """Sin esto, el filtro de puntadas cortas se llevaria el contorno entero."""
    from bordado.geometria import circulo
    from bordado.puntadas import satin_de_anillo
    puntos = satin_de_anillo(circulo((0, 0), 20, 200), circulo((0, 0), 19.7, 200),
                             ParamSatin(densidad_mm=0.4, compensacion_mm=0.0),
                             ancho_minimo_mm=0.7)[0]
    largos = [math.dist(puntos[i], puntos[i + 1]) for i in range(len(puntos) - 1)]
    assert min(largos) == pytest.approx(0.7, abs=0.01)
