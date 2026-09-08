"""
Control de calidad del patron (capa de QA, independiente del constructor).

Esta es la parte que separa una matriz vendible de una que te genera
devoluciones. Se ejecuta sobre el patron YA CODIFICADO, o sea sobre lo que
la maquina realmente va a leer, no sobre la intencion del diseno.

Se puede correr en CI: si `reporte.ok` es False, el archivo no se publica.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pyembroidery as pe

from .parametros import ParamGlobales

UNIDADES_POR_MM = 10.0

# Limites fisicos reales de maquinas domesticas/industriales.
PUNTADA_MIN_MM = 0.6    # menos que esto: la aguja repica el mismo hoyo y se quiebra
PUNTADA_MAX_MM = 12.1   # limite de codificacion de DST/PES; sobre esto se parte sola


@dataclass
class Reporte:
    metricas: dict = field(default_factory=dict)
    errores: list[str] = field(default_factory=list)
    advertencias: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errores

    def texto(self) -> str:
        lineas = ["=" * 58, " REPORTE DE CALIDAD", "=" * 58]
        for k, v in self.metricas.items():
            lineas.append(f"  {k:.<34} {v}")
        lineas.append("-" * 58)
        if self.errores:
            lineas.append(f"  ERRORES ({len(self.errores)}) - NO PUBLICABLE:")
            lineas += [f"    x {e}" for e in self.errores]
        if self.advertencias:
            lineas.append(f"  ADVERTENCIAS ({len(self.advertencias)}):")
            lineas += [f"    ! {a}" for a in self.advertencias]
        if self.ok and not self.advertencias:
            lineas.append("  Sin observaciones. Listo para publicar.")
        lineas.append("=" * 58)
        return "\n".join(lineas)


def validar(patron: pe.EmbPattern, g: ParamGlobales,
            paradas_esperadas: int | None = None) -> Reporte:
    """
    `paradas_esperadas` es la cantidad de bloques de color que el diseno DEBE
    tener. Se usa en aplique, donde cada parada es una instruccion para el
    operador: si una se pierde, la maquina cose los pasos de corrido y arruina
    la pieza. Por eso ahi es un ERROR, no una advertencia.
    """
    r = Reporte()

    # Normalizamos: aplicamos el mismo encoder que usan los writers, para
    # analizar exactamente los comandos que iran al archivo.
    norm = patron.get_normalized_pattern()
    stitches = norm.stitches
    if not stitches:
        r.errores.append("El patron no contiene puntadas.")
        return r

    # ---------------- Dimensiones vs aro ----------------
    xmin, ymin, xmax, ymax = norm.bounds()
    ancho = (xmax - xmin) / UNIDADES_POR_MM
    alto = (ymax - ymin) / UNIDADES_POR_MM
    util_w = g.aro.ancho_mm - 2 * g.margen_seguridad_mm
    util_h = g.aro.alto_mm - 2 * g.margen_seguridad_mm

    cabe = (ancho <= util_w and alto <= util_h)
    cabe_rotado = (alto <= util_w and ancho <= util_h)
    if not cabe:
        msg = (f"No cabe en {g.aro.nombre}: {ancho:.1f}x{alto:.1f} mm "
               f"vs area util {util_w:.0f}x{util_h:.0f} mm")
        if cabe_rotado:
            r.advertencias.append(msg + " (si cabe rotado 90 grados)")
        else:
            r.errores.append(msg)

    # ---------------- Longitudes de puntada ----------------
    cortas = largas = 0
    saltos_largos = 0
    total_mm = 0.0
    prev = None
    corte_pendiente = True   # tras un TRIM el salto es legitimo, no un defecto
    for x, y, cmd in stitches:
        base = cmd & pe.COMMAND_MASK
        if base in (pe.TRIM, pe.COLOR_CHANGE, pe.STOP, pe.NEEDLE_SET):
            corte_pendiente = True
        if prev is not None and base in (pe.STITCH, pe.JUMP):
            d = math.hypot(x - prev[0], y - prev[1]) / UNIDADES_POR_MM
            if base == pe.STITCH:
                total_mm += d
                if 0 < d < PUNTADA_MIN_MM:
                    cortas += 1
                elif d > PUNTADA_MAX_MM:
                    largas += 1
            elif d > g.salto_max_sin_corte_mm and not corte_pendiente:
                saltos_largos += 1
        if base in (pe.STITCH, pe.JUMP, pe.SEQUIN_EJECT):
            prev = (x, y)
        if base == pe.STITCH:
            corte_pendiente = False

    n_puntadas = norm.count_stitch_commands(pe.STITCH)
    n_colores = norm.count_color_changes() + 1
    n_trims = sum(1 for s in stitches if (s[2] & pe.COMMAND_MASK) == pe.TRIM)
    area_cm2 = max(ancho * alto / 100.0, 0.01)

    r.metricas = {
        "Puntadas": n_puntadas,
        "Cambios de color": n_colores,
        "Cortes (TRIM)": n_trims,
        "Dimensiones (mm)": f"{ancho:.1f} x {alto:.1f}",
        "Aro objetivo": g.aro.nombre,
        "Hilo consumido (m)": f"{total_mm / 1000:.2f}",
        "Densidad (punt/cm2)": f"{n_puntadas / area_cm2:.0f}",
        "Tiempo estimado (min)": f"{n_puntadas / g.velocidad_ppm:.1f}",
    }

    # ---------------- Reglas de aceptacion ----------------
    if cortas:
        r.errores.append(
            f"{cortas} puntadas menores a {PUNTADA_MIN_MM} mm: quiebran agujas "
            "y hacen nido de hilo. Baja la densidad o simplifica la curva.")
    if largas:
        r.advertencias.append(
            f"{largas} puntadas sobre {PUNTADA_MAX_MM} mm: la maquina las "
            "partira sola, pero pueden engancharse.")
    if saltos_largos:
        r.advertencias.append(
            f"{saltos_largos} saltos largos sin corte: revisa el orden de objetos.")
    if n_colores > 8:
        r.advertencias.append(
            f"{n_colores} colores. Sobre 8 cambios el cliente domestico se frustra.")
    if paradas_esperadas is not None and n_colores != paradas_esperadas:
        r.errores.append(
            f"El diseno quedo con {n_colores} bloques de color y necesita "
            f"{paradas_esperadas}. Cada bloque es una parada de la maquina; "
            "si falta una, los pasos se cosen de corrido.")
    dens = n_puntadas / area_cm2
    if dens > 900:
        r.advertencias.append(
            f"Densidad alta ({dens:.0f} punt/cm2): riesgo de agarrotar la tela.")
    return r
