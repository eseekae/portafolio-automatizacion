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
from ..parametros import AROS


@dataclass(frozen=True)
class Trabajo:
    """Lo que el usuario configuro en la ventana."""
    carpeta: Path
    formato: str = "jef"
    recursivo: bool = True
    dir_salida: Path | None = None
    sobrescribir: bool = False
    verificar: bool = True
    escala: float = 1.0

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


@dataclass(frozen=True)
class TrabajoImagen:
    """Lo que el usuario configuro en la pestana de digitalizacion."""
    imagen: Path
    ancho_mm: float = 80.0
    n_colores: int = 5
    formatos: tuple[str, ...] = ("jef",)
    dir_salida: Path | None = None
    aro: str = "brother_5x7"
    densidad_mm: float = 0.40
    quitar_fondo: bool = True
    semilla: int = 0
    aplique: bool = False
    perfil: str = "equilibrada"

    def validar(self) -> str:
        if not str(self.imagen).strip() or str(self.imagen) == ".":
            return "Elige una imagen."
        if not self.imagen.is_file():
            return f"No existe el archivo:\n{self.imagen}"
        if not 10.0 <= self.ancho_mm <= 400.0:
            return "El ancho debe estar entre 10 y 400 mm."
        if not 2 <= self.n_colores <= 12:
            return ("Elige entre 2 y 12 colores. Mas de 12 hilos no lo borda "
                    "nadie a mano.")
        if not self.formatos:
            return "Elige al menos un formato de salida."
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


@dataclass
class Mensaje:
    """Linea suelta de progreso, para tareas que no van archivo por archivo."""
    texto: str
    tono: str = ""


@dataclass
class FinImagen:
    resumen: str = ""
    calidad: str = ""
    archivos: list[Path] = field(default_factory=list)
    vista_previa: Path | None = None
    error: str = ""


Evento = Inicio | Avance | Fin | Mensaje | FinImagen


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

    def iniciar_imagen(self, t: TrabajoImagen) -> bool:
        if self.ocupado:
            return False
        self._cancelar.clear()
        self._hilo = threading.Thread(target=self._trabajar_imagen, args=(t,),
                                      daemon=True)
        self._hilo.start()
        return True

    def _trabajar_imagen(self, t: TrabajoImagen) -> None:
        """
        Digitaliza una imagen. Corre en el hilo trabajador igual que el lote:
        segmentar y trazar contornos toma segundos, y con la interfaz bloqueada
        Windows la marcaria como "no responde".
        """
        try:
            # numpy y Pillow se cargan solo si el usuario usa esta pestana.
            from ..exportar import exportar
            from ..imagen.digitalizar import digitalizar
            from ..parametros import ParamGlobales

            self.cola.put(Mensaje(f"Analizando {t.imagen.name}...", "titulo"))
            g = ParamGlobales(aro=AROS[t.aro])
            destino = t.dir_salida or t.imagen.parent
            nombre = t.imagen.stem

            patron, d, _ = digitalizar(
                t.imagen, ancho_mm=t.ancho_mm, n_colores=t.n_colores,
                formato_hilos=t.formatos[0], g=g, densidad_mm=t.densidad_mm,
                quitar_fondo=t.quitar_fondo, semilla=t.semilla,
                aplique=t.aplique, perfil=t.perfil)

            if self._cancelar.is_set():
                self.cola.put(FinImagen(error="Cancelado."))
                return

            self.cola.put(Mensaje(d.resumen()))
            if d.notas:
                self.cola.put(Mensaje("\n" + d.notas, "titulo"))
            # Con aplique cada bloque de color es una parada de la maquina.
            # Si un formato pierde una, el archivo no sirve: se comprueba.
            reporte, archivos = exportar(
                patron, nombre, destino, g, formatos=list(t.formatos),
                paradas_esperadas=d.paradas if t.aplique else None,
                notas=d.notas)
            previa = next((a for a in archivos if a.name.endswith("_preview.png")),
                          None)
            self.cola.put(FinImagen(resumen=d.resumen(),
                                    calidad=reporte.texto(),
                                    archivos=archivos, vista_previa=previa))
        except Exception as e:  # noqa: BLE001 - la ventana no puede morir en silencio
            self.cola.put(FinImagen(error=f"{type(e).__name__}: {e}"))

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
                escala=t.escala,
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
