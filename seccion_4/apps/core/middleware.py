"""Cabeceras de seguridad que Django no agrega por sí solo."""
from urllib.parse import urlsplit

from django.conf import settings

# Política de contenido: solo scripts y recursos del propio dominio (sin CDN ni scripts en línea).
# style-src permite atributos style en línea porque los gráficos SVG y el admin de Django los usan.
CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "font-src 'self'",
    "connect-src 'self'{agente}",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])


class CabecerasSeguridadMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        url = urlsplit(getattr(settings, "AGENTE_CHAT_URL", ""))
        origen = f" {url.scheme}://{url.netloc}" if url.scheme == "https" and url.netloc else ""
        self.csp = CSP.format(agente=origen)       # el navegador solo puede hablar con la app y con el agente

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault("Content-Security-Policy", self.csp)
        response.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
        usuario = getattr(request, "user", None)
        if usuario is not None and usuario.is_authenticated:
            # Las páginas internas contienen datos de clientes: no se guardan en caché compartida.
            response.setdefault("Cache-Control", "private, no-store")
        return response
