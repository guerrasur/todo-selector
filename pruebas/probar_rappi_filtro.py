"""Regresión del drawer fuera del viewport y de errores tapados al cerrar.

Los casos async no usan navegador. La geometría ejecuta el JS de producción
con Node sobre cajas controladas, incluidas las de un drawer translateX(-100%).
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

class Paneles:
    def __init__(self, p): self.p=p
    async def evaluate_all(self, script): return [0] if self.p.abierto else []
    def nth(self, i): return self
    def get_by_role(self, role, name, exact): return self.p.cierre

class Filtro(unittest.IsolatedAsyncioTestCase):
    def crear(self):
        p=SimpleNamespace(abierto=False)
        async def abrir(**kw): p.abierto=True
        async def cerrar(*args, **kw): p.abierto=False
        p.disparador=SimpleNamespace(click=AsyncMock(side_effect=abrir))
        p.cierre=SimpleNamespace(count=AsyncMock(return_value=1),
            click=AsyncMock(side_effect=cerrar),evaluate=AsyncMock(side_effect=cerrar))
        p.locator=lambda _:p.disparador
        p.wait_for_timeout=AsyncMock()
        r=Rappi(p,store_id='AR100',brand_id='AR10')
        r._panel_tiendas=lambda:Paneles(p)
        return p,r

    async def test_panel_montado_fuera_de_pantalla_requiere_abrir(self):
        p,r=self.crear()
        self.assertIsNone(await r._panel_abierto())
        self.assertIsNotNone(await r._abrir_filtro())
        p.disparador.click.assert_awaited_once_with(timeout=5000)

    async def test_panel_abierto_no_vuelve_a_pulsar_disparador(self):
        p,r=self.crear(); p.abierto=True
        await r._abrir_filtro()
        p.disparador.click.assert_not_awaited()

    async def test_panel_cerrado_no_intenta_clicar_close_fuera_de_pantalla(self):
        p,r=self.crear()
        await r._cerrar_filtro()
        p.cierre.click.assert_not_awaited()
        p.cierre.evaluate.assert_not_awaited()

    async def test_cierre_fuera_de_viewport_invoca_handler_y_confirma_cerrado(self):
        p,r=self.crear(); p.abierto=True
        p.cierre.click.side_effect=TimeoutError('outside viewport')
        await r._cerrar_filtro()
        p.cierre.click.assert_awaited_once_with(timeout=2000)
        p.cierre.evaluate.assert_awaited_once()
        self.assertFalse(p.abierto)

    async def test_cierre_normal_no_necesita_js(self):
        p,r=self.crear(); p.abierto=True
        await r._cerrar_filtro()
        p.cierre.evaluate.assert_not_awaited()
        self.assertIsNone(await r._panel_abierto())

    async def test_limpieza_fallida_conserva_error_de_seleccion(self):
        p,r=self.crear(); p.url='https://restaurantes.rappi.com/menu?storeIds=AR100'
        r._lista_filtro=AsyncMock(side_effect=ValueError('error original de Marca'))
        r._cerrar_filtro=AsyncMock(side_effect=TimeoutError('Close fuera de pantalla'))
        with self.assertLogs('rappi',level='WARNING'):
            with self.assertRaisesRegex(ValueError,'error original de Marca'):
                await r._seleccionar_tienda(forzar=True)
        self.assertIsNone(p._todo_tienda)

    def test_js_descarta_drawer_desplazado_y_conserva_panel_activo(self):
        script=r'''
const fs=require('fs'), assert=require('assert/strict');
const geometria=eval('('+fs.readFileSync(0,'utf8')+')');
global.innerWidth=1000; global.innerHeight=700;
global.getComputedStyle=e=>e.estilo;
const panel=(left,top,right,bottom,oculto=false)=>({
 getBoundingClientRect:()=>({left,top,right,bottom}),
 closest:()=>oculto?{}:null,estilo:{display:'flex',visibility:'visible'}
});
const fuera=panel(-480,0,0,700), abierto=panel(0,0,480,700);
assert.deepEqual(geometria([fuera]),[]);
assert.deepEqual(geometria([fuera,abierto]),[1]);
assert.deepEqual(geometria([panel(1000,0,1480,700)]),[]);
assert.deepEqual(geometria([panel(0,700,480,1400)]),[]);
assert.deepEqual(geometria([panel(0,0,480,700,true)]),[]);
assert.deepEqual(geometria([panel(-400,0,80,700)]),[0]);
const hidden=panel(0,0,480,700);hidden.estilo.visibility='hidden';
assert.deepEqual(geometria([hidden]),[]);
'''
        p=subprocess.run(['node','-e',script],input=Rappi.JS_PANELES_EN_PANTALLA,
            text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stderr)

if __name__=='__main__': unittest.main()
