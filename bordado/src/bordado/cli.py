"""
Interfaz de linea de comandos.

Estructura de subcomandos pensada para crecer: hoy solo `convertir`, manana
`digitalizar`, `redimensionar`, `validar`. El CLI solo parsea y presenta;
toda la logica vive en los modulos del paquete.

    matriz convertir ENTRADA... --a jef [-o SALIDA] [opciones]

Ejemplos:
    matriz convertir disenos/ --a jef -o convertidos/
    matriz convertir *.pes --a jef
    matriz convertir catalogo/ -r --a dst -o salida/ --sobrescribir
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .convertir import (
    FORMATOS_ESCRITURA, FORMATOS_LECTURA, FORMATOS_MAQUINA,
    Resultado, convertir_lote, recolectar,
)

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
    print(f"{'':3}{'ARCHIVO':<30}{'PUNT.':>8}{'COL':>5}{'TAMANO mm':>14}  DETALLE")
    print("-" * ANCHO)
    for r in resultados:
        tam = f"{r.ancho_mm:.1f} x {r.alto_mm:.1f}" if r.puntadas else ""
        nombre = r.origen.name
        if len(nombre) > 29:
            nombre = nombre[:26] + "..."
        punt = f"{r.puntadas:,}" if r.puntadas else ""
        col = str(r.colores) if r.colores else ""
        print(f"{simbolo[r.estado]}{nombre:<30}{punt:>8}{col:>5}{tam:>14}  {r.detalle}")


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

    print(f"Convirtiendo {len(archivos)} archivo(s) a .{formato}"
          f"{' [SIMULACION]' if args.seco else ''}")
    print("=" * ANCHO)

    resultados = convertir_lote(
        archivos, formato,
        dir_salida=dir_salida, raiz=raiz, plano=args.plano,
        ajustes=ajustes,
        sobrescribir=args.sobrescribir,
        verificar=not args.sin_verificar,
        paleta_aparte=not args.sin_paleta,
        seco=args.seco,
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
    if dir_salida and not args.seco:
        print(f"Salida: {dir_salida}")
    return 1 if err else 0


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
    c.set_defaults(func=_cmd_convertir)

    f = sub.add_parser("formatos", help="lista los formatos soportados")
    f.set_defaults(func=_cmd_formatos)
    return p


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
