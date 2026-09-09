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
class Perfil:
    """
    Compromiso entre acabado y tiempo de maquina.

    Las tres palancas que mueven la aguja son la separacion entre pasadas, el
    largo de puntada y cuanto underlay se pone. Ninguna es gratis, pero el
    tramo entre "alta" y "rapida" cuesta poco a la vista y ahorra un tercio
    del tiempo, que en produccion es la diferencia entre 25 y 17 minutos.
    """
    nombre: str
    densidad_mm: float
    largo_mm: float
    area_underlay_tatami_mm2: float   # sobre esto, base cruzada
    area_underlay_contorno_mm2: float # sobre esto, al menos un contorno
    salto_max_sin_corte_mm: float
    descripcion: str


# El ultimo numero es cuando cortar el hilo en vez de saltar. Cortar detiene
# la maquina alrededor de 1.5 s; saltar no la detiene pero deja un hilo suelto
# sobre la tela, que hay que recortar despues (las maquinas de la ultima
# decada lo cortan solas). Cuanto mas alto el umbral, menos paradas y mas
# hilos que repasar a mano.
PERFILES = {
    "alta": Perfil(
        "alta", 0.38, 3.2, 40.0, 8.0, 8.0,
        "Maximo acabado y minimo hilo suelto. Mas paradas de maquina."),
    "equilibrada": Perfil(
        "equilibrada", 0.40, 3.5, 60.0, 12.0, 12.0,
        "Lo que usa la industria. Buen acabado a tiempo razonable."),
    "rapida": Perfil(
        "rapida", 0.45, 4.0, 150.0, 20.0, 18.0,
        "Un tercio menos de tiempo y la mitad de paradas. Deja algun hilo "
        "suelto mas que recortar."),
}
PERFIL_POR_DEFECTO = "equilibrada"


@dataclass(frozen=True)
class ParamGlobales:
    """Parametros que aplican al patron completo."""
    aro: Aro = AROS["brother_4x4"]
    margen_seguridad_mm: float = 2.0   # holgura minima contra el borde del aro
    # Tres tramos, no dos. Si la siguiente costura empieza CERCA, se llega
    # cosiendo: sin salto, sin corte y sin remates. Solo cuando queda lejos
    # vale la pena levantar la aguja, y solo cuando queda MUY lejos, cortar.
    enlace_max_mm: float = 5.0            # hasta aqui se llega cosiendo
    salto_max_sin_corte_mm: float = 12.0  # salto mas largo que esto -> TRIM
    puntada_min_mm: float = 0.7        # filtro de puntadas cortas (limite fisico aguja)
    puntada_max_mm: float = 11.0       # tope al fusionar puntadas cortas
    remate_puntadas: int = 3           # tie-in / tie-off: puntadas de amarre
    remate_largo_mm: float = 0.7
    velocidad_ppm: int = 700           # puntadas/min, para estimar tiempo de bordado
    # La cuenta "puntadas / velocidad" se queda corta: cada corte detiene la
    # maquina y cada cambio de color son decenas de segundos reenhebrando.
    segundos_por_corte: float = 1.5
    segundos_por_color: float = 25.0
