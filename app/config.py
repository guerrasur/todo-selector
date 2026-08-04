"""Ajustes de la app. Se guardan en la tabla `preferencias` (clave/valor).

Por que en la base y no en un archivo al lado del codigo: la carpeta de la
app se pisa en cada autoupdate (ver actualizar.ps1) y la base vive afuera,
en %LOCALAPPDATA%. Un config.json adentro del repo se perdia en el primer
arranque.

TODO lo que hay aca tiene como default exactamente lo que la app venia
haciendo hardcodeado, asi que una base sin ninguna preferencia guardada se
comporta igual que antes. Nada de esto necesita migracion: `preferencias` ya
existe y es clave/valor.

Las claves llevan el prefijo `cfg_` para no chocar con las marcas sueltas
que ya vivian en esa tabla (`catalogo_manual`, `novedades_ignoradas`).
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from .database import SessionLocal
from .models import Preferencia

log = logging.getLogger("config")

PREFIJO = "cfg_"

# Los ids de sucursal terminan adentro de una URL. No hay usuarios ajenos en
# una app local, pero un espacio de mas convierte un ajuste mal tipeado en
# una navegacion a otro lado sin ningun mensaje util.
RE_ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


@dataclass(frozen=True)
class Opcion:
    clave: str
    titulo: str
    defecto: Any
    tipo: str = "bool"          # bool | entero | texto | eleccion
    ayuda: str = ""
    grupo: str = "General"
    minimo: int | None = None
    maximo: int | None = None
    unidad: str = ""
    # Para tipo "eleccion": [(valor, etiqueta), ...]
    opciones: tuple = field(default_factory=tuple)
    # Solo para tipo "texto": si puede guardarse vacío. Los ids de sucursal
    # (pedidosya_menu_id, etc.) son obligatorios a propósito -- un vacío ahí
    # es un error de tipeo, no una decisión. rappi_comun_store_id es el
    # primer campo de verdad opcional: la mayoría de los locales no lo usa,
    # y sin esto guardar CUALQUIER ajuste fallaba con "no puede quedar
    # vacío" apenas ese campo existía sin llenar.
    opcional: bool = False


OPCIONES = (
    # ---------------- Cierre: apagar/prender toda una plataforma ----------
    Opcion(
        clave="cierre_accion",
        titulo="Qué apagado usa «Apagar todo»",
        defecto="apagar_hoy",
        tipo="eleccion",
        grupo="Apagar todo",
        opciones=(("apagar_hoy", "Por hoy (vuelve solo mañana)"),
                  ("apagar_indef", "Indefinido (hasta que lo prendas)")),
        ayuda="Al cierre casi siempre conviene «por hoy»: el portal lo revive "
              "solo al otro día y no hay que acordarse de prenderlo.",
    ),
    Opcion(
        clave="cierre_releer",
        titulo="Leer el portal antes de apagar todo",
        defecto=True,
        grupo="Apagar todo",
        ayuda="Tarda ~35 s más, pero evita encolar los que ya están apagados. "
              "Sin esto se decide con la última lectura, que puede estar vieja.",
    ),
    Opcion(
        clave="cierre_incluir_pausados",
        titulo="Incluir los productos en pausa",
        defecto=False,
        grupo="Apagar todo",
        ayuda="Los pausados son los que este mes no se venden. Normalmente ya "
              "están apagados y no hace falta tocarlos.",
    ),
    Opcion(
        clave="apertura_solo_propios",
        titulo="«Prender todo» prende solo lo que apagó la app",
        defecto=True,
        grupo="Apagar todo",
        ayuda="Con esto prendido, lo que figura «apagado (afuera)» queda como "
              "está: si alguien lo apagó desde el portal, fue a propósito.",
    ),

    # ---------------- Tiendas en pausa ----------------
    #
    # Una tienda entera "desactivada": la app NO la prende (ni de a un
    # producto ni con «Prender todo») hasta que la saques de pausa. Sigue
    # leyéndose y se puede apagar, que es justo lo que hace falta para
    # dejarla apagada: lo que no puede pasar es que un click de más la
    # reviva. Es el mismo concepto que pausar un producto, pero de la
    # tienda entera (pedido del usuario, 2026-08-04: "los jefes me piden
    # desactivar Rappi Común").
    #
    # Van una por plataforma y escritas a mano (no generadas) para que
    # `OPCIONES` siga siendo la lista completa y la pantalla de Ajustes las
    # dibuje sola. La que no está activa en esta instalación no se muestra
    # (ver para_la_pantalla).
    Opcion(
        clave="tienda_pausada_pedidosya",
        titulo="PedidosYa en pausa",
        defecto=False,
        grupo="Tiendas en pausa",
        ayuda="Con esto prendido, la app no prende nada en PedidosYa. "
              "Apagar sí se puede.",
    ),
    Opcion(
        clave="tienda_pausada_rappi",
        titulo="Rappi (Turbo) en pausa",
        defecto=False,
        grupo="Tiendas en pausa",
        ayuda="Con esto prendido, la app no prende nada en Rappi Turbo. "
              "Apagar sí se puede.",
    ),
    Opcion(
        clave="tienda_pausada_rappi_comun",
        titulo="Rappi Común en pausa",
        defecto=False,
        grupo="Tiendas en pausa",
        ayuda="Con esto prendido, la app no prende nada en Rappi Común. "
              "Apagar sí se puede.",
    ),

    # ---------------- Ritmo del worker ----------------
    Opcion(
        clave="minutos_ronda",
        titulo="Releer las dos cartas cada",
        defecto=15,
        tipo="entero",
        grupo="Ritmo",
        minimo=0,
        maximo=240,
        unidad="minutos",
        ayuda="0 = nunca. Es la ronda que mantiene la pantalla al día y caza "
              "lo que el portal revivió solo.",
    ),
    Opcion(
        clave="sostener_apagados",
        titulo="Volver a apagar lo que el portal revive",
        defecto=True,
        grupo="Ritmo",
        ayuda="Si se apaga, la ronda sigue leyendo y actualizando la pantalla "
              "pero no reencola nada por su cuenta.",
    ),
    Opcion(
        clave="verificacion_rapida",
        titulo="Confirmar un apagado a los",
        defecto=120,
        tipo="entero",
        grupo="Ritmo",
        minimo=0,
        maximo=1800,
        unidad="segundos",
        ayuda="0 = no confirmar. PedidosYa a veces revive el producto unos "
              "minutos después de apagarlo.",
    ),
    Opcion(
        clave="frescura_pestana",
        titulo="Refrescar la pestaña si tiene más de",
        defecto=120,
        tipo="entero",
        grupo="Ritmo",
        minimo=10,
        maximo=3600,
        unidad="segundos",
        ayuda="Antes de cada operación. Más bajo = más seguro y más lento.",
    ),
    Opcion(
        clave="max_intentos",
        titulo="Reintentos por operación",
        defecto=3,
        tipo="entero",
        grupo="Ritmo",
        minimo=1,
        maximo=10,
    ),
    Opcion(
        clave="refresco_pantalla",
        titulo="La pantalla se actualiza cada",
        defecto=3,
        tipo="entero",
        grupo="Ritmo",
        minimo=1,
        maximo=60,
        unidad="segundos",
    ),

    # ---------------- Que local es ----------------
    #
    # Vienen VACIOS: son los datos de TU local y la app no tiene forma de
    # adivinarlos. Se completan una sola vez, la primera que abrís la app
    # (la pantalla te lo pide sola). Antes venían con los del local para el
    # que se escribió esto, que además de no servirle a nadie más era
    # publicar en un repo público a qué sucursal pertenecen.
    Opcion(
        clave="pedidosya_menu_id",
        titulo="Id de menú de PedidosYa",
        defecto="",
        tipo="texto",
        grupo="Sucursal",
        ayuda="Entrá al menú en el portal de PedidosYa y miralo al final de "
              "la URL: /menus/PY_AR/<esto>. Son números.",
    ),
    Opcion(
        clave="rappi_brand_id",
        titulo="brandId de Rappi",
        defecto="",
        tipo="texto",
        grupo="Sucursal",
        ayuda="Está en la URL del menú de Rappi Partners: "
              "/menu?brandId=<esto>&storeIds=… Suele empezar con las dos "
              "letras del país.",
    ),
    Opcion(
        clave="rappi_store_id",
        titulo="storeId de Rappi (Turbo)",
        defecto="",
        tipo="texto",
        grupo="Sucursal",
        ayuda="La tienda principal de Rappi, de la misma URL "
              "(storeId=<esto>). Si tenés más de una, esta es la que la app "
              "usa siempre; la otra se carga abajo, en «Rappi Común». OJO: "
              "son tiendas independientes y NO comparten la carta — apagar "
              "en una no apaga en la otra.",
    ),
    # Grupo aparte y NO "Sucursal" a propósito: ese grupo es el que la
    # pantalla de primer arranque exige completar entero antes de dejar
    # usar la app (ver pasoSucursal() en static/index.html). Esto es
    # opcional — la mayoría de los locales no vende por Rappi Común — así
    # que no puede bloquear a nadie que no lo tenga.
    # Solo para poder MOSTRAR si la tienda entera esta abierta o cerrada
    # (ver conversacion del 2026-07-30). Rappi no expone el storeId en la
    # pantalla de Conectividad, asi que hay que decirle a la app como se
    # llama la tienda ahi para encontrar la fila correcta. Opcional: sin
    # esto la pantalla simplemente no muestra el estado de esta tienda, no
    # rompe nada mas (leer_estado_tienda devuelve None).
    #
    # Grupo aparte y NO "Sucursal" a propósito, mismo motivo que
    # rappi_comun_store_id mas abajo: ese grupo es el que la pantalla de
    # primer arranque exige completar ENTERO antes de dejar usar la app
    # (pasoSucursal() en static/index.html no mira `opcional`). Un campo
    # opcional metido ahi bloqueaba el primer arranque de cualquier
    # instalacion nueva (confirmado por pruebas/probar_primer_arranque.py).
    Opcion(
        clave="rappi_nombre_tienda",
        titulo="Nombre de la tienda en \"Conectividad\" (Rappi)",
        defecto="",
        tipo="texto_libre",
        grupo="Estado de tienda",
        opcional=True,
        ayuda="Para mostrar si la tienda está abierta o cerrada. Es el "
              "nombre EXACTO que Rappi Partners muestra en Administración → "
              "Conectividad, columna «Tienda» (ej: «Mi Local - Turbo»). "
              "Vacío = la pantalla no muestra el estado de esta tienda.",
    ),
    # Rappi Común ya tenia su override de brandId para Conectividad y Turbo
    # no: si la pantalla de Conectividad de Turbo tambien vive bajo otra
    # marca, no habia ningun ajuste que lo arreglara. Mismo significado y
    # mismo default (vacio = el rappi_brand_id de siempre).
    Opcion(
        clave="rappi_brand_id_conectividad",
        titulo="brandId de Rappi (Turbo) en \"Conectividad\"",
        defecto="",
        tipo="texto",
        grupo="Estado de tienda",
        opcional=True,
        ayuda="Normalmente NO hace falta tocarlo. Solo si el badge de estado "
              "de Rappi Turbo dice que Conectividad no se quedó en tu tienda: "
              "entrá a Administración → Conectividad y mirá el brandId de la "
              "URL, puede no ser el mismo que el del menú. Vacío = usa el "
              "brandId de siempre.",
    ),
    Opcion(
        clave="rappi_comun_store_id",
        titulo="storeId de Rappi Común",
        defecto="",
        tipo="texto",
        grupo="Rappi Común",
        opcional=True,
        ayuda="Solo si tu local vende también por la tienda Rappi «común», "
              "aparte de la Turbo. Vacío = la app no la toca: no le abre "
              "pestaña, no aparece en la pantalla y no le encola nada. Si "
              "lo llenás, pasa a ser una tercera plataforma con su propio "
              "chip y su propio botón (mismo brandId, storeId distinto, "
              "sale de la URL del menú de esa tienda). Son tiendas "
              "INDEPENDIENTES y su carta no es la misma: apagar en una no "
              "apaga en la otra, así que hay que decirle en la pantalla "
              "Carta qué producto de una es cuál de la otra. Después, un "
              "solo botón apaga las dos.",
    ),
    Opcion(
        clave="rappi_comun_nombre_tienda",
        titulo="Nombre de la tienda en \"Conectividad\" (Rappi Común)",
        defecto="",
        tipo="texto_libre",
        grupo="Rappi Común",
        opcional=True,
        ayuda="Igual que el de Rappi, pero el nombre EXACTO de la tienda "
              "Común en esa misma tabla de Conectividad.",
    ),
    # CONFIRMADO EN VIVO (2026-07-30): pese a lo que dice "rappi_comun_store_id"
    # mas arriba ("mismo brandId, storeId distinto"), Rappi Común puede tener
    # su PROPIO brandId, distinto del de Turbo (en la cuenta de prueba:
    # AR72021 contra AR75000). No hacia falta para el menu de productos
    # (Rappi tolera el storeId aunque el brandId de la URL sea el de la otra
    # tienda), pero SI hace falta para encontrar la fila correcta en
    # Conectividad. Vacio = usa el mismo rappi_brand_id de siempre.
    Opcion(
        clave="rappi_comun_brand_id_conectividad",
        titulo="brandId de Rappi Común en \"Conectividad\"",
        defecto="",
        tipo="texto",
        grupo="Rappi Común",
        opcional=True,
        ayuda="Normalmente NO hace falta tocarlo. Solo si el badge de estado "
              "de Rappi Común nunca muestra nada: entrá a Administración → "
              "Conectividad con la tienda Común seleccionada y mirá el "
              "brandId en la URL — puede ser distinto al de Rappi Turbo. "
              "Vacío = usa el mismo brandId de Rappi Turbo.",
    ),
)

POR_CLAVE = {o.clave: o for o in OPCIONES}

_cache: dict | None = None


# ---------- Leer ----------

def _convertir(opcion: Opcion, crudo: str) -> Any:
    """El valor guardado (texto) al tipo que espera el codigo."""
    if opcion.tipo == "bool":
        return crudo == "1"
    if opcion.tipo == "entero":
        try:
            return int(crudo)
        except (TypeError, ValueError):
            return opcion.defecto
    if opcion.tipo == "eleccion":
        validos = [v for v, _ in opcion.opciones]
        return crudo if crudo in validos else opcion.defecto
    return crudo


def recargar() -> dict:
    """Relee todo de la base. La llaman el arranque y cada guardado."""
    global _cache
    valores = {o.clave: o.defecto for o in OPCIONES}

    db = SessionLocal()
    try:
        for pref in db.query(Preferencia).all():
            if not pref.clave.startswith(PREFIJO):
                continue
            opcion = POR_CLAVE.get(pref.clave[len(PREFIJO):])
            if opcion is None:
                continue        # sobro de una version anterior; no molesta
            valores[opcion.clave] = _convertir(opcion, pref.valor)
    except Exception as e:
        # Sin base todavia (o rota) la app tiene que arrancar igual: con los
        # defaults se comporta como antes de que existieran los ajustes.
        log.warning("No pude leer los ajustes, uso los valores por defecto: %s", e)
    finally:
        db.close()

    _cache = valores
    return valores


def todo() -> dict:
    global _cache
    if _cache is None:
        recargar()
    return dict(_cache)


def obtener(clave: str) -> Any:
    global _cache
    if _cache is None:
        recargar()
    if clave not in _cache:
        raise KeyError(f"ajuste desconocido: {clave}")
    return _cache[clave]


def entero(clave: str) -> int:
    return int(obtener(clave))


def activo(clave: str) -> bool:
    return bool(obtener(clave))


def texto(clave: str) -> str:
    return str(obtener(clave))


# Las plataformas que SIEMPRE existen. El resto son opcionales y solo
# cuentan si el usuario las configuró. La lista completa (la que valida los
# nombres) es catalogo.PLATAFORMAS; esta dice cuáles están en uso HOY.
PLATAFORMAS_FIJAS = ("pedidosya", "rappi")

# plataforma opcional -> ajuste que la prende. Vacío = no existe para esta
# instalación: no se le abre pestaña, no se la ve en la pantalla y no se le
# encolan operaciones.
PLATAFORMAS_OPCIONALES = {"rappi_comun": "rappi_comun_store_id"}


def plataformas_activas() -> list[str]:
    """Las plataformas que esta instalación realmente usa.

    Es UNA sola respuesta para toda la app: el worker decide con esto a qué
    portal abrirle pestaña, la API con qué operaciones acepta, y la pantalla
    qué chips dibuja. Sin esto, "Rappi Común" le aparecía a todo el mundo
    (un chip de más en cada producto y una fila de más en «Apagar todo»)
    aunque no la usara.
    """
    activas = list(PLATAFORMAS_FIJAS)
    activas += [plat for plat, clave in PLATAFORMAS_OPCIONALES.items()
                if texto(clave)]
    return activas


# plataforma -> ajuste que la pone en pausa. OJO: una tienda en pausa SIGUE
# activa. Se le abre pestaña, se lee y se puede apagar; lo unico que no pasa
# es que la app la prenda. Sacarla de plataformas_activas() la volveria
# invisible y entonces no habria ni como apagarla ni como ver como quedo.
PAUSA_POR_PLATAFORMA = {
    "pedidosya": "tienda_pausada_pedidosya",
    "rappi": "tienda_pausada_rappi",
    "rappi_comun": "tienda_pausada_rappi_comun",
}


def tienda_pausada(plataforma: str) -> bool:
    """True si esa tienda esta en pausa: la app no la prende."""
    clave = PAUSA_POR_PLATAFORMA.get(plataforma)
    return bool(clave) and activo(clave)


def tiendas_pausadas() -> list[str]:
    """Las tiendas activas que estan en pausa, en el orden de siempre."""
    return [p for p in plataformas_activas() if tienda_pausada(p)]


# ---------- Escribir ----------

def _validar(opcion: Opcion, valor: Any) -> Any:
    if opcion.tipo == "bool":
        return bool(valor)

    if opcion.tipo == "entero":
        try:
            numero = int(valor)
        except (TypeError, ValueError):
            raise ValueError(f"«{opcion.titulo}» tiene que ser un número")
        if opcion.minimo is not None and numero < opcion.minimo:
            raise ValueError(f"«{opcion.titulo}»: el mínimo es {opcion.minimo}")
        if opcion.maximo is not None and numero > opcion.maximo:
            raise ValueError(f"«{opcion.titulo}»: el máximo es {opcion.maximo}")
        return numero

    if opcion.tipo == "eleccion":
        validos = [v for v, _ in opcion.opciones]
        if valor not in validos:
            raise ValueError(f"«{opcion.titulo}»: {valor} no es una opción")
        return valor

    if opcion.tipo == "texto_libre":
        # A diferencia de "texto" (ids que van en una URL), esto es un
        # nombre tal cual lo escribe el portal: tiene espacios, tildes,
        # guiones sueltos. Sin validar formato, solo que no venga vacio si
        # no es opcional.
        limpio = str(valor).strip()
        if opcion.opcional and not limpio:
            return ""
        if not limpio:
            raise ValueError(f"«{opcion.titulo}» no puede estar vacío")
        if len(limpio) > 120:
            raise ValueError(f"«{opcion.titulo}»: demasiado largo")
        return limpio

    limpio = str(valor).strip()
    if opcion.opcional and not limpio:
        return ""
    if not RE_ID.match(limpio):
        raise ValueError(f"«{opcion.titulo}»: solo letras, números, - y _")
    return limpio


def _a_texto(opcion: Opcion, valor: Any) -> str:
    if opcion.tipo == "bool":
        return "1" if valor else "0"
    return str(valor)


def guardar(db, cambios: dict) -> dict:
    """Valida y guarda. Devuelve la config entera ya aplicada.

    Se valida TODO antes de escribir nada: media tanda guardada seria peor
    que ninguna, porque no habria forma de saber cual quedo.
    """
    limpios = {}
    for clave, valor in cambios.items():
        opcion = POR_CLAVE.get(clave)
        if opcion is None:
            raise ValueError(f"ajuste desconocido: {clave}")
        limpios[clave] = _validar(opcion, valor)

    for clave, valor in limpios.items():
        opcion = POR_CLAVE[clave]
        fila = db.query(Preferencia).get(PREFIJO + clave)
        if fila is None:
            fila = Preferencia(clave=PREFIJO + clave)
            db.add(fila)
        nuevo = _a_texto(opcion, valor)
        if fila.valor != nuevo:
            log.info("ajuste %s: '%s' -> '%s'", clave, fila.valor, nuevo)
        fila.valor = nuevo

    db.flush()
    return limpios


def restablecer(db) -> dict:
    """Borra lo guardado: vuelve a los valores por defecto."""
    (db.query(Preferencia)
       .filter(Preferencia.clave.like(PREFIJO + "%"))
       .delete(synchronize_session=False))
    db.flush()
    return {o.clave: o.defecto for o in OPCIONES}


def para_la_pantalla() -> list[dict]:
    """La definicion de cada ajuste + su valor actual, para dibujar el panel.

    La pantalla no sabe que ajustes existen: los dibuja de esto. Agregar uno
    nuevo es agregarlo a OPCIONES y nada mas.

    Lo unico que se filtra es la pausa de una tienda que esta instalacion no
    usa: "Rappi Común en pausa" en un local que no vende por ahi no es un
    ajuste, es una pregunta sin sentido (regla 9: que plataformas hay lo
    dice plataformas_activas(), no una lista escrita a mano).
    """
    valores = todo()
    activas = plataformas_activas()
    escondidas = {clave for plat, clave in PAUSA_POR_PLATAFORMA.items()
                  if plat not in activas}
    return [{
        "clave": o.clave,
        "titulo": o.titulo,
        "ayuda": o.ayuda,
        "grupo": o.grupo,
        "tipo": o.tipo,
        "unidad": o.unidad,
        "minimo": o.minimo,
        "maximo": o.maximo,
        "opciones": [{"valor": v, "etiqueta": e} for v, e in o.opciones],
        "defecto": o.defecto,
        "valor": valores[o.clave],
    } for o in OPCIONES if o.clave not in escondidas]
