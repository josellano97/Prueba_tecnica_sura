"""Formato de números en español (Colombia) para los textos generados en el servidor."""
from datetime import date

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]
MESES_C = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def _miles(txt: str) -> str:
    entero, _, dec = txt.partition(".")
    signo = "-" if entero.startswith("-") else ""
    entero = entero.lstrip("-")
    grupos = []
    while len(entero) > 3:
        grupos.insert(0, entero[-3:])
        entero = entero[:-3]
    grupos.insert(0, entero)
    return signo + ".".join(grupos) + ("," + dec if dec else "")


def num(v, dec=0) -> str:
    if v is None:
        return "–"
    v = float(v)
    txt = _miles(f"{abs(v):.{dec}f}")
    return ("−" + txt) if v < 0 and txt.strip("0,.") else txt


def pct(v, dec=1, signo=False) -> str:
    if v is None:
        return "–"
    v = float(v)
    s = num(abs(v) * 100 if signo else v * 100, dec)
    if signo:
        s = ("+" if v >= 0 else "−") + s
    return s + " %"


def cop(v, signo=False) -> str:
    if v is None:
        return "–"
    v = float(v)
    s = "−" if v < 0 else ("+" if signo and v > 0 else "")
    v = abs(v)
    if v >= 1e9:
        return f"{s}$ " + num(v / 1e9, 2) + " mil M"
    return f"{s}$ " + num(v / 1e6, 1) + " M"


def delta(v, dec=0) -> str:
    """Número con signo explícito (+ / −)."""
    if v is None:
        return "–"
    return ("+" if v > 0 else "−" if v < 0 else "") + num(abs(v), dec)


def mes(p: date, corto=False) -> str:
    return f"{MESES_C[p.month - 1]} {p.year}" if corto else f"{MESES[p.month - 1]} de {p.year}"


def valor_kpi(kpi, v) -> str:
    if v is None:
        return "–"
    return {"entero": lambda: num(v), "decimal1": lambda: num(v, 1), "decimal2": lambda: num(v, 2),
            "conteo": lambda: num(v) if float(v).is_integer() else num(v, 1),
            "pct1": lambda: pct(v), "cop": lambda: cop(v)}[kpi.formato]()
