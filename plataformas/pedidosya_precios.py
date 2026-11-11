"""Destino del nuevo portal de precios de PedidosYa.

La identidad incluye local Y menú. La URL anterior de disponibilidad no
identifica este editor. Los selectores de lectura/editor/guardado quedan
pendientes del HTML real; este módulo no escribe precios ni navega.
"""

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urlsplit


@dataclass(frozen=True)
class DestinoPreciosPedidosYa:
    vendor_id: str
    menu_id: str

    BASE = "https://portal-app.pedidosya.com/menu-management-v2"

    def __post_init__(self):
        for identidad in (self.vendor_id, self.menu_id):
            if not isinstance(identidad, str) or not re.fullmatch(r"[0-9]{1,40}", identidad):
                raise ValueError("El local y el menú de PedidosYa deben tener IDs numéricas")

    @classmethod
    def desde_url(cls, url):
        if not isinstance(url, str) or len(url) > 2048 or any(c.isspace() for c in url.strip()):
            raise ValueError("Pegá el enlace completo del menú de PedidosYa")
        try:
            partes = urlsplit(url.strip())
            if (partes.scheme != "https" or partes.netloc != "portal-app.pedidosya.com"
                    or partes.path.rstrip("/") != "/menu-management-v2"):
                raise ValueError()
            parametros = parse_qs(partes.query, keep_blank_values=True)
            vendors = parametros.get("vendor", [])
            menus = parametros.get("activeMenuId", [])
            if len(vendors) != 1 or len(menus) != 1 or not vendors[0].startswith("PY_AR;"):
                raise ValueError()
            return cls(vendors[0][len("PY_AR;"):], menus[0])
        except ValueError as e:
            raise ValueError("Usá el enlace de menu-management-v2 con vendor y activeMenuId de Argentina") from e

    @property
    def url(self):
        return self.BASE + "?" + urlencode({
            "vendor": "PY_AR;" + self.vendor_id, "activeMenuId": self.menu_id})

    @property
    def contexto(self):
        # Copia serializable para congelar el destino de lecturas y planes.
        return [self.vendor_id, self.menu_id]

    def coincide(self, url):
        try:
            return self == self.desde_url(url)
        except ValueError:
            return False

    def exigir(self, url):
        if not self.coincide(url):
            raise ValueError("Cambió el local o el menú de PedidosYa; volvé a leer los precios")
