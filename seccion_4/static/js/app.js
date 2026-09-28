/**
 * Comportamiento común de la interfaz: menú lateral en móvil, menú de usuario, tema claro/oscuro,
 * cierre de avisos y confirmación de acciones sensibles. No contiene lógica de negocio.
 */
const TEMA_CLAVE = "monitoreo.tema";

/** Lee/escribe el tema preferido del usuario (preferencia local del navegador). */
function aplicarTemaGuardado() {
  try {
    const tema = localStorage.getItem(TEMA_CLAVE);
    if (tema === "light" || tema === "dark") document.documentElement.dataset.theme = tema;
  } catch { /* almacenamiento no disponible: se usa el tema del sistema */ }
}

function alternarTema() {
  const actual = document.documentElement.dataset.theme
    || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  const nuevo = actual === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = nuevo;
  try { localStorage.setItem(TEMA_CLAVE, nuevo); } catch { /* sin almacenamiento */ }
  document.dispatchEvent(new CustomEvent("tema-cambiado"));
}

function configurarLateral() {
  const lateral = document.getElementById("lateral");
  const velo = document.querySelector("[data-cerrar-lateral]");
  const boton = document.querySelector("[data-abrir-lateral]");
  if (!lateral || !boton) return;
  const fijar = abierto => {
    lateral.classList.toggle("abierto", abierto);
    velo.hidden = !abierto;
    boton.setAttribute("aria-expanded", String(abierto));
  };
  boton.addEventListener("click", () => fijar(!lateral.classList.contains("abierto")));
  velo.addEventListener("click", () => fijar(false));
  document.addEventListener("keydown", e => { if (e.key === "Escape") fijar(false); });
}

function configurarMenuUsuario() {
  const boton = document.querySelector("[data-menu-usuario]");
  if (!boton) return;
  const menu = boton.nextElementSibling;
  const fijar = abierto => { menu.hidden = !abierto; boton.setAttribute("aria-expanded", String(abierto)); };
  boton.addEventListener("click", e => { e.stopPropagation(); fijar(menu.hidden); });
  document.addEventListener("click", e => { if (!menu.contains(e.target)) fijar(false); });
  document.addEventListener("keydown", e => { if (e.key === "Escape") fijar(false); });
}

function configurarAvisosYConfirmaciones() {
  document.querySelectorAll("[data-cerrar-aviso]").forEach(b =>
    b.addEventListener("click", () => b.closest(".aviso").remove()));
  document.querySelectorAll("form[data-confirmar]").forEach(f =>
    f.addEventListener("submit", e => { if (!confirm(f.dataset.confirmar)) e.preventDefault(); }));
}

/** Formularios que se envían al cambiar una lista (análisis): un clic menos; sin JS queda el botón. */
function configurarAutoenvio() {
  document.querySelectorAll("form[data-autoenvio]").forEach(f => {
    f.querySelectorAll("[data-sin-js]").forEach(b => { b.hidden = true; });
    f.querySelectorAll("select").forEach(s => s.addEventListener("change", () => f.requestSubmit()));
  });
  // un enlace a una lista dentro de un bloque plegado lo despliega antes de saltar
  document.querySelectorAll("a[data-abrir]").forEach(a => a.addEventListener("click", () => {
    document.querySelector("#" + a.dataset.abrir + " details")?.setAttribute("open", "");
  }));
}

/** Vistas ampliadas (<dialog>): se abren con [data-dialogo="id"] y se cierran con Escape, la X o clic afuera. */
function configurarDialogos() {
  document.querySelectorAll("[data-dialogo]").forEach(boton => boton.addEventListener("click", () => {
    const dlg = document.getElementById(boton.dataset.dialogo);
    if (dlg && typeof dlg.showModal === "function") dlg.showModal();
  }));
  document.querySelectorAll("dialog").forEach(dlg => {
    dlg.querySelectorAll("[data-cerrar-dialogo]").forEach(b => b.addEventListener("click", () => dlg.close()));
    dlg.addEventListener("click", e => { if (e.target === dlg) dlg.close(); });   // clic en el fondo oscuro
  });
}

/** En celular los filtros se muestran plegados: el botón "Filtros" los abre o los cierra. */
function configurarFiltrosMovil() {
  document.querySelectorAll("[data-plegar-filtros]").forEach(boton => boton.addEventListener("click", () => {
    const abierto = boton.closest(".filtros").classList.toggle("abierto");
    boton.setAttribute("aria-expanded", String(abierto));
  }));
}

aplicarTemaGuardado();
document.querySelector("[data-tema]")?.addEventListener("click", alternarTema);
configurarLateral();
configurarMenuUsuario();
configurarAvisosYConfirmaciones();
configurarAutoenvio();
configurarDialogos();
configurarFiltrosMovil();
