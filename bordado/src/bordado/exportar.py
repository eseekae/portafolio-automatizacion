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
             comprimir: bool = True, paradas_esperadas: int | None = None,
             notas: str = "") -> tuple[Reporte, list[Path]]:
    """
    Exporta el patron a todos los formatos pedidos y devuelve (reporte, archivos).

    NOTA: no bloquea la exportacion si el QA falla; devuelve el reporte para
    que quien llame decida. En un pipeline de publicacion, la regla es:
    `if not reporte.ok: no publicar`.
    """
    formatos = formatos or ["pes", "jef", "dst"]
    destino.mkdir(parents=True, exist_ok=True)
    generados: list[Path] = []

    reporte = validar(patron, g, paradas_esperadas)

    for fmt in formatos:
        ruta = destino / f"{nombre}.{fmt}"
        # write() enruta al writer correcto por extension y aplica el encoder.
        pe.write(patron, str(ruta), AJUSTES.get(fmt, {}))
        generados.append(ruta)
        # Las paradas se verifican POR FORMATO releyendo lo escrito: no todos
        # los escritores las conservan igual. El de .pes, por ejemplo, fusiona
        # dos bloques contiguos del mismo color y ahi una parada desaparece.
        if paradas_esperadas is not None:
            try:
                leidas = pe.read(str(ruta)).count_color_changes() + 1
            except Exception as e:  # noqa: BLE001
                reporte.errores.append(f".{fmt}: no se pudo releer ({e})")
                continue
            if leidas != paradas_esperadas:
                reporte.errores.append(
                    f".{fmt} perdio paradas: quedaron {leidas} de "
                    f"{paradas_esperadas}. Ese formato no sirve para este "
                    "diseno de aplique.")

    # --- Vista previa PNG (requiere Pillow) ---
    # El patron ya viene con el eje Y en la convencion de pyembroidery (hacia
    # abajo, ver patron._u), que es la misma del PNG. No se voltea nada.
    #
    # Antes SI se volteaba aqui, y ese volteo estaba tapando un error: los
    # archivos se escribian espejados verticalmente y la preview los enderezaba
    # solo para la pantalla. Se veia bien y se bordaba al reves. Si algun dia
    # esta preview vuelve a salir invertida, el problema esta en patron._u, no
    # aqui: se arregla en la frontera, no con un segundo volteo.
    try:
        png = destino / f"{nombre}_preview.png"
        pe.write_png(patron, str(png))
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
    ft.write_text((notas + "\n\n" if notas else "")
                  + reporte.texto() + "\n\nSECUENCIA DE HILOS\n" + "\n".join(
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
