"""Adaptador real de productos contra un DOM lxml, sin navegador ni portales.

Ejecutar con lxml instalado como dependencia de desarrollo.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock
from lxml import html
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from plataformas.rappi import Rappi
from plataformas.base import NombreAmbiguo

class Locator:
    def __init__(self, nodes): self.nodes=list(dict.fromkeys(nodes))
    @property
    def first(self): return Locator(self.nodes[:1])
    def nth(self,i): return Locator(self.nodes[i:i+1])
    async def count(self): return len(self.nodes)
    def locator(self,selector):
        if selector.startswith('xpath='): expr=selector[6:]
        elif selector=='[data-testid*="availability-switch-control"], '+Rappi.SELECTOR_TOGGLE_NUEVO:
            expr='.//*[@data-component="menu-item-availability-switch"]//button[@role="switch"]'
        elif 'button[aria-checked]' in selector:
            expr='.//*[@role="switch"] | .//input[@type="checkbox"]'
        else: raise AssertionError('Selector inesperado '+selector)
        return Locator(n for node in self.nodes for n in node.xpath(expr))
    def filter(self,has_text):
        return Locator(n for n in self.nodes if has_text.search(''.join(n.itertext())))
    def or_(self,other): return Locator(self.nodes+other.nodes)
    async def all_text_contents(self): return [''.join(n.itertext()) for n in self.nodes]
    async def inner_text(self,**kw): return ''.join(self.nodes[0].itertext())
    async def get_attribute(self,attr,**kw): return self.nodes[0].get(attr)
    async def is_checked(self): return self.nodes[0].get('checked') is not None
    async def evaluate_all(self,script):
        return [(str(i),''.join(n.itertext())[:70]) for i,n in enumerate(self.nodes)]
    async def wait_for(self,**kw):
        if not self.nodes: raise TimeoutError('Sin productos renderizados')

class Page:
    url='https://restaurantes.rappi.com/menu?storeIds=AR100'
    def __init__(self,markup): self.doc=html.fromstring('<main>'+markup+'</main>')
    def locator(self,selector):
        if selector==Rappi.SELECTOR_TOGGLE_NUEVO:
            return Locator(self.doc.xpath('.//*[@data-component="menu-item-availability-switch"]//button[@role="switch"]'))
        if selector=='input[type="password"]': return Locator([])
        if selector=='img[data-testid="catalog-item-image"]': return Locator([])
        raise AssertionError('Selector inesperado '+selector)
    def get_by_text(self,text,exact=True):
        return Locator(n for n in self.doc.iter() if not len(n) and n.text==text)

def fila(nombre,estado,descripcion=True):
    desc='<div data-component="menu-product-description"><p>Descripción</p></div>' if descripcion else ''
    return (f'<div><div><div><p>{nombre}</p></div>{desc}'
        '<div data-component="menu-product-tags"><p>Sin toppings</p></div></div>'
        '<div><span>Precio</span><span>$100</span>'
        f'<div data-component="menu-item-availability-switch"><button role="switch" aria-checked="{estado}"/></div>'
        '<button aria-label="Editar"/></div></div>')

def crear(markup):
    r=Rappi(Page(markup),store_id='AR100',brand_id='AR10')
    r.ir_al_menu=AsyncMock();r.neutralizar_estorbos=AsyncMock()
    r.huella_de_pantalla=AsyncMock(return_value='diagnóstico de pantalla')
    return r

class Filas(unittest.IsolatedAsyncioTestCase):
    async def test_lee_nombre_y_estado_con_y_sin_descripcion_ni_foto(self):
        r=crear(fila('Prueba','true')+fila('Prueba chica','false',False))
        self.assertEqual(await r.listar_productos(),['Prueba','Prueba chica'])
        self.assertEqual(await r.leer_todos(),{'Prueba':True,'Prueba chica':False})
        self.assertTrue((await r.leer_estado('Prueba')).disponible)
        self.assertIsNone(await r.leer_estado('Prueb'))

    async def test_categoria_no_cuenta_como_producto(self):
        cat='<div data-component="menu-item-availability-switch"><button role="switch" aria-checked="true"/></div>'
        r=crear(cat+fila('Prueba','false'))
        self.assertEqual(await r.listar_productos(),['Prueba'])
        self.assertEqual(await r.leer_todos(),{'Prueba':False})

    async def test_duplicados_reales_no_se_eligen_por_posicion(self):
        r=crear(fila('Duplicado','true')+fila('Duplicado','false',False))
        with self.assertRaises(NombreAmbiguo): await r.leer_estado('Duplicado')

    async def test_cero_filas_es_error_y_no_lectura_valida(self):
        r=crear('<h1>Menú</h1>')
        with self.assertRaisesRegex(RuntimeError,'filas de productos'):
            await r.leer_todos()

    async def test_asegurar_sesion_no_fuerza_filtro_otra_vez(self):
        r=crear(fila('Prueba','true'))
        r._seleccionar_tienda=AsyncMock()
        r._tienda_verificada=AsyncMock(return_value=True)
        self.assertTrue(await r.asegurar_sesion())
        self.assertTrue(await r.asegurar_sesion())
        r._seleccionar_tienda.assert_not_awaited()

    async def test_selector_renderizado_tarde_se_valida_sin_forzar(self):
        r=crear(fila('Prueba','true'))
        r._seleccionar_tienda=AsyncMock()
        r._tienda_verificada=AsyncMock(return_value=False)
        self.assertTrue(await r.asegurar_sesion())
        r._seleccionar_tienda.assert_awaited_once_with()

    async def test_estado_tienda_no_navega_a_conectividad_antigua(self):
        r=crear(fila('Prueba','true'));r.page.goto=AsyncMock()
        self.assertIsNone(await r.leer_estado_tienda())
        r.page.goto.assert_not_awaited()

if __name__=='__main__': unittest.main()
