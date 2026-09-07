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

## Aplicación de escritorio (ejecutable)

Ventana para quien no usa terminal: eliges una carpeta, eliges el formato y
convierte todo. Los archivos que ya están en ese formato se omiten solos.

**Descargar:** pestaña *Actions* → *Ejecutables* → último build → artefactos
`ConversorBordado-windows` (`.exe`), `-macos` (`.app`) o `-linux`. Al publicar
una etiqueta `v*` quedan además adjuntos a la Release.

**Generarlo tú mismo** (en el sistema operativo de destino):

```bash
pip install -e ".[build]"
pyinstaller empaquetar/conversor.spec --noconfirm
# el ejecutable queda en dist/
```

> **PyInstaller no compila de forma cruzada.** Empaqueta el intérprete nativo
> de la máquina donde corre, así que un `.exe` de Windows tiene que generarse
> en Windows. Por eso el workflow `.github/workflows/ejecutables.yml` construye
> los tres en runners separados.

Sin empaquetar, la misma ventana se abre con `matriz-gui` o
`python -m bordado.gui`.

## Instalación

```bash
pip install -e .          # deja disponible `matriz` y `matriz-gui`
pytest -q
```

## Conversor por lotes

Convierte entre 47 formatos de entrada y 19 de salida. **No redimensiona ni
re-digitaliza**: reescribe las mismas puntadas en otro contenedor.

```bash
# 40 archivos .pes a .jef con un comando, replicando la estructura de carpetas
matriz convertir catalogo/ -r --a jef -o convertidos/

# comodines, o archivos sueltos
matriz convertir *.pes --a jef

# ver qué haría sin escribir nada
matriz convertir catalogo/ --a dst -o salida/ --seco

matriz formatos          # lista de formatos soportados
```

| Opción | Qué hace |
|---|---|
| `-r` | incluye subcarpetas |
| `-o DIR` | carpeta de destino (por defecto, junto al original) |
| `--plano` | vuelca todo en una carpeta; avisa si hay nombres que colisionan |
| `--sobrescribir` | reemplaza archivos existentes (por defecto los omite) |
| `--seco` | simulación |
| `--sin-verificar` | omite la relectura de control |
| `--version-pes {1,6}` | v1 = máxima compatibilidad con Brother antiguas |

**Lo que lo diferencia de un conversor cualquiera:**

- **Verifica lo que escribe.** Relee cada archivo generado y compara puntadas
  y dimensiones contra el original. Un binario corrupto pesa igual que uno
  bueno y no se queja hasta que la máquina lo rechaza.
- **Aísla los errores.** Un archivo corrupto entre 40 no bota el lote.
- **No pierde los colores.** `.dst`, `.exp` y `.u01` no guardan color en el
  binario: el conversor emite el `.edr` / `.inf` acompañante.
- **No pisa nada en silencio.** Detecta colisiones de nombre y nunca escribe
  sobre el archivo de origen.

> **Límite real de convertir:** un archivo de bordado guarda *puntadas*, no
> objetos. Es como pasar un JPG a PNG — cambias el envase, no recuperas el
> vector. Por eso convertir nunca permite reescalar más de ±10-20% sin
> arruinar la densidad. Reescalar de verdad exige re-digitalizar.

## Generación de diseños

```bash
python disenos/demo_emblema.py
```

## Arquitectura

Capas con dependencia en un solo sentido. La capa de dominio no conoce
formatos de archivo; solo `patron.py` toca pyembroidery.

```
gui/app.py          ventana tkinter: solo widgets y presentación
gui/controlador.py  hilo trabajador + cola de eventos (probable sin pantalla)
cli.py              subcomandos: convertir · [futuro] digitalizar, redimensionar
convertir.py        motor de conversión por lotes (puro, sin I/O de consola)

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

## Hoja de ruta

1. **Conversor por lotes** — hecho (CLI + ventana + ejecutable)
2. **Auto-digitizer**: imagen (PNG/JPG/SVG) → matriz
   - segmentación → vectorización → limpieza
   - decisión de puntada por región → ordenamiento de objetos y colores
   - mapeo a hilos reales (Madeira / Isacord)
3. **Redimensionador** con recálculo de densidad
4. Integración de todo en un solo programa distribuible

## Estado actual

Implementado y testeado (40 tests):

- Conversor por lotes con verificación por relectura
- Aplicación de escritorio y empaquetado a ejecutable
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
