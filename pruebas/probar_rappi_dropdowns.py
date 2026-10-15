"""Flujo de selección con dropdowns que ignoran Escape.

Ejecuta la apertura/cierre real de listas y _seleccionar_tienda sobre un portal
controlado; prueba tanto opciones que cierran la lista como las que la dejan.
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from plataformas.rappi import Rappi

class Control:
    def __init__(self,p,campo): self.p,self.campo=p,campo
    def locator(self,_): return self
    async def count(self): return 1
    async def click(self,**kw):
        if self.campo=='Aplicar filtro':
            if self.p.lista is not None: raise RuntimeError('Aplicar quedó tapado por lista abierta')
            self.p.aplicados.append(self.p.tienda)
            self.p.url='https://restaurantes.rappi.com/menu?storeIds=AR'+self.p.tienda
            self.p.nombre=self.p.marcas[self.p.marca][self.p.tienda]
        else:
            self.p.lista=None if self.p.lista==self.campo else self.campo
            self.p.clicks.append(self.campo)

class Opcion:
    def __init__(self,p,campo,ident): self.p,self.campo,self.ident=p,campo,ident
    async def count(self):
        return int(self.ident in (self.p.marcas if self.campo=='Marca' else self.p.marcas[self.p.marca]))
    def locator(self,_): return self
    async def get_attribute(self,attr):
        if attr=='value': return self.ident
        return str(self.ident==(self.p.marca if self.campo=='Marca' else self.p.tienda)).lower()
    async def inner_text(self): return self.p.marcas[self.p.marca][self.ident]
    async def click(self):
        assert self.p.lista==self.campo,'Se intentó elegir en una lista cerrada'
        if self.campo=='Marca':
            if self.ident!=self.p.marca: self.p.tienda=next(iter(self.p.marcas[self.ident]))
            self.p.marca=self.ident
        else: self.p.tienda=self.ident
        if self.p.autocierre: self.p.lista=None

class Lista:
    def __init__(self,p,campo): self.p,self.campo=p,campo
    async def evaluate_all(self,js):
        if 'els.map(e => e.value)' in js: return list(self.p.marcas)
        return [0] if self.p.lista==self.campo else []
    def nth(self,i): return self
    def locator(self,_): return self
    def get_by_role(self,role,checked=False):
        if checked:
            return Opcion(self.p,self.campo,self.p.marca if self.campo=='Marca' else self.p.tienda)
        return self
    def filter(self,has): return Opcion(self.p,self.campo,has.ident)

class Panel:
    def __init__(self,p): self.p=p
    def get_by_text(self,campo,exact): return Control(self.p,campo)
    def get_by_role(self,role,name,exact): return Control(self.p,name)

class Portal:
    def __init__(self,autocierre):
        self.marcas={'10':{'100':'Centro común','101':'Sucursal distinta'},'20':{'200':'Centro Turbo'}}
        self.marca='10';self.tienda='100';self.nombre='Centro común'
        self.url='https://restaurantes.rappi.com/menu?storeIds=AR100'
        self.lista=None;self.clicks=[];self.aplicados=[];self.autocierre=autocierre
        self.keyboard=SimpleNamespace(press=AsyncMock())
        self.reload=AsyncMock();self.wait_for_selector=AsyncMock();self.wait_for_timeout=AsyncMock()
    def locator(self,selector):
        if 'button[role="radio"][value=' in selector:
            return SimpleNamespace(ident=selector.split('value="')[1].split('"')[0])
        return Lista(self,'Tienda' if selector=='[data-component="store-list"]' else 'Marca')

def adaptador(p,tienda):
    r=Rappi(p,store_id=tienda,brand_id='AR10')
    r._abrir_filtro=AsyncMock(return_value=Panel(p))
    r._esperar_panel=AsyncMock()
    r._nombre_tienda_actual=AsyncMock(side_effect=lambda:p.nombre)
    return r

class Dropdowns(unittest.IsolatedAsyncioTestCase):
    async def test_lista_abierta_se_reutiliza_sin_toggle(self):
        p=Portal(False);r=adaptador(p,'AR200');p.lista='Marca'
        await r._lista_filtro('Marca')
        self.assertEqual(p.clicks,[])
        self.assertEqual(p.lista,'Marca')

    async def test_cierre_toca_disparador_y_no_escape(self):
        p=Portal(False);r=adaptador(p,'AR200');p.lista='Marca'
        await r._cerrar_lista_filtro()
        self.assertIsNone(p.lista)
        self.assertEqual(p.clicks,['Marca'])
        p.keyboard.press.assert_not_awaited()

    async def test_flujo_completo_aplica_ambas_tiendas_con_y_sin_autocierre(self):
        for autocierre in (False,True):
            with self.subTest(autocierre=autocierre):
                p=Portal(autocierre)
                turbo=adaptador(p,'AR200');comun=adaptador(p,'AR100')
                await turbo._seleccionar_tienda(forzar=True)
                self.assertEqual(p.aplicados,['200'])
                self.assertEqual(p._todo_tienda['store_id'],'AR200')
                await comun._seleccionar_tienda(forzar=True)
                self.assertEqual(p.aplicados,['200','100'])
                self.assertEqual(p._todo_tienda['store_id'],'AR100')
                p.keyboard.press.assert_not_awaited()

    async def test_seleccion_ya_verificada_no_repite_aplicar(self):
        p=Portal(False);r=adaptador(p,'AR200')
        await r._seleccionar_tienda()
        await r._seleccionar_tienda()
        self.assertEqual(p.aplicados,['200'])
        self.assertEqual(p.reload.await_count,1)

    async def test_misma_tienda_tambien_pulsa_aplicar_una_vez(self):
        p=Portal(False);r=adaptador(p,'AR100')
        await r._seleccionar_tienda(forzar=True)
        self.assertEqual(p.aplicados,['100'])
        p.reload.assert_not_awaited()

if __name__=='__main__': unittest.main()
