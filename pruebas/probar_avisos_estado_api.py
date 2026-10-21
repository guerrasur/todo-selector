"""Contrato del estado para los avisos; SQLite aislada, sin portales."""
import sys
import unittest
from pathlib import Path
from datetime import datetime
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.database import Base
from app import main
from app.worker import Worker, MENU_NO_CARGO


class EstadoAvisos(unittest.TestCase):
    def test_motivos_y_verificacion_viajan_sin_convertirse_en_sesion_ok(self):
        motor = create_engine('sqlite:///:memory:')
        self.addCleanup(motor.dispose)
        Base.metadata.create_all(motor)
        w = Worker()
        w.sesion_ok = {'pedidosya': False, 'rappi': False}
        w.motivo_sesion = {'rappi': MENU_NO_CARGO}
        w.verificacion = {'pedidosya': {
            'desde': datetime.now(), 'origen': 'captcha', 'detalle': 'Press & Hold'}}
        with Session(motor) as db, \
             patch.object(main, 'worker', w), \
             patch.object(main.config, 'texto', return_value='LOCAL'), \
             patch.object(main.config, 'plataformas_activas', return_value=['pedidosya', 'rappi']), \
             patch.object(main.config, 'tiendas_pausadas', return_value=[]), \
             patch.object(main.config, 'entero', return_value=0):
            estado = main.estado_sistema(db)
        self.assertEqual(estado['sesiones'], {'pedidosya': False, 'rappi': False})
        self.assertEqual(estado['motivos_sesion'], {'rappi': MENU_NO_CARGO})
        self.assertEqual(estado['verificacion']['pedidosya']['origen'], 'captcha')
        self.assertIsInstance(estado['verificacion']['pedidosya']['desde'], str)
        w.motivo_sesion.clear()
        self.assertEqual(estado['motivos_sesion'], {'rappi': MENU_NO_CARGO})


if __name__ == '__main__':
    unittest.main()
