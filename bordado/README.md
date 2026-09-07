# bordado — pipeline de matrices de bordado (.PES / .JEF / .DST)

Generación programática de matrices de bordado listas para máquina, con
**control de calidad automatizado** y empaquetado comercial.

## Por qué código y no solo un digitalizador manual

Un digitalizador (Ink/Stitch, Wilcom) es insuperable para **arte**: dibujar,
decidir dirección de puntada, corregir a ojo. Este repo cubre lo otro:

- **Variantes en masa**: un diseño × 6 tamaños × 5 formatos = 30 archivos, en segundos.
- **QA reproducible**: reglas físicas (puntada mínima, densidad, aro) verificadas
  en cada build. Si falla, no se publica.
- **Diseño paramétrico**: monogramas, marcos, patrones geométricos, mandalas,
  parches con texto — donde la geometría es una fórmula, no un dibujo.
- **Ficha técnica y empaquetado**: PNG de preview, secuencia de hilos, ZIP.

## Instalación

```bash
pip install -r requirements.txt
python disenos/demo_emblema.py
pytest -q
```

## Arquitectura

Capas con dependencia en un solo sentido. La capa de dominio no conoce
formatos de archivo; solo `patron.py` toca pyembroidery.

```
disenos/*.py        definición del diseño (geometría + colores + orden)
     |
puntadas.py         STRATEGY: geometría -> corridas de puntadas
     |                 · puntada_recta / puntada_triple
     |                 · columna_satin  (bordes, letras)
     |                 · relleno_tatami (áreas)
     |
geometria.py        matemática pura en mm, sin dependencias externas
parametros.py       value objects inmutables (densidad, aro, compensación)
     |
patron.py           BUILDER: corridas -> EmbPattern
     |                 orden de colores · JUMP vs TRIM · remates
     |                 filtro de puntadas cortas (restricción física)
     |
validador.py        QA sobre el patrón ya codificado -> Reporte.ok
exportar.py         PES/JEF/DST/EXP/VP3 + preview PNG + ficha + ZIP
```

**Convención de unidades:** todo el dominio trabaja en **milímetros** (float).
La conversión a unidades de máquina (1/10 mm) ocurre solo en `patron.py`.

**Eje Y:** los formatos de bordado usan Y hacia arriba; las imágenes, hacia
abajo. `exportar.py` invierte el eje solo para el PNG de preview.

## Parámetros clave (valores de industria, poliéster 40wt / aguja 75-11)

| Parámetro | Rango | Efecto si te equivocas |
|---|---|---|
| Densidad de relleno | 0.35–0.45 mm | Muy densa: agarrota y rompe la tela |
| Largo de puntada tatami | 3.0–4.0 mm | Muy larga: se engancha |
| Ancho máximo de satin | ~8 mm | Más ancho: el hilo queda flojo |
| Pull compensation | 0.10–0.20 mm | Sin ella: se ve la tela en los bordes |
| Puntada mínima | 0.6 mm | Menor: quiebra agujas, nido de hilo |
| Desfase de fila | ~1.4 mm | Sin él: "efecto cremallera" visible |

Estimación de puntadas de un relleno de área `A`, densidad `d`, largo `l`:
`N ≈ A / (d · l)`. Tiempo de bordado: `t = N / v`, con `v ≈ 700 ppm.`

## Estado actual

Implementado y testeado (9 tests):
- Relleno tatami con underlay cruzado, serpentina y corte en concavidades
- Columna satin con underlay de eje y compensación de tracción
- Puntada corrida y triple
- Filtro de puntadas cortas, remates, TRIM automático
- Validador: aro, puntadas cortas/largas, saltos, densidad, conteo de colores
- Export a PES/JEF/DST/EXP/VP3 + PNG + ficha JSON/TXT + ZIP

Limitaciones conocidas (documentadas en el código):
- `desplazar_contorno()` es un offset por normales; falla en concavidades
  agudas. Reemplazar por Shapely (`buffer`) para producción.
- Sin importador de SVG: los diseños se definen en Python. Para arte dibujado,
  el camino es Inkscape + Ink/Stitch (ver abajo).
- `.exp` no almacena colores: necesita un `.inf`/`.edr` acompañante.

## Ecosistema open source de bordado

| Herramienta | Qué es | Licencia | Uso |
|---|---|---|---|
| **Ink/Stitch** | Extensión de Inkscape. Digitalización visual completa | GPL-3.0 | Arte dibujado, lettering |
| **pyembroidery** | Lee 40+ / escribe 10 formatos. Motor de Ink/Stitch | MIT | Este repo |
| **libembroidery / Embroidermodder** | Librería C + GUI | Zlib | Conversión, lectura |
| **PEmbroider** | Librería de Processing (Java) | LGPL | Bordado generativo |
| **TurtleStitch** | Programación visual tipo Snap! | AGPL | Educación, espirógrafos |

> La licencia del software **no** alcanza a los diseños que produce: las
> matrices generadas son tuyas y se pueden vender. Lo que sí importa
> legalmente es el origen del **arte** (personajes, logos, tipografías).
