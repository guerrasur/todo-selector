"""Identidad remota persistente y filas completas; SQLite aislado, sin portales."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import catalogo
from app.database import Base
from app.models import Producto

ACTIVAS = ['pedidosya', 'rappi', 'rappi_comun']


class Vinculos(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, autoflush=False)
        self.db = self.sessions()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def crear(self, nombre, mapas):
        p = Producto(nombre=nombre, activo=True)
        self.db.add(p)
        self.db.flush()
        for plat, remoto in mapas.items():
            catalogo._poner_alias(self.db, p, plat, remoto)
            catalogo._poner_estado(self.db, p, plat)
        self.db.commit()
        self.db.expire_all()
        return p

    def test_renombrar_conserva_remotos_implicitos_tras_reabrir(self):
        p = self.crear('Plato original', dict.fromkeys(ACTIVAS, 'Plato original'))
        pid = p.id
        catalogo.cambiar_nombre(self.db, p, 'Mi plato')
        self.db.commit()
        self.db.close()
        self.db = self.sessions()
        p = self.db.get(Producto, pid)
        self.assertEqual(p.nombre, 'Mi plato')
        for plat in ACTIVAS:
            self.assertEqual(catalogo.nombre_remoto(p, plat), 'Plato original')
            self.assertEqual(catalogo.agregar(self.db, plat, 'Plato original').id, pid)
        self.assertEqual(self.db.query(Producto).count(), 1)

    def test_renombrar_varias_veces_conserva_alias_distintos(self):
        mapas = {'pedidosya': 'Plato', 'rappi': 'Plato Turbo', 'rappi_comun': 'Plato común'}
        p = self.crear('Plato', mapas)
        for nombre in ('Nombre nuevo', 'Plato Turbo', 'Definitivo'):
            catalogo.cambiar_nombre(self.db, p, nombre)
            self.db.commit()
            self.db.expire_all()
            self.assertEqual({plat: catalogo.nombre_remoto(p, plat) for plat in ACTIVAS}, mapas)

    def test_tres_filas_se_unen_y_no_reaparecen_al_repetir(self):
        mapas = dict(zip(ACTIVAS, ['Plato original', 'Plato Turbo', 'Plato común']))
        for plat, remoto in mapas.items():
            self.crear(remoto, {plat: remoto})
        p = catalogo.vincular_varios(self.db, mapas, nombre='Plato único')
        self.db.commit()
        pid = p.id
        self.db.close()
        self.db = self.sessions()
        self.assertEqual(catalogo.vincular_varios(self.db, mapas).id, pid)
        for plat, remoto in mapas.items():
            self.assertEqual(catalogo.agregar(self.db, plat, remoto).id, pid)
        self.assertEqual(self.db.query(Producto).filter_by(activo=True).count(), 1)

    def test_renombrar_al_vincular_dos_preserva_la_tercera(self):
        p = self.crear('Plato', dict.fromkeys(ACTIVAS, 'Plato'))
        otro = self.crear('Plato PY nuevo', {'pedidosya': 'Plato PY nuevo'})
        unificado = catalogo.vincular_varios(self.db, {
            'pedidosya': 'Plato PY nuevo', 'rappi': 'Plato'}, nombre='Rótulo nuevo')
        self.db.commit()
        self.db.expire_all()
        self.assertEqual(catalogo.nombre_remoto(unificado, 'rappi_comun'), 'Plato')

    def test_incompletos_segun_plataformas_activas_y_pausados(self):
        p = self.crear('Plato', {'pedidosya': 'Plato', 'rappi': 'Plato'})
        p.pausado = True
        self.assertEqual(catalogo.revision_vinculos([p], ACTIVAS)[p.id]['faltantes'], ['rappi_comun'])
        self.assertEqual(catalogo.revision_vinculos([p], ACTIVAS[:2])[p.id]['faltantes'], [])

    def test_detecta_duplicados_implicitos_y_explicitos_sin_elegir_uno(self):
        a = self.crear('Plato', {'pedidosya': 'Plato'})
        b = self.crear('Copia', {'pedidosya': 'Plato'})
        revision = catalogo.revision_vinculos([a, b], ACTIVAS)
        self.assertEqual(revision[a.id]['duplicados'], ['pedidosya'])
        self.assertEqual(revision[b.id]['duplicados'], ['pedidosya'])
        with self.assertRaisesRegex(ValueError, 'varios productos'):
            catalogo.agregar(self.db, 'pedidosya', 'Plato')
        self.assertEqual(self.db.query(Producto).count(), 2)
        b.activo = False
        self.db.commit()
        self.assertEqual(catalogo.buscar_por_remoto(self.db, 'pedidosya', 'Plato').id, a.id)

    def test_nombres_parecidos_no_se_fusionan(self):
        a = self.crear('Plato', {'pedidosya': 'Plato'})
        b = self.crear('Plato chico', {'pedidosya': 'Plato chico'})
        for r in catalogo.revision_vinculos([a, b], ACTIVAS).values():
            self.assertEqual(r['duplicados'], [])

    def test_endpoint_renombrar_y_listados_conservan_identidad(self):
        from app.main import renombrar, RenombrarIn, listar_productos, ver_catalogo
        p = self.crear('Plato', dict.fromkeys(ACTIVAS, 'Plato'))
        renombrar(RenombrarIn(producto_id=p.id, nombre='Nombre común'), self.db)
        with patch('app.main.config.plataformas_activas', return_value=ACTIVAS):
            filas = listar_productos(self.db)
            self.assertEqual(len(filas), 1)
            self.assertEqual(filas[0]['alias'], dict.fromkeys(ACTIVAS, 'Plato'))
            self.assertEqual(filas[0]['revision_vinculos'], {'faltantes': [], 'duplicados': []})
            self.assertEqual(ver_catalogo(self.db)['productos'][0]['plataformas'], dict.fromkeys(ACTIVAS, 'Plato'))

    def test_endpoint_vincular_serializado_reutiliza_fila(self):
        from app.main import vincular, VincularIn
        mapas = dict.fromkeys(ACTIVAS, 'Plato')
        with patch('app.main.config.plataformas_activas', return_value=ACTIVAS):
            primero = vincular(VincularIn(nombres=mapas), self.db)['producto']['id']
            # Otra request usa otra sesión, como dos pestañas sucesivas.
            self.db.close()
            self.db = self.sessions()
            segundo = vincular(VincularIn(nombres=mapas), self.db)['producto']['id']
        self.assertEqual(primero, segundo)
        self.assertEqual(self.db.query(Producto).count(), 1)

    def test_endpoint_no_encola_publicacion_duplicada(self):
        from app.main import encolar_accion, AccionIn
        from fastapi import HTTPException
        from app.models import Operacion
        a = self.crear('Plato', dict.fromkeys(ACTIVAS, 'Plato'))
        self.crear('Copia', {'pedidosya': 'Plato'})
        with patch('app.main.config.plataformas_activas', return_value=ACTIVAS):
            with self.assertRaises(HTTPException) as error:
                encolar_accion(AccionIn(producto_id=a.id, accion='prender', plataformas=ACTIVAS), self.db)
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(self.db.query(Operacion).count(), 0)


if __name__ == '__main__':
    unittest.main()
