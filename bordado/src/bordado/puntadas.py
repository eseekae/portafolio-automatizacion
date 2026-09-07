"""
Generadores de puntada (patron de diseno: STRATEGY).

Cada generador recibe geometria en mm + sus parametros, y devuelve
`list[Polilinea]`: una lista de "corridas" continuas de puntadas.
Una corrida = secuencia de perforaciones sin levantar la aguja.
Entre corridas puede haber salto (JUMP) o corte (TRIM); eso lo decide
la capa superior (`patron.py`), no el generador.

Contrato unico -> los generadores son intercambiables y testeables solos.
"""

from __future__ import annotations

import math

from .geometria import (
    Polilinea, Punto, centroide, cruces_scanline, desplazar_contorno,
    longitud, remuestrear, rotar,
)
from .parametros import ParamRecta, ParamRelleno, ParamSatin


# --------------------------------------------------------------------------
# 1. Puntada corrida (running stitch)
# --------------------------------------------------------------------------

def puntada_recta(trazo: Polilinea, p: ParamRecta,
                  cerrada: bool = False) -> list[Polilinea]:
    """Contornos finos, detalles, tallos, y underlay de eje."""
    return [remuestrear(trazo, p.largo_mm, cerrada=cerrada)]


def puntada_triple(trazo: Polilinea, p: ParamRecta,
                   cerrada: bool = False) -> list[Polilinea]:
    """
    Bean stitch / triple: ida-vuelta-ida sobre el mismo camino.
    Triplica el grosor visual sin cambiar de hilo. Muy usada en line art.
    """
    base = remuestrear(trazo, p.largo_mm, cerrada=cerrada)
    return [base + base[::-1] + base]


# --------------------------------------------------------------------------
# 2. Columna satin
# --------------------------------------------------------------------------

def columna_satin(riel_a: Polilinea, riel_b: Polilinea,
                  p: ParamSatin) -> list[Polilinea]:
    """
    Zigzag denso entre dos rieles.

    Pasos:
      1. Se calcula cuantos zigzags caben:  n = L_promedio / densidad
      2. Se remuestrean AMBOS rieles a n puntos (asi quedan sincronizados
         aunque tengan largos distintos: es lo que hace que el satin siga
         curvas sin abrirse).
      3. Pull compensation: se separan los rieles `compensacion_mm` hacia
         afuera. El hilo, al tensarse, encoge la columna a lo ancho; si no
         compensas, aparece la tela entre el borde y el relleno.
    """
    L = (longitud(riel_a) + longitud(riel_b)) / 2.0
    n = max(2, int(L / p.densidad_mm))

    a = _remuestrear_a_n(riel_a, n)
    b = _remuestrear_a_n(riel_b, n)

    corridas: list[Polilinea] = []

    # --- Underlay: estabiliza la tela antes de poner el satin encima ---
    if p.underlay == "center":
        eje = [((a[i][0] + b[i][0]) / 2, (a[i][1] + b[i][1]) / 2) for i in range(n)]
        corridas.append(remuestrear(eje, 2.0))
    elif p.underlay == "zigzag":
        # Zigzag de baja densidad (~4x mas abierto que el satin final).
        paso = max(1, int(p.densidad_mm * 4 / p.densidad_mm))
        corridas.append([a[i] if i % 2 == 0 else b[i] for i in range(0, n, max(1, paso * 4))])

    # --- Satin propiamente tal, con compensacion ---
    zig: Polilinea = []
    for i in range(n):
        ax, ay = a[i]
        bx, by = b[i]
        dx, dy = bx - ax, by - ay
        d = math.hypot(dx, dy) or 1.0
        ux, uy = dx / d, dy / d
        c = p.compensacion_mm
        pa = (ax - ux * c, ay - uy * c)
        pb = (bx + ux * c, by + uy * c)
        # Secuencia correcta: a0, b0, a1, b1, ...
        # Cada puntada CRUZA la columna (largo = ancho), y el avance entre
        # penetraciones del mismo riel es exactamente `densidad_mm`.
        # (Alternar el orden por fila genera puntadas de largo = densidad,
        #  o sea < 0.5 mm: rompe agujas. Es el error clasico del satin.)
        zig.extend([pa, pb])
    corridas.append(zig)
    return corridas


def satin_desde_eje(eje: Polilinea, ancho_mm: float,
                    p: ParamSatin) -> list[Polilinea]:
    """Construye los dos rieles desplazando un eje +-ancho/2 por la normal."""
    a, b = [], []
    n = len(eje)
    for i in range(n):
        p0 = eje[max(0, i - 1)]
        p1 = eje[min(n - 1, i + 1)]
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        d = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / d, dx / d          # normal unitaria
        h = ancho_mm / 2.0
        a.append((eje[i][0] + nx * h, eje[i][1] + ny * h))
        b.append((eje[i][0] - nx * h, eje[i][1] - ny * h))
    return columna_satin(a, b, p)


def _remuestrear_a_n(linea: Polilinea, n: int) -> Polilinea:
    """Remuestrea a exactamente n puntos distribuidos por longitud de arco."""
    if len(linea) < 2:
        return linea * n
    acum = [0.0]
    for i in range(len(linea) - 1):
        acum.append(acum[-1] + math.dist(linea[i], linea[i + 1]))
    total = acum[-1] or 1.0
    salida: Polilinea = []
    j = 0
    for k in range(n):
        objetivo = total * k / (n - 1)
        while j < len(acum) - 2 and acum[j + 1] < objetivo:
            j += 1
        seg = (acum[j + 1] - acum[j]) or 1.0
        t = (objetivo - acum[j]) / seg
        x = linea[j][0] + t * (linea[j + 1][0] - linea[j][0])
        y = linea[j][1] + t * (linea[j + 1][1] - linea[j][1])
        salida.append((x, y))
    return salida


# --------------------------------------------------------------------------
# 3. Relleno tatami
# --------------------------------------------------------------------------

def relleno_tatami(poligono: Polilinea, p: ParamRelleno) -> list[Polilinea]:
    """
    Relleno por barrido (scanline) en serpentina.

    Se rota el poligono -angulo, se rellena con lineas HORIZONTALES (mucho
    mas simple y estable numericamente), y se rota de vuelta.

    El `desfase_mm` corre el inicio de las perforaciones fila a fila. Sin el,
    todos los puntos de penetracion quedan alineados y se forma una linea
    visible que parte el bordado: el "efecto cremallera" (zipper effect).
    """
    corridas: list[Polilinea] = []
    cen = centroide(poligono)

    # --- Underlay ---
    if p.underlay == "contorno":
        corridas.append(remuestrear(desplazar_contorno(poligono, -0.8), 2.0, cerrada=True))
    elif p.underlay == "tatami":
        corridas.append(remuestrear(desplazar_contorno(poligono, -0.8), 2.5, cerrada=True))
        base = ParamRelleno(
            densidad_mm=p.densidad_underlay_mm,
            largo_mm=4.0,
            angulo_grados=p.angulo_grados + 90.0,  # cruzado al relleno final
            desfase_mm=0.0,
            underlay="none",
        )
        corridas.extend(_barrido(desplazar_contorno(poligono, -0.5), base, cen))

    corridas.extend(_barrido(poligono, p, cen))
    return corridas


def _barrido(poligono: Polilinea, p: ParamRelleno, centro: Punto) -> list[Polilinea]:
    """Motor del tatami: barrido horizontal en el espacio rotado."""
    rot = rotar(poligono, -p.angulo_grados, centro)
    ys = [q[1] for q in rot]
    y = min(ys) + p.densidad_mm / 2.0
    y_fin = max(ys)

    corridas: list[Polilinea] = []
    corrida: Polilinea = []
    fila = 0
    hacia_derecha = True
    # Un poligono concavo (o con dos lobulos) produce VARIOS tramos por fila.
    # Saltar de un tramo al siguiente con una puntada normal dejaria un hilo
    # cruzando el hueco. Si el hueco supera este umbral, se corta la corrida.
    hueco_max = max(p.largo_mm * 1.5, 4.0)

    while y <= y_fin:
        xs = cruces_scanline(rot, y)
        # Pares (entra, sale) segun regla par-impar.
        tramos = [(xs[i], xs[i + 1]) for i in range(0, len(xs) - 1, 2)]
        if not hacia_derecha:
            tramos = [(b, a) for a, b in reversed(tramos)]

        for x0, x1 in tramos:
            if corrida and abs(x0 - corrida[-1][0]) > hueco_max:
                corridas.append(corrida)
                corrida = []
            largo = abs(x1 - x0)
            if largo < p.largo_mm * 0.4:
                continue  # tramo mas corto que una puntada: se descarta
            signo = 1.0 if x1 >= x0 else -1.0
            # Desfase de fila -> rompe la alineacion de perforaciones.
            off = (fila * p.desfase_mm) % p.largo_mm if p.largo_mm else 0.0
            puntos = [(x0, y)]
            d = p.largo_mm - off if off else p.largo_mm
            while d < largo:
                puntos.append((x0 + signo * d, y))
                d += p.largo_mm
            # Si el ultimo punto quedo pegado al borde, se REEMPLAZA en vez
            # de agregar: si no, queda una "astilla" de decimas de mm.
            if len(puntos) > 1 and abs(largo - (d - p.largo_mm)) < p.largo_mm * 0.4:
                puntos[-1] = (x1, y)
            else:
                puntos.append((x1, y))
            corrida.extend(puntos)

        if tramos:
            hacia_derecha = not hacia_derecha
        fila += 1
        y += p.densidad_mm

    if corrida:
        corridas.append(corrida)
    # Se descartan fragmentos de una sola puntada y se vuelve al angulo real.
    return [rotar(c, p.angulo_grados, centro) for c in corridas if len(c) >= 2]
