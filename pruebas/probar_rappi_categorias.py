"""Flujo de apertura acotado; los selectores reales se prueban con linkedom."""
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plataformas.rappi_carta import CartaRappi


class Locator:
    def __init__(self, page, cerradas=False):
        self.page = page
        self.cerradas = cerradas

    @property
    def first(self):
        return self

    async def count(self):
        return sum(not x for x in self.page.estados) if self.cerradas else len(self.page.estados)

    async def click(self, timeout):
        i = self.page.estados.index(False)
        self.page.clicks.append(i)
        if not self.page.trabado:
            self.page.estados[i] = True


class Page:
    def __init__(self, estados):
        self.estados = list(estados)
        self.clicks = []
        self.trabado = False
        self.wait_for_timeout = AsyncMock()

    def locator(self, selector):
        base = CartaRappi.SELECTOR_CATEGORIA_CARTA
        assert selector in (base, base + '[aria-expanded="false"]')
        return Locator(self, selector != base)

    async def evaluate(self, script, selector):
        assert script == CartaRappi.JS_CATEGORIAS_CARTA
        assert selector == CartaRappi.SELECTOR_CATEGORIA_CARTA
        return [{'nombre': f'Categoría {i}', 'abierta': x} for i, x in enumerate(self.estados)]

    async def wait_for_function(self, script, arg, timeout):
        # Simula el timeout del navegador cuando no se reducen las cerradas.
        if await self.locator(arg['selector']).count() >= arg['antes']:
            raise TimeoutError('La categoría no se desplegó')


def crear(estados):
    r = CartaRappi()
    r.page = Page(estados)
    r._exigir_tienda = AsyncMock()
    return r


class Categorias(unittest.IsolatedAsyncioTestCase):
    async def test_abre_solo_cerradas_y_segunda_llamada_no_cierra_nada(self):
        r = crear([True, False, False, False])
        estados = await r._abrir_categorias_carta_nueva()
        self.assertTrue(all(x['abierta'] for x in estados))
        self.assertEqual(r.page.clicks, [1, 2, 3])
        await r._abrir_categorias_carta_nueva()
        self.assertEqual(r.page.clicks, [1, 2, 3])

    async def test_clic_sin_progreso_se_detiene_sin_bucle(self):
        r = crear([False, False]); r.page.trabado = True
        with self.assertRaises(TimeoutError):
            await r._abrir_categorias_carta_nueva()
        self.assertEqual(r.page.clicks, [0])

    async def test_cambio_tienda_antes_de_clic_detiene_apertura(self):
        r = crear([False])
        r._exigir_tienda.side_effect = [None, RuntimeError('Cambió la tienda')]
        with self.assertRaisesRegex(RuntimeError, 'Cambió la tienda'):
            await r._abrir_categorias_carta_nueva()
        self.assertEqual(r.page.clicks, [])

    async def test_sin_encabezados_da_diagnostico(self):
        r = crear([])
        with self.assertRaisesRegex(RuntimeError, 'encabezados'):
            await r._abrir_categorias_carta_nueva()
        self.assertEqual(r.page.clicks, [])


if __name__ == '__main__':
    unittest.main()
