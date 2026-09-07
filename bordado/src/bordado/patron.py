"""
Ensamblado del patron (patron de diseno: BUILDER).

Aqui se traduce el dominio (mm, corridas de puntos) al modelo de pyembroidery
(unidades de 1/10 mm + comandos de maquina). Es la UNICA capa que conoce
pyembroidery, por lo que cambiar de backend implica reescribir solo este archivo.

Responsabilidades que NO tienen los generadores de puntada y si tiene esta capa:
  - orden de objetos y secuencia de colores (minimizar cambios de hilo)
  - saltos (JUMP) vs cortes (TRIM)
  - remates de entrada y salida (tie-in / tie-off)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pyembroidery as pe

from .geometria import Polilinea
from .parametros import ParamGlobales

# Los formatos PES/JEF/DST codifican coordenadas en decimas de milimetro.
UNIDADES_POR_MM = 10.0


@dataclass
class ObjetoBordado:
    """Un elemento del diseno: geometria ya convertida en puntadas + su hilo."""
    nombre: str
    color: str                       # "#RRGGBB"
    corridas: list[Polilinea]
    catalogo: str = ""               # ej. "Madeira Polyneon 1801" (para la ficha tecnica)


class ConstructorPatron:
    """
    Builder fluido:

        patron = (ConstructorPatron(globales)
                  .agregar("fondo",  "#1B4F9C", corridas_fondo)
                  .agregar("borde",  "#FFFFFF", corridas_borde)
                  .construir())
    """

    def __init__(self, g: ParamGlobales | None = None) -> None:
        self.g = g or ParamGlobales()
        self.objetos: list[ObjetoBordado] = []

    def agregar(self, nombre: str, color: str, corridas: list[Polilinea],
                catalogo: str = "") -> "ConstructorPatron":
        corridas = [c for c in corridas if len(c) >= 2]
        if corridas:
            self.objetos.append(ObjetoBordado(nombre, color, corridas, catalogo))
        return self

    # ----------------------------------------------------------------------

    def construir(self) -> pe.EmbPattern:
        patron = pe.EmbPattern()
        color_actual: str | None = None
        ultimo: tuple[float, float] | None = None

        for obj in self.objetos:
            # --- Cambio de hilo solo si el color realmente cambia ---
            if color_actual is not None and obj.color != color_actual:
                patron.trim()
                patron.color_change()
            if obj.color != color_actual:
                patron.add_thread({"hex": obj.color, "description": obj.nombre,
                                   "catalog_number": obj.catalogo})
                color_actual = obj.color

            for corrida in obj.corridas:
                corrida = self._filtrar_cortas(corrida)
                if len(corrida) < 2:
                    continue
                inicio = corrida[0]
                # --- Salto o corte segun distancia recorrida en vacio ---
                if ultimo is not None:
                    salto = math.dist(ultimo, inicio)
                    if salto > self.g.salto_max_sin_corte_mm:
                        patron.trim()   # evita el "hilo de telarana" entre partes
                patron.move_abs(*self._u(inicio))

                # --- Tie-in: amarra el hilo antes de empezar ---
                for pnt in self._remate(corrida):
                    patron.stitch_abs(*self._u(pnt))

                for pnt in corrida:
                    patron.stitch_abs(*self._u(pnt))

                # --- Tie-off: amarra antes de cortar ---
                for pnt in self._remate(corrida[::-1]):
                    patron.stitch_abs(*self._u(pnt))

                ultimo = corrida[-1]

        patron.end()
        return patron

    # ----------------------------------------------------------------------

    def _u(self, p: tuple[float, float]) -> tuple[float, float]:
        """mm -> unidades de maquina (1/10 mm)."""
        return p[0] * UNIDADES_POR_MM, p[1] * UNIDADES_POR_MM

    def _filtrar_cortas(self, corrida: Polilinea) -> Polilinea:
        """
        Filtro de puntadas cortas ("short stitch removal").

        Restriccion FISICA, no estetica: si dos perforaciones quedan a menos
        de ~0.6 mm, la aguja vuelve a entrar por el mismo agujero, el hilo no
        agarra y termina en aguja quebrada o nido de hilo por debajo.

        Aparecen inevitablemente en los giros de fin de fila del tatami.
        La solucion estandar es eliminar el punto redundante -> la puntada
        resultante se alarga. Solo se elimina si el resultado NO supera
        `puntada_max_mm`, para no crear un hilo largo enganchable.
        """
        mn, mx = self.g.puntada_min_mm, self.g.puntada_max_mm
        salida: Polilinea = [corrida[0]]
        for pnt in corrida[1:-1]:
            if math.dist(salida[-1], pnt) >= mn:
                salida.append(pnt)
        ultimo = corrida[-1]
        while (len(salida) > 1
               and math.dist(salida[-1], ultimo) < mn
               and math.dist(salida[-2], ultimo) <= mx):
            salida.pop()
        if math.dist(salida[-1], ultimo) >= mn or len(salida) == 1:
            salida.append(ultimo)
        return salida

    def _remate(self, corrida: Polilinea) -> Polilinea:
        """
        Puntadas de amarre: micro ida-y-vuelta sobre la direccion inicial.
        Sin esto el bordado se deshila apenas se corta el hilo suelto.
        """
        if len(corrida) < 2 or self.g.remate_puntadas <= 0:
            return []
        p0, p1 = corrida[0], corrida[1]
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        d = math.hypot(dx, dy) or 1.0
        ux, uy = dx / d, dy / d
        L = self.g.remate_largo_mm
        out: Polilinea = []
        for i in range(self.g.remate_puntadas):
            f = L if i % 2 == 0 else 0.0
            out.append((p0[0] + ux * f, p0[1] + uy * f))
        return out
