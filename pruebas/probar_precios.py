"""Precios: importes, planes, idempotencia, tiendas y persistencia. Sin portales."""
import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
TEMP = tempfile.TemporaryDirectory(prefix="todo-selector-precios-")
with patch.object(Path, "home", return_value=Path(TEMP.name)), patch.dict(os.environ, {"LOCALAPPDATA": TEMP.name}):
    from app import config
    from app.database import init_db, SessionLocal
    from app.precios import GestorPrecios
    from app.worker import Worker
    from plataformas.precios import importe, aumentar


class Importes(unittest.TestCase):
    def test_formatos(self):
        for texto in ("$ 17.500,50", "17500,50", "17500.50"):
            self.assertEqual(importe(texto, portal=True), importe("17500.50"))
        self.assertEqual(importe("$ 17.500", portal=True), importe("17500"))
        self.assertEqual(importe("$17500", portal=True), importe("17500"))

    def test_rechaza_invalidos(self):
        for texto in ("NaN", "Infinity", "-1", "1e4", "", "abc", "17.500", "1,0000", True, None):
            with self.assertRaises(ValueError, msg=str(texto)): importe(texto)

    def test_aumentos_exactos(self):
        self.assertEqual(aumentar(importe("17500"), "pesos", "500"), importe("18000"))
        self.assertEqual(aumentar(importe("17500"), "porcentaje", "10,5"), importe("19337.50"))
        self.assertEqual(aumentar(importe("17500"), "porcentaje", "10,5", "100"), importe("19300"))

    def test_redondeo_no_reduce(self):
        with self.assertRaises(ValueError): aumentar(importe("149"), "pesos", "0.10", "100")
        with self.assertRaises(ValueError): aumentar(importe("1"), "pesos", "0")
        with self.assertRaises(ValueError): aumentar(importe("1"), "porcentaje", "1001")


class Lotes(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        init_db()
        with SessionLocal() as db:
            config.guardar(db, {"rappi_brand_id": "marca_prueba", "rappi_store_id": "turbo_prueba",
                               "rappi_comun_store_id": "comun_prueba"}); db.commit()
        config.recargar()
        self.w = Worker()
        self.w.modo_simulado = False
        self.w._preparar = AsyncMock(return_value=(True, ""))
        self.ps = {}
        for t in ("rappi", "rappi_comun"):
            plat = SimpleNamespace(listar_precios=AsyncMock(return_value=[
                {"nombre": "Producto de prueba", "id_remoto": "producto-1", "precio": "1000.00", "error": ""},
                {"nombre": "Otro producto", "id_remoto": "producto-2", "precio": "1500.00", "error": ""}]),
                cambiar_precio=AsyncMock(return_value=True), en_verificacion=AsyncMock(return_value=False),
                ir_al_menu=AsyncMock(), volver_del_editor_precio=AsyncMock())
            self.ps[t] = plat
        self.w.plataformas = self.ps
        self.temp = tempfile.TemporaryDirectory(dir=TEMP.name)
        self.g = GestorPrecios(self.w, self.temp.name)
        self.leida = await self.g.leer(["rappi", "rappi_comun"])

    def plan(self, **kwargs):
        parametros = dict(lectura=self.leida["lectura"], tiendas=["rappi"], modo="pesos",
                          alcance="toda", cantidad="100", seleccionados=[], individuales={}, redondeo="centavos")
        parametros.update(kwargs)
        return self.g.preparar(**parametros)

    async def test_todas_y_tiendas_independientes(self):
        p = self.plan(); self.assertEqual(len(p["filas"]), 2)
        lote = self.g.ejecutar(p["plan"]); await self.g.tarea
        self.assertTrue(all(f["estado"] == "confirmado" for f in self.g.estado(lote["id"])["filas"]))
        self.ps["rappi_comun"].cambiar_precio.assert_not_called()

    async def test_seleccion_y_porcentaje(self):
        clave = self.leida["filas"][0]["clave"]
        p = self.plan(modo="porcentaje", cantidad="10", alcance="seleccionados", seleccionados=[clave])
        self.assertEqual([f["despues"] for f in p["filas"]], ["1100.00"])

    async def test_individual_distinto_por_tienda(self):
        filas = self.leida["filas"]
        p = self.plan(tiendas=["rappi", "rappi_comun"], modo="individual", individuales={
            filas[0]["clave"]: "1200", filas[2]["clave"]: "1300"})
        self.assertEqual([f["despues"] for f in p["filas"]], ["1200.00", "1300.00"])

    async def test_pedidosya_rechazado(self):
        with self.assertRaises(ValueError): await self.g.leer(["pedidosya"])
        with self.assertRaises(ValueError): self.plan(tiendas=["pedidosya"])
        self.assertNotIn("pedidosya", self.g.tiendas())

    async def test_doble_ejecutar_no_duplica(self):
        p = self.plan(); a = self.g.ejecutar(p["plan"]); b = self.g.ejecutar(p["plan"])
        self.assertEqual(a["id"], b["id"]); await self.g.tarea
        self.g.ejecutar(p["plan"])
        self.assertEqual(self.ps["rappi"].cambiar_precio.await_count, 2)

    async def test_otro_lote_se_rechaza(self):
        p, q = self.plan(), self.plan(cantidad="200")
        self.g.ejecutar(p["plan"])
        with self.assertRaises(ValueError): self.g.ejecutar(q["plan"])
        await self.g.tarea

    async def test_manual_no_modifica_originales(self):
        clave = self.leida["filas"][0]["clave"]
        with self.assertRaises(ValueError): self.plan(modo="individual", individuales={clave: "1000"})
        with self.assertRaises(ValueError): self.plan(modo="individual", individuales={clave: "0"})

    async def test_error_no_confirma_y_continua(self):
        self.ps["rappi"].cambiar_precio.side_effect = [ValueError("Cambió el precio"), True]
        p = self.plan(); lote = self.g.ejecutar(p["plan"]); await self.g.tarea
        self.assertEqual([f["estado"] for f in self.g.estado(lote["id"])["filas"]], ["sin_confirmar", "confirmado"])
        self.assertEqual(self.ps["rappi"].cambiar_precio.await_count, 2)

    async def test_verificacion_no_toca_pestana(self):
        self.w._preparar = AsyncMock(return_value=(False, "Verificación manual"))
        p = self.plan(); self.g.ejecutar(p["plan"]); await self.g.tarea
        self.ps["rappi"].cambiar_precio.assert_not_called(); self.ps["rappi"].volver_del_editor_precio.assert_not_called()

    async def test_cancelar_pendientes(self):
        p = self.plan(); lote = self.g.ejecutar(p["plan"])
        self.g.cancelar(lote["id"]); await self.g.tarea
        self.assertTrue(all(f["estado"] == "cancelado" for f in self.g.estado(lote["id"])["filas"]))
        self.ps["rappi"].cambiar_precio.assert_not_called()

    async def test_cambio_tienda_rechazado(self):
        p = self.plan()
        with SessionLocal() as db:
            config.guardar(db, {"rappi_store_id": "otra_prueba"}); db.commit()
        config.recargar()
        with self.assertRaises(ValueError): self.g.ejecutar(p["plan"])

    async def test_cambio_mientras_espera_lock(self):
        lock = self.w.bloqueo("rappi"); await lock.acquire()
        p = self.plan(); self.g.ejecutar(p["plan"]); await asyncio.sleep(0)
        with SessionLocal() as db:
            config.guardar(db, {"rappi_store_id": "otra_prueba"}); db.commit()
        config.recargar(); lock.release(); await self.g.tarea
        self.ps["rappi"].cambiar_precio.assert_not_called()

    async def test_persistencia_sin_reejecutar(self):
        p = self.plan(); lote = self.g.ejecutar(p["plan"]); await self.g.tarea
        nuevo = GestorPrecios(self.w, self.temp.name)
        self.assertEqual(nuevo.estado(lote["id"])["estado"], "terminado")
        self.assertEqual(len(nuevo.historial()), 1)

    async def test_reinicio_interrumpido(self):
        identidad = "a"*32
        self.g._guardar({"id": identidad, "estado": "ejecutando", "filas": [{"estado": "en_curso"}]})
        nuevo = GestorPrecios(self.w, self.temp.name)
        self.assertEqual(nuevo.estado(identidad)["estado"], "interrumpido")
        self.ps["rappi"].cambiar_precio.assert_not_called()

    async def test_lectura_parcial_bloquea_toda(self):
        f = self.g.lecturas[self.leida["lectura"]]["filas"][0]; f["error"] = "Sin precio"
        with self.assertRaises(ValueError): self.plan()
        clave = self.leida["filas"][1]["clave"]
        self.assertEqual(len(self.plan(alcance="seleccionados", seleccionados=[clave])["filas"]), 1)

    async def test_preview_vencida_y_seleccion_ajena(self):
        with self.assertRaises(ValueError): self.plan(seleccionados=["otra"])
        self.g.lecturas[self.leida["lectura"]]["instante"] -= 1801
        with self.assertRaises(ValueError): self.plan()

    async def test_simulado_nunca_afirma_confirmacion(self):
        self.w.modo_simulado = True
        leida = await self.g.leer(["rappi"])
        p = self.plan(lectura=leida["lectura"]); lote = self.g.ejecutar(p["plan"]); await self.g.tarea
        self.assertTrue(all(f["estado"] == "simulado" for f in self.g.estado(lote["id"])["filas"]))
        self.ps["rappi"].cambiar_precio.assert_not_called()


if __name__ == "__main__": unittest.main(verbosity=2)
