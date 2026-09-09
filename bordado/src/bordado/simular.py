"""
Simulador: ver como la maquina cose la matriz, puntada a puntada.

PARA QUE SIRVE
    Un archivo de bordado es una lista de perforaciones y comandos. Leerlo no
    dice nada; verlo cosiendose lo dice todo. Con la reproduccion se detectan
    de un vistazo las fallas que ningun numero delata:

      - la aguja yendo y viniendo de un extremo al otro (recorrido malo)
      - cortes de hilo donde la costura seguia justo al lado
      - saltos largos que van a dejar un hilo cruzando la pieza
      - zonas que se cosen dos veces
      - el orden de colores, que decide que tapa a que

QUE PRODUCE
    Un archivo HTML autonomo: no necesita internet, ni instalar nada, ni que
    el que lo abra tenga el programa. Se abre en cualquier navegador y se
    puede mandar por correo o WhatsApp a un cliente para que apruebe el
    diseno antes de bordarlo.

    Se eligio HTML y no un GIF o un video porque hace falta CONTROL: parar,
    retroceder, ir despacio justo en la zona sospechosa. Un video no deja
    inspeccionar.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import pyembroidery as pe

UNIDADES_POR_MM = 10.0
PUNTADA_MIN_MM = 0.6


@dataclass
class Trazo:
    """Un tramo del recorrido: cosido o en vacio."""
    x1: float
    y1: float
    x2: float
    y2: float
    tipo: str          # "puntada" | "salto"
    color: int
    aviso: str = ""    # "corta" | "larga" | "salto_largo"


@dataclass
class Guion:
    """Todo lo que hace falta para reproducir el bordado."""
    trazos: list[Trazo] = field(default_factory=list)
    colores: list[str] = field(default_factory=list)
    nombres: list[str] = field(default_factory=list)
    cortes: list[int] = field(default_factory=list)   # indices de trazo
    ancho_mm: float = 0.0
    alto_mm: float = 0.0
    x0: float = 0.0
    y0: float = 0.0

    def a_json(self) -> str:
        return json.dumps({
            "trazos": [[round(t.x1, 2), round(t.y1, 2), round(t.x2, 2),
                        round(t.y2, 2), 0 if t.tipo == "puntada" else 1,
                        t.color, t.aviso] for t in self.trazos],
            "colores": self.colores,
            "nombres": self.nombres,
            "cortes": self.cortes,
            "ancho": round(self.ancho_mm, 2),
            "alto": round(self.alto_mm, 2),
            "x0": round(self.x0, 2),
            "y0": round(self.y0, 2),
        }, separators=(",", ":"))


def guionizar(patron: pe.EmbPattern, salto_largo_mm: float = 12.0) -> Guion:
    """Convierte el patron en la secuencia de trazos que se va a reproducir."""
    g = Guion()
    norm = patron.get_normalized_pattern()
    x0, y0, x1, y1 = norm.bounds()
    g.x0, g.y0 = x0 / UNIDADES_POR_MM, y0 / UNIDADES_POR_MM
    g.ancho_mm = (x1 - x0) / UNIDADES_POR_MM
    g.alto_mm = (y1 - y0) / UNIDADES_POR_MM

    hilos = [h for h in norm.threadlist if h is not None]
    g.colores = [f"#{h.get_red():02X}{h.get_green():02X}{h.get_blue():02X}"
                 for h in hilos] or ["#333333"]
    g.nombres = [(h.description or "").strip() or "sin nombre" for h in hilos] \
        or ["hilo"]

    color = 0
    previo = None       # ultima perforacion
    aguja = None        # ultima posicion fisica
    for x, y, cmd in norm.stitches:
        base = cmd & pe.COMMAND_MASK
        # Sin cambio de signo: el patron ya viene con Y hacia abajo, igual que
        # el lienzo del navegador (ver patron._u). Este modulo dibuja lo que
        # dice el archivo; si el archivo esta al reves, se tiene que ver al
        # reves, que para eso es un simulador.
        px, py = x / UNIDADES_POR_MM, y / UNIDADES_POR_MM
        if base == pe.STITCH:
            if previo is not None:
                d = math.dist(previo, (px, py))
                aviso = "corta" if d < PUNTADA_MIN_MM else (
                    "larga" if d > 12.1 else "")
                g.trazos.append(Trazo(previo[0], previo[1], px, py,
                                      "puntada", color, aviso))
            elif aguja is not None:
                # Primera perforacion tras un salto: el tramo ya se dibujo
                # como salto, aqui solo se retoma la costura.
                pass
            previo = aguja = (px, py)
        elif base == pe.JUMP:
            if aguja is not None:
                d = math.dist(aguja, (px, py))
                g.trazos.append(Trazo(aguja[0], aguja[1], px, py, "salto",
                                      color,
                                      "salto_largo" if d > salto_largo_mm else ""))
            previo = None
            aguja = (px, py)
        elif base == pe.TRIM:
            g.cortes.append(len(g.trazos))
            previo = None
        elif base in (pe.COLOR_CHANGE, pe.NEEDLE_SET):
            color = min(color + 1, len(g.colores) - 1)
            previo = None
    return g


def escribir_html(g: Guion, destino: Path, titulo: str = "Simulacion") -> Path:
    """Escribe el HTML autonomo con la reproduccion."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(_PLANTILLA.replace("__TITULO__", titulo)
                       .replace("__DATOS__", g.a_json()), encoding="utf-8")
    return destino


def simular(patron: pe.EmbPattern, destino: Path, titulo: str = "Simulacion",
            salto_largo_mm: float = 12.0) -> tuple[Path, Guion]:
    g = guionizar(patron, salto_largo_mm)
    return escribir_html(g, destino, titulo), g


_PLANTILLA = r"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITULO__</title>
<style>
 :root{--fondo:#f6f6f4;--panel:#fff;--linea:#d8d8d2;--texto:#232323;
       --suave:#6b6b66;--acento:#1B4F9C}
 *{box-sizing:border-box}
 body{margin:0;font:14px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
      background:var(--fondo);color:var(--texto)}
 header{padding:14px 18px;border-bottom:1px solid var(--linea);background:var(--panel)}
 h1{margin:0;font-size:16px;font-weight:600}
 .sub{color:var(--suave);font-size:12px;margin-top:2px}
 main{display:flex;flex-wrap:wrap;gap:16px;padding:16px;align-items:flex-start}
 .lienzo{background:var(--panel);border:1px solid var(--linea);border-radius:8px;
         padding:10px;flex:1 1 520px;min-width:320px}
 canvas{width:100%;height:auto;display:block;border-radius:4px;
        touch-action:none;cursor:crosshair}
 aside{flex:0 1 290px;min-width:250px;display:flex;flex-direction:column;gap:12px}
 .caja{background:var(--panel);border:1px solid var(--linea);border-radius:8px;padding:12px}
 .caja h2{margin:0 0 8px;font-size:12px;text-transform:uppercase;
          letter-spacing:.05em;color:var(--suave);font-weight:600}
 .fila{display:flex;justify-content:space-between;gap:8px;padding:2px 0}
 .fila b{font-variant-numeric:tabular-nums;font-weight:600}
 .mandos{display:flex;gap:8px;align-items:center;margin-bottom:10px;flex-wrap:wrap}
 button{font:inherit;padding:7px 14px;border:1px solid var(--linea);border-radius:6px;
        background:var(--panel);cursor:pointer}
 button:hover{border-color:var(--acento);color:var(--acento)}
 button.primario{background:var(--acento);color:#fff;border-color:var(--acento)}
 input[type=range]{width:100%}
 label{display:flex;gap:6px;align-items:center;font-size:13px;padding:2px 0;cursor:pointer}
 .hilo{display:flex;gap:8px;align-items:center;padding:3px 0}
 .muestra{width:16px;height:16px;border-radius:3px;border:1px solid #0002;flex:none}
 .telas{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}
 .tela{width:26px;height:26px;border-radius:5px;border:2px solid transparent;
       cursor:pointer;box-shadow:inset 0 0 0 1px #0002;padding:0}
 .tela:hover{border-color:var(--acento)}
 .tela[aria-pressed="true"]{border-color:var(--acento)}
 .elegir{justify-content:space-between}
 .elegir input[type=color]{width:44px;height:26px;padding:0;border:1px solid var(--linea);
                           border-radius:5px;background:none;cursor:pointer}
 .pie{color:var(--suave);font-size:12px;margin-top:6px;text-align:center}
 .aviso{color:#B3261E}
 .ok{color:#1B7F3B}
</style></head><body>
<header>
 <h1>__TITULO__</h1>
 <div class="sub" id="sub"></div>
</header>
<main>
 <div class="lienzo">
  <div class="mandos">
   <button id="play" class="primario">Reproducir</button>
   <button id="reinicio">Reiniciar</button>
   <button id="fin">Ir al final</button>
   <button id="ajustar">Ajustar a la pantalla</button>
   <label>Velocidad
    <select id="vel">
     <option value="0.25">lenta</option><option value="1" selected>normal</option>
     <option value="4">rapida</option><option value="20">muy rapida</option>
    </select></label>
  </div>
  <input type="range" id="barra" min="0" value="0" step="1">
  <canvas id="lienzo"></canvas>
  <div class="pie">Rueda del raton o pellizco para acercar · arrastra para mover
   · <b id="zoom">100%</b></div>
 </div>
 <aside>
  <div class="caja"><h2>Avance</h2>
   <div class="fila"><span>Puntada</span><b id="n">0</b></div>
   <div class="fila"><span>Recorrido cosido</span><b id="hilo">0 m</b></div>
   <div class="fila"><span>Cortes hechos</span><b id="nc">0</b></div>
  </div>
  <div class="caja"><h2>Tela</h2>
   <div class="telas" id="telas"></div>
   <label class="elegir">Otro color
    <input type="color" id="fondo" value="#FFFFFF"></label>
  </div>
  <div class="caja"><h2>Ver</h2>
   <label><input type="checkbox" id="vsaltos" checked> Saltos de aguja</label>
   <label><input type="checkbox" id="vavisos" checked> Marcar problemas</label>
   <label><input type="checkbox" id="vcortes" checked> Cortes de hilo</label>
  </div>
  <div class="caja"><h2>Hilos</h2><div id="hilos"></div></div>
  <div class="caja"><h2>Revision</h2><div id="revision"></div></div>
 </aside>
</main>
<script>
const D = __DATOS__;
const T = D.trazos, N = T.length;
const cv = document.getElementById('lienzo'), cx = cv.getContext('2d');
const $ = id => document.getElementById(id);
let i = 0, tocando = false, margen = 12;
// Encuadre: `base` es la escala que hace caber el diseno entero; `zoom` es lo
// que el usuario acerca encima; `dx`/`dy` es el arrastre, en pixeles de lienzo.
let base = 1, zoom = 1, dx = 0, dy = 0;
const DPR = () => devicePixelRatio || 1;
const escalaAct = () => base * zoom;

function medir(){
  // El lienzo se dimensiona contra el hueco que queda EN PANTALLA, no solo
  // contra el ancho del contenedor. Si solo se mira el ancho, un diseno alto
  // (una insignia, un escudo) sale mas largo que la ventana y hay que
  // scrollear para verlo entero, que es justo lo que no sirve cuando lo que
  // se busca es una vision de conjunto.
  const caja = cv.parentElement.getBoundingClientRect();
  const ancho = Math.max(280, caja.width - 20);
  // Lo que sobra de alto hasta el borde de la ventana, con un respiro para el
  // pie y para que en el telefono se vea que la pagina sigue.
  const disponible = Math.max(240, innerHeight - cv.getBoundingClientRect().top - 70);
  const rel = D.alto / Math.max(D.ancho, 1e-6);
  const alto = Math.min(ancho * rel + margen * 2, disponible);
  const dpr = DPR();
  cv.width = ancho * dpr;
  cv.height = alto * dpr;
  cv.style.width = ancho + 'px';
  cv.style.height = alto + 'px';
  base = Math.min((cv.width - 2 * margen * dpr) / Math.max(D.ancho, 1e-6),
                  (cv.height - 2 * margen * dpr) / Math.max(D.alto, 1e-6));
}

function ajustar(){ zoom = 1; dx = dy = 0; medir(); mostrarZoom(); }
function mostrarZoom(){ $('zoom').textContent = Math.round(zoom * 100) + '%'; }

// El diseno va centrado en el lienzo: asi al alejar no queda pegado a un borde.
const centroX = () => (cv.width - D.ancho * escalaAct()) / 2 + dx;
const centroY = () => (cv.height - D.alto * escalaAct()) / 2 + dy;
const X = v => centroX() + (v - D.x0) * escalaAct();
const Y = v => centroY() + (v - D.y0) * escalaAct();

// --- color de la tela ----------------------------------------------------
// Un bordado no se mira sobre papel blanco: se mira sobre la prenda. Con el
// fondo blanco, un hilo blanco es invisible y no hay forma de revisarlo; y un
// diseno pensado para una polera negra se ve distinto de lo que sera.
// Los atajos son los colores de polera mas comunes; el selector permite
// cualquier color, incluido el exacto de la tela que se vaya a usar.
const TELAS = [['#FFFFFF','blanco'], ['#111111','negro'], ['#9AA0A6','gris'],
               ['#1B2A4A','azul marino'], ['#7A1220','burdeo'],
               ['#0F5132','verde'], ['#E8DCC8','crudo'], ['#C8102E','rojo']];
let tela = '#FFFFFF';

function marcarTela(){
  for (const b of document.querySelectorAll('.tela'))
    b.setAttribute('aria-pressed', b.dataset.c.toUpperCase() === tela.toUpperCase());
}
function ponerTela(c){ tela = c; $('fondo').value = c; marcarTela(); pintar(); }

$('telas').innerHTML = TELAS.map(([c, n]) =>
  `<button class="tela" data-c="${c}" style="background:${c}" title="${n}"></button>`
).join('');
for (const b of document.querySelectorAll('.tela'))
  b.onclick = () => ponerTela(b.dataset.c);
$('fondo').oninput = e => ponerTela(e.target.value);
marcarTela();

function pintar(){
  cx.fillStyle = tela; cx.fillRect(0, 0, cv.width, cv.height);
  const saltos = $('vsaltos').checked, avisos = $('vavisos').checked,
        cortes = $('vcortes').checked;
  cx.lineCap = 'round';
  for (let k = 0; k < i; k++){
    const t = T[k];
    if (t[4] === 1){                       // salto
      if (!saltos) continue;
      cx.strokeStyle = t[6] ? '#E8590C' : '#bbb';
      cx.setLineDash(t[6] ? [6,4] : [3,4]);
      cx.lineWidth = Math.max(1, DPR());
    } else {
      cx.strokeStyle = D.colores[t[5]] || '#333';
      cx.setLineDash([]);
      cx.lineWidth = Math.max(1.4, 0.42 * escalaAct());
    }
    cx.beginPath(); cx.moveTo(X(t[0]), Y(t[1])); cx.lineTo(X(t[2]), Y(t[3])); cx.stroke();
    if (avisos && t[6] && t[4] === 0){
      cx.setLineDash([]); cx.fillStyle = '#B3261E';
      cx.beginPath(); cx.arc(X(t[2]), Y(t[3]), 2.4 * DPR(), 0, 7); cx.fill();
    }
  }
  cx.setLineDash([]);
  if (cortes) for (const c of D.cortes){
    if (c > i || c >= N) continue;
    const t = T[Math.max(c - 1, 0)];
    cx.strokeStyle = '#B3261E'; cx.lineWidth = 1.6 * DPR();
    const x = X(t[2]), y = Y(t[3]), r = 3.4 * DPR();
    cx.beginPath(); cx.moveTo(x-r,y-r); cx.lineTo(x+r,y+r);
    cx.moveTo(x+r,y-r); cx.lineTo(x-r,y+r); cx.stroke();
  }
  if (i > 0 && i <= N){                    // posicion actual de la aguja
    const t = T[i-1];
    cx.strokeStyle = '#111'; cx.lineWidth = 1.6 * DPR();
    cx.beginPath(); cx.arc(X(t[2]), Y(t[3]), 4.5 * DPR(), 0, 7); cx.stroke();
  }
}

function estado(){
  let punt = 0, largo = 0, nc = 0;
  for (let k = 0; k < i; k++){
    if (T[k][4] === 0){ punt++; largo += Math.hypot(T[k][2]-T[k][0], T[k][3]-T[k][1]); }
  }
  for (const c of D.cortes) if (c <= i) nc++;
  $('n').textContent = punt.toLocaleString('es');
  $('hilo').textContent = (largo/1000).toFixed(2) + ' m';
  $('nc').textContent = nc;
  $('barra').value = i;
}

let ultimo = 0;
function cuadro(ts){
  if (tocando && i < N){
    const v = parseFloat($('vel').value);
    const paso = Math.max(1, Math.round((ts - ultimo) * 0.6 * v));
    i = Math.min(N, i + paso);
    pintar(); estado();
    if (i >= N){ tocando = false; $('play').textContent = 'Reproducir'; }
  }
  ultimo = ts;
  requestAnimationFrame(cuadro);
}

$('play').onclick = () => {
  if (i >= N) i = 0;
  tocando = !tocando;
  $('play').textContent = tocando ? 'Pausa' : 'Reproducir';
};
$('reinicio').onclick = () => { i = 0; tocando = false;
  $('play').textContent = 'Reproducir'; pintar(); estado(); };
$('fin').onclick = () => { i = N; tocando = false;
  $('play').textContent = 'Reproducir'; pintar(); estado(); };
$('barra').oninput = e => { i = +e.target.value; pintar(); estado(); };
for (const id of ['vsaltos','vavisos','vcortes']) $(id).onchange = pintar;
$('ajustar').onclick = () => { ajustar(); pintar(); };
addEventListener('resize', () => {
  // Al girar el telefono o cambiar el tamano de la ventana se recalcula el
  // encuadre, pero se respeta el zoom que el usuario haya puesto.
  medir(); pintar();
});

// --- acercar y mover ---------------------------------------------------
// Un simulador sirve para mirar de cerca: el detalle fino (letras, numeros,
// bordes) no se juzga desde el encuadre completo.
const ZOOM_MIN = 1, ZOOM_MAX = 40;

function acercar(factor, cx_, cy_){
  const antes = escalaAct();
  const z = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, zoom * factor));
  if (z === zoom) return;
  zoom = z;
  // Se acerca respecto del punto senalado, no del centro: si no, lo que
  // estabas mirando se te escapa de la pantalla.
  const k = escalaAct() / antes;
  dx = cx_ - k * (cx_ - dx);
  dy = cy_ - k * (cy_ - dy);
  mostrarZoom(); pintar();
}

function enLienzo(e){
  const r = cv.getBoundingClientRect();
  return [(e.clientX - r.left) * DPR(), (e.clientY - r.top) * DPR()];
}

cv.addEventListener('wheel', e => {
  e.preventDefault();
  const [px, py] = enLienzo(e);
  acercar(Math.exp(-e.deltaY * 0.0015), px, py);
}, {passive: false});

let punteros = new Map(), pinza = 0;
cv.addEventListener('pointerdown', e => {
  cv.setPointerCapture(e.pointerId);
  punteros.set(e.pointerId, enLienzo(e));
});
cv.addEventListener('pointermove', e => {
  if (!punteros.has(e.pointerId)) return;
  const previo = punteros.get(e.pointerId), actual = enLienzo(e);
  punteros.set(e.pointerId, actual);
  if (punteros.size === 1){                       // arrastrar
    dx += actual[0] - previo[0];
    dy += actual[1] - previo[1];
    pintar();
  } else if (punteros.size === 2){                // pellizcar
    const [a, b] = [...punteros.values()];
    const d = Math.hypot(a[0]-b[0], a[1]-b[1]);
    if (pinza) acercar(d / pinza, (a[0]+b[0])/2, (a[1]+b[1])/2);
    pinza = d;
  }
});
for (const ev of ['pointerup','pointercancel','pointerleave'])
  cv.addEventListener(ev, e => { punteros.delete(e.pointerId); pinza = 0; });

// --- resumen y revision ---
(function(){
  let punt = 0, saltos = 0, largo = 0, recorrido = 0, cortas = 0, largas = 0, sl = 0;
  for (const t of T){
    const d = Math.hypot(t[2]-t[0], t[3]-t[1]);
    if (t[4] === 0){ punt++; largo += d; if (t[6]==='corta') cortas++;
                     if (t[6]==='larga') largas++; }
    else { saltos++; recorrido += d; if (t[6]==='salto_largo') sl++; }
  }
  $('sub').textContent = `${D.ancho.toFixed(1)} x ${D.alto.toFixed(1)} mm · `
    + `${punt.toLocaleString('es')} puntadas · ${(largo/1000).toFixed(1)} m de hilo · `
    + `${D.cortes.length} cortes`;
  $('hilos').innerHTML = D.colores.map((c,k) =>
    `<div class="hilo"><span class="muestra" style="background:${c}"></span>`
    + `<span>${k+1}. ${D.nombres[k]||''} <span style="color:#6b6b66">${c}</span></span></div>`
  ).join('');
  const filas = [];
  filas.push(`<div class="fila"><span>Saltos de aguja</span><b>${saltos}</b></div>`);
  filas.push(`<div class="fila"><span>Recorrido en vacio</span>`
    + `<b>${(recorrido/10).toFixed(0)} cm</b></div>`);
  filas.push(`<div class="fila"><span>Saltos largos</span>`
    + `<b class="${sl?'aviso':'ok'}">${sl}</b></div>`);
  filas.push(`<div class="fila"><span>Puntadas cortas</span>`
    + `<b class="${cortas?'aviso':'ok'}">${cortas}</b></div>`);
  filas.push(`<div class="fila"><span>Puntadas largas</span>`
    + `<b class="${largas?'aviso':'ok'}">${largas}</b></div>`);
  $('revision').innerHTML = filas.join('');
  $('barra').max = N;
})();

ajustar(); pintar(); estado(); requestAnimationFrame(cuadro);
</script></body></html>
"""
