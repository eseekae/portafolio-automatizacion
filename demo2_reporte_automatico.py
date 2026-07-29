"""
DEMO DE PORTAFOLIO — Automatización de reportes de ventas (CSV -> Excel)
==========================================================================

Caso de uso real: una pyme lleva sus ventas en un CSV (exportado desde su
sistema de punto de venta, o un Google Sheet). Cada fin de mes alguien
pierde horas armando un resumen a mano en Excel: total por producto,
por categoría, por vendedor, evolución en el tiempo.

Este script automatiza todo eso: toma el CSV crudo y genera un Excel
con varias hojas de resumen listas para revisar o enviar al dueño del
negocio. Se puede correr manualmente o programar para que corra solo
cada semana/mes (ej. con un cron job o un Google Apps Script si vive
en Sheets).

Cómo correrlo:
1. pip install pandas openpyxl --break-system-packages
2. python demo2_reporte_automatico.py
   (usa sample_ventas.csv como entrada de ejemplo)
3. Revisar reporte_ventas.xlsx generado
"""

import pandas as pd

ARCHIVO_ENTRADA = "sample_ventas.csv"
ARCHIVO_SALIDA = "reporte_ventas.xlsx"


def cargar_datos(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["fecha"])
    df["total"] = df["cantidad"] * df["precio_unitario"]
    return df


def resumen_por_producto(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.groupby("producto")
        .agg(unidades_vendidas=("cantidad", "sum"), ingresos_totales=("total", "sum"))
        .sort_values("ingresos_totales", ascending=False)
        .reset_index()
    )


def resumen_por_categoria(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.groupby("categoria")
        .agg(unidades_vendidas=("cantidad", "sum"), ingresos_totales=("total", "sum"))
        .sort_values("ingresos_totales", ascending=False)
        .reset_index()
    )


def resumen_por_vendedor(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.groupby("vendedor")
        .agg(ventas_realizadas=("total", "count"), ingresos_generados=("total", "sum"))
        .sort_values("ingresos_generados", ascending=False)
        .reset_index()
    )


def resumen_diario(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.groupby(df["fecha"].dt.date)
        .agg(ventas=("total", "count"), ingresos=("total", "sum"))
        .reset_index()
        .rename(columns={"fecha": "dia"})
    )


def generar_reporte(path_entrada: str, path_salida: str):
    df = cargar_datos(path_entrada)

    tabla_producto = resumen_por_producto(df)
    tabla_categoria = resumen_por_categoria(df)
    tabla_vendedor = resumen_por_vendedor(df)
    tabla_diaria = resumen_diario(df)

    total_ingresos = df["total"].sum()
    total_unidades = df["cantidad"].sum()
    resumen_general = pd.DataFrame({
        "métrica": ["Ingresos totales", "Unidades vendidas", "Ticket promedio"],
        "valor": [total_ingresos, total_unidades, round(total_ingresos / df.shape[0], 0)],
    })

    with pd.ExcelWriter(path_salida, engine="openpyxl") as writer:
        resumen_general.to_excel(writer, sheet_name="Resumen General", index=False)
        tabla_producto.to_excel(writer, sheet_name="Por Producto", index=False)
        tabla_categoria.to_excel(writer, sheet_name="Por Categoria", index=False)
        tabla_vendedor.to_excel(writer, sheet_name="Por Vendedor", index=False)
        tabla_diaria.to_excel(writer, sheet_name="Evolucion Diaria", index=False)

    print(f"Reporte generado: {path_salida}")
    print(f"Ingresos totales del período: ${total_ingresos:,.0f}")


if __name__ == "__main__":
    generar_reporte(ARCHIVO_ENTRADA, ARCHIVO_SALIDA)
