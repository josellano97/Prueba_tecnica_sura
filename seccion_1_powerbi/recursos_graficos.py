"""
Genera los recursos gráficos del reporte: fondos de página (con el "cromo" del
encabezado, la franja de filtros y el logo SURA integrados, igual que el patrón del
Power BI de referencia) e iconos de navegación en azul SURA.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ESCALA = 2                     # fondos a 2560x1440 para nitidez (el reporte es 1280x720)
W, H = 1280, 720
AZUL = (0, 85, 160)
CIAN = (0, 171, 196)
LIENZO = (233, 236, 241)
BLANCO = (255, 255, 255)
BORDE = (220, 225, 232)


def _s(v):
    return int(round(v * ESCALA))


def _tarjeta(d: ImageDraw.ImageDraw, x, y, w, h, r=10):
    d.rounded_rectangle([_s(x), _s(y), _s(x + w), _s(y + h)], radius=_s(r), fill=BLANCO, outline=BORDE, width=2)


def recolorear(origen: Path, destino: Path, color=AZUL, tam=160):
    """Pasa un icono a azul SURA conservando transparencia y los detalles blancos."""
    im = Image.open(origen).convert("RGBA")
    px = im.load()
    for yy in range(im.height):
        for xx in range(im.width):
            r, g, b, a = px[xx, yy]
            if a and not (r > 215 and g > 215 and b > 215):
                px[xx, yy] = (*color, a)
    im.thumbnail((tam, tam), Image.LANCZOS)
    im.save(destino)
    return im


def icono_info(destino: Path, tam=160):
    im = Image.new("RGBA", (tam * 4, tam * 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse([8, 8, tam * 4 - 8, tam * 4 - 8], fill=AZUL)
    c = tam * 2
    d.ellipse([c - 34, 110, c + 34, 178], fill=BLANCO)
    d.rounded_rectangle([c - 30, 220, c + 30, tam * 4 - 110], radius=18, fill=BLANCO)
    im = im.resize((tam, tam), Image.LANCZOS)
    im.save(destino)
    return im


def _pegar(fondo, icono_path: Path, x, y, lado):
    ic = Image.open(icono_path).convert("RGBA").resize((_s(lado), _s(lado)), Image.LANCZOS)
    fondo.alpha_composite(ic, (_s(x), _s(y)))


def _logo(fondo, logo_path: Path, x, y, alto):
    lg = Image.open(logo_path).convert("RGBA")
    ancho = alto * lg.width / lg.height
    lg = lg.resize((_s(ancho), _s(alto)), Image.LANCZOS)
    fondo.alpha_composite(lg, (_s(x), _s(y)))
    return ancho


def fondo_contenido(destino: Path, logo: Path, iconos: dict[str, Path], adelante_activo=True, atras_activo=True):
    """Fondo de páginas de análisis: encabezado + navegación + franja de filtros."""
    im = Image.new("RGBA", (_s(W), _s(H)), (*LIENZO, 255))
    d = ImageDraw.Draw(im)
    _tarjeta(d, 6, 6, 1128, 68)             # encabezado (logo, título, filtros globales)
    _tarjeta(d, 1140, 6, 134, 68)           # navegación
    _tarjeta(d, 6, 80, 1268, 66)            # franja de filtros aplicados y filtros de página
    _logo(im, logo, 16, 14, 52)
    d.line([_s(156), _s(16), _s(156), _s(64)], fill=BORDE, width=2)
    _pegar(im, iconos["inicio"], 1150, 22, 36)
    _pegar(im, iconos["atras"] if atras_activo else iconos["atras_inactivo"], 1194, 22, 36)
    _pegar(im, iconos["adelante"] if adelante_activo else iconos["adelante_inactivo"], 1236, 22, 36)
    d.line([_s(1188), _s(24), _s(1188), _s(56)], fill=BORDE, width=2)
    _pegar(im, iconos["mas_filtros"], 1182, 91, 40)
    _pegar(im, iconos["borrar_filtros"], 1228, 91, 40)
    im.convert("RGB").save(destino, quality=95)


def fondo_panel(destino: Path, logo: Path, iconos: dict[str, Path]):
    """Fondo del panel de filtros y de la página de información: encabezado + gran tarjeta."""
    im = Image.new("RGBA", (_s(W), _s(H)), (*LIENZO, 255))
    d = ImageDraw.Draw(im)
    _tarjeta(d, 6, 6, 1182, 68)
    _tarjeta(d, 1194, 6, 80, 68)
    _tarjeta(d, 6, 80, 1268, 634)
    _logo(im, logo, 16, 14, 52)
    d.line([_s(156), _s(16), _s(156), _s(64)], fill=BORDE, width=2)
    _pegar(im, iconos["atras"], 1216, 22, 36)
    im.convert("RGB").save(destino, quality=95)


def fondo_inicio(destino: Path, foto: Path, logo: Path, iconos_nav: list[Path], ico_cal: Path):
    """Portada: foto a la derecha con degradado a blanco (patrón de la referencia)."""
    im = Image.new("RGBA", (_s(W), _s(H)), (*BLANCO, 255))
    ft = Image.open(foto).convert("RGBA")
    alto = _s(H)
    ancho = int(ft.width * alto / ft.height)
    ft = ft.resize((ancho, alto), Image.LANCZOS)
    x0 = _s(W) - ancho
    im.alpha_composite(ft, (x0, 0))
    # degradado: blanco sólido hasta x=470 y transición suave hasta x=760
    grad = Image.new("L", (_s(W), 1), 0)
    for x in range(_s(W)):
        xx = x / ESCALA
        a = 255 if xx < 470 else max(0, int(255 * (1 - (xx - 470) / 290)))
        grad.putpixel((x, 0), a)
    capa = Image.new("RGBA", (_s(W), _s(H)), (*BLANCO, 255))
    capa.putalpha(grad.resize((_s(W), _s(H))))
    im.alpha_composite(capa)
    d = ImageDraw.Draw(im)
    # franja de marca inferior
    d.rectangle([0, _s(H - 6), _s(W), _s(H)], fill=AZUL)
    d.rectangle([0, _s(H - 6), _s(260), _s(H)], fill=CIAN)
    _logo(im, logo, 40, 30, 70)
    for i, p in enumerate(iconos_nav):
        _pegar(im, p, 44, 280 + i * 64, 44)
    _pegar(im, ico_cal, 44, 600, 40)
    im.convert("RGB").save(destino, quality=95)


def generar(carpeta_recursos: Path, raiz: Path, iconos_ref: Path) -> dict[str, str]:
    """Crea todos los recursos y devuelve {clave: nombre_de_archivo}."""
    carpeta_recursos.mkdir(parents=True, exist_ok=True)
    tmp = carpeta_recursos
    logo = raiz / "Logo_sura.png"
    foto = raiz / "Logo_pantalla_inicial_power_bi_nueva_version.jpg"
    ic = {}
    fuentes = {
        "inicio": "Home5842409368456178.png", "atras": "Atras_Activo9926502000793769.png",
        "adelante": "Adelante_Activo5958631615535022.png", "mas_filtros": "Mas_Filtros07028228317737661.png",
        "borrar_filtros": "Borrar_Filtros4603367731735426.png", "calendario": "calendario23632411076822222.png",
        "kpi": "Radar5417021712296308.png", "barras": "Barras_y_Lineas_26856589761745286.png",
        "prevencion": "entrenamiento-avanzado08092174555859355.png",
    }
    for clave, archivo in fuentes.items():
        ic[clave] = tmp / f"ico_{clave}.png"
        recolorear(iconos_ref / archivo, ic[clave])
    for clave, base in [("atras_inactivo", "atras"), ("adelante_inactivo", "adelante")]:
        ic[clave] = tmp / f"ico_{clave}.png"
        recolorear(iconos_ref / fuentes[base], ic[clave], color=(170, 182, 196))
    ic["info"] = tmp / "ico_info.png"
    icono_info(ic["info"])

    salida = {}
    variantes = {"fondo_p1.jpg": (False, True), "fondo_p2.jpg": (True, True), "fondo_p3.jpg": (True, False)}
    for nombre, (atras, adelante) in variantes.items():
        fondo_contenido(tmp / nombre, logo, ic, adelante_activo=adelante, atras_activo=atras)
        salida[nombre] = nombre
    fondo_panel(tmp / "fondo_panel.jpg", logo, ic)
    salida["fondo_panel.jpg"] = "fondo_panel.jpg"
    fondo_inicio(tmp / "fondo_inicio.jpg", foto, logo, [ic["kpi"], ic["barras"], ic["prevencion"], ic["info"]],
                 ic["calendario"])
    salida["fondo_inicio.jpg"] = "fondo_inicio.jpg"
    # los iconos ya quedaron integrados en los fondos: se eliminan para no registrar recursos sin uso
    for p in ic.values():
        p.unlink(missing_ok=True)
    return salida
