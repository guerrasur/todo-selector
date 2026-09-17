"""Limpieza exacta de duplicados, sin portales ni datos del local."""
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
TEMP = tempfile.TemporaryDirectory(prefix='todo-duplicados-')
with (patch.object(Path, 'home', return_value=Path(TEMP.name)),
      patch.dict(os.environ, {'LOCALAPPDATA': TEMP.name})):
    from app import catalogo, limpieza, config
    from app.database import Base, engine, init_db, SessionLocal
    from app.models import Producto, EstadoItem, Operacion, HistorialCatalogo
    from app.worker import Worker
    from app.main import limpiar_duplicados, LimpiarDuplicadosIn, encolar_accion, AccionIn
    from fastapi import HTTPException


class Duplicados(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(engine)
        init_db()
        config._cache = None
        self.db = SessionLocal()

    def tearDown(self):
        self.db.close()

    def agregar(self, nombre, mapas, categoria='', estado=EstadoItem.DESCONOCIDO):
        p = Producto(nombre=nombre, categoria=categoria)
        self.db.add(p); self.db.flush()
        for plat, remoto in mapas.items():
            catalogo._poner_alias(self.db, p, plat, remoto)
            est = catalogo._poner_estado(self.db, p, plat)
            est.estado = estado
            if estado != EstadoItem.DESCONOCIDO:
                est.verificado_en = datetime(2026, 9, 1)
        self.db.commit(); self.db.expire_all()
        return self.db.get(Producto, p.id)

    def pareja(self):
        a = self.agregar('Plato de prueba', {'pedidosya':'Plato de prueba'},
                         'Platos', EstadoItem.PRENDIDO)
        b = self.agregar('Plato de prueba (PedidosYa)', {'pedidosya':'Plato de prueba'})
        return a,b

    def limpiar(self):
        resultado=limpieza.ejecutar(self.db, limpieza.planificar(self.db)['firma'])
        self.db.commit(); self.db.expire_all()
        return resultado

    def test_copia_exacta_archivada_con_historial_y_categoria(self):
        a,b=self.pareja();bid=b.id
        op=Operacion(producto_id=bid,plataforma='pedidosya',accion='apagar_hoy',estado=Operacion.ERROR)
        self.db.add(op);self.db.commit();oid=op.id
        plan=limpieza.planificar(self.db)
        self.assertEqual(plan['total'],1)
        self.assertEqual(plan['grupos'][0]['conservar']['id'],a.id)
        self.assertEqual(self.limpiar(), {'archivados':1})
        self.assertFalse(self.db.get(Producto,bid).activo)
        self.assertEqual(self.db.get(Operacion,oid).producto_id,bid)
        self.assertEqual(catalogo.buscar_por_remoto(self.db,'pedidosya','Plato de prueba').id,a.id)
        self.assertEqual(a.estados[0].estado,EstadoItem.PRENDIDO)
        self.assertEqual(a.categoria,'Platos')
        self.assertEqual(limpieza.planificar(self.db)['total'],0)

    def test_deshacer_restaura_filas_y_fechas(self):
        a,b=self.pareja();aid,bid=a.id,b.id
        self.limpiar()
        catalogo.deshacer(self.db);self.db.commit();self.db.expire_all()
        self.assertTrue(self.db.get(Producto,bid).activo)
        self.assertEqual(self.db.get(Producto,aid).estados[0].verificado_en,datetime(2026,9,1))
        self.assertEqual(limpieza.planificar(self.db)['total'],1)

    def test_deshacer_no_pisa_lecturas_nuevas_ni_otros_productos(self):
        a,b=self.pareja()
        otro=self.agregar('Otro',{'rappi':'Otro'})
        self.limpiar()
        a.estados[0].estado=EstadoItem.APAGADO_HOY
        otro.estados[0].estado=EstadoItem.PRENDIDO
        self.db.commit()
        catalogo.deshacer(self.db);self.db.commit();self.db.expire_all()
        self.assertTrue(b.activo)
        self.assertEqual(a.estados[0].estado,EstadoItem.APAGADO_HOY)
        self.assertEqual(otro.estados[0].estado,EstadoItem.PRENDIDO)

    def test_no_confunde_con_sin_ni_tamanos_ni_portales(self):
        for i,(plat,nombre) in enumerate([
                ('pedidosya','Agua con gas'),('pedidosya','Agua sin gas'),
                ('pedidosya','Tarta'),('pedidosya','Tarta chica'),('rappi','Tarta')]):
            self.agregar(str(i),{plat:nombre})
        self.assertEqual(limpieza.planificar(self.db)['total'],0)

    def test_sufijo_no_demuestra_identidad(self):
        self.agregar('Tarta',{'pedidosya':'Tarta'})
        self.agregar('Tarta (2)',{'pedidosya':'Tarta (2)'})
        self.assertEqual(limpieza.planificar(self.db)['total'],0)

    def test_conflicto_en_otra_plataforma_no_se_limpia(self):
        self.agregar('Uno',{'pedidosya':'Tarta','rappi':'Tarta grande'})
        self.agregar('Dos',{'pedidosya':'Tarta','rappi':'Tarta chica'})
        p=limpieza.planificar(self.db)
        self.assertEqual(p['total'],0);self.assertEqual(len(p['revisar']),1)

    def test_sin_fila_que_cubra_todos_no_se_inventa_union(self):
        self.agregar('Uno',{'pedidosya':'Tarta','rappi':'Tarta'})
        self.agregar('Dos',{'pedidosya':'Tarta','rappi_comun':'Tarta'})
        self.assertEqual(limpieza.planificar(self.db)['total'],0)

    def test_pausas_distintas_se_muestran_para_revision(self):
        a,b=self.pareja();b.pausado=True;self.db.commit()
        self.assertEqual(limpieza.planificar(self.db)['total'],0)

    def test_cola_viva_impide_archivar(self):
        a,b=self.pareja()
        for estado in Operacion.VIVAS:
            self.db.query(Operacion).delete()
            self.db.add(Operacion(producto_id=b.id,plataforma='pedidosya',accion='prender',estado=estado))
            self.db.commit()
            self.assertEqual(limpieza.planificar(self.db)['total'],0)

    def test_firma_vencida_rechazada(self):
        a,b=self.pareja();firma=limpieza.planificar(self.db)['firma']
        b.pausado=True;self.db.commit()
        with self.assertRaises(ValueError):limpieza.ejecutar(self.db,firma)
        self.assertTrue(b.activo)

    def test_estados_contradictorios_quedan_sin_confirmar(self):
        a,b=self.pareja();b.estados[0].estado=EstadoItem.APAGADO_HOY;self.db.commit()
        self.limpiar()
        self.assertEqual(a.estados[0].estado,EstadoItem.DESCONOCIDO)
        self.assertIsNone(a.estados[0].verificado_en)

    def test_lectura_no_sostiene_ni_actualiza_archivados(self):
        a,b=self.pareja();bid=b.id;self.limpiar()
        Worker._guardar_estados('pedidosya',{'Plato de prueba':False},sostener=True)
        self.db.expire_all()
        self.assertEqual(self.db.get(Producto,bid).estados[0].estado,EstadoItem.DESCONOCIDO)
        with self.assertRaises(HTTPException):
            encolar_accion(AccionIn(producto_id=bid,plataformas=['pedidosya'],accion='prender'),self.db)

    def test_absorber_mismo_remoto_no_fabrica_restos(self):
        a=self.agregar('Uno',{'pedidosya':'Tarta'})
        b=self.agregar('Dos',{'pedidosya':'Tarta','rappi':'Tarta'})
        catalogo._absorber(self.db,a,b);self.db.commit();self.db.expire_all()
        self.assertEqual(self.db.query(Producto).count(),1)
        self.assertEqual(catalogo.nombre_remoto(a,'rappi'),'Tarta')

    def test_backup_fallido_no_archiva(self):
        a,b=self.pareja();firma=limpieza.planificar(self.db)['firma']
        with patch('app.main.hacer_backup',side_effect=OSError('disco lleno')):
            with self.assertRaises(HTTPException) as error:
                limpiar_duplicados(LimpiarDuplicadosIn(firma=firma),self.db)
        self.db.rollback()
        self.assertEqual(error.exception.status_code,500)
        self.assertTrue(self.db.get(Producto,b.id).activo)
        self.assertEqual(self.db.query(HistorialCatalogo).count(),0)

    def test_endpoint_crea_backup_y_archiva(self):
        a,b=self.pareja();firma=limpieza.planificar(self.db)['firma']
        with patch('app.main.hacer_backup') as backup:
            resultado=limpiar_duplicados(LimpiarDuplicadosIn(firma=firma),self.db)
            backup.assert_called_once_with(refrescar_horas=0)
        self.assertEqual(resultado['archivados'],1)


if __name__=='__main__':
    try:unittest.main(verbosity=2)
    finally:engine.dispose();TEMP.cleanup()
