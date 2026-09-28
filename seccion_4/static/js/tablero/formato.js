/** Formatos numéricos en español de Colombia y utilidades de texto seguro. */
export const fmtEntero = new Intl.NumberFormat("es-CO", { maximumFractionDigits: 0 });
export const fmt1 = new Intl.NumberFormat("es-CO", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
export const fmt2 = new Intl.NumberFormat("es-CO", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** Pesos en millones: $ 842,5 M (o miles de millones si aplica). */
export function fmtCOP(v) {
  if (v >= 1e9) return "$ " + fmt2.format(v / 1e9) + " mil M";
  return "$ " + fmt1.format(v / 1e6) + " M";
}

/** Escapa texto antes de insertarlo como HTML (los nombres vienen de la base de datos). */
export const esc = s => String(s ?? "").replace(/[&<>"']/g, ch =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));

export const ESTADOS = {
  critico: { txt: "Crítico", icono: "▲" },
  moderado: { txt: "Moderado", icono: "■" },
  bajo: { txt: "Bajo", icono: "●" },
  sin_dato: { txt: "Sin dato", icono: "–" },
};
