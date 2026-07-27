"""Carga inicial de productos con sus nombres en cada plataforma.

IMPORTANTE: los nombres difieren mucho entre PedidosYa y Rappi.
Formato: (nombre_canonico, categoria, nombre_en_pedidosya, nombre_en_rappi)
Si un nombre es None, ese producto NO existe en esa plataforma.

REVISAR LAS MARCAS "DUDA" ANTES DE USAR EN PRODUCCION.
"""

from .database import SessionLocal
from .models import Producto, AliasPlataforma, EstadoItem

# (canonico, categoria, pedidosya, rappi)
PRODUCTOS = [
    # ---------------- Platos ----------------
    ("Tarta de choclo", "Platos", "Tarta de choclo", "Tarta de choclo y queso"),
    ("Flan casero", "Platos", "Flan casero", "Flan casero"),
    ("Milanesa con pure", "Platos", "Milanesa con pure", "Ensalada milanesa"),
    ("Budín de pan", "Platos", "Budín de pan", "Budín de pan"),
    ("Milanesa napolitana", "Platos", "Milanesa napolitana", "Ensalada con zapallo"),
    ("Pollo al horno", "Platos", "Pollo al horno", "Pollo al horno"),
    ("Sopa del dia", "Platos", "Sopa del dia", "Sopa del día"),
    ("Pollo al verdeo", "Platos", "Pollo al verdeo", "Pollo al verdeo"),

    # Mixta: descontinuada, no se usa mas. Se deja comentada por si vuelve.
    # ("Mixta", "Platos", "Mixta", None),

    # CONFIRMADO: "Ñoquis del 29" no existe en PedidosYa.
    ("Ñoquis del 29", "Platos", None, "Ñoquis del 29"),

    # ---------------- Tartas ----------------
    ("Tarta de choclo", "Tartas", "Tarta de choclo", "Tarta de choclo"),
    ("Tarta de verdura", "Tartas", "Tarta de verdura", "Tarta de verdura"),
    ("Tarta de cebolla", "Tartas", "Tarta de cebolla", "Tarta de cebolla"),
    ("Tarta de espinaca", "Tartas",
     "Tarta de espinaca", "Tarta de espinaca"),

    # DUDA IMPORTANTE: en PedidosYa dice "chica", en Rappi "individual".
    # Asumo que son el mismo producto con distinta guarnicion en el nombre.
    # CONFIRMAR: son el mismo plato o son distintos?
    ("Tarta de verdura chica", "Tartas",
     "Tarta de verdura chica", "Tarta de verdura individual"),
    ("Tarta de zapallo chica", "Tartas",
     "Tarta de zapallo chica", "Tarta de zapallo individual"),
    ("Tarta de cebolla chica", "Tartas",
     "Tarta de cebolla chica", "Tarta de cebolla individual"),
    ("Tarta de espinaca chica", "Tartas",
     "Tarta de espinaca chica", "Tarta de espinaca individual"),

    # CONFIRMADO: "Tarta de zapallo" (sin guarnicion) no existe en PedidosYa.
    ("Tarta de zapallo", "Tartas", None, "Tarta de zapallo"),
    # CONFIRMADO: "Tarta de choclo individual" no existe en PedidosYa.
    ("Tarta de choclo individual", "Tartas", None, "Tarta de choclo individual"),

    # ---------------- Platos ----------------
    # En PedidosYa estos figuran bajo "Platos"; en Rappi bajo "Plato del Dia".
    # Los dejo como categoria propia para que se vean juntos en la UI.
    ("Empanada de carne", "Platos", "Empanada de carne", "Empanada de carne"),
    ("Ensalada mixta", "Platos", "Ensalada mixta", "Ensalada mixta de hojas"),
    ("Tarta de jamon y queso", "Platos", "Tarta de jamon y queso", "Tarta de jamón y queso"),
    ("fideos con salsa", "Platos",
     "fideos con salsa", "fideos con salsa"),
    ("Pollo al horno", "Platos", "Pollo al horno", "Pollo al horno"),
    ("Pollo al horno sin sal", "Platos",
     "Pollo al horno sin sal", "Pollo al horno sin sal"),

    # CONFIRMADO: la Locro no existe en PedidosYa.
    ("Locro del sabado", "Platos",
     None, "Locro del sabado"),

    # ---------------- Bebidas ----------------
    ("Agua chica", "Bebidas", "Agua chica", "Manantial sin gas 500 ml"),
    ("Agua chica con gas", "Bebidas", "Agua chica con gas", "Manantial con gas 500 ml"),
    ("Gaseosa cola", "Bebidas", "Gaseosa cola", "Gaseosa cola 500 ml"),

    # CONFIRMADO: en PedidosYa se cargo mal y quedo "Gaseosa cola cero".
    # El nombre esta asi en el portal, no es un typo de esta lista.
    ("Gaseosa cola cero", "Bebidas", "Gaseosa cola cero", "Gaseosa cola sin azucar 500 ml"),
]

PLATAFORMAS = ["pedidosya", "rappi"]


def sembrar():
    db = SessionLocal()
    try:
        if db.query(Producto).count() > 0:
            return  # ya sembrado

        for i, (canonico, categoria, n_py, n_rappi) in enumerate(PRODUCTOS):
            p = Producto(nombre=canonico, categoria=categoria, orden=i)
            db.add(p)
            db.flush()

            # Alias solo si difiere del canonico
            if n_py and n_py != canonico:
                db.add(AliasPlataforma(producto_id=p.id, plataforma="pedidosya",
                                       nombre_remoto=n_py))
            if n_rappi and n_rappi != canonico:
                db.add(AliasPlataforma(producto_id=p.id, plataforma="rappi",
                                       nombre_remoto=n_rappi))

            # Solo creamos estado en las plataformas donde el producto existe
            for plat, nombre in (("pedidosya", n_py), ("rappi", n_rappi)):
                if nombre is None:
                    continue
                db.add(EstadoItem(producto_id=p.id, plataforma=plat,
                                  estado=EstadoItem.DESCONOCIDO))

        db.commit()
    finally:
        db.close()
