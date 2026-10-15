"""URLs reales por formato, con ids ficticios y sin tocar portales."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plataformas.rappi import Rappi

class PortalNuevo(unittest.TestCase):
    def test_tienda_exacta(self):
        pagina = SimpleNamespace(url='')
        rappi = Rappi(pagina, store_id='AR100', brand_id='AR900')
        self.assertEqual(rappi.url_menu, 'https://restaurantes.rappi.com/menu?storeIds=AR100')
        for url, esperado in [
            (rappi.url_menu, True),
            (rappi.url_menu + '&otro=1', True),
            (rappi.url_menu + '0', False),
            (rappi.url_menu + ',AR200', False),
            (rappi.url_menu + '&storeIds=AR200', False),
            (rappi.url_menu + '&storeId=AR200', False),
            ('https://partners.rappi.com/menu?storeId=AR100&storeIds=AR100,AR200', True),
            ('https://restaurantes.rappi.com/home?storeIds=AR100', False),
            ('https://otro.test/menu?storeIds=AR100', False),
        ]:
            with self.subTest(url=url):
                pagina.url = url
                self.assertEqual(rappi.en_el_menu(), esperado)

if __name__ == '__main__':
    unittest.main()
