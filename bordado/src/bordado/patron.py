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
    forzar_bloque: bool = False      # exige parada aunque el color se repita
    enlazar: bool = True             # False: se salta entre corridas, no se cose


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
        self._anterior: Polilinea = []

    def agregar(self, nombre: str, color: str, corridas: list[Polilinea],
                catalogo: str = "", forzar_bloque: bool = False,
                enlazar: bool = True) -> "ConstructorPatron":
        """
        `forzar_bloque` exige que este objeto empiece un bloque de color nuevo
        aunque el color coincida con el anterior. Lo usa el aplique, donde la
        parada de la maquina es la instruccion para el operador y fusionar dos
        bloques la haria desaparecer.

        `enlazar=False` prohibe llegar COSIENDO de una corrida a la siguiente.
        Lo usan las letras: los trazos de un numero estan a uno o dos
        milimetros unos de otros, asi que el enlace siempre se activa y deja
        una linea de hilo cruzando el caracter por el medio. Sobre un relleno
        eso no se ve; sobre un "8" de cuatro milimetros, lo arruina. Entre
        trazos se salta con la aguja arriba, que es lo que se hace en
        lettering.
        """
        corridas = [c for c in corridas if len(c) >= 2]
        if corridas:
            self.objetos.append(ObjetoBordado(nombre, color, corridas,
                                              catalogo, forzar_bloque, enlazar))
        return self

    # ----------------------------------------------------------------------

    def construir(self) -> pe.EmbPattern:
        patron = pe.EmbPattern()
        color_actual: str | None = None
        ultimo: tuple[float, float] | None = None

        # Si el objeto ANTERIOR prohibia enlazar, tampoco se enlaza al salir de
        # el: el hilo cruzaria igual la letra, solo que hacia afuera.
        permitir_enlace = True

        for obj in self.objetos:
            # --- Cambio de hilo si el color cambia, o si se exige parada ---
            nuevo_bloque = obj.color != color_actual or obj.forzar_bloque
            if color_actual is not None and nuevo_bloque:
                patron.trim()
                patron.color_change()
            if nuevo_bloque:
                patron.add_thread({"hex": obj.color, "description": obj.nombre,
                                   "catalog_number": obj.catalogo})
                color_actual = obj.color

            for corrida in obj.corridas:
                corrida = self._filtrar_cortas(corrida)
                if len(corrida) < 2:
                    continue
                inicio = corrida[0]

                # --- Como se llega a la costura siguiente -----------------
                # Tres casos, no dos. El del medio es el que faltaba y el que
                # hacia que la maquina cortara para moverse dos milimetros.
                enlazar = cortar = False
                if ultimo is None:
                    cortar = True                     # arranque del bloque
                else:
                    salto = math.dist(ultimo, inicio)
                    if (salto <= self.g.enlace_max_mm
                            and obj.enlazar and permitir_enlace):
                        enlazar = True                # se llega cosiendo
                    elif salto > self.g.salto_max_sin_corte_mm:
                        cortar = True                 # muy lejos: se corta

                if cortar and ultimo is not None:
                    # Remate de salida: solo tiene sentido si se va a cortar.
                    # Sin corte no hay punta suelta que asegurar.
                    for pnt in self._remate(self._anterior[::-1]):
                        patron.stitch_abs(*self._u(pnt))
                    patron.trim()

                if enlazar:
                    # Se cose el tramo hasta el inicio, partido para que
                    # ninguna puntada se pase de larga.
                    for pnt in self._enlace(ultimo, inicio):
                        patron.stitch_abs(*self._u(pnt))
                    # Si el arranque cae practicamente encima de donde quedo
                    # la aguja, se omite: repetir esa perforacion daria una
                    # puntada mas corta que el minimo y la aguja repicaria el
                    # mismo agujero.
                    if math.dist(ultimo, inicio) < self.g.puntada_min_mm:
                        corrida = corrida[1:]
                        if len(corrida) < 2:
                            continue
                else:
                    patron.move_abs(*self._u(inicio))
                    if cortar:
                        # Remate de entrada: amarra el hilo recien cortado.
                        for pnt in self._remate(corrida):
                            patron.stitch_abs(*self._u(pnt))

                for pnt in corrida:
                    patron.stitch_abs(*self._u(pnt))

                ultimo = corrida[-1]
                self._anterior = corrida

            permitir_enlace = obj.enlazar

        # Remate final de la ultima costura, que si se va a cortar.
        if self.objetos and self._anterior:
            for pnt in self._remate(self._anterior[::-1]):
                patron.stitch_abs(*self._u(pnt))

        patron.end()
        return patron

    # ----------------------------------------------------------------------

    def _u(self, p: tuple[float, float]) -> tuple[float, float]:
        """
        mm -> unidades de maquina (1/10 mm), INVIRTIENDO el eje Y.

        Aqui se cruza la unica frontera de convencion del proyecto y hay que
        cruzarla bien, porque equivocarse no se ve en pantalla: se ve en la
        tela, con el diseno cabeza abajo.

        El dominio (geometria.py, puntadas.py, los disenos) trabaja con Y
        hacia ARRIBA, como en matematicas: es lo natural para calcular
        angulos, normales y barridos.

        pyembroidery trabaja internamente con Y hacia ABAJO, como una imagen.
        No es una eleccion nuestra ni es discutible, se comprueba en su
        propio codigo: JefWriter escribe `-dy` al volcar al archivo (el
        formato JEF si usa Y hacia arriba, y por eso lo niega), y PngWriter
        dibuja la fila `y - min_y`, o sea Y hacia abajo.

        Por eso el signo se cambia AQUI, una sola vez. Antes no se cambiaba
        en ninguna parte y los archivos salian espejados verticalmente; la
        vista previa y el simulador lo compensaban con un volteo propio, asi
        que en pantalla todo parecia correcto mientras la maquina bordaba el
        diseno al reves. Ese volteo de cortesia ya no existe en ningun lado:
        ahora el archivo es la verdad y todos lo leen tal cual.
        """
        return p[0] * UNIDADES_POR_MM, -p[1] * UNIDADES_POR_MM

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

    def _enlace(self, desde: tuple[float, float],
                hasta: tuple[float, float]) -> Polilinea:
        """
        Camino cosido entre dos costuras vecinas.

        Es lo que evita el corte inutil: si el siguiente arranque queda a unos
        milimetros, la aguja llega cosiendo en vez de levantarse, cortar y
        volver a amarrar.

        Devuelve solo los puntos INTERMEDIOS. El punto de llegada lo cose la
        propia costura siguiente, que empieza justo ahi; anadirlo aqui daria
        una puntada de largo cero.
        """
        d = math.dist(desde, hasta)
        if d <= self.g.puntada_max_mm:
            return []          # se llega de una puntada, sin partir nada
        trozos = int(math.ceil(d / self.g.puntada_max_mm))
        return [(desde[0] + (hasta[0] - desde[0]) * k / trozos,
                 desde[1] + (hasta[1] - desde[1]) * k / trozos)
                for k in range(1, trozos)]

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
