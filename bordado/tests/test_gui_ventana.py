"""
Prueba de la ventana real. Se salta sola si no hay entorno grafico
(contenedores, CI sin display), asi nunca rompe el build.

Cubre lo unico que el test del controlador no puede ver: que los widgets se
creen, que el bucle `after()` traslade los eventos del hilo trabajador a la
interfaz, y que los botones queden en el estado correcto al terminar.
"""

import time
from pathlib import Path

import pyembroidery as pe
import pytest

from bordado.geometria import circulo
from bordado.parametros import ParamGlobales, ParamRelleno
from bordado.patron import ConstructorPatron
from bordado.puntadas import relleno_tatami

tk = pytest.importorskip("tkinter")


@pytest.fixture
def ventana():
    try:
        raiz = tk.Tk()
    except tk.TclError as e:            # sin DISPLAY / sin servidor grafico
        pytest.skip(f"sin entorno grafico: {e}")
    raiz.withdraw()
    yield raiz
    raiz.destroy()


@pytest.fixture
def carpeta(tmp_path: Path) -> Path:
    b = ConstructorPatron(ParamGlobales())
    b.agregar("a", "#1B4F9C", relleno_tatami(circulo((0, 0), 8), ParamRelleno()))
    patron = b.construir()
    raiz = tmp_path / "entrada"
    raiz.mkdir()
    for i in range(3):
        pe.write(patron, str(raiz / f"d{i}.pes"), {"version": 1})
    return raiz


def test_ventana_convierte_de_punta_a_punta(ventana, carpeta: Path):
    from bordado.gui.app import Aplicacion

    app = Aplicacion(ventana)
    ventana.update()

    # La carpeta de salida se sugiere sola y sigue al formato elegido.
    app.v_carpeta.set(str(carpeta))
    ventana.update()
    assert app.v_salida.get().endswith("convertidos_jef")
    app.v_formato.set("dst")
    ventana.update()
    assert app.v_salida.get().endswith("convertidos_dst")
    app.v_formato.set("jef")
    ventana.update()

    app._convertir()
    assert str(app.btn_convertir["state"]) == "disabled"

    limite = time.monotonic() + 60
    while app.ctrl.ocupado or app.ctrl.cola.qsize():
        ventana.update()
        time.sleep(0.02)
        assert time.monotonic() < limite, "la conversion no termino"
    ventana.update()

    assert len(list(Path(app.v_salida.get()).rglob("*.jef"))) == 3
    assert "3 convertidos" in app.v_estado.get()
    assert str(app.btn_convertir["state"]) == "normal"
    assert str(app.btn_cancelar["state"]) == "disabled"
    assert int(app.barra["value"]) == int(app.barra["maximum"]) == 3


def test_pestana_de_imagen_digitaliza_de_punta_a_punta(ventana, tmp_path):
    """
    La segunda pestana, completa: elegir imagen -> digitalizar -> archivos
    en disco y miniatura del resultado en pantalla.
    """
    from PIL import Image, ImageDraw

    from bordado.gui.app import Aplicacion

    origen = tmp_path / "logo.png"
    img = Image.new("RGB", (240, 240), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.ellipse([20, 20, 220, 220], fill=(26, 62, 110))
    d.rectangle([90, 100, 150, 140], fill=(240, 232, 210))
    img.save(origen)

    app = Aplicacion(ventana)
    ventana.update()
    app.cuaderno.select(1)
    app.v_imagen.set(str(origen))
    ventana.update()
    # La carpeta de salida se propone sola junto a la imagen.
    assert app.v_salida_img.get().endswith("bordado")

    app.v_ancho.set(45.0)
    app.v_colores.set(3)
    app.v_fmt_img["pes"].set(True)
    ventana.update()

    app._digitalizar()
    assert str(app.btn_digitalizar["state"]) == "disabled"

    limite = time.monotonic() + 120
    while app.ctrl.ocupado or app.ctrl.cola.qsize():
        ventana.update()
        time.sleep(0.02)
        assert time.monotonic() < limite, "la digitalizacion no termino"
    ventana.update()

    salida = Path(app.v_salida_img.get())
    assert (salida / "logo.jef").exists() and (salida / "logo.pes").exists()
    assert (salida / "logo_preview.png").exists()
    assert str(app.btn_digitalizar["state"]) == "normal"
    assert "Listo" in app.v_estado.get()
    assert len(app._miniaturas) == 2      # original + resultado


def test_imagen_inexistente_avisa_y_no_arranca(ventana, monkeypatch, tmp_path):
    from bordado.gui import app as modulo

    avisos: list = []
    monkeypatch.setattr(modulo.messagebox, "showwarning",
                        lambda *a, **k: avisos.append(a))
    app = modulo.Aplicacion(ventana)
    ventana.update()
    app.cuaderno.select(1)
    app.v_imagen.set(str(tmp_path / "fantasma.png"))
    app._digitalizar()
    assert avisos and not app.ctrl.ocupado


def test_campo_vacio_no_convierte_el_directorio_actual(ventana, monkeypatch):
    """Sin carpeta elegida debe avisar, no ponerse a convertir donde sea."""
    from bordado.gui import app as modulo

    avisos: list = []
    monkeypatch.setattr(modulo.messagebox, "showwarning",
                        lambda *a, **k: avisos.append(a))
    app = modulo.Aplicacion(ventana)
    ventana.update()
    app._convertir()
    assert avisos and not app.ctrl.ocupado
