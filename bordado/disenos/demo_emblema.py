"""
Diseno de demostracion: emblema circular "Cordillera".

Geometria 100% original y generada por codigo -> sin problemas de licencia
ni de propiedad intelectual. Es el tipo de diseno que SI se puede vender.

Orden de bordado (importante: define la calidad del resultado):
  1. Fondo (relleno tatami)   - lo mas grande primero
  2. Sol   (relleno tatami)
  3. Cerros(relleno tatami)   - encima del fondo
  4. Borde (columna satin)    - siempre al final: tapa los bordes crudos
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bordado.exportar import exportar
from bordado.geometria import circulo
from bordado.parametros import (
    AROS, ParamGlobales, ParamRelleno, ParamSatin,
)
from bordado.patron import ConstructorPatron
from bordado.puntadas import columna_satin, relleno_tatami

# --- Parametros globales: aro Brother 4x4, el mas comun en casa -------------
G = ParamGlobales(aro=AROS["brother_4x4"], velocidad_ppm=700)

R_EXT = 28.0        # radio exterior del emblema (mm) -> 56 mm de diametro
ANCHO_BORDE = 2.6   # ancho de la columna satin del borde


def construir():
    b = ConstructorPatron(G)

    # 1. Fondo crema -----------------------------------------------------
    fondo = circulo((0, 0), R_EXT - ANCHO_BORDE / 2 - 0.3, segmentos=120)
    b.agregar("fondo", "#F2E4C9",
              relleno_tatami(fondo, ParamRelleno(angulo_grados=0.0,
                                                 densidad_mm=0.42)),
              catalogo="Madeira Polyneon 1751")

    # 2. Sol amarillo ----------------------------------------------------
    sol = circulo((-12.0, 13.0), 5.0, segmentos=64)
    b.agregar("sol", "#F5B301",
              relleno_tatami(sol, ParamRelleno(angulo_grados=90.0,
                                               underlay="contorno")),
              catalogo="Madeira Polyneon 1624")

    # 3. Cerros azules ---------------------------------------------------
    cerros = [
        (-24.0, -12.0), (-9.0, 9.0), (-1.0, -1.0),
        (9.0, 14.0), (24.0, -12.0),
    ]
    b.agregar("cerros", "#1B4F9C",
              relleno_tatami(cerros, ParamRelleno(angulo_grados=45.0,
                                                  densidad_mm=0.40)),
              catalogo="Madeira Polyneon 1734")

    # 4. Borde satin -----------------------------------------------------
    # Para un anillo, los dos rieles son dos circulos concentricos exactos:
    # mas preciso que desplazar un eje por normales.
    riel_ext = circulo((0, 0), R_EXT + ANCHO_BORDE / 2, segmentos=200)
    riel_int = circulo((0, 0), R_EXT - ANCHO_BORDE / 2, segmentos=200)
    riel_ext.append(riel_ext[0])   # cierra el anillo
    riel_int.append(riel_int[0])
    b.agregar("borde", "#2B2B2B",
              columna_satin(riel_ext, riel_int,
                            ParamSatin(densidad_mm=0.38, compensacion_mm=0.15)),
              catalogo="Madeira Polyneon 1800")

    return b.construir()


if __name__ == "__main__":
    patron = construir()
    salida = Path(__file__).resolve().parents[1] / "salida"
    reporte, archivos = exportar(patron, "emblema_cordillera", salida, G,
                                 formatos=["pes", "jef", "dst", "exp", "vp3"])
    print(reporte.texto())
    print("\nArchivos generados:")
    for a in archivos:
        print(f"  {a.name:<34} {a.stat().st_size:>8,} bytes")
    raise SystemExit(0 if reporte.ok else 1)
