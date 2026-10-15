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

if __name__=='__main__': unittest.main()
