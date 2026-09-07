"""
Capa de exportacion: patron -> archivos vendibles.

Genera el "paquete comercial" completo, que es lo que realmente se vende:
  - los binarios de maquina (.pes, .jef, .dst, .exp, .vp3)
  - una vista previa PNG (la foto del listing)
  - la ficha tecnica JSON + TXT (medidas, colores, puntadas, orden de hilos)
  - todo comprimido en un ZIP listo para subir a la tienda
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pyembroidery as pe

from .parametros import ParamGlobales
from .validador import Reporte, validar

# Ajustes por formato. PES v1 es el mas compatible con maquinas Brother
# antiguas; v6 guarda mas metadata pero no todas las maquinas lo leen.
AJUSTES = {
    "pes": {"pes version": 1},
    "jef": {},
    "dst": {"extended header": True},
    "exp": {},
    "vp3": {},
}


def exportar(patron: pe.EmbPattern, nombre: str, destino: Path,
             g: ParamGlobales, formatos: list[str] | None = None,
             comprimir: bool = True) -> tuple[Reporte, list[Path]]:
    """
    Exporta el patron a todos los formatos pedidos y devuelve (reporte, archivos).

    NOTA: no bloquea la exportacion si el QA falla; devuelve el reporte para
    que quien llame decida. En un pipeline de publicacion, la regla es:
    `if not reporte.ok: no publicar`.
    """
    formatos = formatos or ["pes", "jef", "dst"]
    destino.mkdir(parents=True, exist_ok=True)
    generados: list[Path] = []

    reporte = validar(patron, g)

    for fmt in formatos:
        ruta = destino / f"{nombre}.{fmt}"
        # write() enruta al writer correcto por extension y aplica el encoder.
        pe.write(patron, str(ruta), AJUSTES.get(fmt, {}))
        generados.append(ruta)

    # --- Vista previa PNG (requiere Pillow) ---
    # OJO con el eje Y: los formatos de bordado usan Y hacia ARRIBA (como en
    # matematicas), mientras que una imagen usa Y hacia ABAJO. Si no se
    # invierte, la preview sale espejada verticalmente -> el cliente ve algo
    # distinto a lo que borda la maquina. Es un error clasico y caro.
    try:
        png = destino / f"{nombre}_preview.png"
        espejo = patron.copy()
        m = pe.EmbMatrix()
        m.post_scale(1, -1)
        espejo.transform(m)
        pe.write_png(espejo, str(png))
        generados.append(png)
    except Exception as e:  # noqa: BLE001 - la preview no debe romper el pipeline
        reporte.advertencias.append(f"No se pudo generar el PNG de preview: {e}")

    # --- Ficha tecnica ---
    ficha = {
        "diseno": nombre,
        "metricas": reporte.metricas,
        "aro_objetivo": {
            "nombre": g.aro.nombre,
            "ancho_mm": g.aro.ancho_mm,
            "alto_mm": g.aro.alto_mm,
        },
        "secuencia_de_hilos": [
            {
                "orden": i + 1,
                "hex": f"#{h.get_red():02X}{h.get_green():02X}{h.get_blue():02X}",
                "descripcion": h.description or "",
                "catalogo": h.catalog_number or "",
            }
            for i, h in enumerate(patron.threadlist)
        ],
        "formatos_incluidos": formatos,
        "qa_aprobado": reporte.ok,
        "errores": reporte.errores,
        "advertencias": reporte.advertencias,
    }
    fj = destino / f"{nombre}_ficha.json"
    fj.write_text(json.dumps(ficha, indent=2, ensure_ascii=False), encoding="utf-8")
    generados.append(fj)

    ft = destino / f"{nombre}_ficha.txt"
    ft.write_text(reporte.texto() + "\n\nSECUENCIA DE HILOS\n" + "\n".join(
        f"  {h['orden']}. {h['hex']}  {h['descripcion']}"
        for h in ficha["secuencia_de_hilos"]
    ) + "\n", encoding="utf-8")
    generados.append(ft)

    # --- Paquete comercial ---
    if comprimir:
        zpath = destino / f"{nombre}.zip"
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            for f in generados:
                z.write(f, arcname=f.name)
        generados.append(zpath)

    return reporte, generados
