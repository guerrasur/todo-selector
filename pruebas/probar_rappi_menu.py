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
  E) El dialogo de verdad (?dialogo=portal): portal de floating-ui, opciones
     por data-testid y el texto SIN tilde. Buscar el texto exacto no
     encuentra nada; hay que elegir la opcion comparando sin tildes, sin
     elegir nunca por posicion, y no dejar el dialogo abierto.
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


async def el_dialogo_de_floating_ui(navegador):
    print("\n== E) El dialogo real: opciones por testid y texto sin tilde ==")
    plat, pagina = await abrir_plataforma(navegador, "?dialogo=portal")
    await plat.asegurar_sesion()

    nombre = "Villavicencio con gas 500 ml"

    # El texto que tenemos escrito NO esta en el dialogo: el unico match es
    # el fantasma escondido. Asi se veia el 2026-08-03.
    revisar(await plat.visible(
        pagina.get_by_text(plat.TXT_POR_HOY, exact=True)).count() == 0,
        "el texto exacto del radio no aparece en ningun lado visible")

    revisar(await plat.apagar(nombre, por_hoy=True),
            "apagar() igual encuentra la opcion (compara sin tildes)")

    apagados = await pagina.evaluate("localStorage.getItem('apagados')")
    revisar("582221" in (apagados or ""), "y el producto quedo apagado")

    revisar(await plat._opciones_abiertas().count() == 0,
            "el dialogo no quedo abierto tapando la pantalla")

    # Que NO eligio por posicion: la 3ra opcion es "Personalizar", que pide
    # una fecha y no apaga nada. Si la hubiera elegido, el producto seguiria
    # prendido y esto no se distinguiria de un OK.
    revisar(await plat.prender(nombre), "prender() lo vuelve a prender")

    # Con una opcion que no existe, la operacion tiene que fallar EN ROJO y
    # dejar la pantalla limpia, no quedarse con el dialogo abierto.
    class SinOpcion(type(plat)):
        TXT_POR_HOY = "Hasta el jueves que viene"

    plat.__class__ = SinOpcion
    revisar(not await plat.apagar(nombre, por_hoy=True),
            "una opcion que el portal no tiene da False (no apaga a ciegas)")
    revisar(plat.opciones_vistas and
            any("Solo por hoy" in t for t in plat.opciones_vistas),
            f"y el log puede decir que opciones habia ({plat.opciones_vistas})")
    revisar(await plat._opciones_abiertas().count() == 0,
            "y tampoco ahi queda el dialogo abierto para el intento siguiente")

    estado = await plat.leer_estado(nombre)
    revisar(estado is not None and estado.disponible,
            "el producto sigue prendido: no se toco nada")

    await pagina.close()


async def lo_tapa_un_ancestro(navegador):
    print("\n== F) Lo que tapa el toggle es un ANCESTRO suyo (2026-08-05) ==")
    plat, pagina = await abrir_plataforma(navegador, "?tapa=ancestro")
    revisar(await plat.asegurar_sesion(), "asegurar_sesion() deja el menu listo")

    # Defensa 1: el ::after del <ul>, que si esta en SELECTORES_ESTORBO.
    sin_clicks = await pagina.evaluate(
        """() => getComputedStyle(
               document.querySelector('ul[data-testid="menu-categories"]'),
               '::after').pointerEvents""")
    revisar(sin_clicks == "none",
            "el ::after del <ul> de categorias ya no recibe clicks")

    # Defensa 2: .cat-cuerpo::before NO esta en ninguna lista, asi que este
    # lo tiene que resolver el peldaño de destapar de clickear(). Es el que
    # importa: cuando el portal cambie el DOM otra vez, es el unico que
    # sigue sirviendo.
    quien_tapa = await pagina.evaluate(
        """() => {
            const l = document.querySelector('[data-testid$="582222-availability-switch-control"]');
            const r = l.getBoundingClientRect();
            const a = document.elementFromPoint(r.left + r.width / 2,
                                                r.top + r.height / 2);
            return a.className + '|' + a.contains(l);
        }""")
    revisar(quien_tapa == "cat-cuerpo|true",
            f"al toggle lo tapa un ancestro suyo ({quien_tapa})")

    tarjeta = plat._tarjeta("Villavicencio sin gas 500 ml")
    entro = await plat.clickear(plat._toggle_clickeable(tarjeta), que="toggle",
                                profundo=True)
    revisar(entro, "el click entra igual, destapando, SIN pasar por el JS")

    # Y la pagina queda como estaba: el usuario mira esta misma ventana.
    quedo = await pagina.evaluate(
        """() => [document.querySelector('.cat-cuerpo').style.pointerEvents,
                  (window.__tsDestapado || []).length]""")
    revisar(quedo == ["", 0], f"y los pointer-events quedan restaurados ({quedo})")

    await plat.cerrar_dialogo()

    # Lo de fondo: apagar() ahora abre el popup. El handler vive en la
    # perilla y escucha pointerdown, que es lo que el .click() sobre el
    # <label> no despertaba nunca.
    nombre = "Villavicencio con gas 500 ml"
    revisar(await plat.apagar(nombre, por_hoy=True),
            "apagar() abre el popup y confirma el cambio")
    estado = await plat.leer_estado(nombre)
    revisar(estado is not None and not estado.disponible,
            "quedo apagado de verdad")

    # El for="switch-hidden-input" esta repetido en toda la carta: si algo
    # activa el label por la via nativa, el que se apaga es el PRIMERO.
    otro = await plat.leer_estado("Gaseosa cola 500 ml")
    revisar(otro is not None and otro.disponible,
            "y no se toco el switch de otro producto (for= repetido)")

    revisar(await plat.prender(nombre), "prender() lo vuelve a prender")

    await pagina.close()


async def mas_capas_que_el_limite_viejo(navegador):
    print("\n== G) Mas ancestros tapando que el limite viejo (2026-08-05) ==")
    plat, pagina = await abrir_plataforma(navegador, "?tapa=muchos")
    revisar(await plat.asegurar_sesion(), "asegurar_sesion() deja el menu listo")

    # El log real destapo tres capas y el toggle SEGUIA tapado: el tope de 3
    # era inventado. Aca son cinco, asi que destapar de a una con ese tope no
    # alcanza ni de casualidad.
    cuantos = await pagina.evaluate(
        """() => {
            const l = document.querySelector('[data-testid$="582222-availability-switch-control"]');
            const r = l.getBoundingClientRect();
            const pila = document.elementsFromPoint(r.left + r.width / 2,
                                                    r.top + r.height / 2);
            const i = pila.findIndex(n => n === l || l.contains(n));
            return (i < 0 ? pila : pila.slice(0, i))
                   .filter(n => n !== l && n.contains(l)).length;
        }""")
    revisar(cuantos > 3,
            f"al toggle lo tapan {cuantos} ancestros (mas que las 3 capas viejas)")

    tarjeta = plat._tarjeta("Villavicencio sin gas 500 ml")
    entro = await plat.clickear(plat._toggle_clickeable(tarjeta), que="toggle",
                                profundo=True)
    revisar(entro, "el click entra igual, destapandolas TODAS de una, sin JS")

    quedo = await pagina.evaluate(
        """() => [[...document.querySelectorAll('.capa, .cat-cuerpo')]
                    .every(n => n.style.pointerEvents === ''),
                  (window.__tsDestapado || []).length]""")
    revisar(quedo == [True, 0],
            f"y los pointer-events de las cinco quedan restaurados ({quedo})")

    await plat.cerrar_dialogo()

    nombre = "Villavicencio con gas 500 ml"
    revisar(await plat.apagar(nombre, por_hoy=True),
            "apagar() abre el popup y confirma el cambio")
    estado = await plat.leer_estado(nombre)
    revisar(estado is not None and not estado.disponible, "quedo apagado de verdad")

    await pagina.close()


async def el_toggle_no_esta_en_su_pila(navegador):
    print("\n== H) El toggle NO aparece en su propia pila (2026-08-05) ==")
    plat, pagina = await abrir_plataforma(navegador, "?tapa=recorte")
    revisar(await plat.asegurar_sesion(), "asegurar_sesion() deja el menu listo")

    # No lo tapa nada: esta recortado, y el punto que Playwright clickea no
    # le pertenece. Contesta un ancestro, igual que cuando SI lo tapan, y
    # hasta ahora las dos cosas se leian igual.
    afuera = await pagina.evaluate(
        """() => {
            const l = document.querySelector('[data-testid$="582222-availability-switch-control"]');
            const r = l.getBoundingClientRect();
            const pila = document.elementsFromPoint(r.left + r.width / 2,
                                                    r.top + r.height / 2);
            return {en_la_pila: pila.some(n => n === l || l.contains(n)),
                    arriba_es_ancestro: pila.length > 0 && pila[0].contains(l)};
        }""")
    revisar(not afuera["en_la_pila"] and afuera["arriba_es_ancestro"],
            f"el toggle no esta en su pila y arriba contesta un ancestro ({afuera})")

    diag = await plat._diagnosticar(plat._toggle_clickeable(
        plat._tarjeta("Villavicencio sin gas 500 ml")))
    revisar(not diag.alcanzable,
            "el diagnostico lo marca como NO alcanzable")
    revisar("NO aparece en su propia pila" in diag.texto,
            f"y el log lo dice con todas las letras ({diag.texto[-90:]})")
    # Lo que importa: NO se va a gastar los intentos destapando capas que no
    # son el problema. Destapar aca no arregla nada.
    revisar(not diag.despejado, "y no se lo da por despejado (forzar seria a ciegas)")

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
            await el_dialogo_de_floating_ui(navegador)
            await lo_tapa_un_ancestro(navegador)
            await mas_capas_que_el_limite_viejo(navegador)
            await el_toggle_no_esta_en_su_pila(navegador)
            await navegador.close()
    finally:
        servidor.shutdown()

    print("\n" + ("TODO OK" if not fallos else f"{len(fallos)} FALLAS: {fallos}"))
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
