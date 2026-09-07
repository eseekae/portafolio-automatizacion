"""
Punto de entrada del ejecutable.

Existe separado de `bordado/gui/app.py` por dos razones:

1. PyInstaller necesita un script suelto como raiz del analisis de imports.
2. En modo ventana (--windowed) PyInstaller deja `sys.stdout` y `sys.stderr`
   en None. Cualquier `print()` de una dependencia revienta con AttributeError
   y el usuario solo ve la aplicacion cerrarse sin explicacion. Aqui se
   redirigen a un descarte antes de tocar nada.
"""

import os
import sys

for flujo in ("stdout", "stderr"):
    if getattr(sys, flujo, None) is None:
        setattr(sys, flujo, open(os.devnull, "w"))  # noqa: SIM115

from bordado.gui.app import main  # noqa: E402


def _reportar(exc: BaseException) -> None:
    """
    Un fallo antes de que exista la ventana dejaria el ejecutable muriendo en
    silencio. Se muestra en un cuadro de dialogo, que es lo unico que el
    usuario de un .exe puede ver.
    """
    try:
        import traceback
        from tkinter import Tk, messagebox
        raiz = Tk()
        raiz.withdraw()
        messagebox.showerror(
            "Conversor de matrices de bordado",
            "Ocurrio un error inesperado:\n\n"
            + "".join(traceback.format_exception_only(type(exc), exc)).strip())
        raiz.destroy()
    except Exception:  # noqa: BLE001 - si ni tkinter carga, no hay nada que hacer
        pass


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as e:  # noqa: BLE001
        _reportar(e)
        sys.exit(1)
