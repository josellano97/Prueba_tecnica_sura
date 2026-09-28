/**
 * Gráficos SVG del tablero (reutilizados del tablero HTML original, sin librerías externas).
 * Cada función recibe datos ya calculados por el servidor y solo dibuja.
 */
import { esc, fmt1, fmt2, fmtCOP, fmtEntero } from "./formato.js";

const tip = () => document.getElementById("tooltip");

export function mostrarTip(ev, html) {
  const t = tip();
  t.innerHTML = html;
  t.hidden = false;
  const w = t.offsetWidth, h = t.offsetHeight;
  let x = ev.clientX + 14, y = ev.clientY - h - 10;
  if (x + w > window.innerWidth - 8) x = ev.clientX - w - 14;
  if (y < 8) y = ev.clientY + 16;
  t.style.left = x + "px";
  t.style.top = y + "px";
}
export const ocultarTip = () => { tip().hidden = true; };
export const filaTip = (k, v) => `<div class="fila"><span>${esc(k)}</span><span>${esc(v)}</span></div>`;

const TITULOS = {
  casos: "Casos por mes",
  costo: "Costo total por mes (millones COP)",
  tasa: "Tasa de incidencia por mes (casos por 100 trabajadores)",
};

/**
 * Límites "redondos" del eje Y alrededor de los datos (no desde cero): las líneas muestran mejor los
 * movimientos. Devuelve {lo, hi, paso} con unas 5 divisiones. Solo para líneas; las barras siempre parten de cero.
 */
export function escalaEje(valores) {
  const vs = valores.filter(v => v !== null && v !== undefined && isFinite(v));
  let mn = Math.min(...vs), mx = Math.max(...vs);
  if (!vs.length) { mn = 0; mx = 1; }
  if (mx === mn) { const d = Math.abs(mx) * 0.1 || 1; mn -= d; mx += d; }
  const holgura = (mx - mn) * 0.12;
  mn -= holgura; mx += holgura;
  const bruto = (mx - mn) / 5, mag = Math.pow(10, Math.floor(Math.log10(bruto)));
  const paso = [1, 2, 2.5, 5, 10].map(f => f * mag).find(p => p >= bruto);
  let lo = Math.floor(mn / paso) * paso;
  if (lo < 0 && Math.min(...vs) >= 0) lo = 0;                   // nunca un eje negativo para datos positivos
  return { lo, hi: Math.ceil(mx / paso - 1e-9) * paso, paso };
}

/** Línea de 12 meses con crosshair, tooltip y línea de promedio histórico. El eje empieza cerca del mínimo. */
export function tendencia(cont, leyenda, titulo, datos, metrica) {
  const serie = datos.tendencia;
  const prom = datos.promedio_historico[metrica] || 0;
  const W = Math.max(320, cont.clientWidth), H = 330, m = { t: 16, r: 16, b: 30, l: 58 };
  const vals = serie.map(s => s[metrica] ?? 0);
  const esc_ = escalaEje([prom, ...vals]);
  const x = i => m.l + (serie.length === 1 ? (W - m.l - m.r) / 2 : i * (W - m.l - m.r) / (serie.length - 1));
  const y = v => m.t + (H - m.t - m.b) * (1 - (v - esc_.lo) / (esc_.hi - esc_.lo));
  const fmtEje = v => metrica === "costo" ? fmt1.format(v / 1e6) + " M" : metrica === "tasa" ? fmt1.format(v) : fmtEntero.format(v);
  const fmtVal = v => metrica === "costo" ? fmtCOP(v) : metrica === "tasa" ? fmt2.format(v) : fmtEntero.format(v);
  titulo.textContent = "Tendencia mensual · " + TITULOS[metrica];

  let g = "";
  for (let v = esc_.lo; v <= esc_.hi + esc_.paso / 2; v += esc_.paso) {
    const yy = y(v);
    g += `<line x1="${m.l}" x2="${W - m.r}" y1="${yy}" y2="${yy}" stroke="var(--grid)"/>`;
    g += `<text x="${m.l - 8}" y="${yy + 4}" text-anchor="end" font-size="11" fill="var(--muted)">${fmtEje(v)}</text>`;
  }
  const angosto = W < 560;                             // todos los meses con etiqueta; en celular, su inicial
  serie.forEach((s, i) => {
    const [mes, anio] = s.etiqueta.split(" ");
    const conAnio = mes === "ene" || i === 0;
    if (angosto) {
      g += `<text x="${x(i)}" y="${H - 15}" text-anchor="middle" font-size="11" fill="var(--muted)">${mes[0].toUpperCase()}</text>`;
      if (conAnio) g += `<text x="${x(i)}" y="${H - 3}" text-anchor="middle" font-size="9" fill="var(--muted)">${anio}</text>`;
    } else {
      g += `<text x="${x(i)}" y="${H - 8}" text-anchor="middle" font-size="11" fill="var(--muted)">${mes}${conAnio ? " " + anio.slice(2) : ""}</text>`;
    }
  });
  g += `<line x1="${m.l}" x2="${W - m.r}" y1="${y(prom)}" y2="${y(prom)}" stroke="var(--ref)" stroke-width="1.5" stroke-dasharray="5 4"/>`;
  g += `<text x="${m.l + 6}" y="${y(prom) + (vals[0] > prom ? 15 : -7)}" font-size="11" font-weight="600" fill="var(--text-2)" stroke="var(--card)" stroke-width="4" paint-order="stroke">Promedio histórico: ${fmtVal(prom)}</text>`;
  const pts = vals.map((v, i) => `${x(i)},${y(v)}`).join(" ");
  g += `<polyline points="${pts}" fill="none" stroke="var(--series-1)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
  vals.forEach((v, i) => {
    g += `<circle cx="${x(i)}" cy="${y(v)}" r="${i === vals.length - 1 ? 5 : 3.5}" fill="var(--series-1)" stroke="var(--card)" stroke-width="2"/>`;
  });
  const ult = vals[vals.length - 1];
  g += `<text x="${x(vals.length - 1) - 8}" y="${y(ult) - 10}" text-anchor="end" font-size="12" font-weight="700" fill="var(--text)">${fmtVal(ult)}</text>`;
  g += `<line class="cruz" x1="0" x2="0" y1="${m.t}" y2="${H - m.b}" stroke="var(--muted)" opacity="0"/>`;
  g += `<rect class="zona" x="${m.l}" y="${m.t}" width="${W - m.l - m.r}" height="${H - m.t - m.b}" fill="transparent"/>`;
  cont.innerHTML = `<svg viewBox="0 0 ${W} ${H}" height="${H}" role="img" aria-label="${TITULOS[metrica]}, últimos 12 meses">${g}</svg>`;
  leyenda.innerHTML = `<span><i class="muestra linea"></i>${TITULOS[metrica].split(" (")[0]}</span><span><i class="muestra punteada"></i>Promedio histórico (${datos.promedio_historico.meses} meses)</span>`;

  const svg = cont.querySelector("svg"), cruz = svg.querySelector(".cruz");
  svg.querySelector(".zona").addEventListener("mousemove", ev => {
    const r = svg.getBoundingClientRect();
    const px = (ev.clientX - r.left) * W / r.width;
    const i = Math.max(0, Math.min(serie.length - 1, Math.round((px - m.l) / ((W - m.l - m.r) / Math.max(1, serie.length - 1)))));
    const s = serie[i];
    cruz.setAttribute("x1", x(i)); cruz.setAttribute("x2", x(i)); cruz.setAttribute("opacity", 0.6);
    mostrarTip(ev, `<b>${esc(s.etiqueta_larga)}</b>` + filaTip("Casos", fmtEntero.format(s.casos)) +
      filaTip("Graves", fmtEntero.format(s.graves)) + filaTip("Costo", fmtCOP(s.costo)) +
      filaTip("Tasa", s.tasa === null ? "–" : fmt2.format(s.tasa)) + filaTip("Promedio histórico", fmtVal(prom)));
  });
  svg.querySelector(".zona").addEventListener("mouseleave", () => { cruz.setAttribute("opacity", 0); ocultarTip(); });
}

/** Barras 100 % apiladas: leve vs grave, en cantidad de casos y en costo. */
export function tipo(cont, act) {
  const W = Math.max(280, cont.clientWidth), alto = 30, gap = 18, m = { l: 74, r: 8 }, H = 2 * alto + gap + 8;
  const filas = [
    { nombre: "Casos", leve: act.leves, grave: act.graves, fmt: fmtEntero.format },
    { nombre: "Costo", leve: act.costo_leve, grave: act.costo_grave, fmt: fmtCOP },
  ];
  let g = "";
  filas.forEach((f, i) => {
    const tot = f.leve + f.grave, y0 = 4 + i * (alto + gap), ancho = W - m.l - m.r;
    g += `<text x="0" y="${y0 + alto / 2 + 4}" font-size="12" font-weight="600" fill="var(--text-2)">${f.nombre}</text>`;
    if (!tot) { g += `<text x="${m.l}" y="${y0 + alto / 2 + 4}" font-size="12" fill="var(--muted)">Sin casos</text>`; return; }
    const wl = ancho * f.leve / tot, wg = ancho - wl;
    const seg = (xx, w, color, pct, id) => {
      let s = `<rect class="seg" data-i="${id}" x="${xx}" y="${y0}" width="${Math.max(0, w - (w > 2 ? 1 : 0))}" height="${alto}" rx="4" fill="${color}"/>`;
      if (w > 46) s += `<text x="${xx + 8}" y="${y0 + alto / 2 + 4}" font-size="12" font-weight="600" fill="#fff" pointer-events="none">${fmt1.format(pct)} %</text>`;
      return s;
    };
    g += seg(m.l, wl, "var(--series-1)", f.leve / tot * 100, `${i}-l`);
    g += seg(m.l + wl + 1, wg, "var(--series-2)", f.grave / tot * 100, `${i}-g`);
  });
  cont.innerHTML = `<svg viewBox="0 0 ${W} ${H}" height="${H}" role="img" aria-label="Distribución leve y grave en casos y costo">${g}</svg>`;
  cont.querySelectorAll(".seg").forEach(el => {
    el.addEventListener("mousemove", ev => {
      const [i, t] = el.dataset.i.split("-"); const f = filas[+i]; const tot = f.leve + f.grave;
      const v = t === "l" ? f.leve : f.grave;
      mostrarTip(ev, `<b>${t === "l" ? "Leve" : "Grave"} · ${f.nombre.toLowerCase()}</b>` + filaTip(f.nombre, f.fmt(v)) +
        filaTip("Participación", fmt1.format(v / tot * 100) + " %"));
    });
    el.addEventListener("mouseleave", ocultarTip);
  });
}

/** Barras verticales por clase de riesgo (rampa ordinal de un solo tono). */
export function clase(cont, porClase) {
  const W = Math.max(280, cont.clientWidth), H = 190, m = { t: 22, r: 8, b: 34, l: 8 };
  const maxV = Math.max(1, ...porClase.map(c => c.casos)) * 1.12;
  const bw = (W - m.l - m.r) / porClase.length;
  let g = `<line x1="${m.l}" x2="${W - m.r}" y1="${H - m.b}" y2="${H - m.b}" stroke="var(--grid)"/>`;
  porClase.forEach((d, i) => {
    const h = (H - m.t - m.b) * d.casos / maxV, xx = m.l + i * bw + bw * 0.18, w = bw * 0.64, yy = H - m.b - h;
    g += `<rect class="barra" data-i="${i}" x="${xx}" y="${yy}" width="${w}" height="${Math.max(h, d.activa ? 1 : 0)}" rx="4" fill="var(--seq-${d.clase})" opacity="${d.activa ? 1 : 0.25}"/>`;
    if (d.activa) g += `<text x="${xx + w / 2}" y="${yy - 6}" text-anchor="middle" font-size="12" font-weight="700" fill="var(--text)">${fmtEntero.format(d.casos)}</text>`;
    g += `<text x="${xx + w / 2}" y="${H - m.b + 15}" text-anchor="middle" font-size="12" font-weight="600" fill="var(--text-2)">Clase ${d.clase}</text>`;
    g += `<text x="${xx + w / 2}" y="${H - m.b + 29}" text-anchor="middle" font-size="11" fill="var(--muted)">${d.activa && d.tasa !== null ? "tasa " + fmt2.format(d.tasa) : d.activa ? "sin datos" : "filtrada"}</text>`;
  });
  cont.innerHTML = `<svg viewBox="0 0 ${W} ${H}" height="${H}" role="img" aria-label="Casos por clase de riesgo">${g}</svg>`;
  cont.querySelectorAll(".barra").forEach(el => {
    el.addEventListener("mousemove", ev => {
      const d = porClase[+el.dataset.i];
      mostrarTip(ev, `<b>Clase de riesgo ${d.clase}</b>` + filaTip("Casos", fmtEntero.format(d.casos)) +
        filaTip("Trabajadores", fmtEntero.format(d.trabajadores)) + filaTip("Tasa", d.tasa === null ? "–" : fmt2.format(d.tasa)));
    });
    el.addEventListener("mouseleave", ocultarTip);
  });
}
