"""Prueba selección por ids con un filtro controlado (sin portales reales)."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from plataformas.rappi import Rappi

class Opcion:
    def __init__(self, portal, campo, ident): self.p,self.campo,self.ident=portal,campo,ident
    async def count(self):
        return int(self.ident in (self.p.marcas if self.campo=='Marca' else self.p.marcas[self.p.marca]))
    async def inner_text(self): return self.p.marcas[self.p.marca][self.ident]
    async def get_attribute(self, attr):
        if attr=='value': return self.ident
        return str(self.ident==(self.p.marca if self.campo=='Marca' else self.p.tienda)).lower()
    def locator(self, _): return self
    async def click(self):
        if self.campo=='Marca':
            if self.p.marca!=self.ident: self.p.tienda=next(iter(self.p.marcas[self.ident]))
            self.p.marca=self.ident
        else: self.p.tienda=self.ident

class Lista:
    def __init__(self,p,campo): self.p,self.campo=p,campo
    def locator(self,_): return self
    async def evaluate_all(self,_): return list(self.p.marcas)
    def get_by_role(self,role,checked=False):
        return Opcion(self.p,self.campo,self.p.marca if self.campo=='Marca' else self.p.tienda)

class Portal:
    def __init__(self):
        self.marcas={'10':{'100':'Centro común','101':'Otra sucursal'},'20':{'200':'Centro Turbo'}}
        self.marca='10'; self.tienda='100'; self.url='https://restaurantes.rappi.com/menu?storeIds=AR100'
        self.nombre='Centro común'; self.aplicados=[]; self._todo_tienda=None
        self.reload=AsyncMock(); self.wait_for_selector=AsyncMock()
    def locator(self,_): return self
    async def count(self): return 1
    async def inner_text(self): return self.nombre
    async def wait_for_function(self,script,arg,timeout):
        assert self.url.endswith('storeIds='+arg['id'])
        assert self.nombre==arg['nombre']

class Panel:
    def __init__(self,p): self.p=p
    def get_by_role(self,role,name,exact):
        async def click():
            if name=='Aplicar filtro':
                self.p.aplicados.append(self.p.tienda)
                self.p.url='https://restaurantes.rappi.com/menu?storeIds=AR'+self.p.tienda
                self.p.nombre=self.p.marcas[self.p.marca][self.p.tienda]
        return SimpleNamespace(click=click)
    async def wait_for(self,**kw): pass
    async def count(self): return 1

class Seleccion(unittest.IsolatedAsyncioTestCase):
    def crear(self, tienda='AR200'):
        p=Portal(); r=Rappi(p,store_id=tienda,brand_id='AR10')
        r._lista_filtro=AsyncMock(side_effect=lambda campo: Lista(p,campo))
        r._opcion_id=lambda lista,ident: Opcion(p,lista.campo,ident)
        r._cerrar_lista_filtro=AsyncMock()
        r._abrir_filtro=AsyncMock(return_value=Panel(p))
        r._panel_tiendas=lambda: Panel(p)
        return p,r

    async def test_busca_tienda_en_otra_marca_y_recarga(self):
        p,r=self.crear()
        await r._seleccionar_tienda()
        self.assertEqual(p.aplicados,['200'])
        self.assertEqual(p._todo_tienda['store_id'],'AR200')
        p.reload.assert_awaited_once()
        await r._exigir_tienda()

    async def test_misma_tienda_no_aplica_ni_recarga(self):
        p,r=self.crear('AR100')
        await r._seleccionar_tienda(forzar=True)
        self.assertEqual(p.aplicados,[])
        p.reload.assert_not_awaited()
        self.assertTrue(await r._tienda_verificada())

    async def test_id_ausente_no_aplica_otra_sucursal(self):
        p,r=self.crear('AR999')
        with self.assertRaisesRegex(RuntimeError,'No encontré'):
            await r._seleccionar_tienda()
        self.assertEqual(p.aplicados,[])
        self.assertIsNone(p._todo_tienda)

    async def test_cambio_externo_bloquea_operacion_aun_con_url_vieja(self):
        p,r=self.crear()
        await r._seleccionar_tienda()
        p.nombre='Otra sucursal'
        with self.assertRaisesRegex(RuntimeError,'cambió de tienda'):
            await r._exigir_tienda()

    async def test_cambio_de_url_invalida_cache(self):
        p,r=self.crear()
        await r._seleccionar_tienda()
        p.url='https://restaurantes.rappi.com/menu?storeIds=AR100'
        self.assertFalse(await r._tienda_verificada())

    def test_ids_no_aceptan_selectores(self):
        for valor in ('AR200','200'):
            self.assertEqual(Rappi._id_filtro(valor),'200')
        with self.assertRaises(ValueError): Rappi._id_filtro('200"]')

if __name__=='__main__': unittest.main()
