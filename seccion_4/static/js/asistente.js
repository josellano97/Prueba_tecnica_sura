/**
 * Asistente de siniestralidad: chat embebido que conversa con el agente de n8n.
 * El agente responde con las cifras de la API de la app; aquí solo se envía la pregunta y se muestra la respuesta.
 * La respuesta se inserta como texto escapado: solo se convierten negritas, enlaces https, listas y saltos de línea.
 */
const raiz = document.getElementById("asistente");
const panel = document.getElementById("asistente-panel");
const abrir = document.getElementById("asistente-abrir");
const mensajes = document.getElementById("asistente-mensajes");
const form = document.getElementById("asistente-form");
const texto = document.getElementById("asistente-texto");
const CLAVE_SESION = "asistente.sesion";

function sesion() {
  try {
    let id = sessionStorage.getItem(CLAVE_SESION);
    if (!id) { id = crypto.randomUUID(); sessionStorage.setItem(CLAVE_SESION, id); }
    return id;
  } catch { return (window.__sesionAsistente ||= crypto.randomUUID()); }   // sin almacenamiento: solo en esta página
}

function escapar(s) {
  return s.replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

/** Markdown mínimo y seguro: el texto ya viene escapado antes de convertir. */
function formatear(md) {
  const lineas = escapar(md.trim()).split("\n");
  let html = "", enLista = false;
  for (const bruta of lineas) {
    const l = bruta.trim();
    const item = l.match(/^([-*•]|\d+[.)])\s+(.*)$/);
    const sub = /^\s{2,}/.test(bruta);                  // viñeta con sangría = segundo nivel
    if (item) { if (!enLista) { html += "<ul>"; enLista = true; } html += `<li${sub ? ' class="sub"' : ""}>${item[2]}</li>`; continue; }
    if (enLista) { html += "</ul>"; enLista = false; }
    html += l ? `<p>${l}</p>` : "";
  }
  if (enLista) html += "</ul>";
  return html
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\[([^\]]+)\]\((https:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
    .replace(/(^|[\s(])(https:\/\/[^\s<)]+)/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>');
}

function agregar(tipo, contenido, esHtml = false) {
  const div = document.createElement("div");
  div.className = `msg msg-${tipo}`;
  if (esHtml) div.innerHTML = contenido; else div.textContent = contenido;
  mensajes.appendChild(div);
  mensajes.scrollTop = mensajes.scrollHeight;
  return div;
}

async function preguntar(pregunta) {
  pregunta = pregunta.trim();
  if (!pregunta) return;
  mensajes.querySelector(".asistente-sugerencias")?.remove();
  agregar("usuario", pregunta);
  const espera = agregar("agente cargando", "Consultando los datos…");
  form.querySelector("button").disabled = true;
  try {
    const r = await fetch(raiz.dataset.url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Authorization": raiz.dataset.autorizacion },
      body: JSON.stringify({ action: "sendMessage", sessionId: sesion(), chatInput: pregunta }),
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const datos = await r.json();
    const salida = (Array.isArray(datos) ? datos[0] : datos)?.output || "No recibí respuesta del asistente.";
    espera.remove();
    agregar("agente", formatear(salida), true);
  } catch (e) {
    espera.remove();
    agregar("error", "No fue posible consultar el asistente en este momento. Intente de nuevo en unos segundos.");
  } finally {
    form.querySelector("button").disabled = false;
    texto.focus();
  }
}

function mostrar(visible) {
  panel.hidden = !visible;
  abrir.setAttribute("aria-expanded", String(visible));
  raiz.classList.toggle("abierto", visible);
  if (visible) texto.focus();
}

if (abrir) {                                           // burbuja flotante (en la pestaña «Agente Sura» no existe)
  abrir.addEventListener("click", () => mostrar(panel.hidden));
  document.getElementById("asistente-cerrar").addEventListener("click", () => { mostrar(false); abrir.focus(); });
  panel.addEventListener("keydown", e => { if (e.key === "Escape") { mostrar(false); abrir.focus(); } });
} else {
  texto.focus();
}
mensajes.addEventListener("click", e => {
  const b = e.target.closest("[data-pregunta]");
  if (b) preguntar(b.dataset.pregunta);
});
form.addEventListener("submit", e => { e.preventDefault(); const q = texto.value; texto.value = ""; preguntar(q); });
texto.addEventListener("keydown", e => {                // Enter envía; Shift+Enter, salto de línea
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); }
});
