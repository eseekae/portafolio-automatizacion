"""
Tests del controlador de la interfaz grafica.

No importan tkinter: toda la logica vive fuera de los widgets, justamente
para poder probarla sin pantalla (y en CI, que no tiene una).
"""

import time
from pathlib import Path

import pyembroidery as pe
import pytest

from bordado.convertir import convertir_lote, recolectar
from bordado.geometria import circulo
from bordado.gui.controlador import (
    Avance, Controlador, Fin, Inicio, Trabajo, _filtrar_salida, salida_sugerida,
)
from bordado.parametros import ParamGlobales, ParamRelleno
from bordado.patron import ConstructorPatron
from bordado.puntadas import relleno_tatami


@pytest.fixture
def carpeta(tmp_path: Path) -> Path:
    """Carpeta con 5 .pes en dos niveles, mas un archivo corrupto."""
    b = ConstructorPatron(ParamGlobales())
    b.agregar("a", "#1B4F9C", relleno_tatami(circulo((0, 0), 8), ParamRelleno()))
    patron = b.construir()
    raiz = tmp_path / "entrada"
    (raiz / "sub").mkdir(parents=True)
    for i in range(3):
        pe.write(patron, str(raiz / f"d{i}.pes"), {"version": 1})
    for i in range(2):
        pe.write(patron, str(raiz / "sub" / f"s{i}.pes"), {"version": 1})
    (raiz / "roto.pes").write_bytes(b"#PES0001x")
    return raiz


def _correr(ctrl: Controlador, trabajo: Trabajo, limite: float = 60.0) -> list:
    """Ejecuta el trabajo y devuelve todos los eventos emitidos."""
    assert ctrl.iniciar(trabajo)
    eventos: list = []
    t0 = time.monotonic()
    while True:
        eventos.extend(ctrl.eventos())
        if any(isinstance(e, Fin) for e in eventos):
            return eventos
        if time.monotonic() - t0 > limite:
            raise AssertionError("el controlador no termino a tiempo")
        time.sleep(0.01)


# ------------------------------------------------------------- validacion

def test_validar_rechaza_entradas_malas(tmp_path: Path):
    assert "Elige una carpeta" in Trabajo(carpeta=Path("")).validar()
    assert "No existe" in Trabajo(carpeta=tmp_path / "fantasma").validar()
    assert "formato" in Trabajo(carpeta=tmp_path, formato="zzz").validar()
    assert Trabajo(carpeta=tmp_path).validar() == ""


def test_salida_sugerida():
    assert salida_sugerida(Path("/x/y"), "jef") == Path("/x/y/convertidos_jef")


# --------------------------------------------------------- flujo completo

def test_flujo_emite_inicio_avances_y_fin(carpeta: Path):
    salida = carpeta.parent / "out"
    eventos = _correr(Controlador(),
                      Trabajo(carpeta=carpeta, formato="jef", dir_salida=salida))

    assert isinstance(eventos[0], Inicio) and eventos[0].total == 6
    avances = [e for e in eventos if isinstance(e, Avance)]
    assert len(avances) == 6
    assert [a.indice for a in avances] == [1, 2, 3, 4, 5, 6]

    fin = eventos[-1]
    assert isinstance(fin, Fin) and not fin.cancelado and not fin.error
    assert (fin.convertidos, fin.errores) == (5, 1)   # el corrupto se aisla
    assert len(list(salida.rglob("*.jef"))) == 5
    assert (salida / "sub" / "s0.jef").exists()       # replica el arbol


def test_no_reconvierte_su_propia_salida(carpeta: Path):
    """
    La salida por defecto vive DENTRO de la carpeta de origen. Con busqueda
    recursiva, una segunda pasada intentaria reconvertir lo ya generado.
    """
    salida = salida_sugerida(carpeta, "jef")
    trabajo = Trabajo(carpeta=carpeta, formato="jef", dir_salida=salida)
    assert _correr(Controlador(), trabajo)[-1].convertidos == 5

    fin = _correr(Controlador(), trabajo)[-1]
    assert fin.convertidos == 0
    assert len([r for r in fin.resultados if r.estado == "omitido"]) == 5
    # Lo decisivo: no aparecieron 5 archivos nuevos leidos desde la salida.
    assert len(fin.resultados) == 6


def test_carpeta_vacia_termina_limpio(tmp_path: Path):
    vacia = tmp_path / "nada"
    vacia.mkdir()
    eventos = _correr(Controlador(), Trabajo(carpeta=vacia))
    assert eventos[0].total == 0
    assert isinstance(eventos[-1], Fin) and not eventos[-1].error


def test_una_excepcion_inesperada_llega_como_Fin_con_error(carpeta, monkeypatch):
    """La ventana nunca puede quedarse colgada esperando un Fin que no llega."""
    monkeypatch.setattr("bordado.gui.controlador.recolectar",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    fin = _correr(Controlador(), Trabajo(carpeta=carpeta))[-1]
    assert isinstance(fin, Fin) and "boom" in fin.error


def test_no_admite_dos_lotes_a_la_vez(carpeta: Path):
    ctrl = Controlador()
    ctrl.iniciar(Trabajo(carpeta=carpeta, dir_salida=carpeta.parent / "o1"))
    assert ctrl.iniciar(Trabajo(carpeta=carpeta)) is False
    while ctrl.ocupado:
        time.sleep(0.01)


# ------------------------------------------------------------- cancelacion

def test_cancelacion_detiene_el_lote(carpeta: Path):
    """Se corta entre archivos, nunca a mitad de una escritura."""
    archivos = recolectar([str(carpeta)], recursivo=True)
    procesados: list = []
    res = convertir_lote(
        archivos, "jef", dir_salida=carpeta.parent / "o", raiz=carpeta,
        progreso=lambda i, n, r: procesados.append(r),
        cancelado=lambda: len(procesados) >= 2)
    assert len(res) == 2 < len(archivos)


def test_cancelar_marca_la_bandera():
    ctrl = Controlador()
    assert not ctrl._cancelar.is_set()
    ctrl.cancelar()
    assert ctrl._cancelar.is_set()


# ----------------------------------------------------------------- filtro

def test_filtrar_salida(tmp_path: Path):
    dentro = tmp_path / "out" / "a.pes"
    fuera = tmp_path / "b.pes"
    assert _filtrar_salida([dentro, fuera], tmp_path / "out") == [fuera]
    assert _filtrar_salida([dentro, fuera], None) == [dentro, fuera]


def test_resumen_es_legible():
    assert "CANCELADO" in Fin(cancelado=True).resumen()
    assert Fin(error="x").resumen().startswith("Error:")
