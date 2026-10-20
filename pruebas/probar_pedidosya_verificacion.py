"""Regresiones de bloqueo y cola; sin conectar con los portales.

    python pruebas/probar_pedidosya_verificacion.py
"""
import asyncio
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import worker as modulo_worker
from app.database import Base
from app.models import Operacion, Producto
from app.worker import Worker, VERIFICACION
from plataformas.base import PlataformaBase
from plataformas.pedidosya import PedidosYa, VerificacionHumanaPendiente


class Indicadores:
    """Contenedor visible e iframe oculto, como en el HTML recibido."""
    def __init__(self, pagina, menu=False, indice=0):
        self.pagina, self.menu, self.indice = pagina, menu, indice

    @property
    def first(self):
        return self

    async def count(self):
        return 1 if self.menu else 2

    def nth(self, indice):
        return Indicadores(self.pagina, self.menu, indice)

    async def is_visible(self):
        if self.pagina.error:
            raise RuntimeError("pestaña no disponible")
        if self.menu:
            return self.pagina.menu
        return self.pagina.captcha and self.indice == 0


class Pagina:
    def __init__(self):
        self.url = "https://web-ar.us.restaurant-partners.com/menus/PY_AR/LOCAL"
        self.captcha, self.menu, self.error = True, True, False
        self.frames = [self]
        self.reload = AsyncMock()
        self.goto = AsyncMock()
        self.wait_for_timeout = AsyncMock()
        self.wait_for_selector = AsyncMock()
        self.keyboard = Mock(press=AsyncMock())

    def locator(self, selector):
        if selector == PedidosYa.SELECTOR_VERIFICACION:
            return Indicadores(self)
        if selector == "label.mat-slide-toggle-label":
            return Indicadores(self, menu=True)
        raise AssertionError(f"Consulta inesperada: {selector}")


class VerificacionPedidosYa(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.pagina = Pagina()
        self.plat = PedidosYa(self.pagina, menu_id="LOCAL")
        self.w = Worker()
        self.w.modo_simulado = False
        self.w.plataformas = {"pedidosya": self.plat}
        self.w.ultimo_refresco["pedidosya"] = datetime.now() - timedelta(hours=3)
        self.parches = [
            patch.object(modulo_worker.config, "plataformas_activas",
                         return_value=["pedidosya", "rappi"]),
            patch.object(modulo_worker.config, "familia_de_sesion",
                         side_effect=lambda nombre, **kw: [nombre]),
            patch.object(modulo_worker.config, "entero", return_value=3),
        ]
        for parche in self.parches:
            parche.start()
            self.addCleanup(parche.stop)

    async def test_contenedor_visible_con_iframe_oculto(self):
        self.assertTrue(await self.plat.en_verificacion())
        self.pagina.captcha = False
        self.assertFalse(await self.plat.en_verificacion())

    async def test_indicador_dentro_de_otro_marco(self):
        marco = Pagina()
        self.pagina.captcha = False
        self.pagina.frames.append(marco)
        self.assertTrue(await self.plat.en_verificacion())

    async def test_menu_detras_no_es_sesion_lista(self):
        self.assertFalse(await self.plat.asegurar_sesion())
        self.pagina.goto.assert_not_awaited()

    async def test_preparar_no_recarga_ni_navega(self):
        listo, mensaje = await self.w._preparar("pedidosya")
        self.assertFalse(listo)
        self.assertIn("Press & Hold", mensaje)
        self.assertTrue(self.w.en_verificacion("pedidosya"))
        self.pagina.reload.assert_not_awaited()
        self.pagina.goto.assert_not_awaited()

    async def test_corta_clicks_js_recargas_y_cierre_de_popups(self):
        for metodo in (
            lambda: self.plat.clickear(Mock()),
            lambda: self.plat.clickear_por_js(Mock()),
            lambda: self.plat.recargar_y_preparar(),
            lambda: self.plat._cerrar_popups(),
            lambda: self.plat.ir_al_menu(),
        ):
            with self.assertRaises(VerificacionHumanaPendiente):
                await metodo()
        self.pagina.reload.assert_not_awaited()
        self.pagina.keyboard.press.assert_not_awaited()

    async def test_aparece_durante_click_no_llega_al_fallback(self):
        self.pagina.captcha = False
        objetivo = Mock()
        objetivo.first = objetivo
        objetivo.evaluate = AsyncMock()

        async def click(**kw):
            self.pagina.captcha = True
            raise RuntimeError("intercepts pointer events")

        objetivo.click = AsyncMock(side_effect=click)
        with patch.object(PlataformaBase, "clickear_por_js", new_callable=AsyncMock) as js:
            with self.assertRaises(VerificacionHumanaPendiente):
                await self.plat.clickear(objetivo)
            js.assert_not_awaited()

    async def test_boton_no_libera_desafio_pendiente(self):
        await self.w._actualizar_verificacion_humana()
        salida = await self.w.terminar_verificacion("pedidosya", leer=False)
        self.assertEqual(salida["liberadas"], [])
        self.assertTrue(self.w.en_verificacion("pedidosya"))

    async def test_no_libera_pagina_vacia_error_ni_solo_por_tiempo(self):
        await self.w._actualizar_verificacion_humana()
        self.w.verificacion["pedidosya"]["desde"] -= timedelta(days=2)
        await self.w._actualizar_verificacion_humana()
        self.pagina.captcha, self.pagina.menu = False, False
        await self.w._actualizar_verificacion_humana()
        self.pagina.error = True
        await self.w._actualizar_verificacion_humana()
        self.assertTrue(self.w.en_verificacion("pedidosya"))
        self.pagina.reload.assert_not_awaited()

    async def test_retoma_solo_con_menu_visible(self):
        await self.w._actualizar_verificacion_humana()
        self.pagina.captcha = False  # simula que el usuario completó la prueba
        await self.w._actualizar_verificacion_humana()
        self.assertFalse(self.w.en_verificacion("pedidosya"))
        self.assertTrue(self.w.sesion_ok["pedidosya"])
        self.assertLess((datetime.now() - self.w.ultimo_refresco["pedidosya"]).total_seconds(), 1)
        self.pagina.reload.assert_not_awaited()

    async def test_no_libera_pausas_manuales_ni_rappi(self):
        self.w.empezar_verificacion("pedidosya")
        self.w.empezar_verificacion("rappi")
        self.pagina.captcha = False
        await self.w._actualizar_verificacion_humana()
        self.assertEqual(set(self.w.verificacion), {"pedidosya", "rappi"})

    async def test_sondeo_no_bloquea_otras_tiendas(self):
        async with self.w.bloqueo("pedidosya"):
            await asyncio.wait_for(self.w._actualizar_verificacion_humana(), timeout=0.2)

    async def test_aparece_durante_operacion_sin_gastar_intento(self):
        # SQLite aislada: se ejercita la cola real, sin cambiar datos del usuario.
        motor = create_engine("sqlite://", poolclass=StaticPool)
        self.addCleanup(motor.dispose)
        Base.metadata.create_all(motor)
        sesiones = sessionmaker(bind=motor, autoflush=False)
        with sesiones() as db:
            p = Producto(nombre="Flan")
            db.add(p)
            db.flush()
            op = Operacion(producto_id=p.id, plataforma="pedidosya", accion="prender")
            db.add(op)
            db.commit()
            ident = op.id
        self.pagina.captcha = False
        self.w._preparar = AsyncMock(return_value=(True, ""))

        async def prender(nombre):
            self.pagina.captcha = True
            raise VerificacionHumanaPendiente("verificación pendiente")

        self.plat.prender = AsyncMock(side_effect=prender)
        with patch.object(modulo_worker, "SessionLocal", sesiones):
            await self.w._procesar_pendientes()
            await self.w._procesar_pendientes()
            with sesiones() as db:
                op = db.get(Operacion, ident)
                self.assertEqual((op.estado, op.intentos), (Operacion.PENDIENTE, 0))
            self.plat.prender.assert_awaited_once()
            self.pagina.captcha = False
            await self.w._actualizar_verificacion_humana()
            self.plat.prender = AsyncMock(return_value=True)
            await self.w._procesar_pendientes()
            with sesiones() as db:
                self.assertEqual(db.get(Operacion, ident).estado, Operacion.OK)


if __name__ == "__main__":
    unittest.main(verbosity=2)
