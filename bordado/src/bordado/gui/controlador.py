"""
Controlador de la interfaz grafica: TODA la logica, CERO widgets.

Por que esta separado de `app.py`:

  1. tkinter NO es thread-safe. Solo el hilo principal puede tocar widgets.
     Si el lote corriera en el hilo de la interfaz, la ventana se congelaria
     ("no responde") durante toda la conversion. La solucion estandar es:
     hilo trabajador -> cola de eventos -> el hilo de la interfaz la vacia
     periodicamente con `after()`. Ese es el patron PRODUCTOR/CONSUMIDOR.

  2. Este archivo se puede testear sin pantalla. `app.py` es una capa
     delgada de presentacion encima.
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from pathlib import Path

from ..convertir import FORMATOS_ESCRITURA, Resultado, convertir_lote, recolectar


@dataclass(frozen=True)
class Trabajo:
    """Lo que el usuario configuro en la ventana."""
    carpeta: Path
    formato: str = "jef"
    recursivo: bool = True
    dir_salida: Path | None = None
    sobrescribir: bool = False
    verificar: bool = True

    def validar(self) -> str:
        """Devuelve un mensaje de error, o cadena vacia si esta todo bien."""
        # OJO: Path("") colapsa a Path("."). Si el campo va vacio y no se
        # atrapa aqui, el lote apuntaria al directorio de trabajo del
        # ejecutable (en un .exe, donde sea que lo hayan abierto). El selector
        # de carpetas siempre entrega rutas absolutas, asi que una ruta
        # relativa solo puede venir de un campo en blanco.
        if not str(self.carpeta).strip() or str(self.carpeta) == ".":
            return "Elige una carpeta con archivos de bordado."
        if not self.carpeta.is_dir():
            return f"No existe la carpeta:\n{self.carpeta}"
        if self.formato not in FORMATOS_ESCRITURA:
            return f"No se puede escribir el formato .{self.formato}"
        # La salida puede vivir dentro de la carpeta de origen: sus archivos se
        # excluyen del barrido en `_filtrar_salida`, asi el lote no se come lo
        # que el mismo genero.
        return ""


# --------------------------------------------------------------------------
# Eventos que el hilo trabajador envia a la interfaz
# --------------------------------------------------------------------------

@dataclass
class Inicio:
    total: int


@dataclass
class Avance:
    indice: int
    total: int
    resultado: Resultado


@dataclass
class Fin:
    resultados: list[Resultado] = field(default_factory=list)
    cancelado: bool = False
    error: str = ""

    @property
    def convertidos(self) -> int:
        return sum(1 for r in self.resultados if r.estado == "ok")

    @property
    def omitidos(self) -> int:
        return sum(1 for r in self.resultados if r.estado == "omitido")

    @property
    def errores(self) -> int:
        return sum(1 for r in self.resultados if r.estado == "error")

    def resumen(self) -> str:
        if self.error:
            return f"Error: {self.error}"
        base = (f"{self.convertidos} convertidos · {self.omitidos} omitidos · "
                f"{self.errores} con error")
        return base + (" · CANCELADO" if self.cancelado else "")


Evento = Inicio | Avance | Fin


# --------------------------------------------------------------------------
# Controlador
# --------------------------------------------------------------------------

class Controlador:
    """
    Corre un lote en segundo plano y publica eventos en una cola.

    Uso desde la interfaz:
        ctrl.iniciar(trabajo)
        ...cada 80 ms:  for ev in ctrl.eventos(): pintar(ev)
    """

    def __init__(self) -> None:
        self.cola: queue.Queue[Evento] = queue.Queue()
        self._hilo: threading.Thread | None = None
        self._cancelar = threading.Event()

    # -- estado ------------------------------------------------------------

    @property
    def ocupado(self) -> bool:
        return self._hilo is not None and self._hilo.is_alive()

    def cancelar(self) -> None:
        """El lote se detiene entre archivo y archivo, nunca a medio escribir."""
        self._cancelar.set()

    def eventos(self) -> list[Evento]:
        """Vacia la cola. La llama el hilo de la interfaz, nunca el trabajador."""
        salida: list[Evento] = []
        while True:
            try:
                salida.append(self.cola.get_nowait())
            except queue.Empty:
                return salida

    # -- ejecucion ---------------------------------------------------------

    def iniciar(self, trabajo: Trabajo) -> bool:
        if self.ocupado:
            return False
        self._cancelar.clear()
        self._hilo = threading.Thread(target=self._trabajar, args=(trabajo,),
                                      daemon=True)
        self._hilo.start()
        return True

    def _trabajar(self, t: Trabajo) -> None:
        try:
            archivos = recolectar([str(t.carpeta)], recursivo=t.recursivo)
            archivos = _filtrar_salida(archivos, t.dir_salida)
            self.cola.put(Inicio(total=len(archivos)))
            if not archivos:
                self.cola.put(Fin())
                return

            resultados = convertir_lote(
                archivos, t.formato,
                dir_salida=t.dir_salida, raiz=t.carpeta.resolve(), plano=False,
                sobrescribir=t.sobrescribir, verificar=t.verificar,
                progreso=lambda i, n, r: self.cola.put(Avance(i, n, r)),
                cancelado=self._cancelar.is_set,
            )
            self.cola.put(Fin(resultados=resultados,
                              cancelado=self._cancelar.is_set()))
        except Exception as e:  # noqa: BLE001 - la ventana no puede morir en silencio
            self.cola.put(Fin(error=f"{type(e).__name__}: {e}"))


def _filtrar_salida(archivos: list[Path], dir_salida: Path | None) -> list[Path]:
    """
    Excluye los archivos que estan dentro de la carpeta de salida.

    Sin esto, con la salida dentro de la carpeta de origen y busqueda
    recursiva, una segunda pasada intentaria reconvertir lo ya convertido.
    """
    if dir_salida is None:
        return archivos
    try:
        salida = dir_salida.resolve()
    except OSError:
        return archivos
    return [a for a in archivos if not a.is_relative_to(salida)]


def salida_sugerida(carpeta: Path, formato: str) -> Path:
    """Carpeta de destino por defecto: una subcarpeta, nunca mezclado."""
    return carpeta / f"convertidos_{formato}"
