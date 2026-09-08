"""
Conversion por lotes entre formatos de bordado.

Esta capa es PURA: no imprime nada y no lee argumentos de consola. Recibe
rutas, devuelve resultados. El CLI (`cli.py`) se encarga de presentar.
Asi el mismo motor sirve despues para la GUI del programa completo.

QUE HACE Y QUE NO:
  - Reescribe las MISMAS puntadas en otro contenedor. No redimensiona,
    no recalcula densidad, no re-digitaliza.
  - Cada archivo se procesa de forma aislada: uno corrupto no bota el lote.
  - Verifica lo escrito releyendolo (puntadas y dimensiones deben calzar).

LIMITE REAL DE LA CONVERSION:
  Un archivo de bordado guarda PUNTADAS, no objetos. Convertir es como pasar
  un JPG a PNG: cambias el envase, no recuperas el vector. Por eso convertir
  nunca permite reescalar mas alla de +-10-20% sin arruinar la densidad.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pyembroidery as pe

UNIDADES_POR_MM = 10.0

# --------------------------------------------------------------------------
# Capacidades reales del backend, consultadas en tiempo de ejecucion.
# No se hardcodean: si pyembroidery agrega un formato, aparece solo.
# --------------------------------------------------------------------------

def _formatos() -> tuple[set[str], set[str]]:
    lee, escribe = set(), set()
    for f in pe.supported_formats():
        ext = f["extension"].lower()
        if f.get("reader"):
            lee.add(ext)
        if f.get("writer"):
            escribe.add(ext)
    return lee, escribe


FORMATOS_LECTURA, FORMATOS_ESCRITURA = _formatos()

# Formatos de maquina "de verdad" (excluye utilitarios como csv/json/png/txt).
FORMATOS_MAQUINA = {
    "pes", "jef", "dst", "exp", "vp3", "pec", "xxx", "u01", "tbf", "pmv", "sew",
}

# Estos formatos NO guardan colores en el binario. Se acompanan de un archivo
# de paleta para no perder la secuencia de hilos.
SIN_COLOR = {"dst", "exp", "u01"}
EXT_PALETA = {"dst": "edr", "exp": "inf", "u01": "edr"}

# Ajustes por formato de salida (ver writers de pyembroidery).
AJUSTES_POR_DEFECTO: dict[str, dict] = {
    "pes": {"version": 1},          # v1 = maxima compatibilidad con Brother antiguas
    "jef": {"trims": True},
    "dst": {"extended header": True},
    "exp": {},
    "vp3": {},
}


@dataclass
class Resultado:
    """Resultado de convertir UN archivo. `estado` en {ok, omitido, error}."""
    origen: Path
    destino: Path | None = None
    estado: str = "ok"
    detalle: str = ""
    puntadas: int = 0
    colores: int = 0
    ancho_mm: float = 0.0
    alto_mm: float = 0.0
    escala: float = 1.0
    extras: list[Path] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.estado == "ok"


# --------------------------------------------------------------------------
# Descubrimiento de entradas
# --------------------------------------------------------------------------

def recolectar(entradas: list[str], recursivo: bool = False) -> list[Path]:
    """
    Expande archivos, directorios y comodines a una lista de archivos
    convertibles, sin duplicados y en orden estable.

    Se filtra por extension legible para no intentar convertir un README.
    """
    encontrados: list[Path] = []
    vistos: set[Path] = set()

    def agregar(p: Path) -> None:
        p = p.resolve()
        if p.is_file() and p.suffix.lower().lstrip(".") in FORMATOS_LECTURA:
            if p not in vistos:
                vistos.add(p)
                encontrados.append(p)

    for entrada in entradas:
        ruta = Path(entrada)
        if ruta.is_dir():
            patron = "**/*" if recursivo else "*"
            for p in sorted(ruta.glob(patron)):
                agregar(p)
        elif ruta.exists():
            agregar(ruta)
        else:
            # Comodin sin expandir por la shell (comillas, o Windows).
            base = Path(ruta.anchor or ".")
            resto = str(ruta) if not ruta.anchor else str(ruta.relative_to(base))
            for p in sorted(base.glob(resto)):
                agregar(p)

    return encontrados


def ruta_destino(origen: Path, formato: str, dir_salida: Path | None,
                 raiz: Path | None, plano: bool) -> Path:
    """
    Calcula donde va el archivo convertido.

    - Sin `dir_salida`: queda junto al original.
    - Con `dir_salida` y `plano=False`: replica la estructura de carpetas
      relativa a `raiz`. Asi 40 archivos en subcarpetas no colisionan.
    """
    nombre = origen.with_suffix(f".{formato}").name
    if dir_salida is None:
        return origen.with_name(nombre)
    if plano or raiz is None:
        return dir_salida / nombre
    try:
        relativo = origen.parent.relative_to(raiz)
    except ValueError:
        relativo = Path()
    return dir_salida / relativo / nombre


# --------------------------------------------------------------------------
# Conversion
# --------------------------------------------------------------------------

def convertir_archivo(origen: Path, destino: Path, formato: str,
                      ajustes: dict | None = None,
                      sobrescribir: bool = False,
                      verificar: bool = True,
                      paleta_aparte: bool = True,
                      seco: bool = False,
                      escala: float = 1.0,
                      forzar_escala: bool = False) -> Resultado:
    """
    Convierte un archivo. Nunca lanza excepcion: la reporta en el Resultado.

    `escala` distinta de 1.0 redimensiona ademas de convertir. Solo se admiten
    cambios chicos: escalar puntadas multiplica la separacion entre pasadas
    del relleno por el mismo factor, y eso no se puede recalcular sin conocer
    las regiones. Fuera del rango seguro el archivo se rechaza (y lo dice),
    salvo que se pase `forzar_escala`.
    """
    r = Resultado(origen=origen, destino=destino)

    if formato not in FORMATOS_ESCRITURA:
        r.estado = "error"
        r.detalle = f"no se puede escribir '{formato}'"
        return r
    if origen.suffix.lower().lstrip(".") == formato:
        r.estado = "omitido"
        r.detalle = f"ya esta en .{formato}"
        return r
    if destino.resolve() == origen.resolve():
        r.estado = "error"
        r.detalle = "el destino es el mismo archivo de origen"
        return r
    if destino.exists() and not sobrescribir:
        r.estado = "omitido"
        r.detalle = "ya existe en el destino"
        return r

    # ---- Lectura ----
    try:
        patron = pe.read(str(origen))
    except Exception as e:  # noqa: BLE001 - un archivo malo no bota el lote
        # Los parsers binarios revientan de formas poco descriptivas cuando el
        # archivo esta truncado. Se traduce a algo accionable para el usuario.
        r.estado = "error"
        r.detalle = f"ilegible o corrupto ({type(e).__name__})"
        return r
    if patron is None or not patron.stitches:
        r.estado = "error"
        r.detalle = "sin puntadas (archivo vacio o corrupto)"
        return r

    norm = patron.get_normalized_pattern()
    r.puntadas = norm.count_stitch_commands(pe.STITCH)
    r.colores = max(norm.count_color_changes() + 1, len(patron.threadlist))
    x0, y0, x1, y1 = norm.bounds()
    r.ancho_mm = (x1 - x0) / UNIDADES_POR_MM
    r.alto_mm = (y1 - y0) / UNIDADES_POR_MM

    # ---- Redimensionado opcional ----
    if escala != 1.0:
        from .redimensionar import reescalar
        patron, informe = reescalar(patron, escala, forzar=forzar_escala)
        if patron is None:
            r.estado = "error"
            r.detalle = informe.avisos[0] if informe.avisos else "escala rechazada"
            return r
        r.escala = escala
        r.puntadas = informe.puntadas_despues
        r.ancho_mm = informe.ancho_despues
        r.alto_mm = informe.alto_despues
        if not informe.seguro:
            r.detalle = "escalado forzado fuera del rango seguro"

    if seco:
        r.detalle = "simulado"
        return r

    # ---- Escritura ----
    # Muchos formatos guardan una etiqueta interna; si viene vacia se usa el
    # nombre del archivo para que el diseno sea identificable en la maquina.
    if not patron.get_metadata("name"):
        patron.metadata("name", origen.stem)

    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        cfg = dict(AJUSTES_POR_DEFECTO.get(formato, {}))
        cfg.update(ajustes or {})
        pe.write(patron, str(destino), cfg)
    except Exception as e:  # noqa: BLE001
        r.estado = "error"
        r.detalle = f"no se pudo escribir: {e}"
        return r

    # ---- Paleta acompanante para formatos sin color ----
    if paleta_aparte and formato in SIN_COLOR and patron.threadlist:
        try:
            aux = destino.with_suffix("." + EXT_PALETA[formato])
            pe.write(patron, str(aux))
            r.extras.append(aux)
        except Exception as e:  # noqa: BLE001 - accesorio, no critico
            r.detalle = f"sin archivo de paleta: {e}"

    # ---- Verificacion: releer lo escrito ----
    if verificar:
        problema = _verificar(destino, r)
        if problema:
            r.estado = "error"
            r.detalle = problema
    return r


def _verificar(destino: Path, r: Resultado) -> str:
    """
    Relee el archivo escrito y compara con el original.

    Sin esto no tienes forma de saber si el .jef salio bien: un binario
    corrupto pesa igual y no se queja hasta que la maquina lo rechaza.
    Se tolera +-2 puntadas por diferencias de codificacion de remates/cortes
    entre formatos, y 0.3 mm por el redondeo a decimas de milimetro.
    """
    try:
        vuelta = pe.read(str(destino))
    except Exception as e:  # noqa: BLE001
        return f"verificacion fallida al releer: {e}"
    if vuelta is None or not vuelta.stitches:
        return "verificacion fallida: el archivo escrito no tiene puntadas"

    n = vuelta.get_normalized_pattern().count_stitch_commands(pe.STITCH)
    # Al escalar se parten y fusionan puntadas, asi que la cuenta cambia a
    # proposito: ahi se comprueban las dimensiones, que es lo que importa.
    if r.escala == 1.0 and abs(n - r.puntadas) > 2:
        return f"verificacion fallida: {r.puntadas} puntadas -> {n}"

    x0, y0, x1, y1 = vuelta.bounds()
    ancho, alto = (x1 - x0) / UNIDADES_POR_MM, (y1 - y0) / UNIDADES_POR_MM
    if not (math.isclose(ancho, r.ancho_mm, abs_tol=0.3)
            and math.isclose(alto, r.alto_mm, abs_tol=0.3)):
        return (f"verificacion fallida: {r.ancho_mm:.1f}x{r.alto_mm:.1f} mm -> "
                f"{ancho:.1f}x{alto:.1f} mm")
    return ""


def convertir_lote(archivos: list[Path], formato: str,
                   dir_salida: Path | None = None, raiz: Path | None = None,
                   plano: bool = False,
                   progreso: Callable[[int, int, Resultado], None] | None = None,
                   cancelado: Callable[[], bool] | None = None,
                   **kwargs) -> list[Resultado]:
    """
    Convierte una lista de archivos. Detecta colisiones de nombre.

    `progreso(indice, total, resultado)` se llama tras cada archivo, y
    `cancelado()` se consulta antes de cada uno. Ambos existen para que la
    interfaz grafica pueda mostrar avance y detener el lote sin que este
    modulo sepa nada de tkinter: el motor solo avisa y pregunta.
    """
    resultados: list[Resultado] = []
    usados: dict[Path, Path] = {}
    total = len(archivos)

    for indice, origen in enumerate(archivos, start=1):
        if cancelado is not None and cancelado():
            break
        destino = ruta_destino(origen, formato, dir_salida, raiz, plano)
        if destino in usados:
            r = Resultado(origen=origen, destino=destino, estado="error",
                          detalle=f"colisiona con {usados[destino].name}")
        else:
            usados[destino] = origen
            r = convertir_archivo(origen, destino, formato, **kwargs)
        resultados.append(r)
        if progreso is not None:
            progreso(indice, total, r)
    return resultados
