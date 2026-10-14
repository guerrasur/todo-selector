"""python pruebas/probar_pedidosya_rappi_alertas.py — sin portales."""
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.database import Base
from app.models import Producto, EstadoItem, AliasPlataforma
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


if __name__ == "__main__":
    unittest.main()
