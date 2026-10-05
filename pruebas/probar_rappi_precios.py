"""Flujo real del adaptador de precios contra una réplica local, sin cuentas."""
import asyncio
import functools
import http.server
import socketserver
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playwright.async_api import async_playwright
from plataformas.rappi import Rappi
from plataformas.precios import importe

RAIZ = Path(__file__).resolve().parent


class Portal(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        class Silencioso(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *args): pass
        handler = functools.partial(Silencioso, directory=str(RAIZ))
        cls.server = socketserver.TCPServer(("127.0.0.1", 0), handler)
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}/portal_rappi_precios.html"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close()

    async def asyncSetUp(self):
        self.pw = await async_playwright().start()
        self.browser = await self.pw.chromium.launch(headless=True)
        self.page = await self.browser.new_page()

    async def asyncTearDown(self):
        await self.browser.close(); await self.pw.stop()

    async def abrir(self, query=""):
        url = self.url + "?storeId=tienda_prueba&" + query
        class Local(Rappi):
            @property
            def url_menu(self): return url
            def en_el_menu(self): return self.page.url == url
        plat = Local(self.page, store_id="tienda_prueba", brand_id="marca_prueba")
        await self.page.goto(url)
        return plat

    async def cambiar(self, plat, antes="17500", nuevo="18000", **kwargs):
        return await plat.cambiar_precio("Producto de prueba", importe(antes), importe(nuevo),
          "menu-category-1-product-1-availability-switch-control", **kwargs)

    async def sin_efectos(self):
        self.assertIsNone(await self.page.evaluate("sessionStorage.getItem('toggles')"))
        self.assertIsNone(await self.page.evaluate("sessionStorage.getItem('borrados')"))

    async def test_lapiz_campo_guardar_reload(self):
        plat = await self.abrir("lento=1&rotulo=1")
        self.assertTrue(await self.cambiar(plat))
        self.assertEqual(await plat.leer_precio("Producto de prueba"), importe("18000"))
        self.assertEqual(await self.page.evaluate("sessionStorage.getItem('guardados')"), "1")
        self.assertGreater(int(await self.page.evaluate("sessionStorage.getItem('recargas')")), 1)
        await self.sin_efectos()

    async def test_sin_label_y_campos_flotantes(self):
        plat = await self.abrir("sinlabel=1&flotante=1")
        self.assertTrue(await self.cambiar(plat, nuevo="19000.50")); await self.sin_efectos()

    async def test_lectura_completa_sin_foto_plegada(self):
        plat = await self.abrir("plegada=1")
        filas = await plat.listar_precios()
        self.assertEqual(len(filas), 3)
        self.assertEqual(filas[2]["nombre"], "Producto sin foto")
        self.assertEqual(filas[2]["precio"], "8000.00")
        self.assertTrue(await self.cambiar(plat))

    async def test_no_guarda_no_confirma_ni_repite(self):
        plat = await self.abrir("noguarda=1")
        self.assertFalse(await self.cambiar(plat))
        self.assertEqual(await self.page.evaluate("sessionStorage.getItem('guardados')"), "1")
        await self.sin_efectos()

    async def test_nombre_repetido_no_edita(self):
        plat = await self.abrir("duplicado=1")
        filas = await plat.listar_precios()
        self.assertTrue(filas[0]["error"])
        with self.assertRaises(ValueError): await self.cambiar(plat)
        self.assertIsNone(await self.page.evaluate("sessionStorage.getItem('guardados')"))

    async def test_error_editor_se_limpia_aunque_url_es_menu(self):
        plat = await self.abrir("otronombre=1")
        with self.assertRaises(ValueError): await self.cambiar(plat)
        self.assertEqual(await self.page.get_by_text("Editar producto", exact=True).count(), 1)
        await plat.volver_del_editor_precio()
        self.assertEqual(await self.page.get_by_text("Editar producto", exact=True).count(), 0)
        self.assertEqual(len(await plat.listar_precios()), 3)

    async def test_dos_lapices_no_edita(self):
        plat = await self.abrir("doslapices=1&sinlabel=1")
        with self.assertRaises(ValueError): await self.cambiar(plat)
        self.assertIsNone(await self.page.evaluate("sessionStorage.getItem('guardados')"))

    async def test_editor_otra_identidad_no_guarda(self):
        plat = await self.abrir("otronombre=1")
        with self.assertRaises(ValueError): await self.cambiar(plat)
        self.assertIsNone(await self.page.evaluate("sessionStorage.getItem('guardados')"))

    async def test_precio_viejo_no_edita(self):
        plat = await self.abrir()
        with self.assertRaises(ValueError): await self.cambiar(plat, antes="17000")
        self.assertIsNone(await self.page.evaluate("sessionStorage.getItem('guardados')"))

    async def test_verificacion_no_navega(self):
        plat = await self.abrir()
        recargas = await self.page.evaluate("sessionStorage.getItem('recargas')")
        with self.assertRaises(ValueError): await self.cambiar(plat, puede_tocar=lambda: False)
        self.assertEqual(await self.page.evaluate("sessionStorage.getItem('recargas')"), recargas)
        await self.sin_efectos()


if __name__ == "__main__": unittest.main(verbosity=2)
