"""Identidad de local/menú del nuevo portal. Sin navegar ni editar precios."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from plataformas.pedidosya_precios import DestinoPreciosPedidosYa as Destino


class Destinos(unittest.TestCase):
    def setUp(self):
        self.destino = Destino("100001", "200001")

    def test_enlace_canonico_y_orden_independiente(self):
        self.assertEqual(Destino.desde_url(self.destino.url), self.destino)
        self.assertTrue(self.destino.coincide(Destino.BASE +
            "/?activeMenuId=200001&vendor=PY_AR;100001&tab=products#lista"))

    def test_local_y_menu_se_comprueban_juntos(self):
        for otro in (Destino("100002", "200001"), Destino("100001", "200002"),
                     Destino("100002", "200002")):
            with self.subTest(otro=otro):
                self.assertFalse(self.destino.coincide(otro.url))
                with self.assertRaisesRegex(ValueError, "Cambió el local o el menú"):
                    self.destino.exigir(otro.url)

    def test_no_acepta_ids_parciales_ni_parametros_duplicados(self):
        for query in ("vendor=PY_AR;100001", "activeMenuId=200001",
                      "vendor=PY_AR;100001&activeMenuId=",
                      "vendor=PY_AR;100001&activeMenuId=200001&activeMenuId=200002",
                      "vendor=PY_AR;100001&vendor=PY_AR;100002&activeMenuId=200001",
                      "vendor=PY_UY;100001&activeMenuId=200001",
                      "vendor=PY_AR;100001&activeMenuId=2000010",
                      "vendor=PY_AR;1000010&activeMenuId=200001",
                      "vendor=PY_AR;100001&activeMenuId=200001%26vendor%3DPY_AR%3B100002"):
            with self.subTest(query=query):
                self.assertFalse(self.destino.coincide(Destino.BASE + "?" + query))

    def test_host_ruta_protocolo_y_credenciales(self):
        for url in (self.destino.url.replace("https:", "http:"),
                    self.destino.url.replace(".com/", ".com.ejemplo/"),
                    self.destino.url.replace("portal-app", "usuario@portal-app"),
                    self.destino.url.replace("menu-management-v2", "menu-management-v20"),
                    "https://web-ar.us.restaurant-partners.com/menus/PY_AR/200001",
                    "https://[invalido", None, 12):
            with self.subTest(url=url):
                self.assertFalse(self.destino.coincide(url))

    def test_contexto_no_se_muta_y_no_se_confunde_entre_locales(self):
        contexto = self.destino.contexto
        contexto[0] = "100002"
        self.assertEqual(self.destino.contexto, ["100001", "200001"])
        self.assertNotEqual(self.destino.contexto, Destino("100002", "200002").contexto)

    def test_ids_solo_numericos(self):
        for identidad in ("", "-1", "abc", "1/2", "1?x", "1\n", None, 123):
            with self.subTest(identidad=identidad), self.assertRaises(ValueError):
                Destino(identidad, "200001")


if __name__ == "__main__":
    unittest.main()
