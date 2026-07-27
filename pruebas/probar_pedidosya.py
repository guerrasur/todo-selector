"""Prueba PedidosYa contra una replica local del portal, sin tocar nada real.

    py pruebas/probar_pedidosya.py

Levanta `portal_pedidosya.html` en un puerto local y corre contra el la clase
PedidosYa de verdad: cambiar de categoria, leer, apagar, prender y reconfirmar.

Reproduce las dos situaciones del log del 2026-07-27:

  A) El popup de sonido vuelve en CADA recarga y se cierra con su boton.
     Es lo que pasa en produccion. Aca fallaba _confirmar(): recargaba,
     el popup tapaba la lista, el menu volvia a la primera categoria y la
     relectura no encontraba el producto. Resultado: op#17 dio "fallo"
     sobre un prender que si habia entrado.

  B) El backdrop no se cierra nunca, asi que TODOS los clicks van por el
     fallback JS. Aca se ve el otro problema: un click disparado sobre
     <wk-menu-list-category-item> no hace nada, porque el handler vive en
     un hijo y los eventos suben pero no bajan.
"""

import asyncio
import functools
import http.server
import socketserver
import sys
import threading
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ.parent))

from playwright.async_api import async_playwright          # noqa: E402
from plataformas.pedidosya import PedidosYa                # noqa: E402

PUERTO = 8777
BASE = f"http://127.0.0.1:{PUERTO}/portal_pedidosya.html"

# En esta PC de desarrollo Playwright no tiene su navegador instalado, pero
# hay un Chromium al lado. En la maquina del usuario `launch()` solo alcanza.
CHROME_ALTERNATIVO = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

fallos = []


def revisar(condicion, titulo):
    print(("  OK    " if condicion else "  FALLA ") + titulo)
    if not condicion:
        fallos.append(titulo)


def servir() -> socketserver.TCPServer:
    """Sirve la carpeta de pruebas. Con file:// no anda el localStorage."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(RAIZ))
    servidor = socketserver.TCPServer(("127.0.0.1", PUERTO), handler)
    servidor.allow_reuse_address = True
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    return servidor


async def abrir_navegador(p):
    try:
        return await p.chromium.launch(headless=True)
    except Exception:
        return await p.chromium.launch(headless=True,
                                       executable_path=CHROME_ALTERNATIVO)


async def escenario(navegador, query: str, titulo: str):
    print("\n== " + titulo + " ==")
    pagina = await navegador.new_page()

    class PedidosYaLocal(PedidosYa):
        url_menu = BASE + query

    plat = PedidosYaLocal(pagina)
    await pagina.goto(plat.url_menu)
    # Arrancamos con Budín de pan apagado, como estaba en el log.
    await pagina.evaluate("localStorage.setItem('apagados', '[\"Budín de pan\"]')")
    await pagina.reload()

    revisar(await plat.asegurar_sesion(), "asegurar_sesion() deja la pagina lista")

    revisar(await plat.categorias() == ["Bebidas", "Platos", "Tartas"],
            "categorias() lee las 3 del menu")

    # La pagina arranca en Bebidas y Budín de pan esta en Platos: obliga a
    # cambiar de categoria para encontrarlo.
    estado = await plat.leer_estado("Budín de pan")
    revisar(estado is not None and not estado.disponible,
            "leer_estado('Budín de pan') lo encuentra cambiando de categoria")

    revisar(await plat.prender("Budín de pan"), "prender('Budín de pan') confirma el cambio")
    estado = await plat.leer_estado("Budín de pan")
    revisar(estado is not None and estado.disponible,
            "'Budín de pan' quedo prendido de verdad")

    revisar(await plat.apagar("Tarta de verdura", por_hoy=True),
            "apagar('Tarta de verdura') confirma el cambio")
    estado = await plat.leer_estado("Tarta de verdura")
    revisar(estado is not None and not estado.disponible,
            "'Tarta de verdura' quedo apagado de verdad")

    # El nombre que es prefijo de otro no se tiene que haber tocado.
    estado = await plat.leer_estado("Tarta de verdura chica")
    revisar(estado is not None and estado.disponible,
            "'Tarta de verdura chica' sigue prendido (exact=True)")

    # Un producto que no existe se tiene que poder distinguir de un error.
    revisar(await plat.leer_estado("Producto que no existe") is None,
            "leer_estado() de algo inexistente devuelve None")

    await pagina.close()


async def main():
    servidor = servir()
    try:
        async with async_playwright() as p:
            navegador = await abrir_navegador(p)
            await escenario(navegador, "?popup=cerrable&handler=hijo",
                            "A) popup de sonido cerrable (como en produccion)")
            await escenario(navegador, "?popup=pegado&handler=hijo",
                            "B) backdrop pegado: todos los clicks por JS")
            await navegador.close()
    finally:
        servidor.shutdown()

    print("\n" + ("TODO OK" if not fallos else f"{len(fallos)} FALLAS: {fallos}"))
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
