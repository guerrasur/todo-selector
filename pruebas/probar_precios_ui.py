"""Pantalla y API reales en modo simulado, SQLite temporal y Chromium."""
import asyncio
import os
import socket
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
TEMP = tempfile.TemporaryDirectory(prefix="todo-selector-precios-ui-")
with patch.object(Path, "home", return_value=Path(TEMP.name)), patch.dict(os.environ, {
    "LOCALAPPDATA": TEMP.name, "STOCKSWITCH_SIMULADO": "1"}):
    from app.main import app
    from app.database import init_db, SessionLocal
    from app import config

import uvicorn
from playwright.async_api import async_playwright


async def main():
    init_db()
    with SessionLocal() as db:
        config.guardar(db, {"rappi_brand_id": "marca_prueba", "rappi_store_id": "turbo_prueba",
                           "rappi_comun_store_id": "comun_prueba"}); db.commit()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0)); puerto = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=puerto, log_level="error"))
    hilo = threading.Thread(target=server.run, daemon=True); hilo.start()
    for _ in range(100):
        if server.started: break
        await asyncio.sleep(.05)
    assert server.started
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1365, "height": 900})
            errores = []; page.on("pageerror", lambda e: errores.append(str(e)))
            await page.goto(f"http://127.0.0.1:{puerto}/")
            await page.click('#btn-carta'); await page.click('#btn-precios')
            await page.wait_for_selector('[data-tienda="rappi"]')
            assert await page.locator('[data-tienda="pedidosya"]').count() == 0
            await page.check('[data-tienda="rappi"]'); await page.check('[data-tienda="rappi_comun"]')
            await page.click('#precios-leer'); await page.wait_for_selector('#precios-tabla tbody tr')
            assert await page.locator('#precios-tabla tbody tr').count() == 4
            await page.fill('#precios-cantidad', '10')
            await page.select_option('#precios-modo', 'porcentaje')
            await page.click('#precios-previo'); await page.wait_for_selector('#precios-ejecutar')
            assert await page.locator('#precios-plan tbody tr').count() == 4
            assert '$ 1.100' in await page.locator('#precios-plan').inner_text()
            # La lectura de dashboard no borra controles ni invalida la selección.
            await page.evaluate('cargar()')
            assert await page.input_value('#precios-cantidad') == '10'
            await page.click('#precios-ejecutar')
            await page.wait_for_function("document.querySelector('#precios-lote').textContent.includes('terminado')")
            assert 'simulado' in await page.locator('#precios-lote').inner_text()
            assert 'confirmado' not in await page.locator('#precios-lote').inner_text()
            await page.select_option('#precios-alcance', 'seleccionados')
            await page.locator('#precios-tabla input').first.check()
            await page.fill('#precios-cantidad', '100'); await page.select_option('#precios-modo', 'pesos')
            await page.click('#precios-previo'); await page.wait_for_selector('#precios-ejecutar')
            assert await page.locator('#precios-plan tbody tr').count() == 1
            # Editar el incremento invalida el plan anterior inmediatamente.
            await page.fill('#precios-cantidad', '200')
            assert await page.locator('#precios-ejecutar').count() == 0
            await page.select_option('#precios-modo', 'individual')
            await page.locator('#precios-tabla input').first.fill('1400,50')
            await page.fill('#precios-buscar', 'Otro'); await page.fill('#precios-buscar', '')
            assert await page.locator('#precios-tabla input').first.input_value() == '1400,50'
            await page.click('#precios-previo'); await page.wait_for_selector('#precios-ejecutar')
            assert '$ 1.400,5' in await page.locator('#precios-plan').inner_text()
            # Volver y abrir conserva cambios individuales.
            await page.click('#precios-carta'); await page.click('#btn-precios')
            assert await page.locator('#precios-tabla input').first.input_value() == '1400,50'
            await page.set_viewport_size({"width": 390, "height": 844})
            assert await page.locator('#precios-previo').is_visible()
            assert not errores, errores
            # Barrera backend: un request directo tampoco habilita PedidosYa.
            r = await page.request.post(f'http://127.0.0.1:{puerto}/api/precios/leer', data={"tiendas": ["pedidosya"]})
            assert r.status == 400
            await page.reload(); await page.wait_for_selector('#precios-tiendas input')
            assert page.url.endswith('/precios')
            await browser.close()
            print('OK: pantalla, selección, porcentajes, edición, vista previa, ejecución, navegación y exclusión de PedidosYa')
    finally:
        server.should_exit = True
        await asyncio.to_thread(hilo.join, 10)


if __name__ == '__main__': asyncio.run(main())
