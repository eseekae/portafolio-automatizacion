"""
Importador de SVG: arte vectorial -> regiones, sin pasar por pixeles.

POR QUE EXISTE
    Digitalizar una imagen obliga a rasterizar, agrupar colores y volver a
    trazar contornos. Si el arte YA es vectorial, todo eso es perdida pura:
    los contornos exactos estan en el archivo y los colores son planos por
    definicion. Importarlos directo evita el rodeo y da bordes limpios.

ALCANCE
    Se soporta el subconjunto que produce cualquier editor (Inkscape,
    Illustrator, Figma) al exportar un logo plano:
      formas    path, rect, circle, ellipse, polygon, polyline, line
      comandos  M L H V C S Q T A Z, absolutos y relativos
      grupos    <g> con transformaciones anidadas
      transform matrix, translate, scale, rotate, skewX, skewY
      relleno   atributo fill y style="fill:..."

    Lo que NO se soporta, y se ignora en silencio porque no se puede bordar:
    degradados, filtros, imagenes incrustadas, texto sin convertir a curvas y
    trazos sin relleno. El texto hay que convertirlo a curvas en el editor
    antes de exportar.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from ..geometria import Polilinea, area_shoelace

# Colores con nombre que aparecen de verdad en exportaciones de editores.
NOMBRES = {
    "black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0),
    "green": (0, 128, 0), "blue": (0, 0, 255), "yellow": (255, 255, 0),
    "gray": (128, 128, 128), "grey": (128, 128, 128), "silver": (192, 192, 192),
    "maroon": (128, 0, 0), "olive": (128, 128, 0), "lime": (0, 255, 0),
    "aqua": (0, 255, 255), "teal": (0, 128, 128), "navy": (0, 0, 128),
    "fuchsia": (255, 0, 255), "purple": (128, 0, 128), "orange": (255, 165, 0),
}

_NUM = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")
_COMANDO = re.compile(r"([MmLlHhVvCcSsQqTtAaZz])")
_TRANSFORMACION = re.compile(r"(\w+)\s*\(([^)]*)\)")


# --------------------------------------------------------------------------
# Matrices afines 2x3: (a, b, c, d, e, f) como en SVG
# --------------------------------------------------------------------------

IDENTIDAD = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _componer(m: tuple, n: tuple) -> tuple:
    a, b, c, d, e, f = m
    a2, b2, c2, d2, e2, f2 = n
    return (a * a2 + c * b2, b * a2 + d * b2,
            a * c2 + c * d2, b * c2 + d * d2,
            a * e2 + c * f2 + e, b * e2 + d * f2 + f)


def _aplicar(m: tuple, x: float, y: float) -> tuple[float, float]:
    a, b, c, d, e, f = m
    return a * x + c * y + e, b * x + d * y + f


def _leer_transform(texto: str) -> tuple:
    m = IDENTIDAD
    for nombre, args in _TRANSFORMACION.findall(texto or ""):
        v = [float(x) for x in _NUM.findall(args)]
        if nombre == "matrix" and len(v) == 6:
            n = tuple(v)
        elif nombre == "translate":
            n = (1, 0, 0, 1, v[0], v[1] if len(v) > 1 else 0.0)
        elif nombre == "scale":
            n = (v[0], 0, 0, v[1] if len(v) > 1 else v[0], 0, 0)
        elif nombre == "rotate":
            a = math.radians(v[0])
            n = (math.cos(a), math.sin(a), -math.sin(a), math.cos(a), 0, 0)
            if len(v) >= 3:      # rotacion alrededor de un punto
                n = _componer(_componer((1, 0, 0, 1, v[1], v[2]), n),
                              (1, 0, 0, 1, -v[1], -v[2]))
        elif nombre == "skewX":
            n = (1, 0, math.tan(math.radians(v[0])), 1, 0, 0)
        elif nombre == "skewY":
            n = (1, math.tan(math.radians(v[0])), 0, 1, 0, 0)
        else:
            continue
        m = _componer(m, n)
    return m


# --------------------------------------------------------------------------
# Color
# --------------------------------------------------------------------------

def _propiedad(elemento: ET.Element, nombre: str) -> str | None:
    """Lee una propiedad de presentacion, mirando primero `style`."""
    for trozo in elemento.get("style", "").split(";"):
        if ":" in trozo:
            k, v = trozo.split(":", 1)
            if k.strip() == nombre:
                return v.strip()
    return elemento.get(nombre)


def _leer_color(elemento: ET.Element, heredado,
                propiedad: str = "fill") -> tuple[int, int, int] | None:
    """Devuelve el color de `propiedad` como RGB, o None si no se borda."""
    valor = _propiedad(elemento, propiedad)
    if valor is None:
        return heredado
    valor = valor.strip().lower()
    if valor in ("none", "transparent"):
        return None
    if valor.startswith("url("):
        return None                  # degradado o patron: no se puede bordar
    if valor.startswith("#"):
        h = valor[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) >= 6:
            return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
        return heredado
    if valor.startswith("rgb"):
        v = [float(x) for x in _NUM.findall(valor)][:3]
        if len(v) == 3:
            return tuple(min(255, max(0, int(round(x)))) for x in v)
    return NOMBRES.get(valor, heredado)


# --------------------------------------------------------------------------
# Aplanado de curvas
# --------------------------------------------------------------------------

def _pasos(*puntos) -> int:
    """
    Cuantos segmentos usar para una curva, segun lo lejos que esten sus
    puntos de control. Una curva chica no necesita 30 tramos y una enorme si.
    """
    largo = sum(math.dist(puntos[i], puntos[i + 1]) for i in range(len(puntos) - 1))
    return max(4, min(64, int(largo / 1.5) + 4))


def _cubica(p0, p1, p2, p3) -> Polilinea:
    n = _pasos(p0, p1, p2, p3)
    salida = []
    for i in range(1, n + 1):
        t = i / n
        u = 1 - t
        salida.append((u**3 * p0[0] + 3*u*u*t * p1[0] + 3*u*t*t * p2[0] + t**3 * p3[0],
                       u**3 * p0[1] + 3*u*u*t * p1[1] + 3*u*t*t * p2[1] + t**3 * p3[1]))
    return salida


def _cuadratica(p0, p1, p2) -> Polilinea:
    n = _pasos(p0, p1, p2)
    salida = []
    for i in range(1, n + 1):
        t = i / n
        u = 1 - t
        salida.append((u*u * p0[0] + 2*u*t * p1[0] + t*t * p2[0],
                       u*u * p0[1] + 2*u*t * p1[1] + t*t * p2[1]))
    return salida


def _arco(p0, rx, ry, giro, arco_grande, barrido, p1) -> Polilinea:
    """
    Arco elíptico de SVG. Se pasa de la forma "punto final" a la forma
    "centro", que es la unica con la que se puede muestrear.
    """
    if rx == 0 or ry == 0 or p0 == p1:
        return [p1]
    rx, ry = abs(rx), abs(ry)
    fi = math.radians(giro)
    cos_f, sin_f = math.cos(fi), math.sin(fi)
    dx2, dy2 = (p0[0] - p1[0]) / 2.0, (p0[1] - p1[1]) / 2.0
    x1 = cos_f * dx2 + sin_f * dy2
    y1 = -sin_f * dx2 + cos_f * dy2

    # Radios demasiado chicos para unir los extremos: se agrandan lo justo.
    lam = (x1 * x1) / (rx * rx) + (y1 * y1) / (ry * ry)
    if lam > 1:
        rx *= math.sqrt(lam)
        ry *= math.sqrt(lam)

    num = rx*rx * ry*ry - rx*rx * y1*y1 - ry*ry * x1*x1
    den = rx*rx * y1*y1 + ry*ry * x1*x1
    factor = math.sqrt(max(num / den, 0.0)) if den else 0.0
    if arco_grande == barrido:
        factor = -factor
    cx1 = factor * rx * y1 / ry
    cy1 = -factor * ry * x1 / rx
    cx = cos_f * cx1 - sin_f * cy1 + (p0[0] + p1[0]) / 2.0
    cy = sin_f * cx1 + cos_f * cy1 + (p0[1] + p1[1]) / 2.0

    def angulo(ux, uy, vx, vy):
        n = math.hypot(ux, uy) * math.hypot(vx, vy)
        if n == 0:
            return 0.0
        c = max(-1.0, min(1.0, (ux * vx + uy * vy) / n))
        a = math.acos(c)
        return -a if ux * vy - uy * vx < 0 else a

    theta = angulo(1, 0, (x1 - cx1) / rx, (y1 - cy1) / ry)
    delta = angulo((x1 - cx1) / rx, (y1 - cy1) / ry,
                   (-x1 - cx1) / rx, (-y1 - cy1) / ry)
    if not barrido and delta > 0:
        delta -= 2 * math.pi
    elif barrido and delta < 0:
        delta += 2 * math.pi

    n = max(6, min(96, int(abs(delta) * max(rx, ry) / 1.5) + 6))
    salida = []
    for i in range(1, n + 1):
        a = theta + delta * i / n
        x = rx * math.cos(a)
        y = ry * math.sin(a)
        salida.append((cos_f * x - sin_f * y + cx, sin_f * x + cos_f * y + cy))
    return salida


# --------------------------------------------------------------------------
# Lectura del atributo d
# --------------------------------------------------------------------------

def leer_path(d: str) -> list[Polilinea]:
    """Convierte el atributo `d` en una lista de subtrazados aplanados."""
    trozos = [t for t in _COMANDO.split(d or "") if t.strip()]
    subtrazados: list[Polilinea] = []
    actual: Polilinea = []
    pos = (0.0, 0.0)
    inicio = (0.0, 0.0)
    ctrl_previo = None
    comando = ""
    i = 0

    while i < len(trozos):
        if _COMANDO.fullmatch(trozos[i]):
            comando = trozos[i]
            i += 1
            args = [float(x) for x in _NUM.findall(trozos[i])] if i < len(trozos) \
                and not _COMANDO.fullmatch(trozos[i]) else []
            if args:
                i += 1
        else:
            args = [float(x) for x in _NUM.findall(trozos[i])]
            i += 1

        rel = comando.islower()
        c = comando.upper()

        if c == "Z":
            if len(actual) >= 3:
                subtrazados.append(actual)
            actual = []
            pos = inicio
            ctrl_previo = None
            continue

        k = 0
        while k < len(args) or (c == "Z"):
            def tomar(n):
                nonlocal k
                v = args[k:k + n]
                k += n
                return v

            if c == "M":
                v = tomar(2)
                if len(v) < 2:
                    break
                pos = (pos[0] + v[0], pos[1] + v[1]) if rel else (v[0], v[1])
                if len(actual) >= 3:
                    subtrazados.append(actual)
                actual = [pos]
                inicio = pos
                c = "L"          # los pares siguientes de una M son lineas
            elif c == "L":
                v = tomar(2)
                if len(v) < 2:
                    break
                pos = (pos[0] + v[0], pos[1] + v[1]) if rel else (v[0], v[1])
                actual.append(pos)
            elif c == "H":
                v = tomar(1)
                if not v:
                    break
                pos = (pos[0] + v[0], pos[1]) if rel else (v[0], pos[1])
                actual.append(pos)
            elif c == "V":
                v = tomar(1)
                if not v:
                    break
                pos = (pos[0], pos[1] + v[0]) if rel else (pos[0], v[0])
                actual.append(pos)
            elif c in ("C", "S"):
                v = tomar(6 if c == "C" else 4)
                if len(v) < (6 if c == "C" else 4):
                    break
                if c == "C":
                    p1 = (pos[0] + v[0], pos[1] + v[1]) if rel else (v[0], v[1])
                    p2 = (pos[0] + v[2], pos[1] + v[3]) if rel else (v[2], v[3])
                    fin = (pos[0] + v[4], pos[1] + v[5]) if rel else (v[4], v[5])
                else:
                    # S refleja el control anterior: es lo que la hace suave.
                    p1 = (2 * pos[0] - ctrl_previo[0], 2 * pos[1] - ctrl_previo[1]) \
                        if ctrl_previo else pos
                    p2 = (pos[0] + v[0], pos[1] + v[1]) if rel else (v[0], v[1])
                    fin = (pos[0] + v[2], pos[1] + v[3]) if rel else (v[2], v[3])
                actual += _cubica(pos, p1, p2, fin)
                ctrl_previo, pos = p2, fin
                continue
            elif c in ("Q", "T"):
                v = tomar(4 if c == "Q" else 2)
                if len(v) < (4 if c == "Q" else 2):
                    break
                if c == "Q":
                    p1 = (pos[0] + v[0], pos[1] + v[1]) if rel else (v[0], v[1])
                    fin = (pos[0] + v[2], pos[1] + v[3]) if rel else (v[2], v[3])
                else:
                    p1 = (2 * pos[0] - ctrl_previo[0], 2 * pos[1] - ctrl_previo[1]) \
                        if ctrl_previo else pos
                    fin = (pos[0] + v[0], pos[1] + v[1]) if rel else (v[0], v[1])
                actual += _cuadratica(pos, p1, fin)
                ctrl_previo, pos = p1, fin
                continue
            elif c == "A":
                v = tomar(7)
                if len(v) < 7:
                    break
                fin = (pos[0] + v[5], pos[1] + v[6]) if rel else (v[5], v[6])
                actual += _arco(pos, v[0], v[1], v[2], int(v[3]), int(v[4]), fin)
                pos = fin
            else:
                break
            ctrl_previo = None

    if len(actual) >= 3:
        subtrazados.append(actual)
    return subtrazados


# --------------------------------------------------------------------------
# Formas basicas
# --------------------------------------------------------------------------

def _num(elemento: ET.Element, nombre: str, por_defecto: float = 0.0) -> float:
    v = _NUM.findall(elemento.get(nombre, "") or "")
    return float(v[0]) if v else por_defecto


def _elipse(cx, cy, rx, ry, n=64) -> Polilinea:
    return [(cx + rx * math.cos(2 * math.pi * i / n),
             cy + ry * math.sin(2 * math.pi * i / n)) for i in range(n)]


def _forma(elemento: ET.Element) -> list[Polilinea]:
    etiqueta = elemento.tag.rsplit("}", 1)[-1]
    if etiqueta == "path":
        return leer_path(elemento.get("d", ""))
    if etiqueta == "rect":
        x, y = _num(elemento, "x"), _num(elemento, "y")
        w, h = _num(elemento, "width"), _num(elemento, "height")
        if w <= 0 or h <= 0:
            return []
        return [[(x, y), (x + w, y), (x + w, y + h), (x, y + h)]]
    if etiqueta == "circle":
        r = _num(elemento, "r")
        return [_elipse(_num(elemento, "cx"), _num(elemento, "cy"), r, r)] if r > 0 else []
    if etiqueta == "ellipse":
        rx, ry = _num(elemento, "rx"), _num(elemento, "ry")
        return [_elipse(_num(elemento, "cx"), _num(elemento, "cy"), rx, ry)] \
            if rx > 0 and ry > 0 else []
    if etiqueta in ("polygon", "polyline"):
        v = [float(x) for x in _NUM.findall(elemento.get("points", ""))]
        pts = list(zip(v[0::2], v[1::2]))
        return [pts] if len(pts) >= 3 else []
    return []


# --------------------------------------------------------------------------
# Lectura completa
# --------------------------------------------------------------------------

def _lienzo(raiz: ET.Element) -> tuple[float, float, tuple]:
    """Tamano del dibujo en unidades de usuario y transformacion del viewBox."""
    vb = _NUM.findall(raiz.get("viewBox", "") or "")
    if len(vb) >= 4:
        x, y, w, h = (float(v) for v in vb[:4])
        if w > 0 and h > 0:
            return w, h, (1, 0, 0, 1, -x, -y)
    w = _num(raiz, "width", 0.0)
    h = _num(raiz, "height", 0.0)
    return (w or 100.0), (h or 100.0), IDENTIDAD


def _factor_escala(matriz: tuple) -> float:
    """
    Cuanto agranda la matriz, en promedio.

    `stroke-width` esta en el sistema de coordenadas del elemento, asi que una
    transformacion que agranda la forma agranda tambien su contorno. Se usa la
    media geometrica de los dos ejes, que es lo que hace SVG cuando la escala
    no es uniforme.
    """
    a, b, c, d = matriz[0], matriz[1], matriz[2], matriz[3]
    det = abs(a * d - b * c)
    return math.sqrt(det) if det > 0 else 1.0


@dataclass
class Trazo:
    """Un contorno del SVG: una linea con grosor, no un area."""
    color: tuple[int, int, int]
    puntos: Polilinea
    ancho_mm: float
    cerrado: bool


def leer(ruta: Path, ancho_mm: float
         ) -> tuple[list[tuple[tuple[int, int, int], list[Polilinea]]],
                    list[Trazo]]:
    """
    Lee el SVG UNA vez y devuelve (rellenos, trazos).

    `rellenos` son [(color RGB, subtrazados en mm), ...] EN ORDEN DE DIBUJO,
    que es el que hay que respetar: en SVG lo que viene despues tapa lo
    anterior.

    `trazos` son los contornos (`stroke`). Antes se ignoraban por completo y
    era un agujero grande: en un logo, el contorno blanco de un escudo o el
    marco de una cinta casi nunca es un relleno, es un trazo. Si solo se leen
    los rellenos, esas piezas no llegan al bordado y no hay forma de que el
    usuario las recupere.

    Todo viene ya escalado al ancho pedido, con el eje Y invertido (el SVG lo
    tiene hacia abajo y el bordado hacia arriba) y centrado en el origen. Los
    rellenos aun NO estan separados en exteriores y huecos: de eso se encarga
    `separar`.
    """
    raiz = ET.parse(ruta).getroot()
    ancho_u, alto_u, base = _lienzo(raiz)
    escala = ancho_mm / ancho_u if ancho_u else 1.0

    formas: list[tuple[tuple[int, int, int], list[Polilinea]]] = []
    lineas: list[tuple[tuple[int, int, int], Polilinea, float, bool]] = []

    def recorrer(elemento: ET.Element, matriz: tuple, color, borde, ancho) -> None:
        matriz = _componer(matriz, _leer_transform(elemento.get("transform", "")))
        color = _leer_color(elemento, color)
        borde = _leer_color(elemento, borde, "stroke")
        crudo = _propiedad(elemento, "stroke-width")
        if crudo is not None:
            nums = _NUM.findall(crudo)
            if nums:
                ancho = abs(float(nums[0]))
        etiqueta = elemento.tag.rsplit("}", 1)[-1]

        if etiqueta in ("g", "svg", "a", "switch"):
            for hijo in elemento:
                recorrer(hijo, matriz, color, borde, ancho)
            return
        if etiqueta in ("defs", "clipPath", "mask", "text", "image", "style"):
            return                      # nada de esto se puede bordar
        if color is None and borde is None:
            return                      # ni relleno ni contorno: nada que coser

        # Los subtrazados de UN elemento van juntos: en SVG asi es como se
        # expresa un hueco (la contra de una "o"), con la regla par-impar.
        # Dos elementos distintos, en cambio, son dos formas apiladas.
        crudos = _forma(elemento)
        trozos = [[_aplicar(matriz, x, y) for x, y in c] for c in crudos]

        if color is not None:
            llenos = [t for t in trozos if len(t) >= 3]
            if llenos:
                formas.append((color, llenos))

        if borde is not None and ancho > 0:
            # Un `path` con Z esta cerrado; rect, circle, ellipse y polygon
            # siempre lo estan. Una `polyline` y un path sin Z, no.
            if etiqueta == "path":
                cerrado = "z" in (elemento.get("d", "") or "").lower()
            else:
                cerrado = etiqueta != "polyline"
            # El grosor se mide en el mismo espacio que las coordenadas, asi
            # que la transformacion tambien lo afecta.
            factor = _factor_escala(matriz)
            for t in trozos:
                if len(t) >= 2:
                    lineas.append((borde, t, ancho * factor, cerrado))

    recorrer(raiz, base, None, None, 1.0)

    cx, cy = ancho_u / 2.0, alto_u / 2.0

    def a_mm(t: Polilinea) -> Polilinea:
        return [((x - cx) * escala, (cy - y) * escala) for x, y in t]

    rellenos = [(color, [a_mm(t) for t in trozos]) for color, trozos in formas]
    trazos = [Trazo(color, a_mm(t), ancho * escala, cerrado)
              for color, t, ancho, cerrado in lineas]
    return rellenos, trazos


def cargar(ruta: Path, ancho_mm: float
           ) -> list[tuple[tuple[int, int, int], list[Polilinea]]]:
    """Solo los rellenos. Ver `leer` para el detalle."""
    return leer(ruta, ancho_mm)[0]


def separar(formas: list[tuple[tuple[int, int, int], list[Polilinea]]],
            area_min_mm2: float = 1.0
            ) -> list[tuple[tuple[int, int, int], Polilinea, list[Polilinea]]]:
    """
    Convierte las formas apiladas del SVG en regiones que se puedan bordar.

    EL PROBLEMA
        Un SVG se dibuja como con pintura: lo que viene despues tapa lo
        anterior. Un logo tipico son discos concentricos de colores alternos.
        Bordarlos tal cual significaria coser el disco entero de abajo y
        encima el de arriba: el doble de hilo, la tela acartonada y los
        colores mezclandose por transparencia del hilo.

    LO QUE SE HACE
        Cada forma se cose solo donde va a quedar A LA VISTA: se le restan las
        formas posteriores que caen COMPLETAMENTE dentro de ella. El disco de
        abajo queda como anillo, que es exactamente lo que se ve.

        Solo se restan las contenidas de forma inmediata. Si A contiene a B y
        B contiene a C, restarle C a A tambien volveria a rellenar ese hueco
        por la regla par-impar. C le corresponde a B.

    LIMITACION
        La resta requiere contencion COMPLETA. Dos formas que se solapan a
        medias necesitarian recorte de poligonos de verdad (Shapely), asi que
        ahi se cose el solape dos veces. Se avisa en el informe.
    """
    # 1. Dentro de cada elemento: el subtrazado mayor manda, los contenidos
    #    son huecos suyos (asi expresa el SVG la contra de una letra).
    elementos: list[tuple[tuple[int, int, int], Polilinea, list[Polilinea]]] = []
    for color, trozos in formas:
        trozos = [t for t in trozos if abs(area_shoelace(t)) >= area_min_mm2]
        if not trozos:
            continue
        trozos.sort(key=lambda t: abs(area_shoelace(t)), reverse=True)
        exterior, resto = trozos[0], trozos[1:]
        huecos = [t for t in resto if _contenido(exterior, t)]
        elementos.append((color, exterior, huecos))
        # Un subtrazado que no cae dentro es otra forma suelta del mismo color.
        for suelto in resto:
            if suelto not in huecos:
                elementos.append((color, suelto, []))

    # 2. Entre elementos: se resta lo que quedara tapado por lo posterior.
    figuras: list[tuple[tuple[int, int, int], Polilinea, list[Polilinea]]] = []
    for i, (color, exterior, huecos) in enumerate(elementos):
        tapadores = [j for j in range(i + 1, len(elementos))
                     if _contenido(exterior, elementos[j][1])]
        # Solo los inmediatos: si otro tapador ya lo contiene, no es mio.
        inmediatos = [j for j in tapadores
                      if not any(k != j and _contenido(elementos[k][1],
                                                       elementos[j][1])
                                 for k in tapadores)]
        figuras.append((color, exterior,
                        huecos + [elementos[j][1] for j in inmediatos]))
    return figuras


def _contenido(externo: Polilinea, interno: Polilinea, muestras: int = 12) -> bool:
    """
    True si `interno` cae completamente dentro de `externo`.

    Se comprueban varios puntos repartidos, no solo el primero: dos formas que
    se cruzan tendrian algunos dentro y otros fuera, y esas NO se pueden
    restar sin recorte de poligonos de verdad.
    """
    if len(interno) < 3 or abs(area_shoelace(interno)) >= abs(area_shoelace(externo)):
        return False
    paso = max(1, len(interno) // muestras)
    return all(_dentro(externo, x, y) for x, y in interno[::paso])


def _dentro(anillo: Polilinea, x: float, y: float) -> bool:
    dentro = False
    n = len(anillo)
    for i in range(n):
        x1, y1 = anillo[i]
        x2, y2 = anillo[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            if x < x1 + (y - y1) / (y2 - y1) * (x2 - x1):
                dentro = not dentro
    return dentro
