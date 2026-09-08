"""
Ventana de la aplicacion (tkinter).

Capa DELGADA: arma widgets, lee lo que el usuario eligio y pinta lo que el
controlador va publicando. No convierte ni digitaliza nada por si misma.

Dos pestanas sobre un mismo motor:
  - Convertir formatos : lote de archivos entre .pes/.jef/.dst/...
  - Imagen a bordado   : auto-digitalizacion de un PNG/JPG

La barra de progreso y el registro son compartidos: las dos tareas publican
en la misma cola de eventos, asi que un solo bucle las pinta.

El detalle no obvio es `_bombear`: tkinter no es thread-safe, asi que el hilo
trabajador nunca toca un widget. Deja eventos en una cola y este metodo la
vacia cada 80 ms desde el hilo principal.

tkinter viene incluido en el instalador oficial de Python para Windows y
macOS. En Linux puede requerir el paquete `python3-tk`.
"""

from __future__ import annotations

import sys
import webbrowser
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, WORD, X, Tk, filedialog, messagebox
from tkinter import scrolledtext, ttk

from .. import __version__
from ..convertir import FORMATOS_ESCRITURA, FORMATOS_MAQUINA
from ..parametros import AROS, PERFILES
from .controlador import (
    Avance, Controlador, Fin, FinImagen, Inicio, Mensaje, Trabajo,
    TrabajoImagen, salida_sugerida,
)

TITULO = "Conversor de matrices de bordado"
INTERVALO_MS = 80
MINIATURA = 210

# Se ofrecen solo formatos de maquina: nadie quiere convertir su catalogo a .csv.
FORMATOS = sorted(FORMATOS_MAQUINA & FORMATOS_ESCRITURA)
FORMATOS_COMUNES = [f for f in ("jef", "pes", "dst", "vp3", "exp") if f in FORMATOS]
IMAGENES = [("Imagenes y vectores",
             "*.png *.jpg *.jpeg *.webp *.bmp *.gif *.tif *.tiff *.svg"),
            ("Vectores SVG", "*.svg"),
            ("Todos los archivos", "*.*")]


class Aplicacion(ttk.Frame):
    def __init__(self, raiz: Tk) -> None:
        super().__init__(raiz, padding=10)
        self.raiz = raiz
        self.ctrl = Controlador()
        self._salida_editada = False   # si el usuario la toco, no la pisamos
        self._miniaturas: list = []    # tkinter no retiene las imagenes: hay
                                       # que guardar la referencia o se borran

        raiz.title(f"{TITULO} v{__version__}")
        raiz.minsize(760, 660)
        raiz.geometry("880x760")
        self.pack(fill=BOTH, expand=True)
        self._construir()
        self._bombear()

    # ------------------------------------------------------------ armado

    def _construir(self) -> None:
        import tkinter as tk

        self.v_estado = tk.StringVar(value="Elige una carpeta o una imagen para empezar.")

        self.cuaderno = ttk.Notebook(self)
        self.cuaderno.pack(fill=X)
        p1 = ttk.Frame(self.cuaderno, padding=10)
        p2 = ttk.Frame(self.cuaderno, padding=10)
        self.cuaderno.add(p1, text="  Convertir formatos  ")
        self.cuaderno.add(p2, text="  Imagen a bordado  ")
        self._armar_convertir(p1, tk)
        self._armar_imagen(p2, tk)

        self.barra = ttk.Progressbar(self, mode="determinate")
        self.barra.pack(fill=X, pady=(10, 4))
        ttk.Label(self, textvariable=self.v_estado).pack(anchor="w")

        r = ttk.LabelFrame(self, text="Detalle", padding=6)
        r.pack(fill=BOTH, expand=True, pady=(8, 0))
        self.log = scrolledtext.ScrolledText(r, height=12, wrap=WORD, state="disabled")
        self.log.pack(fill=BOTH, expand=True)
        for etiqueta, color in (("ok", "#1B7F3B"), ("omitido", "#8A6D00"),
                                ("error", "#B3261E"), ("titulo", "#1B4F9C")):
            self.log.tag_config(etiqueta, foreground=color)

    # -------------------------------------------------- pestana convertir

    def _armar_convertir(self, raiz, tk) -> None:
        self.v_carpeta = tk.StringVar()
        self.v_salida = tk.StringVar()
        self.v_formato = tk.StringVar(value="jef" if "jef" in FORMATOS else FORMATOS[0])
        self.v_recursivo = tk.BooleanVar(value=True)
        self.v_sobrescribir = tk.BooleanVar(value=False)
        self.v_verificar = tk.BooleanVar(value=True)
        self.v_escala = tk.DoubleVar(value=100.0)
        self.v_carpeta.trace_add("write", lambda *_: self._sugerir_salida())
        self.v_formato.trace_add("write", lambda *_: self._sugerir_salida())

        c = ttk.LabelFrame(raiz, text="1. Carpeta con los archivos", padding=8)
        c.pack(fill=X)
        fila = ttk.Frame(c); fila.pack(fill=X)
        ttk.Entry(fila, textvariable=self.v_carpeta).pack(side=LEFT, fill=X, expand=True)
        ttk.Button(fila, text="Examinar...", command=self._elegir_carpeta).pack(
            side=LEFT, padx=(6, 0))
        ttk.Checkbutton(c, text="Incluir subcarpetas",
                        variable=self.v_recursivo).pack(anchor="w", pady=(6, 0))

        d = ttk.LabelFrame(raiz, text="2. Convertir a", padding=8)
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
        ttk.Label(fila, text="Redimensionar a:").pack(side=LEFT)
        ttk.Spinbox(fila, from_=88, to=112, increment=1, width=5,
                    textvariable=self.v_escala).pack(side=LEFT, padx=(6, 2))
        ttk.Label(fila, text="%   (100 = sin cambio; mas alla de ±12% hay que "
                             "re-digitalizar el original)").pack(side=LEFT)

        fila = ttk.Frame(d); fila.pack(fill=X, pady=(8, 0))
        ttk.Checkbutton(fila, text="Reemplazar archivos existentes",
                        variable=self.v_sobrescribir).pack(side=LEFT)
        ttk.Checkbutton(fila, text="Verificar cada archivo generado",
                        variable=self.v_verificar).pack(side=LEFT, padx=(16, 0))

        a = ttk.Frame(raiz); a.pack(fill=X, pady=(12, 0))
        self.btn_convertir = ttk.Button(a, text="Convertir", command=self._convertir)
        self.btn_convertir.pack(side=LEFT)
        self.btn_cancelar = ttk.Button(a, text="Cancelar", state="disabled",
                                       command=self.ctrl.cancelar)
        self.btn_cancelar.pack(side=LEFT, padx=(6, 0))
        self.btn_abrir = ttk.Button(a, text="Abrir carpeta de salida",
                                    state="disabled", command=self._abrir_salida)
        self.btn_abrir.pack(side=RIGHT)

    # ---------------------------------------------------- pestana imagen

    def _armar_imagen(self, raiz, tk) -> None:
        self.v_imagen = tk.StringVar()
        self.v_ancho = tk.DoubleVar(value=80.0)
        self.v_colores = tk.IntVar(value=5)
        self.v_aro = tk.StringVar(value="brother_5x7")
        self.v_densidad = tk.DoubleVar(value=0.40)
        self.v_quitar_fondo = tk.BooleanVar(value=True)
        self.v_aplique = tk.BooleanVar(value=False)
        self.v_calidad = tk.StringVar(value="equilibrada")
        self.v_semilla = tk.IntVar(value=0)
        self.v_salida_img = tk.StringVar()
        self.v_fmt_img = {f: tk.BooleanVar(value=(f == "jef"))
                          for f in FORMATOS_COMUNES}
        self.v_imagen.trace_add("write", lambda *_: self._al_elegir_imagen())

        c = ttk.LabelFrame(raiz, text="1. Imagen (PNG, JPG, WEBP...)", padding=8)
        c.pack(fill=X)
        fila = ttk.Frame(c); fila.pack(fill=X)
        ttk.Entry(fila, textvariable=self.v_imagen).pack(side=LEFT, fill=X, expand=True)
        ttk.Button(fila, text="Examinar...", command=self._elegir_imagen).pack(
            side=LEFT, padx=(6, 0))
        ttk.Label(c, text="Funciona mejor con logos y dibujos de colores planos "
                          "que con fotografias. Si tienes el SVG, usalo: los "
                          "contornos salen exactos.").pack(anchor="w", pady=(6, 0))

        d = ttk.LabelFrame(raiz, text="2. Como bordarlo", padding=8)
        d.pack(fill=X, pady=(10, 0))
        fila = ttk.Frame(d); fila.pack(fill=X)
        ttk.Label(fila, text="Ancho final:").pack(side=LEFT)
        ttk.Spinbox(fila, from_=10, to=400, increment=5, width=6,
                    textvariable=self.v_ancho).pack(side=LEFT, padx=(6, 2))
        ttk.Label(fila, text="mm").pack(side=LEFT, padx=(0, 16))
        ttk.Label(fila, text="Colores de hilo:").pack(side=LEFT)
        ttk.Spinbox(fila, from_=2, to=12, width=4,
                    textvariable=self.v_colores).pack(side=LEFT, padx=(6, 16))
        ttk.Label(fila, text="Aro:").pack(side=LEFT)
        ttk.Combobox(fila, textvariable=self.v_aro, values=sorted(AROS),
                     state="readonly", width=13).pack(side=LEFT, padx=(6, 16))
        ttk.Label(fila, text="Calidad:").pack(side=LEFT)
        ttk.Combobox(fila, textvariable=self.v_calidad,
                     values=["alta", "equilibrada", "rapida"],
                     state="readonly", width=12).pack(side=LEFT, padx=(6, 0))

        fila = ttk.Frame(d); fila.pack(fill=X, pady=(8, 0))
        ttk.Label(fila, text="Formatos:").pack(side=LEFT)
        for f in FORMATOS_COMUNES:
            ttk.Checkbutton(fila, text=f".{f}", variable=self.v_fmt_img[f]).pack(
                side=LEFT, padx=(6, 0))
        ttk.Checkbutton(fila, text="Recortar el fondo",
                        variable=self.v_quitar_fondo).pack(side=LEFT, padx=(20, 0))

        fila = ttk.Frame(d); fila.pack(fill=X, pady=(8, 0))
        ttk.Checkbutton(fila, text="Usar aplique en las areas grandes",
                        variable=self.v_aplique).pack(side=LEFT)
        ttk.Label(fila, text="(coses sobre un retazo de tela en vez de rellenar "
                             "con hilo: mucho mas rapido y flexible)"
                  ).pack(side=LEFT, padx=(8, 0))

        fila = ttk.Frame(d); fila.pack(fill=X, pady=(6, 0))
        ttk.Label(fila, text="Calidad rapida quita ~20% del tiempo de maquina; "
                             "alta lo sube ~8%. Se nota en los detalles finos, "
                             "no en las areas grandes.").pack(side=LEFT)

        fila = ttk.Frame(d); fila.pack(fill=X, pady=(8, 0))
        ttk.Label(fila, text="Guardar en:").pack(side=LEFT)
        ttk.Entry(fila, textvariable=self.v_salida_img).pack(
            side=LEFT, fill=X, expand=True, padx=(6, 0))
        ttk.Button(fila, text="Examinar...", command=self._elegir_salida_img).pack(
            side=LEFT, padx=(6, 0))

        a = ttk.Frame(raiz); a.pack(fill=X, pady=(12, 0))
        self.btn_digitalizar = ttk.Button(a, text="Digitalizar",
                                          command=self._digitalizar)
        self.btn_digitalizar.pack(side=LEFT)
        ttk.Label(a, text="Si el corte de colores no te convence, cambia la "
                          "semilla:").pack(side=LEFT, padx=(16, 4))
        ttk.Spinbox(a, from_=0, to=99, width=4,
                    textvariable=self.v_semilla).pack(side=LEFT)

        v = ttk.Frame(raiz); v.pack(fill=X, pady=(10, 0))
        self.lbl_original = ttk.Label(v, text="(sin imagen)", anchor="center",
                                      relief="groove", width=26)
        self.lbl_original.pack(side=LEFT, fill=BOTH, expand=True)
        self.lbl_bordado = ttk.Label(v, text="(sin resultado)", anchor="center",
                                     relief="groove", width=26)
        self.lbl_bordado.pack(side=LEFT, fill=BOTH, expand=True, padx=(10, 0))

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

    def _elegir_imagen(self) -> None:
        f = filedialog.askopenfilename(title="Elige una imagen", filetypes=IMAGENES)
        if f:
            self.v_imagen.set(f)

    def _elegir_salida_img(self) -> None:
        d = filedialog.askdirectory(title="Carpeta de destino")
        if d:
            self.v_salida_img.set(d)

    def _sugerir_salida(self) -> None:
        """Propone `<carpeta>/convertidos_<formato>` mientras el usuario no la edite."""
        if self._salida_editada:
            return
        carpeta = self.v_carpeta.get().strip()
        if carpeta:
            self.v_salida.set(str(salida_sugerida(Path(carpeta), self.v_formato.get())))

    def _al_elegir_imagen(self) -> None:
        ruta = Path(self.v_imagen.get().strip())
        if not self.v_salida_img.get().strip() and ruta.parent.is_dir():
            self.v_salida_img.set(str(ruta.parent / "bordado"))
        self._mostrar(self.lbl_original, ruta, "(sin imagen)")

    def _mostrar(self, etiqueta, ruta: Path, vacio: str) -> None:
        """Pinta una miniatura, o el texto de reserva si no se puede."""
        try:
            from PIL import Image, ImageTk
            img = Image.open(ruta).convert("RGBA")
            fondo = Image.new("RGBA", img.size, (255, 255, 255, 255))
            img = Image.alpha_composite(fondo, img).convert("RGB")
            img.thumbnail((MINIATURA, MINIATURA))
            tk_img = ImageTk.PhotoImage(img)
            self._miniaturas.append(tk_img)
            etiqueta.config(image=tk_img, text="")
        except Exception:  # noqa: BLE001 - la miniatura es un lujo, no un requisito
            etiqueta.config(image="", text=vacio)

    def _trabajo(self) -> Trabajo:
        salida = self.v_salida.get().strip()
        return Trabajo(
            carpeta=Path(self.v_carpeta.get().strip()),
            formato=self.v_formato.get(),
            recursivo=self.v_recursivo.get(),
            dir_salida=Path(salida) if salida else None,
            sobrescribir=self.v_sobrescribir.get(),
            verificar=self.v_verificar.get(),
            escala=float(self.v_escala.get()) / 100.0,
        )

    def _trabajo_imagen(self) -> TrabajoImagen:
        salida = self.v_salida_img.get().strip()
        return TrabajoImagen(
            imagen=Path(self.v_imagen.get().strip()),
            ancho_mm=float(self.v_ancho.get()),
            n_colores=int(self.v_colores.get()),
            formatos=tuple(f for f, v in self.v_fmt_img.items() if v.get()),
            dir_salida=Path(salida) if salida else None,
            aro=self.v_aro.get(),
            densidad_mm=float(self.v_densidad.get()),
            quitar_fondo=self.v_quitar_fondo.get(),
            semilla=int(self.v_semilla.get()),
            aplique=self.v_aplique.get(),
            perfil=self.v_calidad.get(),
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
        self._ocupar()
        self.ctrl.iniciar(trabajo)

    def _digitalizar(self) -> None:
        try:
            trabajo = self._trabajo_imagen()
        except Exception:  # noqa: BLE001 - un spinbox editado a mano puede traer basura
            messagebox.showwarning(TITULO, "Revisa el ancho, los colores y la semilla.")
            return
        problema = trabajo.validar()
        if problema:
            messagebox.showwarning(TITULO, problema)
            return
        self._limpiar_log()
        self._escribir(
            f"Digitalizando {trabajo.imagen.name}\n"
            f"{trabajo.ancho_mm:.0f} mm de ancho · {trabajo.n_colores} colores · "
            f"{', '.join('.' + f for f in trabajo.formatos)}\n", "titulo")
        self.lbl_bordado.config(image="", text="calculando...")
        self._ocupar()
        self.barra.config(mode="indeterminate")
        # 12 ms eran ~80 cuadros por segundo para una barra de progreso: puro
        # gasto. Cada ciclo se reprograma solo, asi que cuanto mas corto, mas
        # presion sobre el bucle de eventos.
        self.barra.start(30)
        self.ctrl.iniciar_imagen(trabajo)

    def _abrir_salida(self) -> None:
        ruta = (self.v_salida.get().strip()
                if self.cuaderno.index("current") == 0
                else self.v_salida_img.get().strip())
        if ruta and Path(ruta).is_dir():
            webbrowser.open(Path(ruta).resolve().as_uri())

    def _ocupar(self) -> None:
        self.barra.config(value=0)
        for b in (self.btn_convertir, self.btn_digitalizar):
            b.config(state="disabled")
        self.btn_cancelar.config(state="normal")
        self.btn_abrir.config(state="disabled")

    def _liberar(self) -> None:
        # `stop()` solo corresponde al modo indeterminado (la digitalizacion,
        # que no sabe cuanto falta). Llamarlo sobre una barra determinada la
        # devuelve a cero, y el usuario ve el progreso deshacerse justo al
        # terminar, como si el trabajo se hubiera perdido.
        if str(self.barra["mode"]) == "indeterminate":
            self.barra.stop()
            self.barra.config(mode="determinate", value=0)
        for b in (self.btn_convertir, self.btn_digitalizar):
            b.config(state="normal")
        self.btn_cancelar.config(state="disabled")

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
            elif isinstance(ev, Mensaje):
                self._escribir(ev.texto + "\n", ev.tono)
            elif isinstance(ev, FinImagen):
                self._terminar_imagen(ev)
            elif isinstance(ev, Fin):
                self._terminar(ev)
        self.raiz.after(INTERVALO_MS, self._bombear)

    def _terminar(self, ev: Fin) -> None:
        self._liberar()
        self.v_estado.set(ev.resumen())
        self._escribir("\n" + ev.resumen() + "\n",
                       "error" if ev.error or ev.errores else "ok")
        salida = self.v_salida.get().strip()
        if salida and Path(salida).is_dir():
            self.btn_abrir.config(state="normal")
        if ev.error:
            messagebox.showerror(TITULO, ev.error)

    def _terminar_imagen(self, ev: FinImagen) -> None:
        self._liberar()
        if ev.error:
            self.v_estado.set(ev.error)
            self._escribir(ev.error + "\n", "error")
            self.lbl_bordado.config(image="", text="(sin resultado)")
            messagebox.showerror(TITULO, ev.error)
            return
        self._escribir("\n" + ev.calidad + "\n", "ok")
        self._escribir("Archivos generados:\n" + "".join(
            f"  {a.name}\n" for a in ev.archivos), "ok")
        self.v_estado.set(f"Listo: {len(ev.archivos)} archivo(s) generados.")
        if ev.vista_previa and ev.vista_previa.exists():
            self._mostrar(self.lbl_bordado, ev.vista_previa, "(sin resultado)")
        salida = self.v_salida_img.get().strip()
        if salida and Path(salida).is_dir():
            self.btn_abrir.config(state="normal")

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
