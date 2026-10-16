"""Tabla real de Gestión de tiendas, nombres ficticios, sin acceso al portal.

NODE_PATH=/tmp/rappi-dom-test/node_modules python pruebas/probar_rappi_estado_tienda_nuevo.py
Requiere linkedom solo para las pruebas de DOM (no para la app).
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plataformas.rappi import Rappi


def fila(nombre, badge='Activo', checked=True):
    return ('<tr data-slot="table-row"><td data-slot="table-cell">' + nombre +
            '</td><td data-slot="table-cell"><div data-slot="badge"><span>' + badge +
            '</span></div></td><td data-slot="table-cell"><label data-component="Toggle">'
            '<input type="checkbox"' + (' checked' if checked else '') +
            '></label></td><td data-slot="table-cell">Hasta horario de prueba</td></tr>')


def tabla(filas):
    return ('<table data-slot="table-content"><thead><tr><th>Nombre tienda</th>'
            '<th>Estado</th></tr></thead><tbody data-slot="table-body">' + filas + '</tbody></table>')


def capturar(markup, nombre):
    runner = r'''
const fs=require('fs'),assert=require('assert/strict'),{parseHTML}=require('linkedom');
const d=JSON.parse(fs.readFileSync(0,'utf8'));
global.document=parseHTML('<html><body>'+d.html+'</body></html>').document;
global.getComputedStyle=e=>({display:e.style.display || 'block',visibility:e.style.visibility || 'visible'});
for (const input of document.querySelectorAll('input')) input.checked=input.hasAttribute('checked');
const antes=document.toString();
const salida=eval('('+d.js+')')(d.nombre);
assert.equal(document.toString(),antes,'La lectura modificó el DOM');
console.log(JSON.stringify(salida));
'''
    r = subprocess.run(['node', '-e', runner], input=json.dumps({
        'html': markup, 'nombre': nombre, 'js': Rappi.JS_TABLA_ESTADOS,
    }), text=True, capture_output=True, check=True)
    return json.loads(r.stdout)


class TablaTiendas(unittest.TestCase):
    def test_lee_cada_tienda_por_nombre_exacto_sin_pulsar_toggles(self):
        html = tabla(fila('Sucursal Turbo') + fila('Sucursal común', 'Inactivo', False))
        self.assertTrue(capturar(html, 'Sucursal Turbo')['abierta'])
        self.assertFalse(capturar(html, 'Sucursal común')['abierta'])

    def test_no_adivina_por_orden_prefijo_o_por_ser_unica(self):
        html = tabla(fila('Sucursal Turbo'))
        for nombre in ('Sucursal', 'Sucursal común', 'sucursal turbo'):
            self.assertNotIn('abierta', capturar(html, nombre))

    def test_duplicados_y_tablas_duplicadas_no_se_elige_la_primera(self):
        self.assertEqual(capturar(tabla(fila('Sucursal') * 2), 'Sucursal')['coincidencias'], 2)
        self.assertNotIn('abierta', capturar(tabla(fila('Sucursal')) * 2, 'Sucursal'))

    def test_estado_inconsistente_o_desconocido_no_inventa_disponibilidad(self):
        for badge, checked in [('Activo', False), ('Inactivo', True), ('Desconocido', False)]:
            self.assertNotIn('abierta', capturar(tabla(fila('Sucursal', badge, checked)), 'Sucursal'))

    def test_toggle_ausente_no_infiere_desde_el_badge(self):
        html = tabla(fila('Sucursal')).replace('data-component="Toggle"', 'data-component="otro"')
        self.assertNotIn('abierta', capturar(html, 'Sucursal'))


class NavegacionTiendas(unittest.IsolatedAsyncioTestCase):
    def crear(self):
        page = SimpleNamespace(url='https://restaurantes.rappi.com/menu?storeIds=AR100',
                               _todo_tienda={'store_id': 'AR100', 'nombre': 'Sucursal Turbo'})
        async def goto(url, **kw):
            page.url = url
        page.goto = AsyncMock(side_effect=goto)
        page.evaluate = AsyncMock(return_value={'abierta': True, 'badge': 'Activo', 'observaciones': 'Hasta horario de prueba'})
        page.wait_for_timeout = AsyncMock()
        r = Rappi(page, store_id='AR100', brand_id='AR10')
        r.en_verificacion = AsyncMock(return_value=False)
        r.ir_al_menu = AsyncMock()
        return r

    async def test_lee_stores_filtrado_y_vuelve_al_menu(self):
        r = self.crear()
        resultado = await r.leer_estado_tienda()
        self.assertTrue(resultado.abierta)
        self.assertIn('Hasta horario', resultado.detalle)
        r.page.goto.assert_awaited_once_with('https://restaurantes.rappi.com/stores?storeIds=AR100', wait_until='domcontentloaded')
        r.page.evaluate.assert_awaited_once_with(r.JS_TABLA_ESTADOS, 'Sucursal Turbo')
        r.ir_al_menu.assert_awaited_once()

    async def test_tabla_tardia_espera_sin_recargar(self):
        r = self.crear()
        r.page.evaluate.side_effect = [{'motivo': 'No cargó'}, {'abierta': False, 'badge': 'Inactivo'}]
        self.assertFalse((await r.leer_estado_tienda()).abierta)
        r.page.wait_for_timeout.assert_awaited_once_with(200)
        self.assertEqual(r.page.goto.await_count, 1)

    async def test_sin_nombre_confirmado_no_navega(self):
        r = self.crear()
        r.page._todo_tienda['store_id'] = 'AR200'
        self.assertIsNone(await r.leer_estado_tienda())
        r.page.goto.assert_not_awaited()

    async def test_redireccion_no_lee_otra_tienda(self):
        r = self.crear()
        async def redirect(*args, **kw):
            r.page.url = 'https://restaurantes.rappi.com/stores?storeIds=AR200'
        r.page.goto.side_effect = redirect
        self.assertIsNone(await r.leer_estado_tienda())
        r.page.evaluate.assert_not_awaited()
        r.ir_al_menu.assert_awaited_once()

    async def test_verificacion_que_aparece_no_se_cierra(self):
        r = self.crear()
        r.en_verificacion.side_effect = [False, True]
        async def verificar(*args, **kw):
            r.page.url = 'https://restaurantes.rappi.com/verification'
        r.page.goto.side_effect = verificar
        self.assertIsNone(await r.leer_estado_tienda())
        r.page.evaluate.assert_not_awaited()
        r.ir_al_menu.assert_not_awaited()

    async def test_verificacion_preexistente_no_se_navega(self):
        r = self.crear()
        r.en_verificacion.return_value = True
        self.assertIsNone(await r.leer_estado_tienda())
        r.page.goto.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
