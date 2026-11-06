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
from app.models import EstadoItem, Operacion, Producto
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
        self.w._leer_despues_de_verificar = AsyncMock()
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
        await asyncio.sleep(0)
        self.w._leer_despues_de_verificar.assert_awaited_once_with(["pedidosya"])
        await self.w._actualizar_verificacion_humana()
        self.w._leer_despues_de_verificar.assert_awaited_once()

    async def test_relectura_automatica_confirma_apagados_y_limpia_avisos(self):
        from app import main

        motor = create_engine("sqlite://", poolclass=StaticPool)
        self.addCleanup(motor.dispose)
        Base.metadata.create_all(motor)
        sesiones = sessionmaker(bind=motor, autoflush=False)
        with sesiones() as db:
            p = Producto(nombre="Flan")
            p.estados = [EstadoItem(plataforma="pedidosya",
                                   estado=EstadoItem.APAGADO_HOY,
                                   verificado_en=datetime.now() - timedelta(hours=2))]
            db.add(p)
            db.commit()
            ident = p.id
        self.w.no_encontrados["pedidosya"] = [{
            "producto_id": ident, "plataforma": "pedidosya"}]
        self.w._leer_despues_de_verificar = (
            Worker._leer_despues_de_verificar.__get__(self.w))
        self.w._preparar = AsyncMock(return_value=(True, ""))
        self.plat.leer_todos = AsyncMock(return_value={"Flan": False})
        self.plat.categorias_de_productos = AsyncMock(return_value={})
        terminado = asyncio.Event()

        async def tiendas():
            terminado.set()

        self.w._refrescar_estado_tiendas = tiendas
        with patch.object(modulo_worker, "SessionLocal", sesiones), \
             patch.object(main, "worker", self.w), \
             patch.object(modulo_worker.config, "activo", return_value=True):
            with sesiones() as db:
                self.assertEqual(len(main.alertas(db)["sin_confirmar"]), 1)
            await self.w._actualizar_verificacion_humana()
            self.pagina.captcha = False
            await self.w._actualizar_verificacion_humana()
            await asyncio.wait_for(terminado.wait(), timeout=1)
            with sesiones() as db:
                est = db.query(EstadoItem).one()
                self.assertEqual(est.estado, EstadoItem.APAGADO_HOY)
                self.assertLess((datetime.now() - est.verificado_en).total_seconds(), 1)
                self.assertEqual(main.alertas(db)["sin_confirmar"], [])
            self.assertEqual(self.w.no_encontrados["pedidosya"], [])
            self.plat.leer_todos.assert_awaited_once()

    async def test_otro_captcha_durante_relectura_no_guarda_ni_sella_hora(self):
        self.pagina.captcha = False
        self.w._preparar = AsyncMock(return_value=(True, ""))
        self.plat.leer_todos = AsyncMock(side_effect=VerificacionHumanaPendiente())
        self.w._guardar_estados = Mock()
        self.w.no_encontrados["pedidosya"] = ["aviso previo"]
        resultado = await self.w.sincronizar_estados("pedidosya")
        self.assertIn("error", resultado["pedidosya"])
        self.assertTrue(self.w.en_verificacion("pedidosya"))
        self.w._guardar_estados.assert_not_called()
        self.assertIsNone(self.w.ultima_lectura)
        self.assertEqual(self.w.no_encontrados["pedidosya"], ["aviso previo"])

    async def test_relectura_respeta_sostener_y_confirma_revividos(self):
        self.w.sincronizar_estados = AsyncMock(return_value={
            "pedidosya": {"revividos": [{"producto_id": 1}]}})
        self.w._reencolar_si_revivio = AsyncMock()
        self.w._refrescar_estado_tiendas = AsyncMock()
        with patch.object(modulo_worker.config, "activo", return_value=True):
            await Worker._leer_despues_de_verificar(self.w, ["pedidosya"])
        self.w.sincronizar_estados.assert_awaited_once_with("pedidosya", sostener=True)
        self.w._reencolar_si_revivio.assert_awaited_once_with({"producto_id": 1})

    async def test_lector_no_devuelve_carta_vacia_como_lectura_valida(self):
        self.pagina.captcha = False
        self.plat.ir_al_menu = AsyncMock()
        vacio = Mock(count=AsyncMock(return_value=0))
        with patch.object(self.pagina, "locator", return_value=vacio):
            # No hay indicadores de CAPTCHA ni categorías.
            with self.assertRaisesRegex(RuntimeError, "categorías"):
                await self.plat.leer_todos()

    async def test_lector_corta_si_captcha_aparece_en_la_ultima_categoria(self):
        self.pagina.captcha = False
        self.plat.ir_al_menu = AsyncMock()
        categorias = Mock(count=AsyncMock(return_value=1))
        filas = Mock(count=AsyncMock(return_value=0))
        locator_original = self.pagina.locator

        def locator(selector):
            if selector == PedidosYa.SELECTOR_CATEGORIAS:
                return categorias
            if selector == "label.mat-slide-toggle-label":
                return filas
            return locator_original(selector)

        async def abrir(indice):
            self.pagina.captcha = True

        self.plat._abrir_categoria = AsyncMock(side_effect=abrir)
        with patch.object(self.pagina, "locator", side_effect=locator):
            with self.assertRaises(VerificacionHumanaPendiente):
                await self.plat.leer_todos()

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
