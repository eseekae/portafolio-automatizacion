"""
Parametros de digitalizacion (capa de dominio).

Regla de unidades del proyecto:
    - TODA la capa de dominio trabaja en MILIMETROS (float).
    - La conversion a unidades de maquina (1/10 mm, que es lo que usan
      PES/JEF/DST internamente) ocurre UNICAMENTE en la capa de exportacion.
    Esto evita el error clasico de mezclar escalas a mitad del pipeline.

Los valores por defecto son los rangos que usa la industria para hilo de
poliester 40wt con aguja 75/11, que es el estandar de mercado.
"""

from dataclasses import dataclass, field


# --------------------------------------------------------------------------
# Aros (hoops). Sin esto no puedes vender: si el diseno no entra en el aro
# del cliente, el archivo es basura por muy lindo que se vea.
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Aro:
    """Area bordable util de un aro, en mm."""
    nombre: str
    ancho_mm: float
    alto_mm: float
    familia: str  # "brother" (.pes) | "janome" (.jef) | "industrial" (.dst)


# Catalogo minimo de aros reales. Amplialo segun el mercado al que vendas.
AROS = {
    # Brother / Babylock -> .PES  (las domesticas mas vendidas en LATAM)
    "brother_4x4":   Aro("Brother 4x4",   100.0, 100.0, "brother"),
    "brother_5x7":   Aro("Brother 5x7",   130.0, 180.0, "brother"),
    "brother_6x10":  Aro("Brother 6x10",  160.0, 260.0, "brother"),
    # Janome -> .JEF
    "janome_110":    Aro("Janome A 110",  110.0, 110.0, "janome"),
    "janome_140x200": Aro("Janome B",     140.0, 200.0, "janome"),
    "janome_200x200": Aro("Janome MB",    200.0, 200.0, "janome"),
    # Industrial -> .DST
    "tajima_300x200": Aro("Tajima 300x200", 300.0, 200.0, "industrial"),
}


# --------------------------------------------------------------------------
# Parametros por tipo de puntada
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ParamRecta:
    """Puntada corrida (running stitch): contornos finos, detalles, underlay."""
    largo_mm: float = 2.0          # 1.5-2.5 mm es el rango util
    largo_min_mm: float = 0.8      # por debajo de esto la aguja perfora el mismo hoyo


@dataclass(frozen=True)
class ParamSatin:
    """
    Columna satin (zigzag denso): letras, bordes, ramas delgadas.

    Limite fisico: sobre ~8-10 mm de ancho el hilo queda flojo y se engancha.
    Para anchos mayores hay que usar relleno (tatami) o split-satin.
    """
    densidad_mm: float = 0.40      # separacion entre penetraciones consecutivas
    compensacion_mm: float = 0.15  # pull compensation: ensancha la columna
    ancho_max_mm: float = 8.0      # sobre esto -> advertencia del validador
    underlay: str = "center"       # "none" | "center" | "zigzag"


@dataclass(frozen=True)
class ParamRelleno:
    """
    Relleno tatami (lineas paralelas en serpentina). Areas grandes.
    """
    densidad_mm: float = 0.40      # separacion entre pasadas
    largo_mm: float = 3.5          # largo de cada puntada dentro de la pasada
    angulo_grados: float = 45.0    # angulo de la trama; 45 es lo mas neutro
    desfase_mm: float = 1.4        # corrimiento por fila -> evita el "efecto cremallera"
    underlay: str = "tatami"       # "none" | "contorno" | "tatami"
    densidad_underlay_mm: float = 2.0


@dataclass(frozen=True)
class ParamGlobales:
    """Parametros que aplican al patron completo."""
    aro: Aro = AROS["brother_4x4"]
    margen_seguridad_mm: float = 2.0   # holgura minima contra el borde del aro
    salto_max_sin_corte_mm: float = 6.0  # salto mas largo que esto -> TRIM
    puntada_min_mm: float = 0.7        # filtro de puntadas cortas (limite fisico aguja)
    puntada_max_mm: float = 11.0       # tope al fusionar puntadas cortas
    remate_puntadas: int = 3           # tie-in / tie-off: puntadas de amarre
    remate_largo_mm: float = 0.7
    velocidad_ppm: int = 700           # puntadas/min, para estimar tiempo de bordado
