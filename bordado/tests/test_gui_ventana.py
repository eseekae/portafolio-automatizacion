"""
Prueba de la ventana real. Se salta sola donde no hay entorno grafico
utilizable, asi nunca rompe el build.

Cubre lo unico que el test del controlador no puede ver: que los widgets se
creen, que el bucle `after()` traslade los eventos del hilo trabajador a la
interfaz, y que los botones queden en el estado correcto al terminar.

DETECCION DEL ENTORNO GRAFICO
    En Linux sin DISPLAY, `Tk()` lanza TclError y basta con atraparlo. En
    macOS sin sesion de ventanas (el caso de los runners de CI) `Tk()` se
    QUEDA BLOQUEADO en codigo C en vez de fallar, y ahi no hay try/except ni
    signal.alarm que valga: el interprete nunca recupera el control.

    Por eso la comprobacion se hace una sola vez en un SUBPROCESO con
    timeout. Un subproceso si se puede matar pase lo que pase. Donde tkinter
    funciona la sonda vuelve en menos de un segundo y los tests corren
    normalmente; donde se cuelga, se saltan con un motivo claro.
"""

import subprocess
import sys
import time
from pathlib import Path

import pyembroidery as pe
import pytest

from bordado.geometria import circulo
from bordado.parametros import ParamGlobales, ParamRelleno
from bordado.patron import ConstructorPatron
from bordado.puntadas import relleno_tatami

tk = pytest.importorskip("tkinter")

SONDA = "import tkinter; r = tkinter.Tk(); r.update(); r.destroy()"


def _hay_entorno_grafico(timeout: float = 25.0) -> tuple[bool, str]:
    """Abre y cierra una ventana en un subproceso desechable."""
    try:
        p = subprocess.run([sys.executable, "-c", SONDA], timeout=timeout,
                           capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        return False, (f"tkinter no respondio en {timeout:.0f} s "
                       "(sesion de ventanas no utilizable)")
    except OSError as e:
        return False, f"no se pudo lanzar la sonda: {e}"
    if p.returncode != 0:
        return False, (p.stderr.strip().splitlines() or ["tkinter fallo"])[-1]
    return True, ""


@pytest.fixture(scope="session")
def entorno_grafico():
    disponible, motivo = _hay_entorno_grafico()
    if not disponible:
        pytest.skip(f"sin entorno grafico utilizable: {motivo}")
    return True


@pytest.fixture
def ventana(entorno_grafico):
    raiz = tk.Tk()
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
