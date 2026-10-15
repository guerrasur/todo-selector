"""Cola finita y pestaña compartida, con SQLite temporal; no toca portales."""
import asyncio
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
temporal = tempfile.TemporaryDirectory()
with patch.object(Path, 'home', return_value=Path(temporal.name)), patch.dict(os.environ, {'LOCALAPPDATA': temporal.name}):
    from app.database import Base, engine, SessionLocal, init_db
    from app.models import Producto, Operacion
    from app.worker import Worker
    from app import config
    from sqlalchemy import or_

class Tandas(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        Base.metadata.drop_all(engine)
        init_db()
        self.db = SessionLocal()
        p = Producto(nombre='Producto ficticio')
        self.db.add(p)
        self.db.flush()
        self.pid = p.id
        self.worker = Worker()

    def tearDown(self):
        self.db.close()

    def agregar(self, tienda):
        op = Operacion(producto_id=self.pid, plataforma=tienda, accion='apagar_hoy', estado=Operacion.PENDIENTE)
        self.db.add(op)
        self.db.flush()
        return op

    def siguiente(self):
        ahora = datetime.now()
        q = self.db.query(Operacion).filter(Operacion.estado == Operacion.PENDIENTE,
            or_(Operacion.reintentar_en.is_(None), Operacion.reintentar_en <= ahora))
        return self.worker._siguiente_pendiente(q)

    def test_turbo_antes_comun_y_fifo_interno(self):
        comun1=self.agregar('rappi_comun'); turbo1=self.agregar('rappi')
        comun2=self.agregar('rappi_comun'); turbo2=self.agregar('rappi')
        for esperado in (turbo1,turbo2,comun1,comun2):
            self.assertEqual(self.siguiente().id,esperado.id)
            esperado.estado=Operacion.OK
            self.db.flush()
        self.assertIsNone(self.siguiente())

    def test_fallo_y_nuevas_ordenes_no_postergan_comun(self):
        t=self.agregar('rappi'); c=self.agregar('rappi_comun')
        self.assertEqual(self.siguiente().id,t.id)
        t.reintentar_en=datetime.now()+timedelta(seconds=30)
        nuevo=self.agregar('rappi')
        self.assertEqual(self.siguiente().id,c.id)
        c.estado=Operacion.OK; self.db.flush()
        self.assertEqual(self.siguiente().id,nuevo.id)

    def test_cancelada_se_salta_y_pedidosya_conserva_turno_previo(self):
        py=self.agregar('pedidosya'); t=self.agregar('rappi'); c=self.agregar('rappi_comun')
        self.assertEqual(self.siguiente().id,py.id)
        py.estado=Operacion.OK; self.db.flush()
        self.assertEqual(self.siguiente().id,t.id)
        t.estado=Operacion.OK; c.estado=Operacion.CANCELADA; self.db.flush()
        self.assertIsNone(self.siguiente())

    async def test_bloqueo_compartido_excluye_lectura_concurrente(self):
        w=self.worker
        self.assertIs(w.bloqueo('rappi'),w.bloqueo('rappi_comun'))
        self.assertIsNot(w.bloqueo('rappi'),w.bloqueo('pedidosya'))
        eventos=[]
        async def operar(tienda):
            async with w.bloqueo(tienda):
                eventos.append(tienda+' inicio'); await asyncio.sleep(.01); eventos.append(tienda+' fin')
        await asyncio.gather(operar('rappi'),operar('rappi_comun'))
        self.assertEqual(eventos,['rappi inicio','rappi fin','rappi_comun inicio','rappi_comun fin'])

    async def test_lectura_general_no_cambia_tienda_en_medio_de_tanda(self):
        w=self.worker;w.modo_simulado=False;w._tanda_rappi=[123]
        w.plataformas={'rappi':SimpleNamespace(), 'rappi_comun':SimpleNamespace()}
        w._preparar=AsyncMock()
        salida=await w.sincronizar_estados()
        self.assertIn('pospuesta',salida['rappi']['error'])
        self.assertIn('pospuesta',salida['rappi_comun']['error'])
        w._preparar.assert_not_awaited()

    async def test_activar_y_desactivar_comun_no_abre_ni_cierra_pagina(self):
        w=self.worker
        pagina=SimpleNamespace(close=AsyncMock())
        w.plataformas['rappi']=SimpleNamespace(page=pagina)
        w.browser=SimpleNamespace(new_page=AsyncMock())
        with patch.object(config,'texto',return_value='AR123'):
            await w._abrir_rappi_comun()
        self.assertIs(w.plataformas['rappi_comun'].page,pagina)
        w.browser.new_page.assert_not_called()
        bloqueo=w.bloqueo('rappi_comun')
        await w._cerrar_plataforma('rappi_comun')
        pagina.close.assert_not_called()
        self.assertIs(w.bloqueo('rappi'),bloqueo)

class Coordinacion(Tandas):
    async def test_guardia_central_frena_lecturas_explicitamente_pedidas(self):
        w = self.worker; w.modo_simulado = False; w._tanda_rappi = [123]
        for tienda in ('rappi', 'rappi_comun'):
            listo, motivo = await w._preparar(tienda)
            self.assertFalse(listo)
            self.assertIn('pospuesta', motivo)
        # PedidosYa no pasa por esta guarda.
        self.assertIn('desconocida', (await w._preparar('pedidosya'))[1])

    async def test_operacion_esperando_lock_bloquea_lectura_y_limpia_turno(self):
        w = self.worker; w.modo_simulado = False
        w.plataformas['rappi'] = SimpleNamespace(configurado=False)
        motivos = []
        async def operar(*args):
            motivos.append((await w._preparar('rappi'))[1])
            return False, 'prueba', ''
        w._ejecutar_sin_turno = AsyncMock(side_effect=operar)
        lock = w.bloqueo('rappi')
        await lock.acquire()
        tarea = asyncio.create_task(w._ejecutar('rappi', 'apagar_hoy', 'Ejemplo'))
        try:
            await asyncio.sleep(0)
            self.assertTrue(w._tareas_operacion_rappi)
            self.assertIn('pospuesta', (await w._preparar('rappi_comun'))[1])
        finally:
            lock.release()
            await tarea
        self.assertIn('falta configurar', motivos[0])
        self.assertEqual(w._tareas_operacion_rappi, set())

    async def test_estado_general_no_prepara_carta_si_no_esta_adaptado(self):
        w = self.worker; w.modo_simulado = False
        w.plataformas['rappi'] = SimpleNamespace(_portal_nuevo=lambda: True)
        w._preparar = AsyncMock()
        resultado = await w.estado_tienda('rappi')
        self.assertIsNone(resultado['abierta'])
        self.assertIn('Gestión de tiendas', resultado['motivo'])
        w._preparar.assert_not_awaited()

class Diagnostico(Tandas):
    async def test_arranque_real_sale_del_diagnostico(self):
        w = self.worker
        async def abrir():
            self.assertFalse(w.rappi_solo_diagnostico)
        w._abrir_navegador = AsyncMock(side_effect=abrir)
        def cerrar_tarea(coro):
            coro.close()
        with patch('app.worker.asyncio.create_task', side_effect=cerrar_tarea):
            await w.iniciar(modo_simulado=False)
        w._abrir_navegador.assert_awaited_once()
        self.assertFalse(w.rappi_solo_diagnostico)

    async def test_log_compara_selector_real_y_termina_sin_escribir(self):
        import json
        from probar_rappi_filas import crear, fila
        plat = crear(fila('Ejemplo', 'false'))
        plat._diagnostico_dom = {'nombres_dom': ['Ejemplo'], 'switches_dom': 1}
        plat._capturar_carta_nueva = AsyncMock(return_value=[
            {'nombre': 'Ejemplo', 'aria': 'false', 'disponible': False}])
        plat._categorias_carta_nueva = AsyncMock(return_value=[])
        plat._abrir_categorias_carta_nueva = AsyncMock(return_value=[])
        plat._nombre_tienda_actual = AsyncMock(return_value='Sucursal ficticia')
        plat._tienda_verificada = AsyncMock(return_value=True)
        plat.apagar = AsyncMock(); plat.prender = AsyncMock()
        with self.assertLogs('worker', level='WARNING') as logs:
            await self.worker._registrar_diagnostico_rappi('rappi', plat)
        mensajes = [r.getMessage() for r in logs.records]
        resumen = json.loads(next(m for m in mensajes if m.startswith('DIAG_RAPPI_RESUMEN ')).split(' ', 1)[1])
        producto = json.loads(next(m for m in mensajes if m.startswith('DIAG_RAPPI_FILA ')).split(' ', 1)[1])
        self.assertEqual(resumen['directo'], 1)
        self.assertEqual(resumen['xpath'], 1)
        self.assertEqual(producto['aria_xpath'], 'false')
        self.assertFalse(producto['disponible'])
        self.assertTrue(mensajes[-1].startswith('DIAG_RAPPI_FIN rappi:'))
        plat.apagar.assert_not_awaited(); plat.prender.assert_not_awaited()

    async def test_cola_rappi_pendiente_no_gasta_intentos(self):
        ops = [self.agregar('rappi'), self.agregar('rappi_comun')]
        self.db.commit()
        w = self.worker; w.rappi_solo_diagnostico = True
        w._ejecutar = AsyncMock()
        await w._procesar_pendientes()
        self.db.expire_all()
        for op in ops:
            self.assertEqual(op.estado, Operacion.PENDIENTE)
            self.assertEqual(op.intentos, 0)
        w._ejecutar.assert_not_awaited()

    async def test_guardas_no_navegan_ni_ejecutan(self):
        w = self.worker; w.rappi_solo_diagnostico = True
        plat = SimpleNamespace(page=SimpleNamespace(reload=AsyncMock()),
                               asegurar_sesion=AsyncMock(), apagar=AsyncMock())
        w.plataformas = {'rappi': plat, 'rappi_comun': plat}
        for tienda in w.plataformas:
            self.assertFalse((await w._preparar(tienda))[0])
            self.assertFalse((await w._ejecutar(tienda, 'apagar_hoy', 'Ejemplo'))[0])
        plat.page.reload.assert_not_awaited()
        plat.asegurar_sesion.assert_not_awaited()
        plat.apagar.assert_not_awaited()

    async def test_precios_no_abren_categorias_en_diagnostico(self):
        from app.precios import GestorPrecios
        w = self.worker; w.rappi_solo_diagnostico = True
        w.motivo_sesion['rappi'] = 'menu_no_cargo'
        w._preparar = AsyncMock()
        gestor = GestorPrecios(w)
        self.assertFalse((await gestor._preparar('rappi'))[0])
        w._preparar.assert_not_awaited()

if __name__=='__main__': unittest.main()
