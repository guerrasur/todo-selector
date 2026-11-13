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

  B) El diálogo de sonido sigue abierto. La preparación mantiene en
     espera las acciones hasta que el menú sea utilizable.
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
from plataformas.base import NombreAmbiguo
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
    # Antes de instanciar: puesto despues, el bind ya paso y correr la
    # prueba de nuevo enseguida explota con "Address already in use".
    socketserver.TCPServer.allow_reuse_address = True
    servidor = socketserver.TCPServer(("127.0.0.1", PUERTO), handler)
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
        ESPERA_MENU = 3 if "popup=pegado" in query else PedidosYa.ESPERA_MENU

    plat = PedidosYaLocal(pagina, menu_id="LOCAL")
    await pagina.goto(plat.url_menu)
    # Arrancamos con Budin de pan apagado, como estaba en el log.
    await pagina.evaluate("localStorage.setItem('apagados', '[\"Budin de pan\"]')")
    await pagina.reload()

    lista = await plat.asegurar_sesion()
    if "popup=pegado" in query:
        revisar(not lista, "un diálogo que sigue abierto impide operar")
        revisar(await plat._hay_overlay(), "el diálogo persiste en la réplica")
        await pagina.close()
        return
    revisar(lista, "asegurar_sesion() deja la pagina lista")

    revisar(await plat.categorias() == ["Bebidas", "Platos", "Tartas"],
            "categorias() lee las 3 del menu")

    # La pagina arranca en Bebidas y Budin de pan esta en Platos: obliga a
    # cambiar de categoria para encontrarlo.
    estado = await plat.leer_estado("Budin de pan")
    revisar(estado is not None and not estado.disponible,
            "leer_estado('Budin de pan') lo encuentra cambiando de categoria")

    revisar(await plat.prender("Budin de pan"), "prender('Budin de pan') confirma el cambio")
    estado = await plat.leer_estado("Budin de pan")
    revisar(estado is not None and estado.disponible,
            "'Budin de pan' quedo prendido de verdad")

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

    # La lectura de toda la carta: es lo que contesta "cual esta prendido"
    # al arrancar, sin que el usuario toque nada.
    todos = await plat.leer_todos()
    revisar(len(todos) == 12,
            f"leer_todos() trae los 12 productos de las 3 categorias (trajo {len(todos)})")
    revisar(todos.get("Budin de pan") is True and todos.get("Tarta de verdura") is False,
            "leer_todos() devuelve bien prendidos y apagados")
    revisar(todos.get("Gaseosa cola") is True,
            "leer_todos() llega tambien a la categoria que estaba abierta")

    # En que categoria vive cada uno sale de ESA misma recorrida: es la
    # unica forma de leer la carta entera en este portal, asi que la
    # categoria se ve al pasar. Hasta el 2026-08-14 se tiraba, y la
    # pantalla mostraba la carta entera bajo "SIN CATEGORIA".
    cats = await plat.categorias_de_productos()
    revisar(cats.get("Gaseosa cola") == "Bebidas" and
            cats.get("Budin de pan") == "Platos" and
            cats.get("Tarta de choclo") == "Tartas",
            "categorias_de_productos() dice en cual esta cada uno")
    revisar(len(cats) == 12, f"y las trae de las 3 categorias ({len(cats)})")

    # Sin ninguna lectura previa no se inventa nada: {} es "no se" (regla 8).
    otra = PedidosYaLocal(pagina, menu_id="LOCAL")
    revisar(await otra.categorias_de_productos() == {},
            "sin haber leido todavia, no afirma ninguna categoria")

    await pagina.close()


async def regresiones_lectura(navegador):
    pagina = await navegador.new_page()

    class PedidosYaLocal(PedidosYa):
        url_menu = BASE
        ESPERA_CATEGORIA = 3

    plat = PedidosYaLocal(pagina, menu_id="LOCAL")

    await pagina.goto(BASE + "?captcha&ariaOculto&demoraMenu=1400")
    revisar(await plat.en_verificacion(), "detecta el iframe px-captcha-modal")
    revisar(not await plat.asegurar_sesion(), "espera la intervención manual")
    await pagina.locator("#px-captcha-modal").evaluate(
        "el => { sessionStorage.setItem('verificacionResuelta', '1'); el.remove(); }")
    revisar(not await plat.verificacion_resuelta(),
            "un switch de fondo solo no da por recuperado el menú")
    await pagina.locator("wk-menu-list-category-item").first.wait_for()
    revisar(await plat.verificacion_resuelta(),
            "detecta categorías y productos detrás del aviso de sonido")
    revisar(await plat.asegurar_sesion(), "cierra el aviso y espera la carta utilizable")
    revisar(await plat.prender("Budin de pan"),
            "confirma el encendido aunque las categorías demoren tras la recarga")

    await pagina.goto(BASE + "?demora=1700&sinEstado=Flan+casero")
    revisar(await plat.asegurar_sesion(), "réplica con categorías lentas")
    todos = await plat.leer_todos()
    revisar(len(todos) == 11 and "Flan casero" not in todos,
            "espera la categoría nueva y deja sin confirmar el switch ilegible")
    revisar((await plat.categorias_de_productos()).get("Budin de pan") == "Platos",
            "los productos de la categoría lenta quedan en su grupo")
    revisar(await plat.leer_estado("Flan casero") is None,
            "un switch ilegible devuelve estado desconocido")

    await pagina.goto(BASE + "?trabada=Platos")
    await plat.asegurar_sesion()
    try:
        await plat.leer_todos()
    except RuntimeError as e:
        revisar("Platos" in str(e) and not await plat.categorias_de_productos(),
                "descarta la carta si una categoría no confirma el cambio")
    else:
        revisar(False, "una categoría trabada debe descartar la carta")

    await pagina.goto(BASE + "?duplicado=1")
    await plat.asegurar_sesion()
    revisar("Budin de pan" not in await plat.leer_todos(),
            "un nombre repetido queda fuera de la lectura de disponibilidad")
    try:
        await plat.prender("Budin de pan")
    except NombreAmbiguo:
        revisar(True, "un duplicado en otra categoría bloquea el cambio")
    else:
        revisar(False, "un duplicado en otra categoría debe bloquear el cambio")

    await pagina.goto(BASE + "?otroPopup=Otro+producto")
    await plat.asegurar_sesion()
    revisar(not await plat.apagar("Tarta de verdura"),
            "no confirma un diálogo de otro producto")
    revisar((await plat.leer_estado("Tarta de verdura")).disponible,
            "el producto sigue disponible si el diálogo tenía otro nombre")
    await pagina.close()


async def main():
    servidor = servir()
    try:
        async with async_playwright() as p:
            navegador = await abrir_navegador(p)
            await escenario(navegador, "?popup=cerrable&handler=hijo",
                            "A) popup de sonido cerrable (como en produccion)")
            await escenario(navegador, "?popup=pegado&handler=hijo",
                            "B) diálogo de sonido que sigue abierto")
            await regresiones_lectura(navegador)
            await navegador.close()
    finally:
        servidor.shutdown()

    print("\n" + ("TODO OK" if not fallos else f"{len(fallos)} FALLAS: {fallos}"))
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
