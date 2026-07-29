"""Una carta INVENTADA para las pruebas.

`app/seed.py` viene vacio a proposito: una instalacion nueva no arranca con
la carta de otro local. Pero las pruebas necesitan un catalogo, asi que
aca hay uno de mentira — un local que no existe.

No es una lista cualquiera: reproduce a proposito las trampas que en este
proyecto ya costaron caro, porque si el ejemplo fuera facil las pruebas
dejarian de cubrirlas.

  - **Prefijos.** "Tarta de verdura" es prefijo de "Tarta de verdura chica".
    Buscar sin `exact=True` apaga el que no era.
  - **Tildes.** El canonico "Budín de pan" lleva tilde y en PedidosYa se
    llama "Budin de pan": buscar "budin" tiene que encontrarlo igual.
  - **Nombres que no se parecen en nada entre portales.** "Agua chica" en
    PedidosYa es "Manantial sin gas 500 ml" en Rappi. Ninguna heuristica
    los junta sola: los vincula el usuario.
  - **Variantes que NO son el mismo plato.** "Tarta de verdura chica",
    "Tarta de verdura individual" y "Tarta de verdura porción" se parecen
    muchisimo y son tres cosas distintas.
  - **Productos que existen en un solo portal**, en los dos sentidos.

Se usa asi, antes de arrancar la app o de llamar a `seed.sembrar()`:

    from catalogo_ejemplo import preparar
    preparar()
"""

# (canonico, categoria, nombre_en_pedidosya, nombre_en_rappi)
PRODUCTOS = [
    # ---------------- Tartas ----------------
    # Se llama igual en los dos: al separarlo, uno de los dos tiene que
    # quedar con un sufijo para no chocar.
    ("Tarta de verdura", "Tartas", "Tarta de verdura", "Tarta de verdura"),

    # Prefijo del anterior, y solo en un portal. Las dos trampas juntas.
    ("Tarta de verdura chica", "Tartas", "Tarta de verdura chica", None),
    ("Tarta de verdura individual", "Tartas", None, "Tarta de verdura individual"),

    ("Tarta de choclo", "Tartas", "Tarta de choclo", "Tarta de choclo y queso"),
    ("Tarta de jamon y queso", "Tartas",
     "Tarta de jamon y queso", "Tarta de jamón y queso"),

    # ---------------- Platos ----------------
    ("Empanada de carne", "Platos", "Empanada de carne", "Empanada de carne"),
    ("Flan casero", "Platos", "Flan casero", "Flan casero"),

    # El canonico con tilde y el nombre de PedidosYa sin ella.
    ("Budín de pan", "Platos", "Budin de pan", "Budín de pan"),

    ("Sopa del dia", "Platos", "Sopa del dia", "Sopa del día"),
    ("Ensalada mixta", "Platos", "Ensalada mixta", "Ensalada mixta de hojas"),
    ("Milanesa con pure", "Platos", "Milanesa con pure", "Milanesa con puré"),
    ("Pollo al horno", "Platos", "Pollo al horno", "Pollo al horno"),

    # Solo en Rappi: el chip de PedidosYa sale en gris con "—".
    ("Locro del sabado", "Platos", None, "Locro del sábado"),
    ("Ñoquis del 29", "Platos", None, "Ñoquis del 29"),

    # ---------------- Bebidas ----------------
    # Los nombres no se parecen en nada entre un portal y el otro.
    ("Agua chica", "Bebidas", "Agua chica", "Manantial sin gas 500 ml"),
    ("Agua chica con gas", "Bebidas",
     "Agua chica con gas", "Manantial con gas 500 ml"),
    ("Gaseosa cola", "Bebidas", "Gaseosa cola", "Gaseosa cola 500 ml"),
]

# Ids de sucursal de mentira. Los de verdad los pone cada uno en Ajustes;
# lo unico que importa aca es que esten, para que la app no se quede en la
# pantalla de primer arranque.
SUCURSAL = {
    "pedidosya_menu_id": "100200",
    "rappi_brand_id": "XX90000",
    "rappi_store_id": "XX90001",
}


def usar_catalogo():
    """Que `seed.sembrar()` siembre esta carta y no la lista vacia."""
    from app import seed
    seed.PRODUCTOS = PRODUCTOS


def preparar(con_sucursal: bool = True):
    """Deja la base lista con la carta de ejemplo y una sucursal cargada.

    `con_sucursal=False` sirve para probar el primer arranque de verdad,
    que es justo el caso en que todavia no hay nada configurado.
    """
    from app import config
    from app.database import init_db, SessionLocal

    usar_catalogo()
    init_db()

    if not con_sucursal:
        return

    db = SessionLocal()
    try:
        config.guardar(db, SUCURSAL)
        db.commit()
    finally:
        db.close()
    config.recargar()
