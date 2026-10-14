"""python pruebas/probar_pedidosya_rappi_alertas.py — sin portales."""
import sys
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.database import Base
from app.models import Producto, EstadoItem, AliasPlataforma, Operacion
from app.catalogo import desparejos


class AvisosPedidosYaRappi(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.p = Producto(nombre="Ensalada", orden=1)
        self.p.estados = [EstadoItem(plataforma=plat, estado=estado,
                                    verificado_en=datetime.now())
                          for plat, estado in (
                              ("pedidosya", EstadoItem.APAGADO_AJENO),
                              ("rappi", EstadoItem.PRENDIDO),
                              ("rappi_comun", EstadoItem.PRENDIDO))]
        self.p.alias = [AliasPlataforma(plataforma="rappi",
                                       nombre_remoto="Ensalada de hojas")]
        self.db.add(self.p)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def avisos(self, activas=("pedidosya", "rappi", "rappi_comun"), **kw):
        self.db.commit()
        return desparejos(self.db, activas,
                         desde=datetime.now() - timedelta(minutes=30), **kw)

    def estado(self, plat):
        return next(e for e in self.p.estados if e.plataforma == plat)

    def test_apagados_y_dos_tiendas(self):
        for apagado in (*EstadoItem.APAGADOS_PROPIOS, EstadoItem.APAGADO_AJENO):
            self.estado("pedidosya").estado = apagado
            avisos = self.avisos()
            self.assertEqual([(a["apagada_en"], a["prendida_en"]) for a in avisos],
                             [("pedidosya", "rappi"), ("pedidosya", "rappi_comun")])
            self.assertEqual(avisos[0]["nombre_remoto"], "Ensalada de hojas")

    def test_solo_tiendas_activas(self):
        self.assertEqual(len(self.avisos(("pedidosya", "rappi"))), 1)
        self.assertEqual(self.avisos(("rappi",)), [])

    def test_no_avisa_inverso_ni_estados_inciertos(self):
        for estado in (EstadoItem.PRENDIDO, EstadoItem.DESCONOCIDO,
                       EstadoItem.FALLO, *EstadoItem.EN_CURSO):
            self.estado("pedidosya").estado = estado
            self.assertEqual(self.avisos(), [])
        self.estado("pedidosya").estado = EstadoItem.PRENDIDO
        self.estado("rappi").estado = EstadoItem.APAGADO_AJENO
        self.assertEqual(self.avisos(("pedidosya", "rappi")), [])

    def test_lecturas_viejas_ausentes_y_no_vistos(self):
        for plat in ("pedidosya", "rappi"):
            for fecha in (None, datetime.now() - timedelta(days=1)):
                self.estado(plat).verificado_en = fecha
                self.assertEqual(self.avisos(("pedidosya", "rappi")), [])
            self.estado(plat).verificado_en = datetime.now()
            self.assertEqual(self.avisos(("pedidosya", "rappi"),
                                        no_vistos={(self.p.id, plat)}), [])

    def test_pausados_archivados_y_sin_vinculo(self):
        self.p.pausado = True
        self.assertEqual(self.avisos(), [])
        self.p.pausado = False
        self.p.activo = False
        self.assertEqual(self.avisos(), [])
        self.p.activo = True
        self.p.estados.remove(self.estado("pedidosya"))
        self.assertEqual(self.avisos(), [])

    def test_el_aviso_se_resuelve_al_apagar_rappi(self):
        self.assertEqual(len(self.avisos()), 2)
        self.estado("rappi").estado = EstadoItem.APAGADO_AJENO
        self.estado("rappi_comun").estado = EstadoItem.APAGADO_AJENO
        self.assertEqual(self.avisos(), [])

    def test_boton_prende_solo_apagadas_sin_duplicar(self):
        from app.main import prender_diferencias
        with patch('app.main.config.plataformas_activas',
                   return_value=['pedidosya', 'rappi', 'rappi_comun']), \
             patch('app.main.config.tienda_pausada', return_value=False):
            resultado = prender_diferencias(self.db)
            self.assertEqual(resultado['encoladas'], ['pedidosya'])
            operaciones = self.db.query(Operacion).all()
            self.assertEqual([(o.plataforma, o.accion) for o in operaciones],
                             [('pedidosya', 'prender')])
            self.assertEqual(self.estado('pedidosya').estado, EstadoItem.PRENDIENDO)
            self.assertEqual(self.estado('rappi').estado, EstadoItem.PRENDIDO)
            self.assertEqual(prender_diferencias(self.db)['encoladas'], [])
            self.assertEqual(self.db.query(Operacion).count(), 1)

    def test_boton_recalcula_y_respeta_pausa(self):
        from app.main import prender_diferencias
        with patch('app.main.config.plataformas_activas',
                   return_value=['pedidosya', 'rappi']), \
             patch('app.main.config.tienda_pausada',
                   side_effect=lambda p: p == 'pedidosya'):
            self.assertEqual(prender_diferencias(self.db)['encoladas'], [])
        self.estado('pedidosya').estado = EstadoItem.PRENDIDO
        self.db.commit()
        self.assertEqual(prender_diferencias(self.db)['encoladas'], [])
        self.assertEqual(self.db.query(Operacion).count(), 0)


if __name__ == "__main__":
    unittest.main()
