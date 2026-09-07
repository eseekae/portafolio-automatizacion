# -*- mode: python ; coding: utf-8 -*-
"""
Receta de PyInstaller. El MISMO archivo produce el ejecutable en Windows,
macOS y Linux; lo que cambia es la maquina donde se ejecuta.

PyInstaller NO puede compilar de forma cruzada: empaqueta el interprete
nativo de la plataforma donde corre. Un .exe de Windows tiene que generarse
en Windows (ver .github/workflows/ejecutables.yml).

    pyinstaller empaquetar/conversor.spec --noconfirm
"""

import sys
from pathlib import Path

NOMBRE = "ConversorBordado"
raiz = Path(SPECPATH).parent

a = Analysis(
    [str(raiz / "empaquetar" / "lanzador.py")],
    pathex=[str(raiz / "src")],
    binaries=[],
    datas=[],
    # pyembroidery resuelve el formato por extension; los lectores y escritores
    # se declaran para que el analisis estatico no deje ninguno fuera.
    hiddenimports=["bordado", "bordado.gui.app", "bordado.convertir"],
    hookspath=[],
    runtime_hooks=[],
    # Peso muerto en una herramienta de conversion: sin esto el ejecutable
    # arrastra numpy/matplotlib si estan en el entorno.
    excludes=["numpy", "matplotlib", "scipy", "pandas", "pytest", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=NOMBRE,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,          # sin ventana negra de consola en Windows
    disable_windowed_traceback=False,
    argv_emulation=False,   # macOS: abrir archivos arrastrandolos
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

if sys.platform == "darwin":
    app = BUNDLE(exe, name=f"{NOMBRE}.app",
                 bundle_identifier="io.github.eseekae.conversorbordado")
