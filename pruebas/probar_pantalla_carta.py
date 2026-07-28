"""Prueba la pantalla Carta de punta a punta, en modo simulado.

    py pruebas/probar_pantalla_carta.py

Levanta la app de verdad con STOCKSWITCH_SIMULADO=1 (no abre navegador ni
toca los portales: /api/carta devuelve la lectura real guardada del
2026-07-27) y la maneja con Playwright como lo haria el usuario: leer la
carta, vincular un par dudoso, separarlo y agregar uno suelto.
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

TEMPORAL = tempfile.mkdtemp(prefix="todoselector-pantalla-")
os.environ["HOME"] = TEMPORAL
os.environ["LOCALAPPDATA"] = TEMPORAL
os.environ["STOCKSWITCH_SIMULADO"] = "1"

import uvicorn                                                # noqa: E402
from playwright.async_api import async_playwright             # noqa: E402

from app.main import app                                      # noqa: E402

PUERTO = 8788
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


def fila_de(pagina, texto_py, texto_rappi):
    """La fila de la carta que cruza esos dos nombres."""
    return (pagina.locator(".par")
            .filter(has_text=texto_py)
            .filter(has_text=texto_rappi)
            .first)


async def esperar_boton(fila, texto, timeout=10000):
    """Espera a que ESA fila ofrezca ese boton.

    No sirve esperar el texto en la pantalla: media carta ya esta vinculada
    y "un solo botón" aparece en un monton de filas desde el primer pintado.
    """
    boton = fila.locator("button", has_text=texto)
    try:
        await boton.wait_for(timeout=timeout)
        return True
    except Exception:
        return False


async def probar_aviso_de_novedad(pagina):
    """El caso del 2026-07-28: agregaron la Locro a la carta de PedidosYa.

    El catalogo la tenia como exclusiva de Rappi, asi que la app la mostraba
    en gris con el chip "no existe ahi" y no habia forma de enterarse.
    """
    print("\n== Aviso: apareció en un portal donde no estaba ==")
    from app import catalogo
    from app.database import SessionLocal
    from app.worker import worker

    db = SessionLocal()
    try:
        leido = {"Locro del sábado": True}
        worker.novedades = {
            "pedidosya": catalogo.detectar_novedades(db, "pedidosya", leido)
        }
    finally:
        db.close()

    revisar(len(worker.novedades["pedidosya"]) == 1,
            "la lectura del portal la detecta")

    await pagina.reload()
    panel = pagina.locator("#panel-novedades")
    await panel.wait_for(timeout=10000)
    texto = await panel.inner_text()
    revisar("Locro" in texto and "PedidosYa" in texto,
            "la pantalla avisa que apareció en PedidosYa")

    await panel.locator("button", has_text="Es el mismo").click()
    await pagina.wait_for_timeout(1500)

    catalogo_json = await pagina.evaluate("fetch('/api/catalogo').then(r => r.json())")
    locro = [p for p in catalogo_json["productos"]
               if p["nombre"].startswith("Locro")]
    revisar(len(locro) == 1 and
            locro[0]["plataformas"]["pedidosya"] == "Locro del sábado",
            "al aceptar, queda enganchada a PedidosYa con el nombre del portal")

    revisar(await pagina.locator("#panel-novedades").is_hidden(),
            "el aviso desaparece una vez resuelto")

    texto_lista = await pagina.locator("#lista").inner_text()
    revisar("PedidosYa: —" not in texto_lista.split("Locro")[1][:80],
            "y el producto deja de figurar en gris en PedidosYa")


async def main():
    servidor = levantar_app()
    for _ in range(100):                      # esperar a que levante
        await asyncio.sleep(0.1)
        if servidor.started:
            break

    async with async_playwright() as p:
        navegador = await abrir_navegador(p)
        pagina = await navegador.new_page()
        await pagina.goto(BASE)

        print("\n== Abrir la carta ==")
        await pagina.click("#btn-carta")
        await pagina.click("#btn-leer-carta")
        await pagina.wait_for_selector(".grupo", timeout=15000)

        revisar(await pagina.locator("h3", has_text="A confirmar — 7").count() == 1,
                "muestra los 7 pares a confirmar")
        revisar(await pagina.locator("h3", has_text="Solo en Rappi — 18").count() == 1,
                "muestra los 18 que estan solo en Rappi")
        revisar("29 en PedidosYa" in await pagina.locator("#carta-cuerpo").inner_text(),
                "muestra cuantos leyo de cada portal")

        print("\n== Los dos tartas de verdura arrancan separados ==")
        fila = fila_de(pagina, "Tarta de verdura chica", "Tarta de verdura individual")
        revisar(await fila.locator("button", has_text="Vincular").count() == 1,
                "el par que el usuario dijo que NO es el mismo ofrece Vincular")
        revisar("Tarta de verdura porción" in await fila.inner_text(),
                "avisa que en Rappi tambien existe 'en porcion'")

        print("\n== Vincular y separar ==")
        await fila.locator("button", has_text="Vincular").click()
        fila = fila_de(pagina, "Tarta de verdura chica", "Tarta de verdura individual")
        revisar(await esperar_boton(fila, "Separar"),
                "despues de vincular, la fila ofrece Separar")
        revisar("un solo botón" in await fila.inner_text(),
                "y avisa que los dos se apagan juntos")

        productos = await pagina.evaluate(
            "fetch('/api/catalogo').then(r => r.json())")
        vinculado = [p for p in productos["productos"]
                     if p["plataformas"]["pedidosya"] == "Tarta de verdura chica"]
        revisar(len(vinculado) == 1 and
                vinculado[0]["plataformas"]["rappi"] == "Tarta de verdura individual",
                "quedo un solo producto con los dos nombres")

        await fila.locator("button", has_text="Separar").click()
        fila = fila_de(pagina, "Tarta de verdura chica", "Tarta de verdura individual")
        revisar(await esperar_boton(fila, "Vincular"),
                "Separar los vuelve a dejar con un boton cada uno")

        print("\n== Agregar uno que solo esta en Rappi ==")
        fila_bowl = pagina.locator(".par").filter(has_text="Guiso de garbanzos").first
        await fila_bowl.locator("button", has_text="Agregar").click()
        fila_bowl = pagina.locator(".par").filter(has_text="Guiso de garbanzos").first
        await fila_bowl.locator(".hecho").wait_for(timeout=10000)
        revisar("cargado" in await fila_bowl.inner_text(),
                "queda marcado como cargado")

        texto_lista = await pagina.locator("#lista").inner_text()
        revisar("Guiso de garbanzos" in texto_lista,
                "y aparece en la lista de productos de la pantalla principal")

        await probar_aviso_de_novedad(pagina)

        await navegador.close()

    shutil.rmtree(TEMPORAL, ignore_errors=True)
    print("\n" + ("TODO OK" if not fallos else f"{len(fallos)} FALLAS: {fallos}"))
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
