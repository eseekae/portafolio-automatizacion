"""
Interfaz de linea de comandos.

Estructura de subcomandos pensada para crecer: hoy solo `convertir`, manana
`digitalizar`, `redimensionar`, `validar`. El CLI solo parsea y presenta;
toda la logica vive en los modulos del paquete.

    matriz convertir ENTRADA... --a jef [-o SALIDA] [opciones]
    matriz digitalizar IMAGEN --ancho 90 [--colores 5] [opciones]
    matriz analizar ARCHIVO

Ejemplos:
    matriz convertir disenos/ --a jef -o convertidos/
    matriz convertir *.pes --a jef
    matriz digitalizar logo.png --ancho 80 --colores 4 -o salida/
    matriz analizar dragon.pes          # donde se va el tiempo y como bajarlo
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .convertir import (
    FORMATOS_ESCRITURA, FORMATOS_LECTURA, FORMATOS_MAQUINA,
    Resultado, convertir_lote, recolectar,
)
from .parametros import AROS, ParamGlobales

ANCHO = 78


def _raiz_comun(archivos: list[Path], entradas: list[str]) -> Path | None:
    """
    Raiz para replicar la estructura de carpetas en la salida.
    Si el usuario paso un directorio, esa es la raiz. Si paso archivos
    sueltos, se usa el ancestro comun.
    """
    dirs = [Path(e).resolve() for e in entradas if Path(e).is_dir()]
    if len(dirs) == 1:
        return dirs[0]
    if not archivos:
        return None
    import os
    return Path(os.path.commonpath([str(a.parent) for a in archivos]))


def _tabla(resultados: list[Resultado]) -> None:
    simbolo = {"ok": "OK ", "omitido": "-- ", "error": "XX "}
    print(f"{'':3}{'ARCHIVO':<28}{'PUNT.':>8}{'COL':>5}{'TAMANO mm':>21}  DETALLE")
    print("-" * ANCHO)
    for r in resultados:
        tam = f"{r.ancho_mm:.1f} x {r.alto_mm:.1f}" if r.puntadas else ""
        if r.escala != 1.0 and r.puntadas:
            tam += f" ({r.escala:.0%})"
        nombre = r.origen.name
        if len(nombre) > 27:
            nombre = nombre[:24] + "..."
        punt = f"{r.puntadas:,}" if r.puntadas else ""
        col = str(r.colores) if r.colores else ""
        print(f"{simbolo[r.estado]}{nombre:<28}{punt:>8}{col:>5}{tam:>21}  {r.detalle}")


def _cmd_convertir(args: argparse.Namespace) -> int:
    formato = args.a.lower().lstrip(".")
    if formato not in FORMATOS_ESCRITURA:
        print(f"error: no se puede escribir '.{formato}'.", file=sys.stderr)
        print(f"Formatos de salida: {', '.join(sorted(FORMATOS_ESCRITURA))}",
              file=sys.stderr)
        return 2

    archivos = recolectar(args.entradas, recursivo=args.recursivo)
    if not archivos:
        print("error: no se encontro ningun archivo de bordado legible.",
              file=sys.stderr)
        print("Sugerencia: usa -r para buscar en subcarpetas.", file=sys.stderr)
        return 2

    dir_salida = Path(args.salida).resolve() if args.salida else None
    raiz = _raiz_comun(archivos, args.entradas) if dir_salida else None

    ajustes: dict = {}
    if formato == "pes" and args.version_pes:
        ajustes["version"] = args.version_pes

    escala = args.escala / 100.0 if args.escala else 1.0

    print(f"Convirtiendo {len(archivos)} archivo(s) a .{formato}"
          + (f" al {args.escala:.0f}%" if args.escala else "")
          + (" [SIMULACION]" if args.seco else ""))
    print("=" * ANCHO)

    resultados = convertir_lote(
        archivos, formato,
        dir_salida=dir_salida, raiz=raiz, plano=args.plano,
        ajustes=ajustes,
        sobrescribir=args.sobrescribir,
        verificar=not args.sin_verificar,
        paleta_aparte=not args.sin_paleta,
        seco=args.seco,
        escala=escala,
        forzar_escala=args.forzar_escala,
    )

    _tabla(resultados)

    ok = sum(1 for r in resultados if r.estado == "ok")
    om = sum(1 for r in resultados if r.estado == "omitido")
    err = sum(1 for r in resultados if r.estado == "error")
    extras = sum(len(r.extras) for r in resultados)

    print("-" * ANCHO)
    verbo = "se convertirian" if args.seco else "convertidos"
    resumen = f"{ok} {verbo}, {om} omitidos, {err} con error"
    if extras:
        resumen += f", {extras} archivos de paleta"
    print(resumen)
    if om and not args.sobrescribir:
        print("Sugerencia: usa --sobrescribir para reemplazar los existentes.")
    if dir_salida and not args.seco:
        print(f"Salida: {dir_salida}")
    return 1 if err else 0


def _cmd_digitalizar(args: argparse.Namespace) -> int:
    # Los modulos de imagen traen numpy y Pillow: se importan aqui para que
    # `matriz convertir` siga arrancando al instante sin cargarlos.
    from .exportar import exportar
    from .imagen.digitalizar import digitalizar

    imagen = Path(args.imagen)
    if not imagen.is_file():
        print(f"error: no existe la imagen {imagen}", file=sys.stderr)
        return 2

    formatos = [f.lower().lstrip(".") for f in args.a]
    desconocidos = [f for f in formatos if f not in FORMATOS_ESCRITURA]
    if desconocidos:
        print(f"error: no se puede escribir {', '.join(desconocidos)}", file=sys.stderr)
        return 2

    g = ParamGlobales(aro=AROS[args.aro])
    destino = Path(args.salida) if args.salida else imagen.parent
    nombre = args.nombre or imagen.stem

    print(f"Digitalizando {imagen.name} -> {args.ancho} mm de ancho, "
          f"{args.colores} colores, calidad {args.calidad}")
    print("=" * ANCHO)

    from .aplique import ParamAplique

    patron, d, seg = digitalizar(
        imagen, ancho_mm=args.ancho, n_colores=args.colores,
        formato_hilos=formatos[0], g=g, px_por_mm=args.detalle,
        densidad_mm=args.densidad, area_min_mm2=args.area_min,
        suavizado=args.suavizado, quitar_fondo=not args.con_fondo,
        semilla=args.semilla, aplique=args.aplique, perfil=args.calidad,
        p_aplique=ParamAplique(ancho_cobertura_mm=args.ancho_cobertura))

    print(d.resumen())
    if d.notas:
        print()
        print(d.notas)
    print("-" * ANCHO)

    # Con aplique, cada bloque de color es una parada de la maquina: si un
    # formato pierde una, el archivo no sirve. Se comprueba releyendo.
    reporte, archivos = exportar(
        patron, nombre, destino, g, formatos=formatos,
        paradas_esperadas=d.paradas if args.aplique else None,
        notas=d.notas)
    print(reporte.texto())

    if args.ver_segmentacion:
        ruta = _guardar_segmentacion(seg, destino / f"{nombre}_segmentacion.png")
        archivos.append(ruta)

    print("\nArchivos generados:")
    for a in archivos:
        print(f"  {a.name:<36} {a.stat().st_size:>9,} bytes")
    return 0 if reporte.ok else 1


def _guardar_segmentacion(seg, ruta: Path) -> Path:
    """Imagen de control: muestra que vio el segmentador antes de coser."""
    import numpy as np
    from PIL import Image
    vis = seg.colores[seg.etiquetas]
    vis[seg.fondo] = (255, 255, 255)
    Image.fromarray(vis.astype(np.uint8)).save(ruta)
    return ruta


def _cmd_analizar(args: argparse.Namespace) -> int:
    import pyembroidery as pe

    from .analizar import analizar

    rutas = recolectar(args.entradas, recursivo=args.recursivo)
    if not rutas:
        print("error: no se encontro ningun archivo de bordado legible.",
              file=sys.stderr)
        return 2

    for i, ruta in enumerate(rutas):
        try:
            patron = pe.read(str(ruta))
        except Exception:  # noqa: BLE001
            print(f"{ruta.name}: ilegible o corrupto", file=sys.stderr)
            continue
        if patron is None or not patron.stitches:
            print(f"{ruta.name}: sin puntadas", file=sys.stderr)
            continue
        if i:
            print()
        print(ruta.name)
        print(analizar(patron, velocidad_ppm=args.velocidad,
                       segundos_por_corte=args.segundos_corte,
                       segundos_por_color=args.segundos_color).texto())
    return 0


def _cmd_formatos(_: argparse.Namespace) -> int:
    print("Formatos de SALIDA (a los que puedes convertir):")
    print("  de maquina : " + ", ".join(sorted(FORMATOS_MAQUINA & FORMATOS_ESCRITURA)))
    print("  utilitarios: " + ", ".join(sorted(FORMATOS_ESCRITURA - FORMATOS_MAQUINA)))
    print(f"\nFormatos de ENTRADA ({len(FORMATOS_LECTURA)} legibles):")
    lista = sorted(FORMATOS_LECTURA)
    for i in range(0, len(lista), 12):
        print("  " + ", ".join(lista[i:i + 12]))
    return 0


def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="matriz",
        description="Herramientas de matrices de bordado.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    sub = p.add_subparsers(dest="comando", required=True)

    c = sub.add_parser("convertir", help="convierte archivos entre formatos")
    c.add_argument("entradas", nargs="+",
                   help="archivos, carpetas o comodines")
    c.add_argument("--a", "--to", required=True, metavar="FORMATO",
                   help="formato de salida (jef, pes, dst, exp, vp3, ...)")
    c.add_argument("-o", "--salida", metavar="DIR",
                   help="carpeta de destino (por defecto: junto al original)")
    c.add_argument("-r", "--recursivo", action="store_true",
                   help="incluye subcarpetas")
    c.add_argument("--plano", action="store_true",
                   help="vuelca todo en una sola carpeta sin replicar el arbol")
    c.add_argument("--sobrescribir", action="store_true",
                   help="reemplaza archivos existentes")
    c.add_argument("--sin-verificar", action="store_true",
                   help="no relee lo escrito (mas rapido, menos seguro)")
    c.add_argument("--sin-paleta", action="store_true",
                   help="no genera el archivo de colores en dst/exp/u01")
    c.add_argument("--seco", "--dry-run", action="store_true",
                   help="muestra que haria sin escribir nada")
    c.add_argument("--version-pes", type=int, choices=(1, 6), default=None,
                   help="version del formato PES (1 = maxima compatibilidad)")
    c.add_argument("--escala", type=float, default=None, metavar="PORCENTAJE",
                   help="redimensiona ademas de convertir (ej: 110 para +10%%). "
                        "Solo se admiten cambios de hasta +-12%%: escalar "
                        "puntadas cambia la densidad del relleno y eso no se "
                        "puede recalcular sin las regiones originales")
    c.add_argument("--forzar-escala", action="store_true",
                   help="acepta una escala fuera del rango seguro, sabiendo "
                        "que el relleno quedara mal")
    c.set_defaults(func=_cmd_convertir)

    dg = sub.add_parser("digitalizar",
                        help="convierte una imagen en una matriz de bordado")
    dg.add_argument("imagen", help="PNG, JPG, WEBP, BMP...")
    dg.add_argument("--ancho", type=float, required=True, metavar="MM",
                    help="ancho final del bordado en milimetros")
    dg.add_argument("--colores", type=int, default=5,
                    help="cantidad de hilos (por defecto 5)")
    dg.add_argument("--a", "--to", nargs="+", default=["jef"], metavar="FORMATO",
                    help="formatos de salida (por defecto jef)")
    dg.add_argument("-o", "--salida", metavar="DIR", help="carpeta de destino")
    dg.add_argument("--nombre", help="nombre base de los archivos")
    dg.add_argument("--aro", default="brother_5x7", choices=sorted(AROS),
                    help="aro objetivo para el control de calidad")
    dg.add_argument("--densidad", type=float, default=0.40, metavar="MM",
                    help="separacion entre pasadas del relleno (0.35-0.45)")
    dg.add_argument("--detalle", type=float, default=8.0, metavar="PX/MM",
                    help="resolucion de trabajo (por defecto 8 px/mm)")
    dg.add_argument("--area-min", type=float, default=1.0, metavar="MM2",
                    help="descarta regiones menores a esta area")
    dg.add_argument("--suavizado", type=int, default=3,
                    help="filtro de mediana previo, en pixeles (impar; 0 lo apaga)")
    dg.add_argument("--con-fondo", action="store_true",
                    help="borda tambien el fondo en vez de recortarlo")
    dg.add_argument("--semilla", type=int, default=0,
                    help="semilla del agrupamiento (cambiala si no te gusta el corte)")
    dg.add_argument("--calidad", default="equilibrada",
                    choices=("alta", "equilibrada", "rapida"),
                    help="compromiso entre acabado y tiempo de maquina "
                         "(rapida ahorra ~20%% del tiempo)")
    dg.add_argument("--aplique", action="store_true",
                    help="usa aplique (coser sobre un retazo de tela) en las "
                         "areas grandes donde ahorre puntadas")
    dg.add_argument("--ancho-cobertura", type=float, default=2.5, metavar="MM",
                    help="ancho del satin que tapa el borde del retazo")
    dg.add_argument("--ver-segmentacion", action="store_true",
                    help="guarda una imagen con los colores detectados")
    dg.set_defaults(func=_cmd_digitalizar)

    an = sub.add_parser("analizar",
                        help="mide una matriz: puntadas, hilo, tiempo real y "
                             "que se puede recortar")
    an.add_argument("entradas", nargs="+", help="archivos o carpetas")
    an.add_argument("-r", "--recursivo", action="store_true",
                    help="incluye subcarpetas")
    an.add_argument("--velocidad", type=int, default=700, metavar="PPM",
                    help="velocidad de tu maquina en puntadas por minuto "
                         "(domesticas: 400-850; por defecto 700)")
    an.add_argument("--segundos-corte", type=float, default=1.5, metavar="S",
                    help="cuanto tarda tu maquina en cortar el hilo")
    an.add_argument("--segundos-color", type=float, default=25.0, metavar="S",
                    help="cuanto tardas en reenhebrar un color")
    an.set_defaults(func=_cmd_analizar)

    f = sub.add_parser("formatos", help="lista los formatos soportados")
    f.set_defaults(func=_cmd_formatos)
    return p


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
