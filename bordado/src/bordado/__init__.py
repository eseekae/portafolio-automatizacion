"""
bordado - pipeline de digitalizacion y exportacion de matrices de bordado.

Arquitectura por capas (dependencias en un solo sentido, hacia abajo):

    disenos/*.py          <- definicion del diseno (geometria + colores)
        |
        v
    puntadas.py           <- Strategy: geometria -> corridas de puntadas
        | usa
        v
    geometria.py          <- matematica pura en mm, sin dependencias
        |
    parametros.py         <- value objects inmutables (densidad, aro, etc.)
        |
        v
    patron.py             <- Builder: corridas -> EmbPattern (pyembroidery)
        |
        v
    validador.py          <- QA sobre el patron codificado
    exportar.py           <- PES/JEF/DST + preview + ficha + ZIP
"""

__version__ = "0.12.0"
