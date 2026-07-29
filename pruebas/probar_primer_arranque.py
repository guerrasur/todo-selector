"""Que un usuario nuevo NO se encuentre con la carta de otro.

    py pruebas/probar_primer_arranque.py

Es la prueba del caso que motivo sacar `app/seed.py`: hasta el 2026-07-28 la
app venia con los 31 productos del local para el que se escribio, y con su
id de menu y su storeId clavados en el codigo. Quien la bajaba se encontraba
con una carta ajena y, peor, apuntando a la sucursal de otro.

Levanta la app en modo simulado con la base VACIA y sin ningun ajuste
guardado, que es exactamente como llega una instalacion nueva, y comprueba:

  - que no haya ni un producto cargado;
  - que la pantalla lo diga y ofrezca los dos pasos, en orden;
  - que "Leer mi carta" este bloqueado hasta decir que local sos;
  - que los datos de la sucursal se puedan cargar desde ahi mismo;
  - y que el panel se vaya cuando ya no hace falta.

Usa un puerto propio (8799): las pruebas con navegador no se pueden correr
dos a la vez.
"""

import asyncio
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))

TEMPORAL = tempfile.mkdtemp(prefix="todoselector-primera-")
os.environ["HOME"] = TEMPORAL
os.environ["LOCALAPPDATA"] = TEMPORAL
os.environ["STOCKSWITCH_SIMULADO"] = "1"

import uvicorn                                                # noqa: E402
from playwright.async_api import async_playwright             # noqa: E402

from app.main import app                                      # noqa: E402

# A PROPOSITO no se llama a catalogo_ejemplo: la gracia de esta prueba es
# que la app arranque tal cual la baja alguien que no es el autor.

PUERTO = 8799
BASE = f"http://127.0.0.1:{PUERTO}/"
CHROME_ALTERNATIVO = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

fallos = []


def revisar(condicion, titulo):
    print(("  OK    " if condicion else "  FALLA ") + titulo)
    if not condicion:
        fallos.append(titulo)


def levantar_app():
    config = uvicorn.Config(app, host="127.0.0.1", port=PUERTO, log_level="warning")
    servidor = uvicorn.Server(config)
    threading.Thread(target=servidor.run, daemon=True).start()
    return servidor


async def abrir_navegador(p):
    try:
        return await p.chromium.launch(headless=True)
    except Exception:
        return await p.chromium.launch(headless=True,
                                       executable_path=CHROME_ALTERNATIVO)


async def probar_arranque_vacio(pagina):
    print("\n== La app no viene con la carta de nadie ==")

    productos = await pagina.evaluate("fetch('/api/productos').then(r => r.json())")
    revisar(productos == [],
            f"no hay ni un producto cargado (hay {len(productos)})")

    sistema = await pagina.evaluate(
        "fetch('/api/estado-sistema').then(r => r.json())")
    revisar(sistema["catalogo_vacio"] is True,
            "la API dice que el catalogo esta vacio")
    revisar(sorted(sistema["falta_sucursal"]) == ["pedidosya", "rappi"],
            f"y que faltan las dos sucursales ({sistema['falta_sucursal']})")

    cfg = await pagina.evaluate("fetch('/api/config').then(r => r.json())")
    sucursal = {o["clave"]: o["valor"] for o in cfg["opciones"]
                if o["grupo"] == "Sucursal"}
    revisar(sucursal and all(v == "" for v in sucursal.values()),
            f"ningun id de sucursal viene precargado ({sucursal})")


async def probar_panel_de_primera_vez(pagina):
    print("\n== La pantalla ofrece los dos pasos ==")
    panel = pagina.locator("#panel-inicio")
    await panel.wait_for(timeout=10000)
    revisar(await panel.is_visible(), "aparece el panel de primera vez")

    # Los titulos van en mayuscula por CSS y eso es lo que devuelve
    # inner_text: hay que comparar sin distinguirlas.
    texto = (await panel.inner_text()).upper()
    revisar(texto.index("QUÉ LOCAL SOS") < texto.index("LEER TU CARTA"),
            "con los dos pasos, y en ese orden")

    boton_leer = panel.locator("button", has_text="Leer mi carta")
    revisar(await boton_leer.is_disabled(),
            "«Leer mi carta» esta bloqueado hasta decir que local sos")

    # Los campos salen de /api/config, no escritos en la pantalla.
    revisar(await panel.locator("[data-clave='pedidosya_menu_id']").count() == 1 and
            await panel.locator("[data-clave='rappi_store_id']").count() == 1 and
            await panel.locator("[data-clave='rappi_brand_id']").count() == 1,
            "pide los tres datos de la sucursal ahi mismo")


async def probar_no_guarda_a_medias(pagina):
    """Guardar un campo vacio dejaria la app rota pero con cara de lista."""
    print("\n== No se guarda a medias ==")
    panel = pagina.locator("#panel-inicio")

    await panel.locator("[data-clave='pedidosya_menu_id']").fill("100200")
    await panel.locator("#btn-guardar-sucursal").click()
    await pagina.wait_for_timeout(800)

    revisar("Faltan" in await panel.locator("#estado-sucursal").inner_text(),
            "avisa que faltan campos en vez de guardar")

    sistema = await pagina.evaluate(
        "fetch('/api/estado-sistema').then(r => r.json())")
    revisar(sorted(sistema["falta_sucursal"]) == ["pedidosya", "rappi"],
            "y no guardo nada de esa tanda")


async def probar_carga_de_sucursal(pagina):
    print("\n== Cargar la sucursal desde la pantalla ==")
    panel = pagina.locator("#panel-inicio")

    await panel.locator("[data-clave='pedidosya_menu_id']").fill("100200")
    await panel.locator("[data-clave='rappi_brand_id']").fill("XX90000")
    await panel.locator("[data-clave='rappi_store_id']").fill("XX90001")
    await panel.locator("#btn-guardar-sucursal").click()

    # El paso 1 desaparece recien cuando el server confirma: lo que queda
    # es el panel pidiendo solo la carta.
    await panel.locator("[data-clave='pedidosya_menu_id']") \
               .wait_for(state="detached", timeout=10000)
    revisar("ninguna carta cargada" in (await panel.inner_text()),
            "el paso 1 se da por hecho y queda solo el de leer la carta")

    cfg = await pagina.evaluate("fetch('/api/config').then(r => r.json())")
    valores = {o["clave"]: o["valor"] for o in cfg["opciones"]}
    revisar(valores["pedidosya_menu_id"] == "100200" and
            valores["rappi_store_id"] == "XX90001",
            "los ajustes quedaron guardados en la base")

    boton_leer = panel.locator("button", has_text="Leer mi carta")
    revisar(await boton_leer.is_enabled(),
            "y «Leer mi carta» se destraba")

    # Recargar no puede perderlos: viven en la base, no en el navegador.
    await pagina.reload()
    await pagina.wait_for_timeout(1200)
    sistema = await pagina.evaluate(
        "fetch('/api/estado-sistema').then(r => r.json())")
    revisar(sistema["falta_sucursal"] == [],
            "y siguen ahi despues de recargar la pantalla")


async def probar_leer_la_carta(pagina):
    """El paso 2: la app arma el catalogo leyendo los portales."""
    print("\n== Leer mi carta ==")
    panel = pagina.locator("#panel-inicio")
    await panel.locator("button", has_text="Leer mi carta").click()

    # En modo simulado /api/carta devuelve la carta de ejemplo. Se espera
    # un titulo de la lectura y no ".grupo" a secas: "Vincular a mano"
    # tambien es un .grupo y aparece antes.
    await pagina.locator("#carta-cuerpo h3", has_text="Solo en Rappi").first \
                .wait_for(timeout=20000)
    # De nuevo en mayusculas: los titulos de grupo los transforma el CSS.
    cuerpo = await pagina.locator("#carta-cuerpo").inner_text()
    revisar("A CONFIRMAR" in cuerpo.upper() and "en PedidosYa" in cuerpo,
            "muestra lo que leyo de los dos portales")

    # Y desde ahi se carga el primero: es el camino que reemplaza a seed.py.
    fila = pagina.locator(".par:not(.manual)").filter(
        has_text="Guiso de garbanzos").first
    await fila.locator("button", has_text="Agregar").click()
    await pagina.wait_for_timeout(1500)

    productos = await pagina.evaluate("fetch('/api/productos').then(r => r.json())")
    revisar(len(productos) == 1 and productos[0]["nombre"] == "Guiso de garbanzos",
            f"el producto queda cargado en la app ({len(productos)} en total)")

    await pagina.wait_for_timeout(1500)
    revisar(await pagina.locator("#panel-inicio").is_hidden(),
            "y el panel de primera vez se va: ya no hace falta")


async def main():
    servidor = levantar_app()
    for _ in range(100):
        await asyncio.sleep(0.1)
        if servidor.started:
            break

    async with async_playwright() as p:
        navegador = await abrir_navegador(p)
        pagina = await navegador.new_page()
        await pagina.goto(BASE)

        await probar_arranque_vacio(pagina)
        await probar_panel_de_primera_vez(pagina)
        await probar_no_guarda_a_medias(pagina)
        await probar_carga_de_sucursal(pagina)
        await probar_leer_la_carta(pagina)

        await navegador.close()

    shutil.rmtree(TEMPORAL, ignore_errors=True)
    print("\n" + ("TODO OK" if not fallos else f"{len(fallos)} FALLAS: {fallos}"))
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
