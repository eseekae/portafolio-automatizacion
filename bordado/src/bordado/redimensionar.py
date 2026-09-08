"""
Redimensionado de matrices ya bordadas.

LO QUE HAY QUE ENTENDER ANTES DE USARLO
    Un archivo de bordado guarda PUNTADAS, no formas. Escalarlo mueve las
    perforaciones, pero la separacion entre pasadas de un relleno se
    multiplica por el mismo factor:

        agrandar 50%  ->  0.40 mm pasa a 0.60 mm  ->  se ve la tela entre pasadas
        achicar  50%  ->  0.40 mm pasa a 0.20 mm  ->  agarrota y rompe la tela

    Eso NO se puede arreglar desde las puntadas: haria falta saber que region
    era cada cosa para volver a trazar las pasadas. Por eso:

    - Cambios chicos (hasta ~12%): se reescala y se corrigen los largos de
      puntada. El resultado es bueno.
    - Cambios grandes: hay que RE-DIGITALIZAR desde la imagen o el SVG
      original, que es donde todavia existen las regiones. `matriz digitalizar
      --ancho N` da el resultado correcto a cualquier tamano.

    Este modulo hace lo primero bien y avisa con claridad cuando toca lo
    segundo, en vez de entregar en silencio un archivo inservible.

LO QUE SI SE CORRIGE
    El largo de cada puntada, que es la otra mitad de la densidad y esa si es
    exacta: al agrandar aparecen puntadas demasiado largas (se enganchan) y al
    achicar demasiado cortas (rompen agujas). Se parten y se fusionan.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pyembroidery as pe

UNIDADES_POR_MM = 10.0

# Fuera de esta banda el relleno deja de servir. 0.40 mm de separacion tipica
# aguanta hasta 0.45 (abierto pero valido) y baja hasta 0.35 (denso pero
# valido): eso es aproximadamente +-12%.
FACTOR_SEGURO_MIN = 0.88
FACTOR_SEGURO_MAX = 1.12

# Separacion de referencia. Casi toda matriz comercial se digitaliza aqui.
SEPARACION_TIPICA_MM = 0.40

PUNTADA_MIN_MM = 0.6
PUNTADA_MAX_MM = 10.0


@dataclass
class Reescalado:
    factor: float = 1.0
    ancho_antes: float = 0.0
    alto_antes: float = 0.0
    ancho_despues: float = 0.0
    alto_despues: float = 0.0
    puntadas_antes: int = 0
    puntadas_despues: int = 0
    divididas: int = 0
    fusionadas: int = 0
    seguro: bool = True
    avisos: list[str] = field(default_factory=list)

    @property
    def separacion_estimada_mm(self) -> float:
        """Separacion resultante, suponiendo que el original venia a 0.40 mm."""
        return SEPARACION_TIPICA_MM * self.factor

    def texto(self) -> str:
        sep = self.separacion_estimada_mm
        lineas = [
            "=" * 58, " REDIMENSIONADO", "=" * 58,
            f"  {'Factor':.<30} {self.factor:.1%}",
            f"  {'Tamano antes (mm)':.<30} "
            f"{self.ancho_antes:.1f} x {self.alto_antes:.1f}",
            f"  {'Tamano despues (mm)':.<30} "
            f"{self.ancho_despues:.1f} x {self.alto_despues:.1f}",
            f"  {'Puntadas':.<30} {self.puntadas_antes:,} -> "
            f"{self.puntadas_despues:,}",
            f"  {'Puntadas largas partidas':.<30} {self.divididas:,}",
            f"  {'Puntadas cortas fusionadas':.<30} {self.fusionadas:,}",
            f"  {'Separacion estimada (mm)':.<30} "
            f"{SEPARACION_TIPICA_MM:.2f} -> {sep:.2f}",
            "-" * 58,
        ]
        if self.avisos:
            lineas += [f"  ! {a}" for a in self.avisos]
        else:
            lineas.append("  Cambio dentro del rango seguro.")
        lineas.append("=" * 58)
        return "\n".join(lineas)


def factor_para(patron: pe.EmbPattern, ancho_mm: float | None = None,
                alto_mm: float | None = None) -> float:
    """Factor necesario para llevar el diseno al ancho o alto pedido."""
    x0, y0, x1, y1 = patron.bounds()
    ancho = (x1 - x0) / UNIDADES_POR_MM
    alto = (y1 - y0) / UNIDADES_POR_MM
    if ancho_mm and ancho > 0:
        return ancho_mm / ancho
    if alto_mm and alto > 0:
        return alto_mm / alto
    return 1.0


def reescalar(patron: pe.EmbPattern, factor: float,
              largo_max_mm: float = PUNTADA_MAX_MM,
              largo_min_mm: float = PUNTADA_MIN_MM,
              forzar: bool = False) -> tuple[pe.EmbPattern | None, Reescalado]:
    """
    Devuelve (patron reescalado, informe). El patron es None si el cambio
    queda fuera del rango seguro y no se paso `forzar`.
    """
    r = Reescalado(factor=factor)
    x0, y0, x1, y1 = patron.bounds()
    r.ancho_antes = (x1 - x0) / UNIDADES_POR_MM
    r.alto_antes = (y1 - y0) / UNIDADES_POR_MM
    r.puntadas_antes = patron.count_stitch_commands(pe.STITCH)
    # Se anticipa el resultado aunque despues se rechace: el usuario quiere
    # saber a que tamano habria quedado, no leer ceros.
    r.ancho_despues = r.ancho_antes * factor
    r.alto_despues = r.alto_antes * factor
    r.puntadas_despues = r.puntadas_antes

    if factor <= 0:
        r.seguro = False
        r.avisos.append("El factor tiene que ser mayor que cero.")
        return None, r

    if not FACTOR_SEGURO_MIN <= factor <= FACTOR_SEGURO_MAX:
        r.seguro = False
        sep = r.separacion_estimada_mm
        que_pasa = ("quedaria tan densa que agarrota la tela y rompe agujas"
                    if factor < 1 else
                    "quedaria tan abierta que se veria la tela entre pasadas")
        r.avisos.append(
            f"Cambio de {factor:.0%}: la separacion entre pasadas pasaria de "
            f"~{SEPARACION_TIPICA_MM:.2f} a ~{sep:.2f} mm y {que_pasa}.")
        r.avisos.append(
            "Desde un archivo de puntadas esto no tiene arreglo. Re-digitaliza "
            "la imagen o el SVG original con `matriz digitalizar --ancho N`.")
        if not forzar:
            return None, r
        r.avisos.append("Se genero igual porque se paso --forzar.")

    nuevo = patron.copy()
    m = pe.EmbMatrix()
    m.post_scale(factor, factor)
    nuevo.transform(m)

    nuevo.stitches, r.divididas, r.fusionadas = _corregir_largos(
        nuevo.stitches, largo_max_mm, largo_min_mm)

    x0, y0, x1, y1 = nuevo.bounds()
    r.ancho_despues = (x1 - x0) / UNIDADES_POR_MM
    r.alto_despues = (y1 - y0) / UNIDADES_POR_MM
    r.puntadas_despues = nuevo.count_stitch_commands(pe.STITCH)
    return nuevo, r


def _corregir_largos(stitches: list, largo_max_mm: float,
                     largo_min_mm: float) -> tuple[list, int, int]:
    """
    Reparte de nuevo las perforaciones para que ningun tramo quede fuera de
    rango. Es la mitad de la densidad que SI se puede recalcular sin conocer
    las regiones: solo depende de dos puntos consecutivos.

    El punto final de cada tramo es especial: hay que conservarlo para que la
    forma cierre donde corresponde. Si quedo demasiado cerca del anterior, se
    REEMPLAZA ese anterior en vez de anadir otra perforacion, siempre que la
    puntada resultante no se pase de larga.
    """
    maximo = largo_max_mm * UNIDADES_POR_MM
    minimo = largo_min_mm * UNIDADES_POR_MM
    salida: list = []
    indices_cosidos: list[int] = []      # posiciones en `salida` de las STITCH
    divididas = fusionadas = 0
    previo: tuple[float, float] | None = None

    def punto(i: int) -> tuple[float, float]:
        return salida[i][0], salida[i][1]

    for indice, (x, y, cmd) in enumerate(stitches):
        base = cmd & pe.COMMAND_MASK
        if base != pe.STITCH or previo is None:
            salida.append([x, y, cmd])
            if base in (pe.STITCH, pe.JUMP, pe.SEQUIN_EJECT):
                previo = (x, y)
                if base == pe.STITCH:
                    indices_cosidos.append(len(salida) - 1)
                else:
                    indices_cosidos.clear()   # el tramo se corta aqui
            continue

        d = math.hypot(x - previo[0], y - previo[1])
        siguiente = stitches[indice + 1] if indice + 1 < len(stitches) else None
        sigue_el_tramo = (siguiente is not None
                          and (siguiente[2] & pe.COMMAND_MASK) == pe.STITCH)

        if d > maximo:
            # Se parte en tramos iguales: la maquina lo haria igual, pero al
            # hacerlo aqui el archivo declara lo que realmente va a coser.
            trozos = int(math.ceil(d / maximo))
            for k in range(1, trozos):
                t = k / trozos
                salida.append([previo[0] + (x - previo[0]) * t,
                               previo[1] + (y - previo[1]) * t, cmd])
                indices_cosidos.append(len(salida) - 1)
            divididas += 1
        elif d < minimo:
            if sigue_el_tramo:
                # Perforacion redundante: la aguja repicaria el mismo agujero.
                fusionadas += 1
                continue
            # Ultima del tramo: se corre la anterior hasta aqui, si al hacerlo
            # la puntada previa no se pasa de larga.
            if len(indices_cosidos) >= 2:
                anterior = punto(indices_cosidos[-2])
                if math.hypot(x - anterior[0], y - anterior[1]) <= maximo:
                    i = indices_cosidos[-1]
                    salida[i] = [x, y, salida[i][2]]
                    fusionadas += 1
                    previo = (x, y)
                    continue

        salida.append([x, y, cmd])
        indices_cosidos.append(len(salida) - 1)
        previo = (x, y)

    return salida, divididas, fusionadas
