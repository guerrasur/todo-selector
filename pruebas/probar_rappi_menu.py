"""Prueba el MENU de Rappi contra una replica local, sin tocar nada real.

    py pruebas/probar_rappi_menu.py

Levanta `portal_rappi_menu.html` en un puerto local y corre contra el la
clase Rappi de verdad. Cubre lo que el log del 2026-08-03 dejo ver:

  A) La franja `menu-categories-hoverable-gap` tapando los toggles. Sin
     neutralizarla, el click normal falla SIEMPRE y se pierden 8 s por
     operacion. Con neutralizar_estorbos() tiene que entrar derecho.
  B) El radio "Sólo por hoy": el modal monta el de verdad con retardo y hay
     un fantasma invisible con el mismo texto. Buscar el visible es lo que
     evita clickear el fantasma y comerse el timeout.
  C) Un nombre que aparece dos veces DENTRO de una tarjeta: inofensivo,
     tiene que operar normal.
  D) Un nombre que aparece en DOS tarjetas: peligroso. NO se toca ninguna,
     se tira NombreAmbiguo.
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
from plataformas.base import NombreAmbiguo                 # noqa: E402
from plataformas.rappi import Rappi                        # noqa: E402

PUERTO = 8778
BASE = f"http://127.0.0.1:{PUERTO}/portal_rappi_menu.html"

# En esta PC de desarrollo Playwright no tiene su navegador instalado, pero
# hay un Chromium al lado. En la maquina del usuario `launch()` solo alcanza.
CHROME_ALTERNATIVO = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

fallos = []


def revisar(condicion, titulo):
    print(("  OK    " if condicion else "  FALLA ") + titulo)
    if not condicion:
        fallos.append(titulo)


def servir() -> socketserver.TCPServer:
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


async def abrir_plataforma(navegador, query: str):
    pagina = await navegador.new_page()

    class RappiLocal(Rappi):
        url_menu = BASE + query

        def en_el_menu(self) -> bool:
            return self.url_menu in self.page.url

    plat = RappiLocal(pagina, store_id="AR000000", brand_id="AR00000")
    await pagina.goto(plat.url_menu)
    await pagina.evaluate("localStorage.setItem('apagados', '[]')")
    await pagina.reload()
    return plat, pagina


async def la_franja_no_impide_el_click(navegador):
    print("\n== A) La franja de hover no puede seguir comiendose los clicks ==")
    plat, pagina = await abrir_plataforma(navegador, "")

    revisar(await plat.asegurar_sesion(), "asegurar_sesion() deja el menu listo")

    # La franja sigue en el DOM: no se oculta nada, solo deja de interceptar.
    franja = pagina.locator('[data-testid^="menu-categories-hoverable-gap"]')
    revisar(await franja.count() == 1,
            "la franja sigue en la pagina (no se borra ni se oculta)")
    revisar(await franja.first.evaluate(
        "el => getComputedStyle(el).pointerEvents") == "none",
        "pero ya no recibe clicks")

    # Lo que importa: que el click NORMAL entre. clickear() devuelve True
    # si entro un click de verdad y False si hubo que ir por JS.
    tarjeta = plat._tarjeta("Villavicencio con gas 500 ml")
    entro = await plat.clickear(plat._toggle_clickeable(tarjeta), que="toggle")
    revisar(entro, "el click sobre el toggle entra SIN pasar por el fallback JS")

    await pagina.close()


async def apagar_y_prender_de_verdad(navegador):
    print("\n== B) Apagar (con su modal) y prender, confirmando releyendo ==")
    plat, pagina = await abrir_plataforma(navegador, "")
    await plat.asegurar_sesion()

    nombre = "Villavicencio con gas 500 ml"
    estado = await plat.leer_estado(nombre)
    revisar(estado is not None and estado.disponible,
            "arranca prendido")

    # El modal monta el radio recien a los 1200 ms y hay un fantasma
    # invisible con el mismo texto: si se agarra el fantasma, esto falla.
    revisar(await plat.apagar(nombre, por_hoy=True),
            "apagar() pasa el modal y confirma el cambio")
    estado = await plat.leer_estado(nombre)
    revisar(estado is not None and not estado.disponible,
            "quedo apagado de verdad")

    revisar(await plat.prender(nombre), "prender() confirma el cambio")
    estado = await plat.leer_estado(nombre)
    revisar(estado is not None and estado.disponible,
            "y quedo prendido de verdad")

    # El que es prefijo de otro no se tiene que haber tocado nunca.
    otro = await plat.leer_estado("Villavicencio sin gas 500 ml")
    revisar(otro is not None and otro.disponible,
            "el otro Villavicencio sigue prendido (exact=True)")

    await pagina.close()


async def el_fantasma_del_radio(navegador):
    print("\n== C) El radio invisible no es el que se clickea ==")
    plat, pagina = await abrir_plataforma(navegador, "")
    await plat.asegurar_sesion()

    # Con el modal cerrado, el UNICO match del texto es el fantasma: es
    # exactamente el `count=1, visible=False` del log.
    todos = pagina.get_by_text(plat.TXT_POR_HOY, exact=True)
    revisar(await todos.count() == 1,
            "con el modal cerrado hay un solo match del texto del radio")
    revisar(not await todos.first.is_visible(),
            "y es invisible: es el que agarraba el `.first` de antes")
    revisar(await plat.visible(todos).count() == 0,
            "visible() no devuelve ninguno, que es la respuesta correcta")

    await pagina.close()


async def nombres_ambiguos(navegador):
    print("\n== D) Un nombre que lleva a dos productos no se toca ==")
    plat, pagina = await abrir_plataforma(navegador, "")
    await plat.asegurar_sesion()

    # Dos veces el mismo texto, pero en UNA sola tarjeta: es inofensivo.
    ids = await plat.tarjetas_del_nombre("Gaseosa cola 500 ml")
    revisar(len(ids) == 1,
            f"el nombre repetido dentro de una tarjeta cuenta como una ({ids})")
    revisar(await plat.apagar("Gaseosa cola 500 ml", por_hoy=True),
            "y por eso se puede apagar normal")

    # Dos tarjetas distintas: no hay forma de saber cual quiso el usuario.
    ids = await plat.tarjetas_del_nombre("Agua con gas")
    revisar(len(ids) == 2, f"el que esta en dos tarjetas cuenta como dos ({ids})")

    antes = await pagina.evaluate("localStorage.getItem('apagados')")
    try:
        await plat.apagar("Agua con gas", por_hoy=True)
        revisar(False, "apagar() tiene que negarse con un nombre ambiguo")
    except NombreAmbiguo as e:
        revisar("2 productos distintos" in str(e),
                f"apagar() se niega y dice por que ({str(e)[:60]}...)")

    try:
        await plat.prender("Agua con gas")
        revisar(False, "prender() tambien tiene que negarse")
    except NombreAmbiguo:
        revisar(True, "prender() tambien se niega")

    revisar(await pagina.evaluate("localStorage.getItem('apagados')") == antes,
            "y NO toco ninguno de los dos productos")

    await pagina.close()


async def main():
    servidor = servir()
    try:
        async with async_playwright() as p:
            navegador = await abrir_navegador(p)
            await la_franja_no_impide_el_click(navegador)
            await apagar_y_prender_de_verdad(navegador)
            await el_fantasma_del_radio(navegador)
            await nombres_ambiguos(navegador)
            await navegador.close()
    finally:
        servidor.shutdown()

    print("\n" + ("TODO OK" if not fallos else f"{len(fallos)} FALLAS: {fallos}"))
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
