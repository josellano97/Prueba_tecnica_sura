"""
Prueba de extremo a extremo con un navegador real (Microsoft Edge vía Playwright).

Recorre la aplicación como lo haría cada rol: login correcto/incorrecto, tablero y filtros,
acceso denegado por URL directa, administración de usuarios, cierre de sesión, vista móvil y
modo oscuro. Falla si aparece cualquier error de JavaScript o violación de la política CSP.

Requisitos (solo desarrollo):
    pip install -r requirements-dev.txt
    DEMO_PASSWORD=... python manage.py cargar_datos_demo --usuarios-demo
    python manage.py runserver 127.0.0.1:8765
    E2E_PASSWORD=... python tests_e2e/prueba_navegador.py [--capturas carpeta]
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

BASE = os.environ.get("E2E_URL", "http://127.0.0.1:8765")
CLAVE = os.environ.get("E2E_PASSWORD", "")
resultados: list[tuple[str, bool, str]] = []


def verificar(nombre, condicion, detalle=""):
    resultados.append((nombre, bool(condicion), detalle))
    print(f"  [{'OK' if condicion else 'FALLA'}] {nombre} {detalle}")


def ingresar(page: Page, usuario: str, clave: str = CLAVE):
    page.goto(f"{BASE}/cuentas/ingresar/")
    page.fill("#id_username", usuario)
    page.fill("#id_password", clave)
    page.click("button[type=submit]")


def salir(page: Page):
    page.click("[data-menu-usuario]")
    page.click("text=Cerrar sesión")
    page.wait_for_url(re.compile(r"/cuentas/ingresar/"))


def kpi_casos(page: Page) -> int:
    return int(re.sub(r"\D", "", page.inner_text("#kpi-casos .valor")))


def casos_api(page: Page, params="") -> int:
    """Valor esperado leído de la API del servidor en la misma sesión (sirve con cualquier fuente de datos)."""
    return page.evaluate(f"fetch('/tablero/api/datos/{params}').then(r => r.json()).then(d => d.kpis.actual.casos)")


def al_tablero(page: Page):
    """Tras el login se llega al análisis gerencial; desde ahí se abre el tablero."""
    page.wait_for_url(re.compile(r"/analisis/"))
    page.goto(f"{BASE}/tablero/")
    esperar_datos(page)


def esperar_datos(page: Page):
    page.wait_for_selector("#contenido-tablero[aria-busy='false']")
    page.wait_for_selector("#kpi-casos .valor")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capturas", type=Path, default=None)
    args = ap.parse_args()
    if not CLAVE:
        sys.exit("Defina E2E_PASSWORD con la contraseña de los usuarios demo.")
    capt = args.capturas
    if capt:
        capt.mkdir(parents=True, exist_ok=True)
    errores_js: list[str] = []

    with sync_playwright() as p:
        nav = p.chromium.launch(channel="msedge", headless=True)
        ctx = nav.new_context(viewport={"width": 1440, "height": 1000}, locale="es-CO", accept_downloads=True)
        page = ctx.new_page()
        page.on("pageerror", lambda e: errores_js.append(f"pageerror: {e}"))
        # Los 403 de las navegaciones a URLs prohibidas son intencionales; cualquier otro error de recurso se reporta.
        page.on("response", lambda r: errores_js.append(f"HTTP {r.status}: {r.url}")
                if r.status >= 400 and r.request.resource_type != "document" else None)
        page.on("console", lambda m: errores_js.append(f"console: {m.text}")
                if m.type == "error" and "Failed to load resource" not in m.text else None)

        print("== Autenticación")
        page.goto(f"{BASE}/tablero/")
        verificar("sin sesión redirige al login", "/cuentas/ingresar/" in page.url and "next=" in page.url)
        if capt:
            page.screenshot(path=capt / "01_login.png")
        ingresar(page, "analista_demo", "clave-equivocada")
        verificar("login incorrecto muestra error", page.is_visible("text=Usuario o contraseña incorrectos"))
        if capt:
            page.screenshot(path=capt / "02_login_error.png")
        ingresar(page, "analista_demo")
        page.wait_for_url(re.compile(r"/analisis/"))
        verificar("login correcto abre el análisis gerencial", page.is_visible("#kpis"))
        page.goto(f"{BASE}/tablero/")
        esperar_datos(page)

        print("== Tablero (rol Usuario)")
        base = kpi_casos(page)
        esperado = casos_api(page)
        verificar("KPI casos = cálculo del servidor", base == esperado, f"{base} vs {esperado}")
        verificar("resumen en lenguaje natural", f"{base:,}".replace(",", ".") + " casos" in page.inner_text("#resumen"))
        verificar("top 10 con 10 filas", page.locator("#tabla-top tbody tr").count() == 10)
        verificar("gráfico de tendencia con 12 puntos", page.locator("#g-tendencia circle").count() == 12)
        if capt:
            page.screenshot(path=capt / "03_tablero_usuario.png", full_page=True)
        page.select_option("#f-sector", label="Construcción")
        esperar_datos(page)
        con_sector = kpi_casos(page)
        verificar("filtro sector actualiza KPI", con_sector < base, f"{base} -> {con_sector}")
        verificar("filtro queda en la URL", "sector=" in page.url)
        verificar("tabla solo muestra el sector filtrado",
                  all("Construcción" in t for t in page.locator("#tabla-top .cliente small").all_inner_texts()))
        page.click(".chip[data-clase='4']")
        esperar_datos(page)
        verificar("filtro de clase actualiza KPI", kpi_casos(page) <= con_sector)
        page.select_option("#f-mes", "2026-03")
        esperar_datos(page)
        ultimo_eje = page.locator("#g-tendencia text").evaluate_all("els => els.map(e => e.textContent)")
        verificar("cambio de mes mueve la tendencia", any(t.startswith("mar") for t in ultimo_eje))
        page.click("#seg-metrica button[data-metrica='tasa']")
        verificar("selector de métrica cambia el título", "Tasa" in page.inner_text("#t-tendencia"))
        page.click("#seg-top button[data-periodo='12m']")
        verificar("tabla 12 meses (rango de meses y sin columna de variación)",
                  " a " in page.inner_text("#sub-top") and "Vs mes ant." not in page.inner_text("#tabla-top thead"))
        with page.expect_download() as d:
            page.click("#btn-exportar")
        verificar("exportación CSV descarga archivo", d.value.suggested_filename.endswith(".csv"), d.value.suggested_filename)
        page.click("#btn-limpiar")
        esperar_datos(page)
        verificar("limpiar filtros restablece", kpi_casos(page) == base)
        page.reload()
        esperar_datos(page)
        verificar("recargar conserva el estado", kpi_casos(page) == base)

        print("== Autorización por URL directa (rol Usuario)")
        r = page.goto(f"{BASE}/cuentas/usuarios/")
        verificar("usuarios -> 403", r.status == 403 and page.is_visible("text=No tiene permiso"))
        if capt:
            page.screenshot(path=capt / "04_acceso_denegado.png")
        verificar("menú sin opción Usuarios", page.locator(".lateral-nav a[href='/cuentas/usuarios/']").count() == 0)
        r = page.goto(f"{BASE}/tablero/configuracion/")
        verificar("configuración -> 403", r.status == 403)
        page.goto(f"{BASE}/tablero/")
        salir(page)
        verificar("logout vuelve al login", "/cuentas/ingresar/" in page.url)
        r = page.goto(f"{BASE}/tablero/api/datos/")
        verificar("tras logout la API no entrega datos", r.url.find("/cuentas/ingresar/") >= 0 or r.status == 403)

        print("== Rol Consulta y Coordinador")
        ingresar(page, "consulta_demo")
        al_tablero(page)
        verificar("consulta: sin botón exportar", page.locator("#btn-exportar").count() == 0)
        r = page.goto(f"{BASE}/tablero/exportar/top10.csv")
        verificar("consulta: exportar por URL -> 403", r.status == 403)
        page.goto(f"{BASE}/tablero/")
        salir(page)
        ingresar(page, "coordinador_demo")
        al_tablero(page)
        coords = set(t.split(" · ")[-1] for t in page.locator("#tabla-top .cliente small").all_inner_texts())
        verificar("coordinador: solo sus clientes", len(coords) == 1, str(coords))
        verificar("coordinador: aviso de alcance", "de su cartera" in page.inner_text("#filtros-activos"))
        verificar("coordinador: sin filtro de coordinador", page.locator("#f-coordinador").count() == 0)
        if capt:
            page.screenshot(path=capt / "05_tablero_coordinador.png")
        page.goto(f"{BASE}/analisis/")
        texto = page.inner_text("#resumen")
        verificar("coordinador: análisis limitado a su cartera", "clientes en el alcance" in page.inner_text(".contexto-datos")
                  and "120 clientes" not in page.inner_text(".contexto-datos"))
        r = page.goto(f"{BASE}/analisis/calidad/")
        verificar("coordinador: calidad de datos -> 403", r.status == 403)
        salir(page)

        print("== Análisis gerencial (rol Usuario)")
        ingresar(page, "analista_demo")
        page.wait_for_url(re.compile(r"/analisis/"))
        n = page.locator("#resumen .punto").count()
        verificar("resumen ejecutivo corto (1 a 4 hechos)", 1 <= n <= 4, str(n))
        verificar("resumen muestra los límites de la lectura", "metas" in page.inner_text("#resumen .limites"))
        verificar("6 KPI de nivel 1", page.locator(".kpi-g").count() == 6, str(page.locator(".kpi-g").count()))
        verificar("sin 'cumplimiento' inventado", "cumplimiento" not in page.inner_text("#kpis").lower())
        verificar("qué revisar: solo prioridad alta", page.locator("#alertas .alerta-fila").count() <= 6
                  and "media" not in " ".join(page.locator("#alertas .alerta-fila").all_inner_texts()).lower())
        antes = page.inner_text("#porque .sub")
        with page.expect_navigation():
            page.select_option("#porque select[name=periodo]", "trimestre")      # se envía solo al cambiar
        verificar("por qué cambió: periodo elegible", page.inner_text("#porque .sub") != antes and "periodo=trimestre" in page.url,
                  page.inner_text("#porque .sub"))
        with page.expect_navigation():
            page.select_option("#porque select[name=por]", "cliente")
        verificar("por qué cambió: abrir por cliente", page.locator("#porque table.divergente tbody tr").count() >= 1
                  and "Cliente" in page.inner_text("#porque table.divergente thead"))
        verificar("concentración resumida en 3 bloques", page.locator("#concentracion .tile-conc").count() == 3)
        verificar("tendencia 24 meses", page.locator("#tendencia svg.grafico-serie circle").count() == 24)
        page.locator(".kpi-g").first.click()
        dlg = page.locator("dialog[open]")
        verificar("clic en un KPI abre su vista ampliada (tendencia, comparaciones y cálculo)",
                  dlg.count() == 1 and dlg.locator("svg.grafico-kpi").count() == 1 and "Cálculo" in dlg.inner_text())
        page.keyboard.press("Escape")
        verificar("Escape cierra la vista ampliada", page.locator("dialog[open]").count() == 0)
        if capt:
            page.screenshot(path=capt / "12_analisis.png", full_page=True)
        enlace = page.locator("#alertas a:has-text('Abrir diagnóstico')").first
        if enlace.count():
            enlace.click()
            verificar("alerta lleva al diagnóstico", "/analisis/diagnostico/" in page.url)
        page.goto(f"{BASE}/analisis/diagnostico/?dim=sector")
        page.locator("table.diagnostico tbody tr td a").first.click()
        verificar("drill-down nivel 2 (clientes del sector)", "Sector:" in page.inner_text(".miga"))
        page.locator("table.diagnostico tbody tr td a").first.click()
        verificar("drill-down nivel 3 (cliente y sus casos)", page.is_visible("text=Evolución mensual") and page.locator(".miga a").count() == 2)
        if capt:
            page.screenshot(path=capt / "13_diagnostico_cliente.png", full_page=True)
        page.locator(".miga a").first.click()
        verificar("volver al total sin perder el contexto", page.locator("table.diagnostico").count() == 1)
        page.goto(f"{BASE}/analisis/metodologia/")
        verificar("diccionario de KPIs y faltantes", page.is_visible("text=Diccionario de indicadores") and page.is_visible("text=información faltante"))
        page.goto(f"{BASE}/analisis/calidad/")
        verificar("calidad de datos con hallazgos", page.locator("table.tabla tbody tr").count() >= 1)
        page.goto(f"{BASE}/tablero/")
        salir(page)

        print("== Administración (rol Administrador)")
        ingresar(page, "admin_demo")
        al_tablero(page)
        page.click(".lateral-nav a[href='/cuentas/usuarios/']")
        verificar("lista de usuarios", page.locator("table.tabla tbody tr").count() >= 4)
        if capt:
            page.screenshot(path=capt / "06_usuarios.png")
        nuevo = f"e2e_{int(time.time())}"  # único por ejecución: la prueba se puede repetir
        page.click("text=Nuevo usuario")
        page.fill("#id_username", nuevo)
        page.fill("#id_email", f"{nuevo}@empresa-ejemplo.co")
        page.fill("#id_first_name", "Prueba")
        page.fill("#id_last_name", "Navegador")
        page.fill("#id_contrasena1", "Clave-E2E-segura-01")
        page.fill("#id_contrasena2", "Clave-E2E-segura-01")
        page.check("label.casilla:has-text('Consulta') input")
        if capt:
            page.screenshot(path=capt / "07_usuario_nuevo.png", full_page=True)
        page.click("button:has-text('Crear usuario')")
        verificar("crear usuario muestra confirmación", page.is_visible("text=creado correctamente"))
        fila = page.locator("tr", has_text=nuevo)
        page.once("dialog", lambda dlg: dlg.accept())
        fila.locator("button:has-text('Desactivar')").click()
        verificar("desactivar usuario", page.is_visible("text=desactivado") and
                  page.locator("tr", has_text=nuevo).locator(".estado-inactivo").count() == 1)
        page.click(".lateral-nav a[href='/cuentas/roles/']")
        verificar("matriz de roles", page.is_visible("text=Ver el tablero de monitoreo"))
        if capt:
            page.screenshot(path=capt / "08_roles.png", full_page=True)
        page.click(".lateral-nav a[href='/tablero/configuracion/']")
        verificar("configuración accesible", page.is_visible("text=Clasificación de clientes"))
        r = page.goto(f"{BASE}/admin/")
        verificar("admin de Django accesible para staff", r.status == 200)
        page.goto(f"{BASE}/tablero/")
        salir(page)
        ingresar(page, nuevo, "Clave-E2E-segura-01")
        verificar("usuario desactivado no puede ingresar", page.is_visible("text=Usuario o contraseña incorrectos"))

        print("== Responsive y modo oscuro")
        movil = nav.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        pm = movil.new_page()
        pm.on("pageerror", lambda e: errores_js.append(f"pageerror móvil: {e}"))
        ingresar(pm, "analista_demo")
        al_tablero(pm)
        ancho = pm.evaluate("document.documentElement.scrollWidth")
        verificar("móvil sin desbordamiento horizontal", ancho <= 390, f"scrollWidth={ancho}")
        verificar("móvil: menú lateral oculto", not pm.locator("#lateral").is_visible() or
                  pm.evaluate("getComputedStyle(document.getElementById('lateral')).transform") != "none")
        pm.click("[data-abrir-lateral]")
        pm.wait_for_timeout(300)
        verificar("móvil: botón abre el menú", "abierto" in pm.get_attribute("#lateral", "class"))
        if capt:
            pm.screenshot(path=capt / "09_movil_menu.png")
        pm.keyboard.press("Escape")
        pm.wait_for_timeout(300)
        verificar("móvil: Escape cierra el menú", "abierto" not in (pm.get_attribute("#lateral", "class") or ""))
        if capt:
            pm.screenshot(path=capt / "10_movil.png", full_page=True)
        oscuro = nav.new_context(viewport={"width": 1440, "height": 1000}, color_scheme="dark")
        po = oscuro.new_page()
        po.on("pageerror", lambda e: errores_js.append(f"pageerror oscuro: {e}"))
        ingresar(po, "analista_demo")
        al_tablero(po)
        fondo = po.evaluate("getComputedStyle(document.body).backgroundColor")
        verificar("modo oscuro aplicado", fondo != "rgb(238, 241, 245)", fondo)
        if capt:
            po.screenshot(path=capt / "11_oscuro.png")
        nav.close()

    csp = [e for e in errores_js if "Content Security Policy" in e or "Refused" in e]
    verificar("sin errores de JavaScript en consola", not errores_js, "; ".join(errores_js[:5]))
    verificar("sin violaciones de CSP", not csp)
    fallas = [r for r in resultados if not r[1]]
    print(f"\nResumen: {len(resultados) - len(fallas)}/{len(resultados)} verificaciones OK")
    return 1 if fallas else 0


if __name__ == "__main__":
    sys.exit(main())
