"""
Tests del conversor por lotes.

La regla que sostiene todo: convertir NO debe alterar el bordado. Mismas
puntadas, mismos colores, mismas dimensiones. Solo cambia el envase.
"""

import math
from pathlib import Path

import pyembroidery as pe
import pytest

from bordado.convertir import (
    FORMATOS_ESCRITURA, Resultado, convertir_archivo, convertir_lote,
    recolectar, ruta_destino,
)
from bordado.geometria import circulo
from bordado.parametros import ParamGlobales, ParamRelleno
from bordado.patron import ConstructorPatron
from bordado.puntadas import relleno_tatami


@pytest.fixture
def pes(tmp_path: Path) -> Path:
    """Un .pes real de dos colores para usar como origen."""
    b = ConstructorPatron(ParamGlobales())
    b.agregar("a", "#1B4F9C", relleno_tatami(circulo((0, 0), 10), ParamRelleno()))
    b.agregar("b", "#F5B301", relleno_tatami(circulo((25, 0), 6), ParamRelleno()))
    f = tmp_path / "origen.pes"
    pe.write(b.construir(), str(f), {"version": 1})
    return f


def _medir(f: Path) -> tuple[int, int, float, float]:
    p = pe.read(str(f))
    n = p.get_normalized_pattern().count_stitch_commands(pe.STITCH)
    x0, y0, x1, y1 = p.bounds()
    return n, p.count_threads(), (x1 - x0) / 10, (y1 - y0) / 10


# ------------------------------------------------------------- equivalencia

@pytest.mark.parametrize("formato", ["jef", "dst", "exp", "vp3", "pes"])
def test_conversion_preserva_el_bordado(pes: Path, tmp_path: Path, formato: str):
    """El invariante central: puntadas y dimensiones no cambian."""
    if formato == "pes":
        pytest.skip("mismo formato de origen: se prueba aparte")
    destino = tmp_path / f"salida.{formato}"
    r = convertir_archivo(pes, destino, formato)
    assert r.ok, r.detalle

    n0, c0, w0, h0 = _medir(pes)
    n1, c1, w1, h1 = _medir(destino)
    assert abs(n1 - n0) <= 2
    assert math.isclose(w1, w0, abs_tol=0.3) and math.isclose(h1, h0, abs_tol=0.3)
    # dst/exp no guardan color en el binario: por eso llevan paleta aparte.
    if formato not in ("dst", "exp"):
        assert c1 == c0


def test_ida_y_vuelta_pes_jef_pes(pes: Path, tmp_path: Path):
    """pes -> jef -> pes debe cerrar el circulo sin deriva."""
    jef = tmp_path / "medio.jef"
    vuelta = tmp_path / "vuelta.pes"
    assert convertir_archivo(pes, jef, "jef").ok
    assert convertir_archivo(jef, vuelta, "pes").ok
    n0, c0, w0, h0 = _medir(pes)
    n1, c1, w1, h1 = _medir(vuelta)
    assert abs(n1 - n0) <= 2 and c1 == c0
    assert math.isclose(w1, w0, abs_tol=0.3)


def test_dst_genera_archivo_de_paleta(pes: Path, tmp_path: Path):
    r = convertir_archivo(pes, tmp_path / "s.dst", "dst")
    assert r.ok and any(x.suffix == ".edr" for x in r.extras)


# ------------------------------------------------------------------ robustez

def test_archivo_corrupto_no_lanza_excepcion(tmp_path: Path):
    """Un archivo malo dentro de un lote de 40 no puede botar el proceso."""
    malo = tmp_path / "roto.pes"
    malo.write_bytes(b"#PES0001basura")
    r = convertir_archivo(malo, tmp_path / "x.jef", "jef")
    assert r.estado == "error" and "corrupto" in r.detalle


def test_no_sobrescribe_sin_permiso(pes: Path, tmp_path: Path):
    destino = tmp_path / "s.jef"
    assert convertir_archivo(pes, destino, "jef").ok
    assert convertir_archivo(pes, destino, "jef").estado == "omitido"
    assert convertir_archivo(pes, destino, "jef", sobrescribir=True).ok


def test_mismo_formato_se_omite(pes: Path, tmp_path: Path):
    assert convertir_archivo(pes, tmp_path / "s.pes", "pes").estado == "omitido"


def test_nunca_escribe_sobre_el_origen(pes: Path):
    r = convertir_archivo(pes, pes, "jef")
    assert r.estado == "error"


def test_modo_seco_no_escribe(pes: Path, tmp_path: Path):
    destino = tmp_path / "s.jef"
    r = convertir_archivo(pes, destino, "jef", seco=True)
    assert r.ok and r.puntadas > 0 and not destino.exists()


def test_verificacion_detecta_escritura_corrupta(pes: Path, tmp_path: Path,
                                                 monkeypatch):
    """Si el binario sale mal, la verificacion debe cazarlo."""
    destino = tmp_path / "s.jef"

    def escribir_basura(patron, ruta, ajustes=None):
        Path(ruta).write_bytes(b"\x00" * 64)

    monkeypatch.setattr(pe, "write", escribir_basura)
    r = convertir_archivo(pes, destino, "jef")
    assert r.estado == "error" and "verificacion" in r.detalle


# --------------------------------------------------------------------- lotes

def test_recolectar_filtra_y_no_duplica(pes: Path, tmp_path: Path):
    (tmp_path / "LEEME.txt").write_text("no soy un bordado")
    archivos = recolectar([str(tmp_path), str(pes)])
    assert archivos == [pes.resolve()]


def test_recolectar_recursivo(pes: Path, tmp_path: Path):
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)
    (sub / "otro.pes").write_bytes(pes.read_bytes())
    assert len(recolectar([str(tmp_path)], recursivo=False)) == 1
    assert len(recolectar([str(tmp_path)], recursivo=True)) == 2


def test_ruta_destino_replica_el_arbol(tmp_path: Path):
    raiz = tmp_path / "in"
    origen = raiz / "col1" / "d.pes"
    salida = tmp_path / "out"
    assert ruta_destino(origen, "jef", salida, raiz, plano=False) == salida / "col1" / "d.jef"
    assert ruta_destino(origen, "jef", salida, raiz, plano=True) == salida / "d.jef"
    assert ruta_destino(origen, "jef", None, None, False) == raiz / "col1" / "d.jef"


def test_lote_detecta_colision_de_nombres(pes: Path, tmp_path: Path):
    """
    Con --plano, dos archivos homonimos en carpetas distintas pisarian uno
    al otro. Debe reportarse como error, no perderse en silencio.
    """
    raiz = tmp_path / "in"
    for sub in ("a", "b"):
        (raiz / sub).mkdir(parents=True)
        (raiz / sub / "igual.pes").write_bytes(pes.read_bytes())
    archivos = recolectar([str(raiz)], recursivo=True)
    res = convertir_lote(archivos, "jef", dir_salida=tmp_path / "out",
                         raiz=raiz, plano=True)
    assert sum(1 for r in res if r.estado == "error") == 1
    assert "colisiona" in [r.detalle for r in res if r.estado == "error"][0]


def test_lote_aisla_los_errores(pes: Path, tmp_path: Path):
    """39 buenos + 1 malo = 39 convertidos, 1 error."""
    raiz = tmp_path / "in"
    raiz.mkdir()
    for i in range(4):
        (raiz / f"d{i}.pes").write_bytes(pes.read_bytes())
    (raiz / "roto.pes").write_bytes(b"#PES0001x")
    res = convertir_lote(recolectar([str(raiz)]), "jef",
                         dir_salida=tmp_path / "out", raiz=raiz)
    assert sum(1 for r in res if r.ok) == 4
    assert sum(1 for r in res if r.estado == "error") == 1


def test_formato_de_salida_invalido(pes: Path, tmp_path: Path):
    r = convertir_archivo(pes, tmp_path / "s.hus", "hus")
    assert r.estado == "error" and "hus" not in FORMATOS_ESCRITURA
