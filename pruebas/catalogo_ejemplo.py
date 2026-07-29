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
  - **Las dos tiendas de Rappi no tienen la misma carta** (ver RAPPI_COMUN):
    hay platos que estan en Turbo y no en Comun, uno que esta en Comun y no
    en Turbo, y una "Empanada de carne chica" que es prefijo de la
    "Empanada de carne" de las otras dos y NO es el mismo plato.

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

# Como se llama cada uno en la tienda Rappi Comun, que es OTRA tienda con
# OTRA carta (no es la de Turbo con otro nombre). Va aparte y no como una
# quinta columna de PRODUCTOS para no tocar el formato que ya usan las
# pruebas y `seed.PRODUCTOS`.
#
# Lo que reproduce, que es justo lo que hace falta cubrir:
#   - el mismo nombre exacto que en Turbo (lo normal);
#   - el nombre con la tilde al reves que en Turbo ("Milanesa con pure");
#   - platos que NO estan en esta tienda (los que no figuran aca): el
#     producto tiene dos botones y no tres;
#   - un plato que esta en Comun y no en Turbo ("Tostado de queso"),
#     porque la carta de las dos tiendas no es la misma;
#   - la trampa del prefijo ENTRE TIENDAS DE RAPPI: en Comun hay una
#     "Empanada de carne chica" que puntua 0.91 contra la "Empanada de
#     carne" de las otras dos y es otro plato.
RAPPI_COMUN = {
    "Tarta de verdura": "Tarta de verdura",
    "Tarta de choclo": "Tarta de choclo y queso",
    "Budín de pan": "Budín de pan",
    "Sopa del dia": "Sopa del día",
    "Milanesa con pure": "Milanesa con pure",
    "Agua chica": "Manantial sin gas 500 ml",
    "Ñoquis del 29": "Ñoquis del 29",
}

# OJO: esto es el CATALOGO (lo que la app tiene vinculado), no la carta que
# muestra el portal de esa tienda. La carta vive en carta_ejemplo.json y
# tiene ademas lo que el catalogo no vinculo: la "Empanada de carne chica"
# —que es otro plato— y algo que en Turbo no esta.

# Ids de sucursal de mentira. Los de verdad los pone cada uno en Ajustes;
# lo unico que importa aca es que esten, para que la app no se quede en la
# pantalla de primer arranque.
SUCURSAL = {
    "pedidosya_menu_id": "100200",
    "rappi_brand_id": "XX90000",
    "rappi_store_id": "XX90001",
}

# La tienda Rappi Comun es opcional: con esto vacio la app ni la nombra.
# Las pruebas que la necesitan lo guardan aparte, para que las demas sigan
# viendo exactamente la instalacion de dos plataformas de siempre.
STORE_ID_RAPPI_COMUN = "XX90002"


def usar_catalogo():
    """Que `seed.sembrar()` siembre esta carta y no la lista vacia."""
    from app import seed
    seed.PRODUCTOS = PRODUCTOS


def vincular_rappi_comun(db):
    """Le cuelga la tienda Comun a los productos del catalogo que la tienen.

    Es lo que deja hecha la "primera pasada" por la pantalla de asociacion,
    para poder probar lo que pasa DESPUES: que el producto vinculado en las
    dos tiendas se apaga en las dos, y que el que no paso por ahi no.
    """
    from app import catalogo
    from app.models import Producto

    for canonico, remoto in RAPPI_COMUN.items():
        producto = db.query(Producto).filter_by(nombre=canonico).first()
        if producto is None:
            continue
        catalogo.enlazar(db, producto.id, "rappi_comun", remoto)
    db.commit()


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
