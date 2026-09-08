"""
Aplique: bordar sobre un retazo de tela en vez de rellenar con hilo.

POR QUE IMPORTA
    Un parche de 8x8 cm relleno de tatami son unas 25 000 puntadas y ~20 min
    de maquina, con la tela endurecida por la cantidad de hilo. En aplique se
    recorta un retazo del color deseado y solo se cosen sus BORDES: unas
    3 000 puntadas, ~3 min, y la pieza queda flexible.

LA SECUENCIA, QUE ES LO QUE HAY QUE ENTENDER
    1. POSICION   La maquina cose el contorno sobre la tela base y se detiene.
                  Ese hilo es solo una guia: marca donde va el retazo.
    2. FIJACION   Con el retazo ya puesto encima, cose por dentro del borde
                  para sujetarlo. Se detiene otra vez.
    3. RECORTE    A mano, con tijera curva, al ras de la fijacion.
    4. COBERTURA  Una columna satin sobre el borde crudo, que lo tapa y lo
                  remata.

COMO SE LOGRA LA PAUSA (el detalle que decide el diseno)
    Lo natural seria el comando STOP, pero no es fiable: comprobado sobre los
    escritores de pyembroidery, en .vp3 desaparece por completo y en .jef se
    pierde parte. Una pausa perdida significa que la maquina cose los tres
    pasos de corrido y arruina la pieza.

    Por eso cada paso se emite como un BLOQUE DE COLOR propio, que todos los
    formatos respetan. Y con COLORES DISTINTOS entre si: el escritor de .pes
    fusiona dos bloques contiguos del mismo color, y ahi se perderia la
    parada. El validador lo verifica.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .geometria import Polilinea, desplazar_contorno, remuestrear
from .parametros import ParamRecta, ParamSatin
from .puntadas import columna_satin, puntada_recta

# Colores de los pasos de guia. Son deliberadamente chillones y distintos
# entre si: en la lista de colores de la maquina se leen como "esto no es
# parte del dibujo, es una instruccion".
COLOR_POSICION = "#FF00FF"
COLOR_FIJACION = "#00C853"


@dataclass(frozen=True)
class ParamAplique:
    """Parametros de la secuencia. Los valores por defecto son de taller."""
    ancho_cobertura_mm: float = 2.5     # satin que tapa el borde crudo
    densidad_cobertura_mm: float = 0.35
    margen_fijacion_mm: float = 0.8     # cuanto hacia adentro cose la fijacion
    largo_posicion_mm: float = 2.5
    color_posicion: str = COLOR_POSICION
    color_fijacion: str = COLOR_FIJACION


@dataclass
class Paso:
    """Un paso de la secuencia, tal como lo vera el bordador en su maquina."""
    orden: int
    nombre: str
    color: str
    instruccion: str
    corridas: list[Polilinea] = field(default_factory=list)
    pausa_despues: bool = True


def secuencia(contorno: Polilinea, huecos: list[Polilinea] | None,
              color_cobertura: str, p: ParamAplique | None = None) -> list[Paso]:
    """
    Construye los tres pasos de un aplique para una region.

    Los huecos se tratan igual que el contorno pero con el desplazamiento
    invertido: lo que para el exterior es "hacia adentro de la tela", para un
    hueco es hacia afuera.
    """
    p = p or ParamAplique()
    huecos = huecos or []
    anillos = [contorno, *huecos]

    # --- 1. Linea de posicion: el contorno exacto -----------------------
    posicion: list[Polilinea] = []
    for anillo in anillos:
        posicion += puntada_recta(anillo, ParamRecta(largo_mm=p.largo_posicion_mm),
                                  cerrada=True)

    # --- 2. Fijacion: por dentro del borde ------------------------------
    fijacion: list[Polilinea] = []
    m = p.margen_fijacion_mm
    fijacion += puntada_recta(desplazar_contorno(contorno, -m),
                              ParamRecta(largo_mm=2.0), cerrada=True)
    for hueco in huecos:
        fijacion += puntada_recta(desplazar_contorno(hueco, m),
                                  ParamRecta(largo_mm=2.0), cerrada=True)

    # --- 3. Cobertura: satin montado sobre el borde crudo ---------------
    ps = ParamSatin(densidad_mm=p.densidad_cobertura_mm, underlay="none")
    cobertura: list[Polilinea] = []
    for anillo in anillos:
        cobertura += _satin_sobre_borde(anillo, p.ancho_cobertura_mm, ps)

    return [
        Paso(1, "Posicion", p.color_posicion,
             "Cose la guia sobre la tela base. Al detenerse, pon el retazo "
             "encima cubriendo la linea.", posicion),
        Paso(2, "Fijacion", p.color_fijacion,
             "Sujeta el retazo. Al detenerse, recorta la tela sobrante al ras "
             "de la costura con tijera curva.", fijacion),
        Paso(3, "Cobertura", color_cobertura,
             "Satin que tapa el borde recortado. Este es el unico paso que se "
             "ve en la pieza terminada.", cobertura, pausa_despues=False),
    ]


def _satin_sobre_borde(anillo: Polilinea, ancho_mm: float,
                       ps: ParamSatin) -> list[Polilinea]:
    """
    Columna satin CENTRADA en el borde: mitad sobre el retazo, mitad sobre la
    tela base. Es lo que tapa el corte y evita que se deshilache.
    """
    fuera = desplazar_contorno(anillo, ancho_mm / 2.0)
    dentro = desplazar_contorno(anillo, -ancho_mm / 2.0)
    if len(fuera) < 3 or len(dentro) < 3:
        return []
    fuera = list(fuera) + [fuera[0]]      # se cierran los rieles
    dentro = list(dentro) + [dentro[0]]
    return columna_satin(fuera, dentro, ps)


def instrucciones(pasos: list[Paso]) -> str:
    """Texto para la ficha tecnica. Es lo que hace usable la funcion."""
    lineas = ["APLIQUE - SECUENCIA DE BORDADO", "=" * 58,
              "La maquina se detiene entre pasos como si pidiera cambio de",
              "color. NO cambies el hilo salvo donde se indique: la parada",
              "esta ahi para que trabajes la tela.", ""]
    for paso in pasos:
        lineas.append(f"  {paso.orden}. {paso.nombre.upper()}  ({paso.color})")
        for trozo in _envolver(paso.instruccion, 54):
            lineas.append(f"     {trozo}")
        if paso.pausa_despues:
            lineas.append("     -> la maquina se detiene aqui")
        lineas.append("")
    lineas.append("Tela sugerida: algodon o fieltro. Con telas que se")
    lineas.append("deshilachan, usa entretela termoadhesiva por el reves.")
    return "\n".join(lineas)


def _envolver(texto: str, ancho: int) -> list[str]:
    palabras, linea, salida = texto.split(), "", []
    for w in palabras:
        if len(linea) + len(w) + 1 > ancho:
            salida.append(linea)
            linea = w
        else:
            linea = f"{linea} {w}".strip()
    if linea:
        salida.append(linea)
    return salida
