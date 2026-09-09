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
    Polilinea, Punto, area_shoelace, centroide, cruces_scanline_anillos,
    desplazar_contorno, longitud, remuestrear, rotar,
)
from .parametros import ParamRecta, ParamRelleno, ParamSatin

# Largo maximo que los formatos DST/PES codifican en una puntada. Por encima,
# la maquina la parte sola y el hilo queda flotando.
CRUCE_MAX_MM = 10.0


def ordenar_corridas(corridas: list[Polilinea],
                     desde: Punto | None = None
                     ) -> tuple[list[Polilinea], Punto | None]:
    """
    Reordena las corridas para que la aguja recorra el menor camino en vacio.

    Es puro orden: no cambia ni una puntada, solo en que secuencia se cosen.
    Pero es la diferencia entre que la maquina borde seguido o que se pase el
    rato viajando de un lado a otro del diseno, y cada viaje largo obliga a
    cortar el hilo. Cada corte detiene la maquina.

    Dos detalles:
      - Una corrida se puede coser en cualquiera de los dos sentidos, asi que
        se mira tambien su final; si queda mas cerca, se da vuelta.
      - Se usa vecino mas cercano, no la ruta optima. El viajante exacto es
        carisimo y aqui la heuristica ya baja el recorrido casi un 80%.

    IMPORTANTE: solo se pueden reordenar corridas INTERCAMBIABLES entre si.
    El underlay tiene que coserse antes que el relleno que sostiene, asi que
    cada fase se ordena por separado.
    """
    pendientes = [c for c in corridas if len(c) >= 2]
    salida: list[Polilinea] = []
    pos = desde
    while pendientes:
        if pos is None:
            elegida = pendientes.pop(0)
        else:
            mejor, invertir, indice = float("inf"), False, 0
            for j, c in enumerate(pendientes):
                d_ini = math.dist(pos, c[0])
                if d_ini < mejor:
                    mejor, invertir, indice = d_ini, False, j
                d_fin = math.dist(pos, c[-1])
                if d_fin < mejor:
                    mejor, invertir, indice = d_fin, True, j
            elegida = pendientes.pop(indice)
            if invertir:
                elegida = elegida[::-1]
        salida.append(elegida)
        pos = elegida[-1]
    return salida, pos


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


def rieles_desde_contorno(anillo: Polilinea) -> tuple[Polilinea, Polilinea] | None:
    """
    Parte el contorno de una region ALARGADA en sus dos lados largos.

    Es el paso que faltaba para hacer satin automatico. Una franja (el trazo
    de una letra, una hoja, una voluta de vapor) tiene un contorno cerrado con
    dos lados largos y dos tapas cortas. Si se identifican las tapas, los dos
    lados son exactamente los rieles que `columna_satin` necesita.

    Las tapas se encuentran con el "doble barrido", la aproximacion clasica
    del diametro de un conjunto de puntos:
        A = punto mas lejano del centroide
        B = punto mas lejano de A
    Es mas robusto que usar el eje principal (PCA) cuando la franja viene
    curvada, porque no supone que sea recta.

    Devuelve None si la figura no se comporta como una franja: si un lado mide
    mucho mas que el otro, no hay dos lados largos que emparejar y el satin
    saldria torcido. En ese caso conviene rellenar.
    """
    n = len(anillo)
    if n < 6:
        return None

    cx = sum(q[0] for q in anillo) / n
    cy = sum(q[1] for q in anillo) / n
    i_a = max(range(n), key=lambda k: math.dist(anillo[k], (cx, cy)))
    i_b = max(range(n), key=lambda k: math.dist(anillo[k], anillo[i_a]))
    if i_a == i_b:
        return None
    if i_a > i_b:
        i_a, i_b = i_b, i_a

    lado_1 = anillo[i_a:i_b + 1]
    lado_2 = anillo[i_b:] + anillo[:i_a + 1]
    if len(lado_1) < 2 or len(lado_2) < 2:
        return None

    l1, l2 = longitud(lado_1), longitud(lado_2)
    if min(l1, l2) <= 0 or max(l1, l2) / min(l1, l2) > 3.0:
        return None
    # El segundo lado se recorre al reves para que ambos avancen en el mismo
    # sentido; si no, el satin cruzaria la figura en diagonal.
    return lado_1, lado_2[::-1]


def eje_de_franja(anillo: Polilinea, pasos: int = 0) -> Polilinea | None:
    """
    Linea central de una franja: el promedio de sus dos lados largos.

    PARA QUE
        Un trazo demasiado fino para rellenar hay que coserlo como LINEA. La
        pregunta es que linea: si se recorre el CONTORNO, se cose el borde del
        trazo y el trazo queda hueco por dentro. Peor todavia, ese contorno
        se dobla sobre si mismo cada medio milimetro, y al muestrearlo a la
        distancia de una puntada (~1 mm) el resultado no se parece en nada a
        la forma: sale un garabato.

        El eje central no tiene ese problema. Sus rasgos estan a la escala de
        la figura -milimetros-, asi que una puntada normal lo sigue bien, y el
        hilo queda donde de verdad va el trazo.

    Devuelve None si la figura no se comporta como franja (se bifurca, tiene
    huecos, es casi tan ancha como larga). Ahi no hay un eje que tenga
    sentido y hay que resolverlo de otra forma.
    """
    rieles = rieles_desde_contorno(anillo)
    if rieles is None:
        return None
    a, b = rieles
    # Los dos lados traen distinta cantidad de puntos: se remuestrean a la
    # misma cantidad para poder emparejarlos uno a uno.
    n = pasos or max(4, min(200, (len(a) + len(b)) // 2))
    ra, rb = _repartir(a, n), _repartir(b, n)
    eje = [((x1 + x2) / 2.0, (y1 + y2) / 2.0)
           for (x1, y1), (x2, y2) in zip(ra, rb)]
    return eje if longitud(eje) > 0 else None


def _repartir(linea: Polilinea, n: int) -> Polilinea:
    """`n` puntos repartidos a lo largo de la linea, extremos incluidos."""
    largos = [0.0]
    for i in range(1, len(linea)):
        largos.append(largos[-1] + math.dist(linea[i - 1], linea[i]))
    total = largos[-1]
    if total <= 0:
        return [linea[0]] * n
    salida: Polilinea = []
    j = 0
    for k in range(n):
        objetivo = total * k / (n - 1) if n > 1 else 0.0
        while j < len(largos) - 2 and largos[j + 1] < objetivo:
            j += 1
        tramo = largos[j + 1] - largos[j]
        t = 0.0 if tramo <= 0 else (objetivo - largos[j]) / tramo
        (x1, y1), (x2, y2) = linea[j], linea[j + 1]
        salida.append((x1 + (x2 - x1) * t, y1 + (y2 - y1) * t))
    return salida


def satin_de_anillo(exterior: Polilinea, hueco: Polilinea, p: ParamSatin,
                    ancho_minimo_mm: float = 0.0) -> list[Polilinea]:
    """
    Borde satin de un ANILLO, cosido entre sus dos orillas.

    Es como la industria borda un contorno: una columna satin necesita dos
    rieles, y en un anillo -el borde de un escudo, el marco de una cinta- los
    dos rieles YA existen. Son el contorno exterior y el hueco. No hay que
    calcular nada intermedio.

    POR QUE ESTO Y NO EL EJE MEDIAL
        El eje medial se obtiene adelgazando la figura, y ese adelgazado
        inventa una bifurcacion en cada irregularidad del borde. Un contorno
        de 15 cm salia partido en unos 160 tramos, y como cada tramo es una
        columna con su principio y su final, el borde quedaba con una muesca
        en cada union. Aqui no hay tramos: es UNA sola columna que da la
        vuelta completa, asi que no puede tener muescas.

    LO UNICO DELICADO ES EMPAREJAR LOS DOS ANILLOS
        Hay que recorrerlos en el mismo sentido y empezar en puntos que se
        correspondan. Si no, la columna cruza la figura en diagonal y sale un
        ovillo. Se resuelve orientando los dos igual y rotando el hueco para
        que arranque en su punto mas cercano al arranque del exterior.
    """
    if len(exterior) < 3 or len(hueco) < 3:
        return []

    a = list(exterior)
    b = list(hueco)
    # 1. Mismo sentido de giro: el hueco suele venir al reves.
    if (area_shoelace(a) >= 0) != (area_shoelace(b) >= 0):
        b = b[::-1]
    # 2. Mismo punto de partida.
    k = min(range(len(b)), key=lambda i: math.dist(b[i], a[0]))
    b = b[k:] + b[:k]

    # 3. Se reparten los dos por igual, cerrados, y se emparejan uno a uno.
    L = (longitud(a, cerrada=True) + longitud(b, cerrada=True)) / 2.0
    n = max(4, int(L / max(p.densidad_mm, 0.05)))
    ra = _repartir(a + [a[0]], n + 1)
    rb = _repartir(b + [b[0]], n + 1)

    zig: Polilinea = []
    for i in range(n + 1):
        ax, ay = ra[i]
        bx, by = rb[i]
        dx, dy = bx - ax, by - ay
        d = math.hypot(dx, dy) or 1.0
        ux, uy = dx / d, dy / d
        # Se separa lo justo para que la puntada no caiga bajo el minimo de
        # la maquina. Es la misma pull compensation de siempre: el hilo tiene
        # grosor propio y cubre algo mas que la linea dibujada. Sin esto, un
        # contorno de medio milimetro no se coseria: el filtro de puntadas
        # cortas se lo llevaria entero.
        c = p.compensacion_mm + max(0.0, (ancho_minimo_mm - d) / 2.0)
        # SIEMPRE en el orden a,b: alternarlo dejaria dos penetraciones
        # seguidas en el mismo riel, separadas solo por el avance.
        zig.append((ax - ux * c, ay - uy * c))
        zig.append((bx + ux * c, by + uy * c))
    return [zig]


def satin_por_eje(eje: Polilinea, semianchos: list[float], p: ParamSatin,
                  ancho_minimo_mm: float = 0.7) -> list[Polilinea]:
    """
    Columna satin a lo largo de un eje, con el ancho que tenga en cada punto.

    Es la pieza que permite bordar letras y numeros chicos. El eje y los
    semianchos salen de `imagen/esqueleto.py`, que descompone la figura en
    trazos; aqui cada trazo se convierte en su columna.

    POR QUE NO SE USA `columna_satin`
        Esa funcion recibe dos rieles independientes y los remuestrea por
        separado, cada uno por su propio largo. Es lo correcto cuando los
        rieles vienen de un contorno y no estan emparejados. Aqui SI lo estan
        -cada par sale del mismo punto del eje-, y remuestrearlos por
        separado los desincroniza: en una curva el riel interior es mas corto
        que el exterior, asi que el punto i de uno deja de corresponder al
        punto i del otro y el satin sale cruzado. Se probo, y por eso los
        numeros salian como garabatos.

        Aqui se remuestrea el EJE, una sola vez, y los dos rieles se derivan
        de el. El emparejamiento no se puede romper.

    `ancho_minimo_mm` ensancha la columna donde el trazo es mas fino que la
    puntada mas corta de la maquina. NO es hacer trampa: es la misma pull
    compensation que aplica cualquier digitalizador, por la misma razon
    fisica -el hilo tiene grosor propio y cubre algo mas que la linea
    dibujada-. Sin esto, en un trazo de 0.5 mm todas las puntadas caerian
    bajo el minimo, el filtro las borraria y la letra no se coseria.
    """
    if len(eje) < 2 or len(semianchos) != len(eje):
        return []

    eje, semianchos = _remuestrear_con_ancho(eje, semianchos, p.densidad_mm)
    n = len(eje)
    if n < 2:
        return []

    zig: Polilinea = []
    for i in range(n):
        if i == 0:
            dx, dy = eje[1][0] - eje[0][0], eje[1][1] - eje[0][1]
        elif i == n - 1:
            dx, dy = eje[-1][0] - eje[-2][0], eje[-1][1] - eje[-2][1]
        else:
            dx, dy = eje[i + 1][0] - eje[i - 1][0], eje[i + 1][1] - eje[i - 1][1]
        L = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / L, dx / L                  # normal al avance
        w = max(semianchos[i], ancho_minimo_mm / 2.0) + p.compensacion_mm
        a = (eje[i][0] + nx * w, eje[i][1] + ny * w)
        b = (eje[i][0] - nx * w, eje[i][1] - ny * w)
        # SIEMPRE en el mismo orden a,b. Alternarlo (a,b / b,a) parece mas
        # elegante y es un error: deja dos penetraciones seguidas en el mismo
        # riel, separadas solo por el avance (0.35 mm), o sea por debajo de la
        # puntada minima. Ya se cometio una vez en este proyecto.
        #
        # Asi, la puntada a->b cruza la columna y la b->a siguiente vuelve a
        # cruzarla en diagonal: las dos miden al menos el ancho del trazo.
        zig += [a, b]
    return [zig] if len(zig) >= 2 else []


def _remuestrear_con_ancho(eje: Polilinea, semianchos: list[float], paso: float
                           ) -> tuple[Polilinea, list[float]]:
    """Reparte el eje cada `paso` mm, interpolando tambien el ancho."""
    largos = [0.0]
    for i in range(1, len(eje)):
        largos.append(largos[-1] + math.dist(eje[i - 1], eje[i]))
    total = largos[-1]
    if total <= 0 or paso <= 0:
        return list(eje), list(semianchos)

    n = max(2, int(round(total / paso)) + 1)
    salida: Polilinea = []
    anchos: list[float] = []
    j = 0
    for k in range(n):
        objetivo = total * k / (n - 1)
        while j < len(largos) - 2 and largos[j + 1] < objetivo:
            j += 1
        tramo = largos[j + 1] - largos[j]
        t = 0.0 if tramo <= 0 else (objetivo - largos[j]) / tramo
        (x1, y1), (x2, y2) = eje[j], eje[j + 1]
        salida.append((x1 + (x2 - x1) * t, y1 + (y2 - y1) * t))
        anchos.append(semianchos[j] + (semianchos[j + 1] - semianchos[j]) * t)
    return salida, anchos


# Por debajo de este ancho la columna no admite una puntada util: ahi termina
# el satin y empieza la punta de la figura.
SATIN_ANCHO_MINIMO_MM = 0.8


def satin_de_region(anillo: Polilinea, p: ParamSatin,
                    ancho_max_mm: float | None = None) -> list[Polilinea] | None:
    """
    Satin sobre una region alargada, tomando su propio contorno como rieles.

    Los dos rieles COMPARTEN las puntas del contorno, y hacia cada punta la
    figura se cierra: el ancho de la columna cae hasta cero. Cosido tal cual,
    el satin arranca y termina con puntadas de largo cero, que la maquina no
    puede dar. Por eso se recortan los extremos donde la columna es mas
    angosta que `SATIN_ANCHO_MINIMO_MM`, que es lo que hace cualquier
    digitalizador serio con las puntas.

    Devuelve None si la region no da para satin: o no se comporta como franja,
    o es mas ancha de lo que el hilo aguanta sin quedar flojo, o al recortar
    las puntas no queda columna util.
    """
    rieles = rieles_desde_contorno(anillo)
    if rieles is None:
        return None
    a, b = rieles

    largo = (longitud(a) + longitud(b)) / 2.0
    n = max(8, min(int(largo / max(p.densidad_mm, 0.05)), 4000))
    ma, mb = _remuestrear_a_n(a, n), _remuestrear_a_n(b, n)
    anchos = [math.dist(ma[i], mb[i]) for i in range(n)]

    tope = ancho_max_mm if ancho_max_mm is not None else p.ancho_max_mm
    if max(anchos) > tope:
        return None

    utiles = [i for i, w in enumerate(anchos) if w >= SATIN_ANCHO_MINIMO_MM]
    if len(utiles) < 4:
        return None
    i0, i1 = utiles[0], utiles[-1]
    corridas = columna_satin(ma[i0:i1 + 1], mb[i0:i1 + 1], p)
    # El underlay del satin va primero; despues la columna. Solo se ordena
    # dentro de cada grupo, nunca mezclandolos.
    if len(corridas) > 2:
        base, pos = ordenar_corridas(corridas[:-1])
        return base + [corridas[-1]]
    return corridas


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

def relleno_tatami(poligono: Polilinea, p: ParamRelleno,
                   huecos: list[Polilinea] | None = None) -> list[Polilinea]:
    """
    Relleno por barrido (scanline) en serpentina.

    `huecos` son anillos interiores que NO se cosen: la contra de una letra
    "o", el centro de una dona. Se resuelven con la regla par-impar del
    scanline, sin logica adicional.

    Se rota el poligono -angulo, se rellena con lineas HORIZONTALES (mucho
    mas simple y estable numericamente), y se rota de vuelta.

    El `desfase_mm` corre el inicio de las perforaciones fila a fila. Sin el,
    todos los puntos de penetracion quedan alineados y se forma una linea
    visible que parte el bordado: el "efecto cremallera" (zipper effect).
    """
    corridas: list[Polilinea] = []
    cen = centroide(poligono)
    huecos = huecos or []
    anillos = [poligono, *huecos]
    base: list[Polilinea] = []

    # --- Underlay ---
    if p.underlay == "contorno":
        base.append(remuestrear(desplazar_contorno(poligono, -0.8), 2.0, cerrada=True))
    elif p.underlay == "tatami":
        base.append(remuestrear(desplazar_contorno(poligono, -0.8), 2.5, cerrada=True))
        cruzado = ParamRelleno(
            densidad_mm=p.densidad_underlay_mm,
            largo_mm=4.0,
            angulo_grados=p.angulo_grados + 90.0,  # cruzado al relleno final
            desfase_mm=0.0,
            underlay="none",
        )
        # El underlay se encoge hacia adentro; los huecos se agrandan, que es
        # el mismo desplazamiento pero con el signo invertido.
        base.extend(_barrido(
            [desplazar_contorno(poligono, -0.5)]
            + [desplazar_contorno(h, 0.5) for h in huecos], cruzado, cen))

    # Cada fase se ordena por separado: el underlay va SIEMPRE antes del
    # relleno que sostiene, pero dentro de cada fase el orden es libre.
    corridas, pos = ordenar_corridas(base)
    relleno, _ = ordenar_corridas(_barrido(anillos, p, cen), pos)
    return corridas + relleno


def _barrido(anillos: list[Polilinea], p: ParamRelleno,
             centro: Punto) -> list[Polilinea]:
    """
    Motor del tatami: descomposicion en celdas (boustrophedon) + serpentina.

    El barrido ingenuo cose fila por fila y corta el hilo cada vez que una
    fila viene partida. En un anillo, TODAS las filas vienen partidas por el
    hueco: 91 corridas y 91 cortes de hilo, cuando bastan 2.

    La descomposicion correcta agrupa los tramos en CELDAS: dos tramos de
    filas consecutivas pertenecen a la misma celda si se solapan en X. Una
    celda es una franja continua que se puede recorrer en serpentina de una
    sola pasada. Un anillo se descompone en 2 celdas (el lado izquierdo y el
    derecho); una figura con tres lobulos, en 3.

    Es el mismo algoritmo que se usa para planificar la cobertura de un
    terreno con un robot: recorrer todo sin levantar la herramienta.
    """
    rot = [rotar(a, -p.angulo_grados, centro) for a in anillos]
    ys = [q[1] for a in rot for q in a]
    if not ys:
        return []

    # --- Barrido: tramos rellenables por fila ---------------------------
    filas: list[tuple[float, list[tuple[float, float]]]] = []
    y = min(ys) + p.densidad_mm / 2.0
    y_fin = max(ys)
    while y <= y_fin:
        xs = cruces_scanline_anillos(rot, y)
        tramos = [(xs[i], xs[i + 1]) for i in range(0, len(xs) - 1, 2)
                  if xs[i + 1] - xs[i] >= p.largo_mm * 0.4]
        if tramos:
            filas.append((y, tramos))
        y += p.densidad_mm

    # --- Agrupamiento en celdas conectadas ------------------------------
    celdas: list[list[tuple[float, float, float]]] = []
    activas: list[list[tuple[float, float, float]]] = []
    for y, tramos in filas:
        siguientes: list[list[tuple[float, float, float]]] = []
        for x0, x1 in tramos:
            elegida = None
            for celda in activas:
                if celda in siguientes:
                    continue          # una celda solo continua en un tramo
                _, cx0, cx1 = celda[-1]
                if min(x1, cx1) > max(x0, cx0):   # se solapan en X
                    elegida = celda
                    break
            if elegida is None:
                elegida = []
                celdas.append(elegida)
            elegida.append((y, x0, x1))
            siguientes.append(elegida)
        activas = siguientes

    # --- Serpentina dentro de cada celda --------------------------------
    # Al pasar de una fila a la siguiente, la serpentina cruza la diferencia
    # de ancho entre ambas. Donde la figura se ensancha de golpe (la punta de
    # una estrella) ese cruce puede superar el largo maximo de puntada que la
    # maquina codifica: 12.1 mm. Ahi se corta la corrida en vez de dejar un
    # hilo largo que se engancha.
    corridas: list[Polilinea] = []
    for celda in celdas:
        if len(celda) < 2:
            continue      # una sola fila: no alcanza para coser nada util
        corrida: Polilinea = []
        for fila, (y, x0, x1) in enumerate(celda):
            ini, fin = (x0, x1) if fila % 2 == 0 else (x1, x0)
            if corrida and math.dist(corrida[-1], (ini, y)) > CRUCE_MAX_MM:
                if len(corrida) >= 2:
                    corridas.append(rotar(corrida, p.angulo_grados, centro))
                corrida = []
            corrida.extend(_puntos_de_fila(ini, fin, y, fila, p))
        if len(corrida) >= 2:
            corridas.append(rotar(corrida, p.angulo_grados, centro))
    return corridas


def _puntos_de_fila(x_ini: float, x_fin: float, y: float, fila: int,
                    p: ParamRelleno) -> Polilinea:
    """Divide un tramo en puntadas, con el desfase de fila aplicado."""
    largo = abs(x_fin - x_ini)
    signo = 1.0 if x_fin >= x_ini else -1.0
    # Desfase de fila: rompe la alineacion de las perforaciones y evita la
    # linea visible que parte el bordado ("efecto cremallera").
    off = (fila * p.desfase_mm) % p.largo_mm if p.largo_mm else 0.0
    puntos: Polilinea = [(x_ini, y)]
    d = p.largo_mm - off if off else p.largo_mm
    while d < largo:
        puntos.append((x_ini + signo * d, y))
        d += p.largo_mm
    if len(puntos) > 1 and abs(largo - (d - p.largo_mm)) < p.largo_mm * 0.4:
        puntos[-1] = (x_fin, y)      # evita una astilla de decimas de mm
    else:
        puntos.append((x_fin, y))
    return puntos
