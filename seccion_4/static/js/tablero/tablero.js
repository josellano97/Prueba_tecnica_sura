/**
 * Controlador del tablero: estado de filtros (sincronizado con la URL para compartir enlaces),
 * llamada a la API del servidor y dibujo de KPI, resumen, gráficos y tabla.
 * Los cálculos se hacen en el servidor (apps/tablero/servicios/indicadores.py).
 */
import { ESTADOS, esc, fmt1, fmt2, fmtCOP, fmtEntero } from "./formato.js";
import * as graficos from "./graficos.js";

const $ = id => document.getElementById(id);
const raiz = $("tablero");
const URL_DATOS = raiz.dataset.urlDatos;
const URL_EXPORTAR = raiz.dataset.urlExportar;
const CLASES = [1, 2, 3, 4, 5];

let estado = estadoDesdeUrl();
let datos = null;
let peticion = null;

/** Estado inicial a partir de la URL (?mes=2026-08&sector=3&clase=4&clase=5...). */
function estadoDesdeUrl() {
  const p = new URLSearchParams(location.search);
  const clases = p.getAll("clase").map(Number).filter(c => CLASES.includes(c));
  return {
    mes: p.get("mes") || $("f-mes").value,
    coordinador: p.get("coordinador") || "",
    sector: p.get("sector") || "",
    clases: new Set(clases.length ? clases : CLASES),
    metrica: ["casos", "costo", "tasa"].includes(p.get("metrica")) ? p.get("metrica") : "casos",
    periodoTop: p.get("top") === "12m" ? "12m" : "mes",
  };
}

function parametros({ incluirVista = false } = {}) {
  const p = new URLSearchParams();
  if (estado.mes) p.set("mes", estado.mes);
  if (estado.coordinador) p.set("coordinador", estado.coordinador);
  if (estado.sector) p.set("sector", estado.sector);
  if (estado.clases.size < CLASES.length) [...estado.clases].sort().forEach(c => p.append("clase", c));
  if (incluirVista) {
    if (estado.metrica !== "casos") p.set("metrica", estado.metrica);
    if (estado.periodoTop !== "mes") p.set("top", estado.periodoTop);
  }
  return p;
}

function sincronizarControles() {
  $("f-mes").value = estado.mes;
  if ($("f-coordinador")) $("f-coordinador").value = estado.coordinador;
  $("f-sector").value = estado.sector;
  document.querySelectorAll(".chip[data-clase]").forEach(b => b.setAttribute("aria-pressed", estado.clases.has(+b.dataset.clase)));
  document.querySelectorAll("#seg-metrica button").forEach(b => b.setAttribute("aria-pressed", b.dataset.metrica === estado.metrica));
  document.querySelectorAll("#seg-top button").forEach(b => b.setAttribute("aria-pressed", b.dataset.periodo === estado.periodoTop));
  const qs = parametros({ incluirVista: true }).toString();
  history.replaceState(null, "", qs ? "?" + qs : location.pathname);
  if (URL_EXPORTAR && $("btn-exportar")) {
    const p = parametros(); p.set("periodo", estado.periodoTop);
    $("btn-exportar").href = URL_EXPORTAR + "?" + p.toString();
  }
}

/** Pide los datos al servidor; cancela la petición anterior si el usuario cambia rápido los filtros. */
async function cargar() {
  sincronizarControles();
  peticion?.abort();
  peticion = new AbortController();
  $("contenido-tablero").setAttribute("aria-busy", "true");
  $("error-datos").hidden = true;
  try {
    const r = await fetch(URL_DATOS + "?" + parametros().toString(), {
      headers: { Accept: "application/json" }, credentials: "same-origin", signal: peticion.signal });
    if (r.status === 401 || r.status === 403 || r.redirected) throw new Error("Su sesión expiró o no tiene permiso. Recargue la página.");
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || "No fue posible cargar los datos.");
    datos = await r.json();
    render();
  } catch (e) {
    if (e.name === "AbortError") return;
    $("error-texto").textContent = e.message;
    $("error-datos").hidden = false;
  } finally {
    $("contenido-tablero").setAttribute("aria-busy", "false");
  }
}

// ------------------------------------------------------------------ render
function variacion(actual, anterior, tipo) {
  if (anterior === null || anterior === undefined || actual === null) return `<span class="igual">Sin dato del mes anterior</span>`;
  const dif = actual - anterior;
  const clase = Math.abs(dif) < 1e-9 ? "igual" : dif > 0 ? "sube-mal" : "baja-bien";
  const flecha = Math.abs(dif) < 1e-9 ? "=" : dif > 0 ? "▲" : "▼";
  const signo = dif >= 0 ? "+" : "−";
  const abs = tipo === "costo" ? signo + fmtCOP(Math.abs(dif)).replace("$ ", "$")
    : tipo === "tasa" ? signo + fmt2.format(Math.abs(dif)) + " pts" : signo + fmtEntero.format(Math.abs(dif));
  const pct = anterior ? ` (${signo}${fmt1.format(Math.abs(dif / anterior * 100))} %)` : "";
  return `<span class="${clase}">${flecha} ${abs}${pct}</span> <span class="cmp">vs ${esc(datos.mes_anterior.corta)}</span>`;
}

function renderKPIs() {
  const a = datos.kpis.actual, p = datos.kpis.anterior;
  const tarjeta = (id, titulo, ayuda, valor, delta, rojo = false) => {
    $(id).innerHTML = `<h2>${titulo} <span class="info" title="${esc(ayuda)}">i</span></h2>
      <div class="valor${rojo ? " alerta" : ""}">${valor}</div><div class="delta">${delta}</div>`;
  };
  tarjeta("kpi-casos", "Casos del mes", "Incidentes ocurridos en el mes", fmtEntero.format(a.casos), variacion(a.casos, p?.casos));
  tarjeta("kpi-costo", "Costo total", "Suma del costo de los casos del mes, en millones de pesos", fmtCOP(a.costo), variacion(a.costo, p?.costo, "costo"));
  tarjeta("kpi-tasa", "Tasa de incidencia", "Casos del mes / trabajadores activos × 100",
    (a.tasa === null ? "–" : fmt2.format(a.tasa)) + "<small> por 100 trab.</small>", variacion(a.tasa, p?.tasa, "tasa"));
  tarjeta("kpi-criticos", "Clientes en estado crítico", `Clientes con tasa del mes mayor a ${fmt2.format(datos.umbrales.critico)}`,
    fmtEntero.format(a.criticos), variacion(a.criticos, p?.criticos), a.criticos > 0);
}

function renderResumen() {
  const a = datos.kpis.actual, p = datos.kpis.anterior;
  if (!datos.alcance.filtrados) {
    $("resumen").innerHTML = "No hay clientes con los filtros seleccionados. Use <b>Limpiar filtros</b>.";
    return;
  }
  let t = `En <strong>${esc(datos.mes.etiqueta)}</strong> se registraron <strong>${fmtEntero.format(a.casos)} casos</strong>`;
  if (p) {
    const d = a.casos - p.casos;
    t += d === 0 ? ", igual que el mes anterior" : `, ${fmtEntero.format(Math.abs(d))} ${d > 0 ? "más" : "menos"} que en ${esc(datos.mes_anterior.etiqueta.split(" de ")[0])}`;
  }
  t += `. La tasa fue de <strong>${a.tasa === null ? "–" : fmt2.format(a.tasa)} casos por cada 100 trabajadores</strong>. `;
  if (a.casos) {
    t += `Los casos graves son el ${fmt1.format(a.graves / a.casos * 100)} % de los casos pero explican el <strong>${fmt1.format(a.costo ? a.costo_grave / a.costo * 100 : 0)} % del costo</strong>. `;
  }
  t += a.criticos
    ? `<strong>${a.criticos} cliente${a.criticos > 1 ? "s están" : " está"} en estado crítico</strong>: revise la tabla inferior.`
    : "Ningún cliente está en estado crítico.";
  $("resumen").innerHTML = t;
}

function renderFiltrosActivos() {
  const partes = [];
  const texto = sel => sel?.options[sel.selectedIndex]?.text;
  if (estado.coordinador) partes.push(`Coordinador: <b>${esc(texto($("f-coordinador")))}</b>`);
  if (estado.sector) partes.push(`Sector: <b>${esc(texto($("f-sector")))}</b>`);
  if (estado.clases.size < CLASES.length) partes.push(`Clase de riesgo: <b>${[...estado.clases].sort().join(", ") || "ninguna"}</b>`);
  const al = datos.alcance;
  $("filtros-activos").innerHTML = `Mostrando <b>${al.filtrados}</b> de ${al.visibles} clientes${al.restringido ? " de su cartera" : ""} · ` +
    (partes.length ? "Filtros aplicados: " + partes.join(" · ") : "Sin filtros aplicados");
}

function renderTop() {
  const filas = datos.top[estado.periodoTop];
  const esMes = estado.periodoTop === "mes";
  const t12 = datos.tendencia;
  $("sub-top").textContent = esMes ? `${datos.mes.etiqueta} · ordenado por casos y, en empate, por costo`
    : `${t12[0].etiqueta} a ${t12[t12.length - 1].etiqueta} · tasa = promedio mensual`;
  if (!filas.length || filas.every(f => f.casos === 0)) {
    $("tabla-top").innerHTML = `<p class="vacio tenue">No hay casos para los filtros seleccionados.</p>`;
    return;
  }
  const cuerpo = filas.map((r, i) => {
    const e = ESTADOS[r.estado];
    let dif = "";
    if (esMes) {
      const d = r.casos - r.casos_anterior;
      dif = `<td class="num">${d === 0 ? '<span class="igual">=</span>' : `<span class="${d > 0 ? "sube-mal" : "baja-bien"}">${d > 0 ? "▲ +" : "▼ −"}${Math.abs(d)}</span>`}</td>`;
    }
    return `<tr><td class="num">${i + 1}</td>
      <td class="cliente">${esc(r.nombre)}<small>${esc(r.sector)} · ${esc(r.coordinador)}</small></td>
      <td><span class="clase clase-${r.clase}" title="Clase de riesgo ${r.clase} (1 = menor, 5 = mayor)">${r.clase}</span></td>
      <td class="num"><b>${fmtEntero.format(r.casos)}</b></td>${dif}
      <td class="num">${fmtEntero.format(r.graves)}</td>
      <td class="num">${r.tasa === null ? "–" : fmt2.format(r.tasa)}</td>
      <td class="num">${fmtCOP(r.costo)}</td>
      <td><span class="semaforo ${r.estado}"><i></i>${e.icono} ${e.txt}</span></td></tr>`;
  }).join("");
  $("tabla-top").innerHTML = `<table class="tabla"><thead><tr><th class="num">#</th><th>Cliente</th><th>Clase riesgo</th>
    <th class="num">Casos</th>${esMes ? '<th class="num">Vs mes ant.</th>' : ""}<th class="num">Graves</th>
    <th class="num" title="Casos por 100 trabajadores (mensual)">Tasa</th><th class="num">Costo</th><th>Estado</th></tr></thead>
    <tbody>${cuerpo}</tbody></table>`;
}

function renderTendencia() {
  graficos.tendencia($("g-tendencia"), $("l-tendencia"), $("t-tendencia"), datos, estado.metrica);
}

function render() {
  if (!datos) return;
  renderFiltrosActivos();
  renderResumen();
  renderKPIs();
  renderTendencia();
  graficos.tipo($("g-tipo"), datos.kpis.actual);
  graficos.clase($("g-clase"), datos.por_clase);
  renderTop();
}

// ------------------------------------------------------------------ controles
function iniciar() {
  $("f-mes").addEventListener("change", e => { estado.mes = e.target.value; cargar(); });
  $("f-coordinador")?.addEventListener("change", e => { estado.coordinador = e.target.value; cargar(); });
  $("f-sector").addEventListener("change", e => { estado.sector = e.target.value; cargar(); });
  document.querySelectorAll(".chip[data-clase]").forEach(b => b.addEventListener("click", () => {
    const c = +b.dataset.clase;
    estado.clases.has(c) ? estado.clases.delete(c) : estado.clases.add(c);
    if (!estado.clases.size) estado.clases.add(c);          // al menos una clase seleccionada
    cargar();
  }));
  $("seg-metrica").addEventListener("click", e => {
    const b = e.target.closest("button"); if (!b) return;
    estado.metrica = b.dataset.metrica; sincronizarControles(); renderTendencia();
  });
  $("seg-top").addEventListener("click", e => {
    const b = e.target.closest("button"); if (!b) return;
    estado.periodoTop = b.dataset.periodo; sincronizarControles(); renderTop();
  });
  $("btn-limpiar").addEventListener("click", () => {
    estado = { ...estadoDesdeUrl(), mes: $("f-mes").options[0].value, coordinador: "", sector: "", clases: new Set(CLASES) };
    cargar();
  });
  $("btn-reintentar").addEventListener("click", cargar);
  let t;
  window.addEventListener("resize", () => { clearTimeout(t); t = setTimeout(render, 150); });
  document.addEventListener("tema-cambiado", render);
  cargar();
}

iniciar();
