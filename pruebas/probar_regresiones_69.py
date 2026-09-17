"""Regresiones v6.9: SQLite temporal y adaptadores falsos, sin portales.

Ejecutar: python pruebas/probar_regresiones_69.py
"""
import asyncio
import logging
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
TEMPORAL = tempfile.TemporaryDirectory(prefix="todo-selector-69-")
with (patch.object(Path, "home", return_value=Path(TEMPORAL.name)),
      patch.dict(os.environ, {"LOCALAPPDATA": TEMPORAL.name})):
    from app import config, cola
    from app.database import Base, engine, init_db, SessionLocal
    from app.models import Producto, EstadoItem, Operacion
    from app.main import encolar_accion, AccionIn, cancelar, CancelarIn
    from app.worker import Worker, DURACION_NO_CONFIRMADA
    from plataformas.base import DuracionNoConfirmada, ResultadoEstado
    from plataformas.rappi import Rappi
    from plataformas.pedidosya import PedidosYa

logging.disable(logging.CRITICAL)


class Regresiones(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        Base.metadata.drop_all(engine)
        init_db()
        config._cache = None
        with SessionLocal() as db:
            config.guardar(db, {"verificacion_rapida": 0})
            db.commit()
            producto = Producto(nombre="Producto de prueba")
            db.add(producto)
            db.flush()
            self.pid = producto.id
            db.add(EstadoItem(producto_id=self.pid, plataforma="rappi",
                              estado=EstadoItem.PRENDIDO))
            db.commit()
        self.w = Worker()
        self.w.corriendo = True
        self.w.modo_simulado = False
        self.w._preparar = AsyncMock(return_value=(True, ""))
        self.plat = SimpleNamespace(
            page=SimpleNamespace(wait_for_timeout=AsyncMock()),
            leer_estado=AsyncMock(return_value=ResultadoEstado(True)))
        self.w.plataformas["rappi"] = self.plat

    def pedir(self, accion):
        with SessionLocal() as db:
            return encolar_accion(AccionIn(producto_id=self.pid,
                                 plataformas=["rappi"], accion=accion), db)

    def poner(self, estado):
        with SessionLocal() as db:
            est = db.query(EstadoItem).first()
            est.estado = estado
            est.verificado_en = datetime(2020, 1, 1)
            db.commit()

    def leer(self):
        with SessionLocal() as db:
            est = db.query(EstadoItem).first()
            return est.estado, est.verificado_en

    def ops(self):
        with SessionLocal() as db:
            return [(o.id, o.accion, o.estado) for o in
                    db.query(Operacion).order_by(Operacion.id)]

    def caso(self):
        with SessionLocal() as db:
            return dict(producto_id=self.pid, producto="Producto de prueba",
                        nombre_remoto="Producto de prueba", plataforma="rappi",
                        estado=EstadoItem.APAGADO_HOY,
                        operacion_id=cola.ultima_id(db, self.pid, "rappi"))

    async def test_indefinido_apagado_no_inventa_ni_reabre(self):
        for clase in (Rappi, PedidosYa):
            falsa = SimpleNamespace(revisar_ambiguedad=AsyncMock(),
                       leer_estado=AsyncMock(return_value=ResultadoEstado(False)),
                       prender=AsyncMock())
            with self.assertRaises(DuracionNoConfirmada):
                await clase.apagar(falsa, "Producto de prueba", por_hoy=False)
            falsa.prender.assert_not_called()
            self.assertTrue(await clase.apagar(falsa, "Producto de prueba", por_hoy=True))

    async def test_duracion_no_se_reintenta_y_no_se_marca_indefinido(self):
        self.pedir("apagar_indef")
        self.plat.configurado = True
        self.plat.apagar = AsyncMock(side_effect=DuracionNoConfirmada("Cambiar en portal"))
        await self.w._procesar_pendientes()
        self.assertEqual(self.leer()[0], EstadoItem.FALLO)
        with SessionLocal() as db:
            op = db.query(Operacion).first()
            self.assertEqual(op.estado, Operacion.ERROR)
            self.assertTrue(op.reintentada)
            self.assertEqual(op.intentos, 1)
            op.finalizada_en = datetime(2020, 1, 1)
            db.commit()
        self.assertEqual(self.w._reencolar_fallidas(), [])

    async def test_ultima_orden_gana_sobre_reintento(self):
        self.w._ejecutar = AsyncMock(side_effect=[(False, "fallo", ""), (True, "", "")])
        self.pedir("apagar_hoy")
        await self.w._procesar_pendientes()
        self.pedir("prender")
        await self.w._procesar_pendientes()
        with SessionLocal() as db:
            db.query(Operacion).update({"reintentar_en": datetime(2020, 1, 1)})
            db.commit()
        await self.w._procesar_pendientes()
        self.assertEqual(self.w._ejecutar.await_count, 2)
        self.assertEqual(self.leer()[0], EstadoItem.PRENDIDO)
        self.assertEqual(self.ops()[0][2], Operacion.CANCELADA)

    async def test_reintento_heredado_de_version_anterior_no_pasa_por_la_orden_nueva(self):
        self.poner(EstadoItem.APAGANDO)
        with SessionLocal() as db:
            db.add(Operacion(producto_id=self.pid, plataforma="rappi",
                             accion="apagar_hoy", estado=Operacion.PENDIENTE))
            db.flush()
            db.add(Operacion(producto_id=self.pid, plataforma="rappi",
                             accion="prender", estado=Operacion.OK))
            db.commit()
        self.w._ejecutar = AsyncMock()
        await self.w._procesar_pendientes()
        self.w._ejecutar.assert_not_called()
        self.assertEqual(self.ops()[0][2], Operacion.CANCELADA)
        self.assertEqual(self.leer()[0], EstadoItem.DESCONOCIDO)

    async def test_tres_cambios_rapidos_no_se_deduplican_con_la_primera_orden(self):
        self.pedir("apagar_hoy")
        self.pedir("prender")
        self.assertEqual(self.pedir("apagar_hoy")["encoladas"], ["rappi"])
        self.assertEqual([o[2] for o in self.ops()],
                         [Operacion.CANCELADA, Operacion.CANCELADA, Operacion.PENDIENTE])
        self.assertEqual(self.pedir("apagar_hoy")["encoladas"], [])

    async def test_cancelar_en_curso_fallida_sale_del_transitorio(self):
        self.pedir("apagar_hoy")
        async def ejecutar(*args):
            with SessionLocal() as db:
                cancelar(CancelarIn(todo=True), db)
            return False, "fallo", ""
        self.w._ejecutar = ejecutar
        await self.w._procesar_pendientes()
        self.assertEqual(self.leer()[0], EstadoItem.DESCONOCIDO)
        self.assertEqual(self.ops()[0][2], Operacion.CANCELADA)

    async def test_orden_nueva_durante_intento_exitoso_sigue_visible(self):
        self.pedir("apagar_hoy")
        async def ejecutar(*args):
            self.pedir("prender")
            return True, "", ""
        self.w._ejecutar = ejecutar
        await self.w._procesar_pendientes()
        self.assertEqual(self.leer()[0], EstadoItem.PRENDIENDO)

    async def test_orden_nueva_durante_intento_fallido_no_se_reintenta(self):
        self.pedir("apagar_hoy")
        async def ejecutar(*args):
            self.pedir("prender")
            return False, "fallo", ""
        self.w._ejecutar = ejecutar
        await self.w._procesar_pendientes()
        self.assertEqual(self.leer()[0], EstadoItem.PRENDIENDO)
        self.assertEqual(self.ops()[0][2], Operacion.CANCELADA)

    async def test_lectura_nula_no_confirma(self):
        self.poner(EstadoItem.APAGADO_HOY)
        self.plat.leer_estado.return_value = None
        await self.w._verificar_luego(self.pid, "rappi", "apagar_hoy", 0)
        self.assertEqual(self.leer()[1], datetime(2020, 1, 1))
        await self.w._reencolar_si_revivio(self.caso())
        self.assertEqual(self.leer()[1], datetime(2020, 1, 1))
        self.assertEqual(self.ops(), [])

    async def test_segunda_lectura_nula_no_sostiene_la_primera(self):
        self.poner(EstadoItem.APAGADO_HOY)
        self.plat.leer_estado.side_effect = [ResultadoEstado(True), None]
        await self.w._verificar_luego(self.pid, "rappi", "apagar_hoy", 0)
        self.assertEqual(self.ops(), [])
        self.assertEqual(self.leer()[1], datetime(2020, 1, 1))

    async def test_confirmacion_apagado_real_actualiza_fecha(self):
        self.poner(EstadoItem.APAGADO_HOY)
        self.plat.leer_estado.return_value = ResultadoEstado(False)
        await self.w._verificar_luego(self.pid, "rappi", "apagar_hoy", 0)
        self.assertGreater(self.leer()[1], datetime(2020, 1, 1))
        self.assertEqual(self.ops(), [])

    async def test_revivido_confirmado_se_encola_una_vez(self):
        self.poner(EstadoItem.APAGADO_HOY)
        caso = self.caso()
        await self.w._reencolar_si_revivio(caso)
        await self.w._reencolar_si_revivio(caso)
        self.assertEqual(len(self.ops()), 1)
        self.assertEqual(self.leer()[0], EstadoItem.APAGANDO)

    async def test_cambio_durante_lectura_rapida_no_se_deshace(self):
        self.poner(EstadoItem.APAGADO_HOY)
        async def leer(*args):
            self.pedir("prender")
            return ResultadoEstado(True)
        self.plat.leer_estado.side_effect = leer
        await self.w._verificar_luego(self.pid, "rappi", "apagar_hoy", 0)
        self.assertEqual([o[1] for o in self.ops()], ["prender"])
        self.assertEqual(self.leer()[0], EstadoItem.PRENDIENDO)

    async def test_cambio_durante_ronda_no_se_deshace(self):
        self.poner(EstadoItem.APAGADO_HOY)
        caso = self.caso()
        async def leer(*args):
            self.pedir("prender")
            return ResultadoEstado(True)
        self.plat.leer_estado.side_effect = leer
        await self.w._reencolar_si_revivio(caso)
        self.assertEqual([o[1] for o in self.ops()], ["prender"])

    async def test_misma_accion_con_nueva_identidad_invalida_verificacion_vieja(self):
        self.pedir("apagar_hoy")
        vieja = self.ops()[0][0]
        with SessionLocal() as db:
            db.query(Operacion).update({"estado": Operacion.OK})
            db.commit()
        self.pedir("apagar_hoy")
        with SessionLocal() as db:
            db.query(Operacion).update({"estado": Operacion.OK})
            db.commit()
        self.poner(EstadoItem.APAGADO_HOY)
        await self.w._verificar_luego(self.pid, "rappi", "apagar_hoy", 0, vieja)
        self.plat.leer_estado.assert_not_called()

    async def test_cambiar_duracion_invalida_verificacion_vieja(self):
        self.poner(EstadoItem.APAGADO_INDEF)
        await self.w._verificar_luego(self.pid, "rappi", "apagar_hoy", 0)
        self.plat.leer_estado.assert_not_called()

    async def test_pausa_y_desactivar_sostenimiento_frenan_verificacion(self):
        self.poner(EstadoItem.APAGADO_HOY)
        with SessionLocal() as db:
            config.guardar(db, {"sostener_apagados": False})
            db.commit()
        await self.w._verificar_luego(self.pid, "rappi", "apagar_hoy", 0)
        self.plat.leer_estado.assert_not_called()


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        engine.dispose()
        TEMPORAL.cleanup()
