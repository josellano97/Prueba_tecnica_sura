"""Filtros de presentación del análisis: formato, color según sentido del KPI y gráficos SVG del servidor."""
import math

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

from ..servicios import formato as F

register = template.Library()


def escala_eje(valores):
    """Límites "redondos" del eje Y alrededor de los datos (no desde cero), con unas 5 divisiones.
    Solo para líneas: así se ven los movimientos. Las barras siempre parten de cero."""
    vs = [float(v) for v in valores if v is not None]
    if not vs:
        return 0.0, 1.0, 0.25
    mn, mx = min(vs), max(vs)
    if mx == mn:
        d = abs(mx) * 0.1 or 1.0
        mn, mx = mn - d, mx + d
    holgura = (mx - mn) * 0.12
    mn, mx = mn - holgura, mx + holgura
    bruto = (mx - mn) / 5
    mag = 10 ** math.floor(math.log10(bruto))
    paso = next(f * mag for f in (1, 2, 2.5, 5, 10) if f * mag >= bruto)
    lo = math.floor(mn / paso) * paso
    if lo < 0 <= min(vs):                        # nunca un eje negativo para datos positivos
        lo = 0.0
    hi = math.ceil(mx / paso - 1e-9) * paso
    return lo, hi, paso


def _texto_eje(formato, v, paso):
    if formato == "cop":
        return F.cop(v)
    if formato == "pct1":
        return F.pct(v, 0 if paso >= 0.01 else 1)
    dec = 0 if paso >= 1 else (1 if paso >= 0.1 else 2)
    return F.num(v, dec)


def _etiqueta_mes(p, i):
    return escape(F.mes(p, True))[:3] + (" " + str(p.year)[2:] if p.month == 1 or i == 0 else "")


@register.filter
def fnum(v, dec=0):
    return F.num(v, int(dec))


@register.filter
def fdelta(v, dec=0):
    return F.delta(v, int(dec))


@register.filter
def fpct(v, dec=1):
    return F.pct(v, int(dec))


@register.filter
def fvar(v):
    """Variación relativa con signo: +12,3 %."""
    return F.pct(v, 1, signo=True)


@register.filter
def fcop(v, signo=False):
    return F.cop(v, bool(signo))


@register.filter
def fmes(p, corto=False):
    return F.mes(p, bool(corto))


@register.filter
def kpi_valor(comp):
    return F.valor_kpi(comp["kpi"], comp["valor"])


@register.filter
def kpi_ref(comp, clave):
    return F.valor_kpi(comp["kpi"], comp["referencias"][clave]["valor"])


@register.filter
def kpi_fmt(valor, kpi):
    """Cualquier valor con el formato del KPI (p. ej. el año corrido)."""
    return F.valor_kpi(kpi, valor)


@register.filter
def kpi_unidad(kpi):
    """Unidad para mostrar junto al valor, sin repetir lo que el formato ya dice ("$", "%")."""
    if kpi.formato == "cop":
        return ""
    if kpi.formato == "pct1":
        return kpi.unidad.removeprefix("% ").removeprefix("%").strip()
    return kpi.unidad


ESTADOS_CORTOS = {
    "peor": "Peor que lo habitual", "mejor": "Mejor que lo habitual", "normal": "En su rango habitual",
    "neutro": "Descriptivo", "foto": "Foto al corte", "sin_referencia": "Sin historial",
}


@register.filter
def estado_corto(juicio):
    return ESTADOS_CORTOS.get(juicio.get("estado"), "")


@register.filter
def clase_var(variacion, kpi):
    """'peor' / 'mejor' / 'neutro' según el sentido del KPI (no se juzga lo descriptivo)."""
    if variacion is None or kpi.sentido == "neutro" or abs(variacion) < 1e-9:
        return "neutro"
    sube = variacion > 0
    return "peor" if (sube and kpi.sentido == "baja") or (not sube and kpi.sentido == "sube") else "mejor"


@register.filter
def color_comp(c, clave):
    """Color de una comparación SOLO si la diferencia es significativa (si no, gris: no se sugiere un juicio).

    Tasa y casos: prueba de Poisson de esa comparación (p < 0,05).
    Otros KPIs: solo la comparación con los 12 meses previos, cuando el juicio del KPI es significativo.
    """
    kpi = c["kpi"]
    variacion = c["referencias"][clave]["variacion"]
    prueba = c["pruebas"].get(clave) if c.get("pruebas") else None
    if prueba is not None:
        significativo = prueba["significancia"] in ("muy_alta", "alta", "moderada")
    else:
        significativo = clave == "promedio_12m" and c["juicio"]["estado"] in ("peor", "mejor")
    return clase_var(variacion, kpi) if significativo else "neutro"


@register.filter
def flecha(variacion):
    if variacion is None or abs(variacion) < 1e-9:
        return "="
    return "▲" if variacion > 0 else "▼"


@register.filter
def get(d, k):
    return d.get(k) if hasattr(d, "get") else None


@register.filter
def ancho(v, maximo):
    """Porcentaje 0–100 para barras en tablas."""
    try:
        valor = max(0.0, min(100.0, abs(v) / maximo * 100)) if maximo else 0.0
    except (TypeError, ZeroDivisionError):
        valor = 0.0
    return f"{valor:.1f}"            # siempre con punto: CSS no acepta coma decimal


@register.simple_tag
def sparkline(valores, ancho_px=120, alto_px=32):
    """Mini-tendencia; el último punto se resalta. Valores None se omiten."""
    pts = [(i, v) for i, v in enumerate(valores) if v is not None]
    if len(pts) < 2:
        return ""
    vs = [v for _, v in pts]
    mn, mx = min(vs), max(vs)
    rango = (mx - mn) or 1
    n = len(valores) - 1 or 1
    xy = [(2 + i * (ancho_px - 4) / n, alto_px - 3 - (v - mn) / rango * (alto_px - 6)) for i, v in pts]
    camino = " ".join(f"{x:.1f},{y:.1f}" for x, y in xy)
    ux, uy = xy[-1]
    return mark_safe(
        f'<svg class="sparkline" viewBox="0 0 {ancho_px} {alto_px}" width="{ancho_px}" height="{alto_px}" aria-hidden="true">'
        f'<polyline points="{camino}" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>'
        f'<circle cx="{ux:.1f}" cy="{uy:.1f}" r="2.6" fill="currentColor"/></svg>')


@register.simple_tag
def grafico_tendencia(serie, clave="tasa", referencia=None, alto=220):
    """Serie de 24 meses con promedio de referencia y marcas de anomalías (pico/caída estadísticos)."""
    datos = [(s["periodo"], s.get(clave), s.get("anomalia")) for s in serie]
    valores = [v for _, v, _ in datos if v is not None]
    if len(valores) < 2:
        return ""
    W, H, m = 760, alto, {"t": 14, "r": 12, "b": 28, "l": 44}
    mn, mx, paso = escala_eje(valores + ([referencia] if referencia else []))
    n = len(datos) - 1
    x = lambda i: m["l"] + i * (W - m["l"] - m["r"]) / n  # noqa: E731
    y = lambda v: m["t"] + (H - m["t"] - m["b"]) * (1 - (v - mn) / (mx - mn))  # noqa: E731
    g = []
    k = 0
    while mn + k * paso <= mx + paso / 2:
        v = mn + k * paso
        g.append(f'<line x1="{m["l"]}" x2="{W - m["r"]}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="rejilla"/>'
                 f'<text x="{m["l"] - 6}" y="{y(v) + 4:.1f}" text-anchor="end" class="eje">{_texto_eje("decimal2", v, paso)}</text>')
        k += 1
    for i, (p, _, _) in enumerate(datos):                  # todos los meses con etiqueta
        g.append(f'<text x="{x(i):.1f}" y="{H - 8}" text-anchor="middle" class="eje">{_etiqueta_mes(p, i)}</text>')
    if referencia:
        g.append(f'<line x1="{m["l"]}" x2="{W - m["r"]}" y1="{y(referencia):.1f}" y2="{y(referencia):.1f}" class="referencia"/>')
    pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, (_, v, _) in enumerate(datos) if v is not None)
    g.append(f'<polyline points="{pts}" class="linea"/>')
    for i, (p, v, anom) in enumerate(datos):
        if v is None:
            continue
        titulo = f"{F.mes(p)}: {F.num(v, 2)}" + (" — pico estadístico" if anom == "pico" else " — caída estadística" if anom == "caida" else "")
        clase = f"punto {anom}" if anom else "punto"
        r = 5 if anom else (4 if i == n else 2.6)
        g.append(f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="{r}" class="{clase}"><title>{escape(titulo)}</title></circle>')
    return mark_safe(f'<svg class="grafico-serie" viewBox="0 0 {W} {H}" role="img" aria-label="Tendencia de 24 meses">{"".join(g)}</svg>')


@register.simple_tag
def sparkline_kpi(c, ancho_px=260, alto_px=46):
    """Mini tendencia de 12 meses de un KPI con la línea punteada de sus 12 meses previos. Eje desde el mínimo."""
    valores = c.get("serie_valores") or []
    ref = c["referencias"]["promedio_12m"]["valor"] if c.get("referencias") else None
    pts = [(i, float(v)) for i, v in enumerate(valores) if v is not None]
    if len(pts) < 2:
        return ""
    mn, mx, _ = escala_eje([v for _, v in pts] + ([ref] if ref is not None else []))
    n = len(valores) - 1 or 1
    x = lambda i: 4 + i * (ancho_px - 8) / n  # noqa: E731
    y = lambda v: 4 + (alto_px - 8) * (1 - (v - mn) / (mx - mn))  # noqa: E731
    g = []
    if ref is not None:
        g.append(f'<line x1="4" x2="{ancho_px - 4}" y1="{y(float(ref)):.1f}" y2="{y(float(ref)):.1f}" class="ref"/>')
    puntos = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in pts)
    g.append(f'<polyline points="{puntos}" class="linea"/>')
    ux, uy = x(pts[-1][0]), y(pts[-1][1])
    g.append(f'<circle cx="{ux:.1f}" cy="{uy:.1f}" r="3.2" class="ultimo"/>')
    return mark_safe(f'<svg class="sparkline-kpi" viewBox="0 0 {ancho_px} {alto_px}" aria-hidden="true">{"".join(g)}</svg>')


@register.simple_tag
def grafico_kpi(c, alto=300):
    """Tendencia de 24 meses de un KPI para la vista ampliada: eje desde el mínimo, todos los meses, línea del
    promedio de los 12 meses previos, valor de cada punto al pasar el mouse y el último valor rotulado."""
    kpi = c["kpi"]
    serie = [(s["periodo"], s["valor"]) for s in c.get("serie") or []]
    valores = [float(v) for _, v in serie if v is not None]
    if len(valores) < 2:
        return ""
    ref = c["referencias"]["promedio_12m"]["valor"]
    W, H, m = 820, alto, {"t": 22, "r": 18, "b": 34, "l": 78}
    mn, mx, paso = escala_eje(valores + ([float(ref)] if ref is not None else []))
    n = len(serie) - 1
    x = lambda i: m["l"] + i * (W - m["l"] - m["r"]) / n  # noqa: E731
    y = lambda v: m["t"] + (H - m["t"] - m["b"]) * (1 - (float(v) - mn) / (mx - mn))  # noqa: E731
    g = []
    k = 0
    while mn + k * paso <= mx + paso / 2:
        v = mn + k * paso
        g.append(f'<line x1="{m["l"]}" x2="{W - m["r"]}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="rejilla"/>'
                 f'<text x="{m["l"] - 8}" y="{y(v) + 4:.1f}" text-anchor="end" class="eje">{_texto_eje(kpi.formato, v, paso)}</text>')
        k += 1
    for i, (p, _) in enumerate(serie):
        g.append(f'<text x="{x(i):.1f}" y="{H - 10}" text-anchor="middle" class="eje">{_etiqueta_mes(p, i)}</text>')
    if ref is not None:
        # la línea del promedio se explica en la leyenda y su valor está en la tabla (un rótulo aquí tapaba la serie)
        g.append(f'<line x1="{m["l"]}" x2="{W - m["r"]}" y1="{y(ref):.1f}" y2="{y(ref):.1f}" class="referencia">'
                 f'<title>Promedio de los 12 meses previos: {escape(F.valor_kpi(kpi, ref))}</title></line>')
    tramos, actual = [], []
    for i, (p, v) in enumerate(serie):                     # la línea se corta en los meses sin dato
        if v is None:
            if actual:
                tramos.append(actual)
            actual = []
        else:
            actual.append(f"{x(i):.1f},{y(v):.1f}")
    if actual:
        tramos.append(actual)
    for t in tramos:
        g.append(f'<polyline points="{" ".join(t)}" class="linea"/>')
    for i, (p, v) in enumerate(serie):
        if v is None:
            continue
        ultimo = i == n
        g.append(f'<g class="punto-kpi{" ultimo" if ultimo else ""}"><circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="12" class="zona"/>'
                 f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="{5 if ultimo else 3.4}" class="punto"/>'
                 f'<title>{escape(F.mes(p))}: {escape(F.valor_kpi(kpi, v))}</title></g>')
    uv = serie[-1][1]
    if uv is not None:
        g.append(f'<text x="{x(n) - 8:.1f}" y="{y(uv) - 12:.1f}" text-anchor="end" class="valor-ultimo">'
                 f'{escape(F.valor_kpi(kpi, uv))}</text>')
    return mark_safe(f'<svg class="grafico-kpi" viewBox="0 0 {W} {H}" role="img" '
                     f'aria-label="{escape(kpi.nombre)}: tendencia de 24 meses">{"".join(g)}</svg>')


@register.simple_tag
def grafico_pareto(curva, corte=0.8, alto=150):
    """Curva de Pareto: % acumulado vs % de elementos, con la línea del 80 %."""
    if not curva:
        return ""
    W, H, m = 360, alto, 26
    n = len(curva)
    x = lambda i: m + i / n * (W - 2 * m)  # noqa: E731
    y = lambda v: H - m - v * (H - 2 * m)  # noqa: E731
    pts = f"{x(0):.1f},{y(0):.1f} " + " ".join(f"{x(i + 1):.1f},{y(v):.1f}" for i, v in enumerate(curva))
    idx = next((i for i, v in enumerate(curva) if v >= corte), n - 1) + 1
    return mark_safe(
        f'<svg class="grafico-pareto" viewBox="0 0 {W} {H}" role="img" aria-label="Curva de concentración">'
        f'<line x1="{m}" x2="{W - m}" y1="{y(corte):.1f}" y2="{y(corte):.1f}" class="referencia"/>'
        f'<line x1="{x(idx):.1f}" x2="{x(idx):.1f}" y1="{y(0):.1f}" y2="{y(corte):.1f}" class="referencia"/>'
        f'<polyline points="{pts}" class="linea"/>'
        f'<text x="{x(idx) + 4:.1f}" y="{y(0) - 6:.1f}" class="eje">{F.pct(idx / n, 0)} de los clientes</text>'
        f'<text x="{m}" y="{y(corte) - 5:.1f}" class="eje">{F.pct(corte, 0)} del total</text>'
        f'<line x1="{m}" x2="{W - m}" y1="{y(0):.1f}" y2="{y(0):.1f}" class="rejilla"/></svg>')
