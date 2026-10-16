"""Duración por value y diálogo ligado al switch; sin acceso a portales."""
import sys
import asyncio
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plataformas.rappi import Rappi
from plataformas.base import ResultadoEstado


def crear(por_hoy=True):
    page = MagicMock(url='https://restaurantes.rappi.com/menu?storeIds=AR100')
    page.wait_for_timeout = AsyncMock()
    r = Rappi(page, store_id='AR100', brand_id='AR10')
    r.cerrar_dialogo = AsyncMock()
    r._exigir_tienda = AsyncMock()
    toggle = MagicMock()
    toggle.click = AsyncMock()
    toggle.get_attribute = AsyncMock(return_value='radix-ejemplo')
    r._tarjeta = MagicMock()
    r._toggle_clickeable = MagicMock(return_value=toggle)
    dialogo = MagicMock()
    dialogo.wait_for = AsyncMock()
    page.locator.return_value = dialogo
    radio = MagicMock()
    radio.count = AsyncMock(return_value=1)
    radio.click = AsyncMock()
    dialogo.locator.return_value = radio
    etiquetas = radio.locator.return_value.locator.return_value
    etiquetas.all_text_contents = AsyncMock(return_value=[r.TXT_POR_HOY if por_hoy else r.TXT_INDEFINIDO])
    confirmar = MagicMock()
    confirmar.wait_for = AsyncMock()
    page.get_by_role.return_value = confirmar
    boton = confirmar.get_by_role.return_value
    boton.count = AsyncMock(return_value=1)
    boton.click = AsyncMock()
    r.recargar_y_preparar = AsyncMock(return_value=True)
    r.leer_estado = AsyncMock(return_value=ResultadoEstado(disponible=False, detalle='aria=false'))
    return r, toggle, dialogo, radio, etiquetas, boton


class ApagadoNuevo(unittest.IsolatedAsyncioTestCase):
    async def test_hoy_ligado_al_switch_y_confirmado_tras_recargar(self):
        r, toggle, dialogo, radio, _, boton = crear()
        self.assertTrue(await r._apagar_portal_nuevo('Producto ficticio', True))
        r.page.locator.assert_called_once_with('[role="dialog"][id="radix-ejemplo"]')
        dialogo.locator.assert_called_once_with('button[role="radio"][value="today"]')
        radio.click.assert_awaited_once()
        boton.click.assert_awaited_once()
        r.page.get_by_role.assert_called_once_with(
            'dialog', name='¿Desactivar producto?', exact=True)
        confirmar = r.page.get_by_role.return_value
        self.assertEqual(confirmar.wait_for.await_args_list, [
            unittest.mock.call(state='visible', timeout=15000),
            unittest.mock.call(state='hidden', timeout=15000),
        ])
        r.recargar_y_preparar.assert_awaited_once()
        r.leer_estado.assert_awaited_once_with('Producto ficticio')

    async def test_indefinido_y_confirmacion_adicional_acotada(self):
        r, _, dialogo, radio, _, boton = crear(False)
        self.assertTrue(await r._apagar_portal_nuevo('Producto ficticio', False))
        dialogo.locator.assert_called_once_with('button[role="radio"][value="indefinitely"]')
        radio.click.assert_awaited_once()
        boton.click.assert_awaited_once()

    async def test_confirmacion_tardia_para_ambas_duraciones(self):
        for por_hoy in (True, False):
            with self.subTest(por_hoy=por_hoy):
                r, _, _, _, _, boton = crear(por_hoy)

                async def esperar(state, timeout):
                    if state == 'visible':
                        # Reproduce un modal que aparece después del límite
                        # anterior: el timeout debe impedir seguir sin pulsar.
                        await asyncio.wait_for(asyncio.sleep(2.1), timeout / 1000)

                r.page.get_by_role.return_value.wait_for.side_effect = esperar
                self.assertTrue(await r._apagar_portal_nuevo('Producto ficticio', por_hoy))
                boton.click.assert_awaited_once()
                r.recargar_y_preparar.assert_awaited_once()

    async def test_sin_confirmacion_no_recarga_ni_declara_exito(self):
        r, _, _, _, _, boton = crear()
        r.page.get_by_role.return_value.wait_for.side_effect = TimeoutError('Sin segundo modal')
        with self.assertRaises(TimeoutError):
            await r._apagar_portal_nuevo('Producto ficticio', True)
        boton.click.assert_not_awaited()
        r.recargar_y_preparar.assert_not_awaited()
        r.leer_estado.assert_not_awaited()

    async def test_confirmacion_ambigua_no_pulsa(self):
        r, _, _, _, _, boton = crear()
        boton.count.return_value = 2
        with self.assertRaisesRegex(RuntimeError, 'inequívoca'):
            await r._apagar_portal_nuevo('Producto ficticio', True)
        boton.click.assert_not_awaited()
        r.recargar_y_preparar.assert_not_awaited()

    async def test_tienda_cambiada_antes_de_confirmar_no_pulsa(self):
        r, _, _, _, _, boton = crear()
        r._exigir_tienda.side_effect = [None, None, RuntimeError('Cambió la tienda')]
        with self.assertRaisesRegex(RuntimeError, 'Cambió la tienda'):
            await r._apagar_portal_nuevo('Producto ficticio', True)
        boton.click.assert_not_awaited()
        r.recargar_y_preparar.assert_not_awaited()

    async def test_modal_sigue_abierto_no_recarga(self):
        r, _, _, _, _, boton = crear()
        r.page.get_by_role.return_value.wait_for.side_effect = [None, TimeoutError('Sigue abierto')]
        with self.assertRaises(TimeoutError):
            await r._apagar_portal_nuevo('Producto ficticio', True)
        boton.click.assert_awaited_once()
        r.recargar_y_preparar.assert_not_awaited()

    async def test_estado_sigue_prendido_no_da_ok(self):
        r, *_ = crear()
        r.leer_estado.return_value = ResultadoEstado(disponible=True, detalle='aria=true')
        self.assertFalse(await r._apagar_portal_nuevo('Producto ficticio', True))
        r.recargar_y_preparar.assert_awaited_once()

    async def test_etiqueta_incompatible_no_selecciona(self):
        r, _, _, radio, etiquetas, _ = crear()
        etiquetas.all_text_contents.return_value = ['Personalizar disponibilidad']
        with self.assertRaisesRegex(RuntimeError, 'significado'):
            await r._apagar_portal_nuevo('Producto ficticio', True)
        radio.click.assert_not_awaited()

    async def test_opcion_duplicada_no_selecciona(self):
        r, _, _, radio, _, _ = crear()
        radio.count.return_value = 2
        with self.assertRaisesRegex(RuntimeError, 'única opción'):
            await r._apagar_portal_nuevo('Producto ficticio', True)
        radio.click.assert_not_awaited()

    async def test_tienda_cambiada_no_selecciona_duracion(self):
        r, _, _, radio, _, _ = crear()
        r._exigir_tienda.side_effect = [None, RuntimeError('Cambió la tienda')]
        with self.assertRaisesRegex(RuntimeError, 'Cambió la tienda'):
            await r._apagar_portal_nuevo('Producto ficticio', True)
        radio.click.assert_not_awaited()

    async def test_dialogo_no_identificado_no_busca_opciones_globales(self):
        r, toggle, _, radio, _, _ = crear()
        toggle.get_attribute.return_value = None
        with self.assertRaisesRegex(RuntimeError, 'identificó'):
            await r._apagar_portal_nuevo('Producto ficticio', True)
        r.page.locator.assert_not_called()
        radio.click.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
