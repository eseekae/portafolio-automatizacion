# Conversor de matrices de bordado

[![Tests](https://github.com/eseekae/portafolio-automatizacion/actions/workflows/tests.yml/badge.svg)](https://github.com/eseekae/portafolio-automatizacion/actions/workflows/tests.yml)
[![Ejecutables](https://github.com/eseekae/portafolio-automatizacion/actions/workflows/ejecutables.yml/badge.svg)](https://github.com/eseekae/portafolio-automatizacion/actions/workflows/ejecutables.yml)

Convierte matrices de bordado entre formatos **por lotes**: eliges una carpeta
y pasa todos tus diseños a `.JEF`, `.PES`, `.DST` o el formato que necesite tu
máquina. Lee **47 formatos** y escribe **19**.

Programa gratis y de código abierto. No necesitas instalar Python ni saber
programar.

![La ventana del programa](ejemplos/ventana.png)

---

# Descargar e instalar

**[⬇ Ir a la página de descargas](https://github.com/eseekae/portafolio-automatizacion/releases/latest)**

Es un solo archivo. No hay instalador, no toca el registro de Windows y no
deja nada en tu sistema: si lo quieres borrar, mandas el archivo a la papelera.

## Windows

1. Descarga **`ConversorBordado.exe`**.
2. Haz doble clic.
3. Aparecerá una pantalla azul que dice **"Windows protegió tu PC"**.
   Es normal: pasa con todo programa que no paga una firma digital (cuestan
   unos US$200 al año). Haz clic en **Más información** → **Ejecutar de todas
   formas**.

Listo. Puedes dejar el `.exe` en el Escritorio o donde te acomode.

## macOS

1. Descarga **`ConversorBordado-macos.zip`** y descomprímelo (doble clic).
2. **Haz clic derecho** sobre `ConversorBordado.app` → **Abrir** → **Abrir**.

> Importante: la primera vez tiene que ser **clic derecho → Abrir**. Con doble
> clic normal, macOS lo bloquea sin dar opción. Si igual aparece "no se pudo
> verificar", ve a **Ajustes del Sistema → Privacidad y seguridad**, baja hasta
> el aviso y pulsa **Abrir igualmente**.

## Linux

```bash
chmod +x ConversorBordado
./ConversorBordado
```

---

# Cómo se usa

1. **Elige la carpeta.** Botón *Examinar...*, seleccionas dónde tienes tus
   diseños. Marca *Incluir subcarpetas* si están repartidos en varias.
2. **Elige el formato.** `jef` para Janome, `pes` para Brother o Babylock,
   `dst` para máquinas industriales.
3. **Pulsa Convertir.**

Los archivos nuevos se guardan en una carpeta aparte (`convertidos_jef`), así
que **tus originales no se tocan nunca**. Al terminar, el botón *Abrir carpeta
de salida* te lleva directo a ellos.

Vas a ver una línea por archivo con su cantidad de puntadas y su tamaño en
milímetros:

| Marca | Significa |
|:---:|---|
| `OK` | Convertido y verificado |
| `--` | Omitido (ya estaba en ese formato, o ya existía) |
| `XX` | El archivo está dañado y no se pudo leer |

## Preguntas frecuentes

**¿Modifica o borra mis archivos originales?**
No. Solo lee. Todo lo nuevo va a una carpeta aparte.

**¿Puedo agrandar o achicar un diseño con esto?**
No, y ningún conversor debería prometerlo. Un archivo de bordado guarda
*puntadas*, no formas: es como pasar un JPG a PNG, cambias el envase pero no
recuperas el dibujo original. Sobre ±10-20% la densidad se arruina y el
bordado sale con huecos o agarrota la tela.

**Mi antivirus lo marca como sospechoso.**
Pasa con casi todos los programas empaquetados de esta forma; es un falso
positivo conocido. El código completo está en este repositorio y los
ejecutables se generan automáticamente desde él, a la vista de todos.

**¿Qué formato usa mi máquina?**

| Formato | Máquinas |
|---|---|
| `.jef` | Janome |
| `.pes` | Brother, Babylock, Bernina |
| `.vp3` | Husqvarna Viking, Pfaff |
| `.dst` | Industriales (Tajima y la mayoría) |
| `.exp` | Melco, Bernina |
| `.xxx` | Singer |

**¿Se pierden los colores?**
No, salvo en `.dst` y `.exp`, que por diseño no guardan color adentro. Para
esos el programa genera un archivo de paleta al lado (`.edr` / `.inf`) para
que no pierdas la secuencia de hilos.

**¿Funciona sin internet?** Sí, todo se procesa en tu computador.

---
---

# Para desarrolladores

Lo de arriba es el programa terminado. De aquí en adelante, el proyecto.

## Instalación desde el código

```bash
pip install -e .          # deja disponibles `matriz` y `matriz-gui`
pytest -q
```

## Conversor por línea de comandos

```bash
# 40 archivos .pes a .jef con un comando, replicando la estructura de carpetas
matriz convertir catalogo/ -r --a jef -o convertidos/

matriz convertir *.pes --a jef          # comodines o archivos sueltos
matriz convertir catalogo/ --a dst --seco   # simulación, no escribe nada
matriz formatos                          # formatos soportados
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

## Generar el ejecutable

```bash
pip install -e ".[build]"
pyinstaller empaquetar/conversor.spec --noconfirm   # queda en dist/
```

> **PyInstaller no compila de forma cruzada.** Empaqueta el intérprete nativo
> de la máquina donde corre, así que un `.exe` de Windows tiene que generarse
> en Windows. Por eso `.github/workflows/ejecutables.yml` construye los tres
> en runners separados.

**Publicar una versión** (deja los binarios en la página de descargas):

```bash
git tag v0.2.0 && git push origin v0.2.0
```

Sin empaquetar, la misma ventana se abre con `matriz-gui` o
`python -m bordado.gui`.

## Generación de diseños

```bash
python disenos/demo_emblema.py
```

Genera una matriz por código, la valida y la exporta a los cinco formatos con
vista previa y ficha técnica.

## Arquitectura

Capas con dependencia en un solo sentido. La capa de dominio no conoce
formatos de archivo; solo `patron.py` toca pyembroidery.

```
gui/app.py          ventana tkinter: solo widgets y presentación
gui/controlador.py  hilo trabajador + cola de eventos (testeable sin pantalla)
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

**Hilos:** tkinter no es thread-safe. El lote corre en un hilo trabajador que
publica eventos en una cola; el hilo de la interfaz la vacía cada 80 ms. Por
eso `gui/controlador.py` no importa tkinter y se puede testear sin pantalla.

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
`N ≈ A / (d · l)`. Tiempo de bordado: `t = N / v`, con `v ≈ 700 ppm`.

## Hoja de ruta

1. **Conversor por lotes** — hecho (CLI + ventana + ejecutable)
2. **Auto-digitizer**: imagen (PNG/JPG/SVG) → matriz
   - segmentación → vectorización → limpieza
   - decisión de puntada por región → ordenamiento de objetos y colores
   - mapeo a hilos reales (Madeira / Isacord)
3. **Redimensionador** con recálculo de densidad — depende del punto 2:
   no se puede reescalar bien desde el binario, solo desde las regiones
4. Integración de todo en un solo programa

## Estado actual

Implementado y testeado (40 tests, en Windows / macOS / Linux):

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

## Licencia

MIT — ver [LICENSE](LICENSE).
