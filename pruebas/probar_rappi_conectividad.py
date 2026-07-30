"""Prueba el estado de tienda de Rappi contra una replica local, sin portal.

    py pruebas/probar_rappi_conectividad.py

Corre la clase Rappi de verdad contra `portal_rappi_conectividad.html`, que
replica el DOM real de Administración → Conectividad (el div de
styled-components que el usuario sacó de DevTools el 2026-07-30), NO una
tabla. La version anterior de _buscar_estado_en_pantalla() buscaba
<td>Estado</td> y encontraba cero celdas siempre: las dos tiendas de Rappi
decian "sin datos" mientras PedidosYa andaba, y nadie se enteraba de por que.

Lo que cubre, que es lo que costo caro:

  1. Una sola tienda: lee "Cerrada"/"Activa" del div, sin tabla y sin
     depender del data-testid (que lo comparte todo texto del portal).
  2. El SPA que tarda: el estado aparece 3 segundos despues del load. Antes
     se miraba una sola vez y se daba por perdido.
  3. Dos tiendas y NINGUN nombre cargado: tiene que devolver None. Adivinar
     cual sos es afirmar el estado de otro local (regla 8 de CLAUDE.md).
  4. Dos tiendas CON el nombre cargado: desempata y lee la que corresponde,
     que es justo el caso de una cuenta con Turbo y Común.
  5. Un estado que no conocemos: None, y el motivo lo dice.
  6. Que el motivo del diagnostico NUNCA venga vacio cuando no se pudo
     confirmar: sin eso el badge "sin datos" no tiene de donde agarrarse.
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
from plataformas.rappi import Rappi                        # noqa: E402

PUERTO = 8779
BASE = f"http://127.0.0.1:{PUERTO}/portal_rappi_conectividad.html"

# Igual que en probar_pedidosya.py: en la PC de desarrollo Playwright no
# tiene su navegador instalado, en la del usuario `launch()` solo alcanza.
CHROME_ALTERNATIVO = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

NOMBRE_TURBO = "Rotisería Ejemplo - Turbo"

fallos = []


def revisar(condicion, titulo):
    print(("  OK    " if condicion else "  FALLA ") + titulo)
    if not condicion:
        fallos.append(titulo)


def servir() -> socketserver.TCPServer:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(RAIZ))
    # Antes de instanciar: puesto despues, el bind ya paso y correr la
    # prueba dos veces seguidas explota con "Address already in use".
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


async def leer(navegador, query: str, nombre_tienda: str = ""):
    """Abre la replica y corre la lectura de DOM de la clase de verdad.

    Se llama a _buscar_estado_en_pantalla() y no a leer_estado_tienda()
    porque el segundo navega al portal real (goto de partners.rappi.com) y
    vuelve al menu: la parte que se puede probar sin portal es justo la que
    esta separada.
    """
    pagina = await navegador.new_page()
    plat = Rappi(pagina, store_id="AR000000", brand_id="AR000000",
                 nombre_tienda=nombre_tienda)
    # La replica pinta rapido: no hace falta esperar 1,5s entre intentos
    # salvo en el escenario que prueba justamente la demora.
    plat.ESPERA_ENTRE_INTENTOS = 1200
    await pagina.goto(BASE + query)
    resultado, diag = await plat._buscar_estado_en_pantalla()
    await pagina.close()
    return resultado, diag


async def main():
    servidor = servir()
    try:
        async with async_playwright() as p:
            navegador = await abrir_navegador(p)

            print("\n== 1) Una sola tienda ==")
            r, d = await leer(navegador, "?tiendas=1&estado=Cerrada")
            revisar(r is not None and r.abierta is False,
                    f"lee 'Cerrada' del div, sin tabla (dio {r})")
            r, d = await leer(navegador, "?tiendas=1&estado=Activa")
            revisar(r is not None and r.abierta is True,
                    f"lee 'Activa' del div (dio {r})")
            r, d = await leer(navegador, "?tiendas=1&estado=Suspendida")
            revisar(r is not None and r.abierta is False,
                    "'Suspendida' cuenta como cerrada")

            print("\n== 2) El SPA tarda en pintar el estado ==")
            r, d = await leer(navegador, "?tiendas=1&estado=Activa&demora=3000")
            revisar(r is not None and r.abierta is True,
                    "reintenta hasta que el estado aparece (3s despues)")

            print("\n== 3) Dos tiendas y ningun nombre cargado ==")
            r, d = await leer(navegador, "?tiendas=2&estado=Cerrada")
            revisar(r is None, "no adivina cual de las dos tiendas sos")
            revisar("nombre de tienda" in d.get("motivo", ""),
                    f"el motivo dice que falta el nombre en Ajustes ({d.get('motivo')!r})")

            print("\n== 4) Dos tiendas con el nombre cargado ==")
            r, d = await leer(navegador, "?tiendas=2&estado=Cerrada", NOMBRE_TURBO)
            revisar(r is not None and r.abierta is False,
                    f"desempata por nombre y lee la Turbo (dio {r})")
            # La otra tarjeta esta 'Activa': si leyera la equivocada, daria True.
            r, d = await leer(navegador, "?tiendas=2&estado=Activa", NOMBRE_TURBO)
            revisar(r is not None and r.abierta is True,
                    "sigue leyendo la tienda del nombre, no la primera que aparece")

            print("\n== 5) Un estado que no conocemos ==")
            r, d = await leer(navegador, "?tiendas=1&estado=Pausada%20por%20Rappi")
            revisar(r is None, "un estado desconocido no se inventa")
            revisar(bool(d.get("textos_en_pantalla")),
                    "el diagnostico trae los textos de la pantalla para poder verlo")

            print("\n== 6) Nunca un 'sin datos' mudo ==")
            for query, nombre in (("?tiendas=2&estado=Cerrada", ""),
                                  ("?tiendas=1&estado=Cualquiera", ""),
                                  ("?tiendas=2&estado=Cerrada", "Tienda que no existe")):
                r, d = await leer(navegador, query, nombre)
                revisar(r is None and bool(d.get("motivo")),
                        f"hay motivo cuando no se pudo confirmar ({query} {nombre!r})")

            await navegador.close()
    finally:
        servidor.shutdown()

    print("\n" + ("TODO OK" if not fallos else f"{len(fallos)} FALLAS: {fallos}"))
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
