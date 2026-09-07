"""
Ventana de la aplicacion (tkinter).

Capa DELGADA: arma widgets, lee lo que el usuario eligio y pinta lo que el
controlador va publicando. No convierte nada por si misma.

El unico detalle no obvio es el bucle `_bombear`: tkinter no es thread-safe,
asi que el hilo trabajador nunca toca un widget. Deja eventos en una cola y
este metodo la vacia cada 80 ms desde el hilo principal.

tkinter viene incluido en el instalador oficial de Python para Windows y
macOS. En Linux puede requerir el paquete `python3-tk`.
"""

from __future__ import annotations

import sys
import webbrowser
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, WORD, X, Tk, filedialog, messagebox
from tkinter import ttk
from tkinter import scrolledtext

from .. import __version__
from ..convertir import FORMATOS_ESCRITURA, FORMATOS_MAQUINA
from .controlador import Avance, Controlador, Fin, Inicio, Trabajo, salida_sugerida

TITULO = "Conversor de matrices de bordado"
INTERVALO_MS = 80

# Se ofrecen solo formatos de maquina: nadie quiere convertir su catalogo a .csv.
FORMATOS = sorted(FORMATOS_MAQUINA & FORMATOS_ESCRITURA)


class Aplicacion(ttk.Frame):
    def __init__(self, raiz: Tk) -> None:
        super().__init__(raiz, padding=12)
        self.raiz = raiz
        self.ctrl = Controlador()
        self._salida_editada = False   # si el usuario la toco, no la pisamos

        raiz.title(f"{TITULO} v{__version__}")
        raiz.minsize(680, 560)
        raiz.geometry("780x640")
        self.pack(fill=BOTH, expand=True)
        self._construir()
        self._bombear()

    # ------------------------------------------------------------ widgets

    def _construir(self) -> None:
        import tkinter as tk

        self.v_carpeta = tk.StringVar()
        self.v_salida = tk.StringVar()
        self.v_formato = tk.StringVar(value="jef" if "jef" in FORMATOS else FORMATOS[0])
        self.v_recursivo = tk.BooleanVar(value=True)
        self.v_sobrescribir = tk.BooleanVar(value=False)
        self.v_verificar = tk.BooleanVar(value=True)
        self.v_estado = tk.StringVar(value="Elige una carpeta para empezar.")

        self.v_carpeta.trace_add("write", lambda *_: self._sugerir_salida())
        self.v_formato.trace_add("write", lambda *_: self._sugerir_salida())

        # --- Origen -------------------------------------------------------
        c = ttk.LabelFrame(self, text="1. Carpeta con los archivos", padding=8)
        c.pack(fill=X)
        fila = ttk.Frame(c); fila.pack(fill=X)
        ttk.Entry(fila, textvariable=self.v_carpeta).pack(
            side=LEFT, fill=X, expand=True)
        ttk.Button(fila, text="Examinar...", command=self._elegir_carpeta).pack(
            side=LEFT, padx=(6, 0))
        ttk.Checkbutton(c, text="Incluir subcarpetas",
                        variable=self.v_recursivo).pack(anchor="w", pady=(6, 0))

        # --- Destino ------------------------------------------------------
        d = ttk.LabelFrame(self, text="2. Convertir a", padding=8)
        d.pack(fill=X, pady=(10, 0))
        fila = ttk.Frame(d); fila.pack(fill=X)
        ttk.Label(fila, text="Formato:").pack(side=LEFT)
        ttk.Combobox(fila, textvariable=self.v_formato, values=FORMATOS,
                     state="readonly", width=8).pack(side=LEFT, padx=(6, 16))
        ttk.Label(fila, text="Los archivos que ya estan en ese formato se omiten."
                  ).pack(side=LEFT)

        fila = ttk.Frame(d); fila.pack(fill=X, pady=(8, 0))
        ttk.Label(fila, text="Guardar en:").pack(side=LEFT)
        e = ttk.Entry(fila, textvariable=self.v_salida)
        e.pack(side=LEFT, fill=X, expand=True, padx=(6, 0))
        e.bind("<Key>", lambda _: setattr(self, "_salida_editada", True))
        ttk.Button(fila, text="Examinar...", command=self._elegir_salida).pack(
            side=LEFT, padx=(6, 0))

        fila = ttk.Frame(d); fila.pack(fill=X, pady=(8, 0))
        ttk.Checkbutton(fila, text="Reemplazar archivos existentes",
                        variable=self.v_sobrescribir).pack(side=LEFT)
        ttk.Checkbutton(fila, text="Verificar cada archivo generado",
                        variable=self.v_verificar).pack(side=LEFT, padx=(16, 0))

        # --- Accion -------------------------------------------------------
        a = ttk.Frame(self); a.pack(fill=X, pady=(12, 0))
        self.btn_convertir = ttk.Button(a, text="Convertir", command=self._convertir)
        self.btn_convertir.pack(side=LEFT)
        self.btn_cancelar = ttk.Button(a, text="Cancelar", state="disabled",
                                       command=self.ctrl.cancelar)
        self.btn_cancelar.pack(side=LEFT, padx=(6, 0))
        self.btn_abrir = ttk.Button(a, text="Abrir carpeta de salida",
                                    state="disabled", command=self._abrir_salida)
        self.btn_abrir.pack(side=RIGHT)

        self.barra = ttk.Progressbar(self, mode="determinate")
        self.barra.pack(fill=X, pady=(10, 4))
        ttk.Label(self, textvariable=self.v_estado).pack(anchor="w")

        # --- Registro -----------------------------------------------------
        r = ttk.LabelFrame(self, text="Detalle", padding=6)
        r.pack(fill=BOTH, expand=True, pady=(10, 0))
        self.log = scrolledtext.ScrolledText(r, height=12, wrap=WORD, state="disabled")
        self.log.pack(fill=BOTH, expand=True)
        for etiqueta, color in (("ok", "#1B7F3B"), ("omitido", "#8A6D00"),
                                ("error", "#B3261E"), ("titulo", "#1B4F9C")):
            self.log.tag_config(etiqueta, foreground=color)

    # ---------------------------------------------------------- acciones

    def _elegir_carpeta(self) -> None:
        d = filedialog.askdirectory(title="Carpeta con los archivos de bordado")
        if d:
            self.v_carpeta.set(d)

    def _elegir_salida(self) -> None:
        d = filedialog.askdirectory(title="Carpeta de destino")
        if d:
            self._salida_editada = True
            self.v_salida.set(d)

    def _sugerir_salida(self) -> None:
        """Propone `<carpeta>/convertidos_<formato>` mientras el usuario no la edite."""
        if self._salida_editada:
            return
        carpeta = self.v_carpeta.get().strip()
        if carpeta:
            self.v_salida.set(str(salida_sugerida(Path(carpeta), self.v_formato.get())))

    def _trabajo(self) -> Trabajo:
        salida = self.v_salida.get().strip()
        return Trabajo(
            carpeta=Path(self.v_carpeta.get().strip()),
            formato=self.v_formato.get(),
            recursivo=self.v_recursivo.get(),
            dir_salida=Path(salida) if salida else None,
            sobrescribir=self.v_sobrescribir.get(),
            verificar=self.v_verificar.get(),
        )

    def _convertir(self) -> None:
        trabajo = self._trabajo()
        problema = trabajo.validar()
        if problema:
            messagebox.showwarning(TITULO, problema)
            return

        self._limpiar_log()
        self._escribir(f"Convirtiendo a .{trabajo.formato}\n"
                       f"Origen : {trabajo.carpeta}\n"
                       f"Destino: {trabajo.dir_salida or 'junto a los originales'}\n",
                       "titulo")
        self.barra.config(value=0)
        self.btn_convertir.config(state="disabled")
        self.btn_cancelar.config(state="normal")
        self.btn_abrir.config(state="disabled")
        self.ctrl.iniciar(trabajo)

    def _abrir_salida(self) -> None:
        ruta = self.v_salida.get().strip()
        if ruta and Path(ruta).is_dir():
            webbrowser.open(Path(ruta).resolve().as_uri())

    # ------------------------------------------------- bucle de eventos

    def _bombear(self) -> None:
        """
        Vacia la cola del controlador desde el hilo principal.
        Es el unico punto donde los resultados del hilo trabajador tocan
        widgets, que es exactamente lo que tkinter exige.
        """
        for ev in self.ctrl.eventos():
            if isinstance(ev, Inicio):
                self.barra.config(maximum=max(ev.total, 1), value=0)
                self.v_estado.set(f"{ev.total} archivo(s) encontrados...")
                if ev.total == 0:
                    self._escribir("No se encontro ningun archivo de bordado "
                                   "legible en esa carpeta.\n", "error")
            elif isinstance(ev, Avance):
                self.barra.config(value=ev.indice)
                self.v_estado.set(f"{ev.indice} de {ev.total}: "
                                  f"{ev.resultado.origen.name}")
                self._linea(ev.resultado)
            elif isinstance(ev, Fin):
                self._terminar(ev)
        self.raiz.after(INTERVALO_MS, self._bombear)

    def _terminar(self, ev: Fin) -> None:
        self.btn_convertir.config(state="normal")
        self.btn_cancelar.config(state="disabled")
        self.v_estado.set(ev.resumen())
        self._escribir("\n" + ev.resumen() + "\n",
                       "error" if ev.error or ev.errores else "ok")
        salida = self.v_salida.get().strip()
        if salida and Path(salida).is_dir():
            self.btn_abrir.config(state="normal")
        if ev.error:
            messagebox.showerror(TITULO, ev.error)

    # ----------------------------------------------------------- registro

    def _linea(self, r) -> None:
        marca = {"ok": "OK", "omitido": "--", "error": "XX"}[r.estado]
        detalle = f"  ({r.detalle})" if r.detalle else ""
        medidas = (f"  {r.puntadas:,} punt · {r.ancho_mm:.0f}x{r.alto_mm:.0f} mm"
                   if r.puntadas else "")
        self._escribir(f"{marca} {r.origen.name}{medidas}{detalle}\n", r.estado)

    def _escribir(self, texto: str, etiqueta: str = "") -> None:
        self.log.config(state="normal")
        self.log.insert(END, texto, etiqueta or ())
        self.log.see(END)
        self.log.config(state="disabled")

    def _limpiar_log(self) -> None:
        self.log.config(state="normal")
        self.log.delete("1.0", END)
        self.log.config(state="disabled")


def main() -> int:
    raiz = Tk()
    try:
        # En Windows y macOS estos temas se ven nativos; en Linux se ignora.
        estilo = ttk.Style()
        for tema in ("vista", "aqua", "clam"):
            if tema in estilo.theme_names():
                estilo.theme_use(tema)
                break
    except Exception:  # noqa: BLE001 - el tema es cosmetico
        pass
    Aplicacion(raiz)
    raiz.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
