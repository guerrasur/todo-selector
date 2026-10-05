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
    from app.models import Producto, AliasPlataforma, EstadoItem

import uvicorn
from playwright.async_api import async_playwright


async def main():
    init_db()
    with SessionLocal() as db:
        config.guardar(db, {"rappi_brand_id": "marca_prueba", "rappi_store_id": "turbo_prueba",
                           "rappi_comun_store_id": "comun_prueba"}); db.commit()
        producto = Producto(nombre="Producto de prueba", categoria="Pruebas")
        db.add(producto); db.flush()
        db.add(AliasPlataforma(producto_id=producto.id, plataforma="rappi", nombre_remoto=producto.nombre))
        db.add(EstadoItem(producto_id=producto.id, plataforma="rappi", estado="prendido"))
        db.commit()
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
            ejecuciones = []
            page.on("request", lambda r: ejecuciones.append(r.post_data) if r.url.endswith('/api/precios/ejecutar') else None)
            await page.goto(f"http://127.0.0.1:{puerto}/")
            await page.wait_for_selector('#lista .item')
            await page.click('#btn-carta'); await page.click('#btn-precios')
            # El repintado con otra pantalla abierta no debe perder la clase
            # que permite volver a mostrar la lista en el dashboard.
            await page.evaluate('cargar()')
            assert await page.locator('#lista').is_hidden(), 'La lista se mostró fuera del dashboard'
            await page.reload()
            await page.wait_for_selector('#precios-tiendas input')
            await page.evaluate('cargar()')
            await page.click('#btn-volver')
            assert await page.locator('#lista .item').first.is_visible(), 'Los productos quedaron ocultos al volver'
            await page.fill('#buscador', 'nombre que no existe')
            await page.evaluate('cargar()')
            assert await page.locator('#lista').evaluate("e => e.classList.contains('solo-dashboard') && e.classList.contains('vacio')")
            await page.click('#btn-carta'); await page.click('#btn-volver')
            assert await page.locator('#lista').is_visible()
            await page.fill('#buscador', '')
            await page.click('#btn-carta'); await page.click('#btn-precios')
            await page.wait_for_selector('[data-tienda="rappi"]')
            assert await page.locator('[data-tienda="pedidosya"]').count() == 0
            await page.check('[data-tienda="rappi"]'); await page.check('[data-tienda="rappi_comun"]')
            await page.click('#precios-leer'); await page.wait_for_selector('#precios-tabla tbody tr')
            assert await page.locator('#precios-tabla tbody tr').count() == 4
            assert await page.input_value('#precios-modo') == 'individual'
            cajas = page.locator('#precios-tabla input[type="text"]')
            assert await cajas.count() == 4
            assert float(await cajas.nth(0).input_value()) == 1000
            assert float(await cajas.nth(1).input_value()) == 1500
            await cajas.nth(0).fill('1400,50'); await cajas.nth(1).fill('1800')
            await cajas.nth(2).fill('1200')
            await page.uncheck('[data-tienda="rappi_comun"]')
            assert '2 precios modificados' in await page.locator('#precios-modificados').inner_text()
            await page.check('[data-tienda="rappi_comun"]')
            assert '3 precios modificados' in await page.locator('#precios-modificados').inner_text()
            await cajas.nth(2).fill('1000,00')
            assert '2 precios modificados' in await page.locator('#precios-modificados').inner_text()
            await page.fill('#precios-buscar', 'Otro'); await page.fill('#precios-buscar', '')
            await page.evaluate('cargar()')
            await page.click('#precios-carta'); await page.click('#btn-precios')
            assert await cajas.nth(0).input_value() == '1400,50'
            assert not ejecuciones, 'Escribir un precio no debe ejecutar cambios'
            await page.click('#precios-previo'); await page.wait_for_selector('#precios-ejecutar')
            assert await page.locator('#precios-plan tbody tr').count() == 2
            assert '$ 1.400,5' in await page.locator('#precios-plan').inner_text()
            assert not ejecuciones, 'La revisión debe esperar confirmación'
            await cajas.nth(1).fill('1900')
            assert await page.locator('#precios-ejecutar').count() == 0
            await page.click('#precios-previo'); await page.wait_for_selector('#precios-ejecutar')
            assert 'Confirmar y ejecutar' in await page.locator('#precios-ejecutar').inner_text()
            await page.click('#precios-ejecutar')
            await page.wait_for_function("document.querySelector('#precios-lote').textContent.includes('terminado')")
            assert len(ejecuciones) == 1
            assert await page.locator('#precios-lote tbody tr').count() == 2
            assert '$ 1.900' in await page.locator('#precios-lote').inner_text()
            await page.select_option('#precios-modo', 'porcentaje')
            await page.fill('#precios-cantidad', '10')
            await page.click('#precios-previo'); await page.wait_for_selector('#precios-ejecutar')
            assert await page.locator('#precios-plan tbody tr').count() == 4
            assert '$ 1.100' in await page.locator('#precios-plan').inner_text()
            # La lectura de dashboard no borra controles ni invalida la selección.
            await page.evaluate('cargar()')
            assert await page.input_value('#precios-cantidad') == '10'
            await page.click('#precios-ejecutar')
            await page.wait_for_function("document.querySelectorAll('#precios-lote tbody tr').length === 4 && document.querySelector('#precios-lote').textContent.includes('terminado')")
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
            await page.locator('#precios-tabla input').nth(1).fill('1500')
            await page.locator('#precios-tabla input').first.fill('1400,50')
            await page.fill('#precios-buscar', 'Otro'); await page.fill('#precios-buscar', '')
            assert await page.locator('#precios-tabla input').first.input_value() == '1400,50'
            await page.click('#precios-previo'); await page.wait_for_selector('#precios-ejecutar')
            assert await page.locator('#precios-plan tbody tr').count() == 1
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
            print('OK: cajas precargadas, cambios individuales, confirmación, aumentos, navegación y exclusión de PedidosYa')
    finally:
        server.should_exit = True
        await asyncio.to_thread(hilo.join, 10)


if __name__ == '__main__': asyncio.run(main())
