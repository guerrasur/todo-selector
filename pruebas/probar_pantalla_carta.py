"""Prueba la pantalla Carta de punta a punta, en modo simulado.

    py pruebas/probar_pantalla_carta.py

Levanta la app de verdad con STOCKSWITCH_SIMULADO=1 (no abre navegador ni
toca los portales: /api/carta devuelve la carta inventada de
pruebas/carta_ejemplo.json) y la maneja con Playwright como lo haria el
usuario: leer la carta, vincular un par dudoso, separarlo y agregar uno
suelto.
"""

import asyncio
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))

TEMPORAL = tempfile.mkdtemp(prefix="todoselector-pantalla-")
os.environ["HOME"] = TEMPORAL
os.environ["LOCALAPPDATA"] = TEMPORAL
os.environ["STOCKSWITCH_SIMULADO"] = "1"

import uvicorn                                                # noqa: E402
from playwright.async_api import async_playwright             # noqa: E402

import catalogo_ejemplo                                       # noqa: E402
from app.main import app                                      # noqa: E402

# app/seed.py viene VACIO a proposito: una instalacion nueva no arranca con
# la carta de otro local. Estas pruebas siembran una carta inventada y una
# sucursal de mentira, para no quedarse en la pantalla de primer arranque
# (que tiene su propia prueba, mas abajo).
catalogo_ejemplo.preparar()

PUERTO = 8788
BASE = f"http://127.0.0.1:{PUERTO}/"
CHROME_ALTERNATIVO = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

fallos = []


def revisar(condicion, titulo):
    print(("  OK    " if condicion else "  FALLA ") + titulo)
    if not condicion:
        fallos.append(titulo)


def levantar_app():
    config = uvicorn.Config(app, host="127.0.0.1", port=PUERTO, log_level="warning")
    servidor = uvicorn.Server(config)
    threading.Thread(target=servidor.run, daemon=True).start()
    return servidor


async def abrir_navegador(p):
    try:
        return await p.chromium.launch(headless=True)
    except Exception:
        return await p.chromium.launch(headless=True,
                                       executable_path=CHROME_ALTERNATIVO)


def fila_de(pagina, texto_py, texto_rappi):
    """La fila de la carta que cruza esos dos nombres.

    Se excluye .manual: la fila de "Vincular a mano" tiene todos los nombres
    adentro de los <select>, asi que matchearia con cualquier busqueda.
    """
    return (pagina.locator(".par:not(.manual)")
            .filter(has_text=texto_py)
            .filter(has_text=texto_rappi)
            .first)


async def esperar(locator, timeout=10000):
    """True si el elemento aparece antes del timeout."""
    try:
        await locator.first.wait_for(timeout=timeout)
        return True
    except Exception:
        return False


async def esperar_boton(fila, texto, timeout=10000):
    """Espera a que ESA fila ofrezca ese boton.

    No sirve esperar el texto en la pantalla: media carta ya esta vinculada
    y "un solo botón" aparece en un monton de filas desde el primer pintado.
    """
    boton = fila.locator("button", has_text=texto)
    try:
        await boton.wait_for(timeout=timeout)
        return True
    except Exception:
        return False


async def probar_aviso_de_novedad(pagina):
    """El caso del 2026-07-28: agregaron el locro a la carta de PedidosYa.

    El catalogo la tenia como exclusiva de Rappi, asi que la app la mostraba
    en gris con el chip "no existe ahi" y no habia forma de enterarse.
    """
    print("\n== Aviso: apareció en un portal donde no estaba ==")
    from app import catalogo
    from app.database import SessionLocal
    from app.worker import worker

    db = SessionLocal()
    try:
        leido = {"Locro del sábado": True}
        worker.novedades = {
            "pedidosya": catalogo.detectar_novedades(db, "pedidosya", leido)
        }
    finally:
        db.close()

    revisar(len(worker.novedades["pedidosya"]) == 1,
            "la lectura del portal la detecta")

    await pagina.reload()
    panel = pagina.locator("#panel-novedades")
    await panel.wait_for(timeout=10000)
    texto = await panel.inner_text()
    revisar("Locro" in texto and "PedidosYa" in texto,
            "la pantalla avisa que apareció en PedidosYa")

    await panel.locator("button", has_text="Es el mismo").click()
    await pagina.wait_for_timeout(1500)

    catalogo_json = await pagina.evaluate("fetch('/api/catalogo').then(r => r.json())")
    locro = [p for p in catalogo_json["productos"]
               if p["nombre"].startswith("Locro")]
    revisar(len(locro) == 1 and
            locro[0]["plataformas"]["pedidosya"] == "Locro del sábado",
            "al aceptar, queda enganchada a PedidosYa con el nombre del portal")

    revisar(await pagina.locator("#panel-novedades").is_hidden(),
            "el aviso desaparece una vez resuelto")

    texto_lista = await pagina.locator("#lista").inner_text()
    revisar("PedidosYa: —" not in texto_lista.split("Locro")[1][:80],
            "y el producto deja de figurar en gris en PedidosYa")


async def probar_vinculador_manual(pagina):
    """Vincular dos cualesquiera, sin esperar a que la app los proponga.

    El caso que lo pidio: el usuario sabe que el "Tarta de verdura chica"
    de PedidosYa es el "Tarta de verdura" de Rappi. Ninguna heuristica lo va a
    proponer, y ademas el de Rappi ya estaba emparejado con otro.
    """
    print("\n== Vincular a mano ==")
    await pagina.click("#btn-carta")
    await pagina.wait_for_selector("#panel-carta:visible", timeout=5000)

    seccion = pagina.locator(".grupo").filter(has_text="Vincular a mano").first
    await seccion.wait_for(timeout=10000)

    await seccion.locator("select[data-plat='pedidosya']").select_option(
        "Tarta de verdura chica")
    await seccion.locator("select[data-plat='rappi']").select_option("Tarta de verdura")
    await seccion.locator("button", has_text="Vincular").click()
    await pagina.wait_for_timeout(2000)

    datos = await pagina.evaluate("fetch('/api/catalogo').then(r => r.json())")
    productos = datos["productos"]

    nuevo = [p for p in productos
             if p["plataformas"]["pedidosya"] == "Tarta de verdura chica"]
    revisar(len(nuevo) == 1 and nuevo[0]["plataformas"]["rappi"] == "Tarta de verdura",
            "los dos que elegi quedan bajo el mismo boton")

    viejo = [p for p in productos
             if p["plataformas"]["pedidosya"] == "Tarta de verdura"]
    revisar(len(viejo) == 1 and viejo[0]["plataformas"]["rappi"] is None,
            "el que estaba emparejado con ese de Rappi no se perdio: quedo suelto")


async def probar_pausa(pagina):
    """Temporalmente inactivo: al final, apagado de color, y sin sostener."""
    print("\n== Pausar un producto ==")
    await pagina.click("#btn-carta")          # cerrar el panel de la carta
    await pagina.wait_for_timeout(300)

    fila = pagina.locator(".item").filter(has_text="Pollo al horno").first
    await fila.locator("button", has_text="Pausar").click()
    await pagina.wait_for_selector(".item.pausado", timeout=10000)

    revisar(await pagina.locator(".categoria", has_text="En pausa").count() == 1,
            "aparece la seccion 'En pausa' al final")

    pausados = pagina.locator(".item.pausado")
    revisar(await pausados.count() == 1 and
            "Pollo al horno" in await pausados.first.inner_text(),
            "el producto pausado se va ahi y queda apagado de color")

    productos = await pagina.evaluate("fetch('/api/productos').then(r => r.json())")
    pausado = [p for p in productos if p["pausado"]]
    revisar(len(pausado) == 1 and pausado[0]["nombre"].startswith("Pollo"),
            "la API lo devuelve marcado como pausado")

    # Y se puede volver atras.
    await pausados.first.locator("button", has_text="Reactivar").click()
    await pagina.wait_for_timeout(1500)
    revisar(await pagina.locator(".item.pausado").count() == 0,
            "Reactivar lo devuelve a la lista de siempre")


async def abrir_panel_carta(pagina):
    """Deja el panel de la carta abierto, este como este."""
    visible = await pagina.evaluate(
        "document.getElementById('panel-carta').style.display === 'block'")
    if not visible:
        await pagina.click("#btn-carta")
    await pagina.wait_for_selector("#panel-carta", state="visible", timeout=5000)


async def probar_renombrar_y_deshacer(pagina):
    """Los dos que faltaban cuando el catalogo queda hecho un lio.

    Renombrar: al separar dos que se llamaban igual, uno queda con un
    sufijo. Deshacer: vincular toca varios productos a la vez y revertirlo
    a mano es un rompecabezas.
    """
    print("\n== Renombrar y deshacer ==")

    pagina.once("dialog", lambda d: asyncio.ensure_future(d.accept("Flan casero ensalada")))
    await pagina.locator(".item .nombre", has_text="Flan casero").first.click()
    await pagina.wait_for_timeout(1500)

    productos = await pagina.evaluate("fetch('/api/productos').then(r => r.json())")
    revisar(any(p["nombre"] == "Flan casero ensalada" for p in productos),
            "el producto queda con el nombre nuevo")

    await abrir_panel_carta(pagina)
    # El panel se muestra antes de terminar de traer /api/catalogo, asi que
    # hay que esperar al texto, no leerlo apenas aparece el boton.
    revisar(await esperar(pagina.locator("#btn-deshacer", has_text="renombrar")),
            "el boton dice que va a deshacer el renombre")

    await pagina.locator("#btn-deshacer").click()
    await pagina.wait_for_timeout(1500)

    productos = await pagina.evaluate("fetch('/api/productos').then(r => r.json())")
    revisar(any(p["nombre"] == "Flan casero" for p in productos),
            "deshacer devuelve el nombre anterior")

    # Y el vinculo que se hizo a mano tiene que seguir donde estaba: deshacer
    # va de a un paso, no borra todo.
    datos = await pagina.evaluate("fetch('/api/catalogo').then(r => r.json())")
    tarta = [p for p in datos["productos"]
              if p["plataformas"]["pedidosya"] == "Tarta de verdura chica"]
    revisar(len(tarta) == 1 and tarta[0]["plataformas"]["rappi"] == "Tarta de verdura",
            "y no toca los cambios anteriores")


async def probar_buscador(pagina):
    """El buscador reemplazo al panel de platos del dia (2026-07-28)."""
    print("\n== Buscador ==")
    buscador = pagina.locator("#buscador")

    # La lista llega por fetch: contarla apenas carga la pagina da cero.
    await pagina.locator("#lista .item").first.wait_for(timeout=10000)
    todos = await pagina.locator("#lista .item").count()
    revisar(todos > 5, f"la lista arranca completa ({todos} productos)")

    await buscador.fill("tarta")
    await pagina.wait_for_timeout(800)
    visibles = await pagina.locator("#lista .item").count()
    revisar(0 < visibles < todos, f"filtra por nombre ({visibles} de {todos})")
    revisar("de" in await pagina.locator("#resultado-busqueda").inner_text(),
            "dice cuantos quedaron")

    # Sin tildes: los nombres de los portales las tienen y nadie las escribe.
    await buscador.fill("budin")
    await pagina.wait_for_timeout(800)
    texto = await pagina.locator("#lista").inner_text()
    revisar("Budín de pan" in texto,
            "encuentra 'Budín de pan' buscando 'budin', sin la tilde")

    # Por el nombre del OTRO portal: es donde mas se pierde uno.
    await buscador.fill("manantial")
    await pagina.wait_for_timeout(800)
    texto = await pagina.locator("#lista").inner_text()
    revisar("Agua chica" in texto,
            "encuentra 'Agua chica' buscando como se llama en Rappi")

    await buscador.fill("zzzzz")
    await pagina.wait_for_timeout(800)
    revisar("No hay ningún producto" in await pagina.locator("#lista").inner_text(),
            "avisa cuando no hay resultados")

    await pagina.click("#btn-limpiar")
    await pagina.wait_for_timeout(800)
    revisar(await pagina.locator("#lista .item").count() == todos,
            "la cruz borra la busqueda y vuelve la lista entera")
    revisar(await buscador.input_value() == "", "y deja el campo vacio")

    # El repintado cada 3 segundos no puede robarle el foco al input.
    await buscador.fill("tarta")
    await pagina.wait_for_timeout(3500)
    revisar(await pagina.evaluate("document.activeElement.id") == "buscador",
            "sigue escribiendo aunque la lista se refresque sola")
    await pagina.click("#btn-limpiar")


async def probar_vista_de_prendidos(pagina):
    """Juntar arriba lo que está prendido, sin tener que recorrer la carta.

    Dos vistas sobre los mismos datos: "prendidos primero" ordena sin
    esconder nada, "solo los prendidos" filtra. Lo que NO puede pasar es que
    filtrar esconda un apagado que la app no puede confirmar: ese es
    exactamente el que puede estar vendiéndose (el pedido del 2026-07-28).
    """
    print("\n== Vista: prendidos primero / solo los prendidos ==")
    from datetime import datetime
    from app.database import SessionLocal
    from app.models import Producto, EstadoItem
    from app.worker import worker

    # En modo simulado todo arranca en "desconocido": hay que dejar un
    # prendido, un apagado y un apagado-sin-confirmar para ver los 3 grupos.
    #
    # El `verificado_en` no es decoracion: un apagado que nadie confirmo
    # nunca cae solo en el grupo de los inciertos (/api/alertas lo reporta
    # por viejo), y entonces la prueba no distinguiria un grupo del otro.
    db = SessionLocal()
    try:
        def poner(nombre, estado, confirmado=False):
            p = db.query(Producto).filter_by(nombre=nombre).first()
            for e in p.estados:
                e.estado = estado
                e.verificado_en = datetime.now() if confirmado else None
            return p

        # "Ensalada mixta" y no "Pollo al horno": el nombre del apagado no puede
        # ser prefijo de otro producto, o buscarlo en la pantalla encuentra
        # al otro ("Pollo al horno vegetariano") y la prueba miente.
        poner("Empanada de carne", EstadoItem.PRENDIDO, confirmado=True)
        poner("Ensalada mixta", EstadoItem.APAGADO_HOY, confirmado=True)
        dudoso = poner("Tarta de jamon y queso", EstadoItem.APAGADO_HOY, confirmado=True)
        db.commit()

        # Y este ademas no aparecio en la ultima lectura del portal: es el
        # apagado que la app NO puede confirmar.
        worker.no_encontrados = {"pedidosya": [{
            "producto_id": dudoso.id, "producto": dudoso.nombre,
            "plataforma": "pedidosya", "nombre_remoto": dudoso.nombre,
            "estado": EstadoItem.APAGADO_HOY, "verificado_en": None,
        }]}
    finally:
        db.close()

    await pagina.reload()
    await pagina.locator("#lista .item").first.wait_for(timeout=10000)

    revisar(await pagina.locator(".chip-vista").count() == 3,
            "hay tres vistas para elegir")
    revisar("prendido" in await pagina.locator("#cuenta-prendidos").inner_text(),
            "la cabecera dice cuántos hay prendidos")

    todos = await pagina.locator("#lista .item").count()

    # --- Prendidos primero: reordena, no esconde ---
    await pagina.locator(".chip-vista[data-vista='primero']").click()
    # La vista se repinta despues de traer /api/productos: esperar el titulo
    # nuevo y no ".categoria", que ya esta en pantalla desde antes del click.
    revisar(await esperar(
                pagina.locator("#lista .categoria", has_text="Prendidos —")),
            "aparece la sección de prendidos")

    # Los titulos van en mayuscula por CSS, y eso es lo que devuelve
    # inner_text: hay que comparar sin distinguirlas.
    titulos = [t.upper()
               for t in await pagina.locator("#lista .categoria").all_inner_texts()]
    revisar(titulos and titulos[0].startswith("PRENDIDOS"),
            f"el primer título es el de los prendidos ({titulos[:1]})")
    revisar(any(t.startswith("APAGADOS") for t in titulos),
            "los apagados siguen estando, abajo")
    revisar(await pagina.locator("#lista .item").count() == todos,
            "no esconde ningún producto")

    # El primer producto de la lista tiene que ser uno prendido.
    primero = await pagina.locator("#lista .item").first.inner_text()
    revisar("Empanada de carne" in primero,
            f"y el prendido quedó arriba de todo ({primero.split(chr(10))[0]})")

    # --- Solo los prendidos: filtra ---
    await pagina.locator(".chip-vista[data-vista='solo']").click()
    await pagina.wait_for_timeout(800)

    visibles = await pagina.locator("#lista .item").count()
    revisar(0 < visibles < todos, f"esconde los apagados ({visibles} de {todos})")

    texto = await pagina.locator("#lista").inner_text()
    revisar("Ensalada mixta" not in texto,
            "el apagado confirmado no está")
    revisar("Tarta de jamon y queso" in texto,
            "pero el apagado que NO se puede confirmar SÍ está: "
            "puede estar vendiéndose")
    revisar("no se muestran en esta vista" in texto,
            "y dice cuántos escondió, en vez de esconderlos calladito")

    # --- La elección sobrevive al repintado automático y a recargar ---
    await pagina.wait_for_timeout(4500)
    revisar(await pagina.locator("#lista .item").count() == visibles,
            "la vista sigue puesta después de que la lista se repinte sola")

    await pagina.reload()
    await pagina.locator("#lista .item").first.wait_for(timeout=10000)
    revisar("sel" in (await pagina.locator(".chip-vista[data-vista='solo']")
                      .get_attribute("class")),
            "y también después de recargar la pantalla")

    # Dejar la pantalla como estaba para las pruebas que siguen.
    worker.no_encontrados = {}
    db = SessionLocal()
    try:
        for nombre in ("Empanada de carne", "Ensalada mixta", "Tarta de jamon y queso"):
            p = db.query(Producto).filter_by(nombre=nombre).first()
            for e in p.estados:
                e.estado = EstadoItem.DESCONOCIDO
                e.verificado_en = None
        db.commit()
    finally:
        db.close()

    await pagina.locator(".chip-vista[data-vista='todos']").click()
    await pagina.wait_for_timeout(800)
    revisar(await pagina.locator("#lista .item").count() == todos,
            "volver a 'por categoría' devuelve la lista entera")


async def probar_seleccion_de_plataforma(pagina):
    """Los chips ACOTAN la accion, y lo elegido sobrevive al repintado.

    Van juntas dos cosas:

    EL PEDIDO (2026-08-03): los chips se marcan de a uno, con un click, y sin
    ninguno marcado el boton actua sobre TODOS los portales del producto —
    que es lo de siempre y lo que se usa casi siempre—. Antes venian los tres
    marcados y el click SACABA: marcar de arranque lo que iba a pasar igual
    no informa nada.

    EL BUG (2026-07-28): la seleccion vivia en una variable local de fila(),
    y la lista se repinta sola cada 3 segundos. Elegias un portal, tardabas
    mas que el refresco en apretar el boton, y el chip volvia solo a como
    estaba, sin ningun aviso. Por eso vive afuera, y por eso se prueba
    esperando MAS que el refresco.
    """
    print("\n== Acotar la accion con los chips ==")
    fila = pagina.locator(".item").filter(has_text="Milanesa con pure").first
    await fila.wait_for(timeout=10000)

    chip_py = fila.locator(".pill[data-plat='pedidosya']")
    chip_rappi = fila.locator(".pill[data-plat='rappi']")
    boton = fila.locator("button", has_text="Apagar hoy")

    revisar("sel" not in (await chip_py.get_attribute("class")) and
            "sel" not in (await chip_rappi.get_attribute("class")),
            "los chips arrancan sin marcar")
    revisar(await boton.is_enabled() and
            "solo" not in await boton.inner_text(),
            "y aun asi el boton anda: sin marcar nada va a los dos portales")

    # Sin tocar ningun chip, la accion tiene que salir a los DOS portales.
    antes = await pagina.evaluate("fetch('/api/historial').then(r => r.json())")
    await boton.click()
    await pagina.wait_for_timeout(1500)
    despues = await pagina.evaluate("fetch('/api/historial').then(r => r.json())")
    ids = {o["id"] for o in antes}
    nuevas = [o for o in despues if o["id"] not in ids]
    revisar(sorted(o["plataforma"] for o in nuevas) == ["pedidosya", "rappi"],
            f"sin chips marcados va a los dos ({[o['plataforma'] for o in nuevas]})")

    await chip_py.click()
    revisar("sel" in (await chip_py.get_attribute("class")),
            "el chip queda marcado al clickearlo")
    revisar("sel" not in (await chip_rappi.get_attribute("class")),
            "y marcar uno NO marca el otro")

    # Mas que el refresco de la pantalla: es el escenario del bug.
    await pagina.wait_for_timeout(4500)
    fila = pagina.locator(".item").filter(has_text="Milanesa con pure").first
    chip_py = fila.locator(".pill[data-plat='pedidosya']")
    boton = fila.locator("button", has_text="Apagar hoy")
    revisar("sel" in (await chip_py.get_attribute("class")),
            "y SIGUE marcado despues de que la lista se repinte sola")

    # El boton tiene que DECIR sobre que portal va a actuar. Antes decia
    # "Apagar hoy" y para saberlo habia que interpretar la opacidad de los
    # chips: el usuario no se enteraba de que existia apagar en uno solo.
    revisar("solo PedidosYa" in await boton.inner_text(),
            f"el boton dice a donde va ({(await boton.inner_text()).strip()})")

    antes = await pagina.evaluate("fetch('/api/historial').then(r => r.json())")
    await boton.click()
    await pagina.wait_for_timeout(1500)
    despues = await pagina.evaluate("fetch('/api/historial').then(r => r.json())")

    ids = {o["id"] for o in antes}
    nuevas = [o for o in despues if o["id"] not in ids]
    revisar(len(nuevas) == 1 and nuevas[0]["plataforma"] == "pedidosya",
            f"la accion va solo a PedidosYa ({[o['plataforma'] for o in nuevas]})")

    # La marca NO se suelta sola al mandar la accion. Si se soltara, el
    # boton siguiente (que sin chips va a TODOS) apagaria en portales que el
    # usuario no habia pedido, y encima sin que se note.
    fila = pagina.locator(".item").filter(has_text="Milanesa con pure").first
    revisar("sel" in (await fila.locator(".pill[data-plat='pedidosya']")
                      .get_attribute("class")),
            "despues de mandar la accion el chip sigue marcado")
    revisar("solo PedidosYa" in await fila.locator(
                "button", has_text="Apagar hoy").inner_text(),
            "y el boton sigue diciendo que va a uno solo")

    # Se suelta clickeandolo de nuevo, y ahi vuelve a ir a los dos.
    await fila.locator(".pill[data-plat='pedidosya']").click()
    await pagina.wait_for_timeout(4500)
    fila = pagina.locator(".item").filter(has_text="Milanesa con pure").first
    revisar("sel" not in (await fila.locator(".pill[data-plat='pedidosya']")
                          .get_attribute("class")),
            "volver a clickearlo lo suelta, y tambien sobrevive al repintado")
    revisar("solo" not in await fila.locator("button", has_text="Apagar hoy")
            .inner_text(),
            "y el boton vuelve a actuar sobre los dos")

    revisar(await pagina.locator("#pista-chips").count() == 1,
            "la pantalla explica que los chips se pueden clickear")


async def probar_aviso_de_apagado_sin_confirmar(pagina):
    """EL BUG DEL 2026-07-28: decia apagado y PedidosYa lo estaba vendiendo.

    La app no puede prometer que no vuelva a pasar (el portal revive cosas
    solo), pero si puede dejar de afirmar en presente algo que no esta
    viendo. Se simula lo que pasa cuando la lectura no encuentra el producto.
    """
    print("\n== Avisar de un apagado que no se puede confirmar ==")
    from app.database import SessionLocal
    from app.models import Producto, EstadoItem
    from app.worker import worker

    db = SessionLocal()
    try:
        p = db.query(Producto).filter_by(nombre="Tarta de verdura").first()
        est = next(e for e in p.estados if e.plataforma == "pedidosya")
        est.estado = EstadoItem.APAGADO_HOY
        db.commit()

        # La lectura del portal no lo encontro: es el agujero exacto.
        worker.no_encontrados = {"pedidosya": [{
            "producto_id": p.id, "producto": p.nombre,
            "plataforma": "pedidosya", "nombre_remoto": "Tarta de verdura",
            "estado": EstadoItem.APAGADO_HOY, "verificado_en": None,
        }]}
        producto_id = p.id
    finally:
        db.close()

    alertas = await pagina.evaluate("fetch('/api/alertas').then(r => r.json())")
    dudas = alertas["sin_confirmar"]
    revisar(any(d["producto_id"] == producto_id and d["motivo"] == "no_aparece"
                for d in dudas),
            f"la API lo reporta como no confirmable ({len(dudas)} en total)")

    await pagina.reload()
    panel = pagina.locator("#panel-alertas")
    await panel.wait_for(timeout=10000)
    texto = await panel.inner_text()
    revisar("Tarta de verdura" in texto and "no puedo confirmar" in texto.lower(),
            "la pantalla lo dice arriba de todo, en rojo")
    revisar("vendiendo" in texto.lower(),
            "y dice por que importa: el portal puede estar vendiendolo")

    fila = pagina.locator(".item.dudoso").filter(has_text="Tarta de verdura").first
    revisar(await fila.count() > 0,
            "y el producto queda marcado en la lista, no solo en el cartel")

    worker.no_encontrados = {}
    db = SessionLocal()
    try:
        p = db.query(Producto).get(producto_id)
        est = next(e for e in p.estados if e.plataforma == "pedidosya")
        est.estado = EstadoItem.PRENDIDO
        db.commit()
    finally:
        db.close()

    await pagina.reload()
    await pagina.wait_for_timeout(1500)
    revisar(await pagina.locator("#panel-alertas").is_hidden(),
            "y el cartel se va cuando deja de haber dudas")


async def probar_ajustes(pagina):
    """El panel de configuracion: que guarde y que valide."""
    print("\n== Ajustes ==")
    await pagina.click("#btn-ajustes")
    await pagina.wait_for_selector("#panel-ajustes:visible", timeout=5000)
    await pagina.wait_for_selector("#cuerpo-ajustes .ajuste", timeout=5000)

    panel = pagina.locator("#panel-ajustes")
    revisar(await panel.locator(".grupo").count() >= 3,
            "los ajustes salen agrupados")
    revisar(await panel.locator("[data-clave='pedidosya_menu_id']").count() == 1,
            "el id de menu de PedidosYa se puede editar desde la pantalla")

    campo = panel.locator("[data-clave='minutos_ronda']")
    await campo.fill("25")
    await panel.locator("[data-clave='sostener_apagados']").uncheck()
    await pagina.click("#btn-guardar-ajustes")
    await pagina.wait_for_timeout(1500)

    cfg = await pagina.evaluate("fetch('/api/config').then(r => r.json())")
    valores = {o["clave"]: o["valor"] for o in cfg["opciones"]}
    revisar(valores["minutos_ronda"] == 25, "guarda el valor nuevo")
    revisar(valores["sostener_apagados"] is False, "y tambien los booleanos")

    # Recargar la pagina no puede perderlos: viven en la base.
    await pagina.reload()
    await pagina.click("#btn-ajustes")
    await pagina.wait_for_selector("#cuerpo-ajustes .ajuste", timeout=5000)
    revisar(await pagina.locator("[data-clave='minutos_ronda']")
            .input_value() == "25",
            "y siguen ahi despues de recargar la pantalla")

    # Un valor fuera de rango tiene que decirlo, no guardarse a medias.
    await pagina.locator("[data-clave='max_intentos']").fill("99")
    await pagina.click("#btn-guardar-ajustes")
    await pagina.wait_for_timeout(1200)
    revisar("No se pudo" in await pagina.locator("#estado-ajustes").inner_text(),
            "avisa cuando un valor esta fuera de rango")

    cfg = await pagina.evaluate("fetch('/api/config').then(r => r.json())")
    valores = {o["clave"]: o["valor"] for o in cfg["opciones"]}
    revisar(valores["max_intentos"] == 3,
            "y no guarda nada de esa tanda")

    pagina.once("dialog", lambda d: asyncio.ensure_future(d.accept()))
    await pagina.click("#btn-restablecer")
    await pagina.wait_for_timeout(1500)
    cfg = await pagina.evaluate("fetch('/api/config').then(r => r.json())")
    valores = {o["clave"]: o["valor"] for o in cfg["opciones"]}
    revisar(valores["minutos_ronda"] == 15 and valores["sostener_apagados"],
            "restablecer los devuelve a los valores por defecto")

    await pagina.click("#btn-ajustes")      # cerrar
    await probar_falta_solo_la_sucursal(pagina)


async def probar_falta_solo_la_sucursal(pagina):
    """Catalogo cargado pero sin los datos del local.

    Es el caso de una instalacion que venia andando cuando los ids de la
    sucursal dejaron de estar clavados en el codigo: el catalogo esta
    intacto y lo unico que falta es a que menu entrar. Aca se llega solo,
    porque «restablecer» acaba de vaciar los ajustes.

    Hablarle de "primera vez" a alguien que ya tiene su carta es mentirle,
    y ofrecerle "leer mi carta" es peor: parece que hay que empezar de cero.
    """
    print("\n== Falta la sucursal, pero la carta esta ==")

    sistema = await pagina.evaluate(
        "fetch('/api/estado-sistema').then(r => r.json())")
    revisar(sorted(sistema["falta_sucursal"]) == ["pedidosya", "rappi"] and
            sistema["catalogo_vacio"] is False,
            "se llega al estado: sin sucursal y con catalogo")

    panel = pagina.locator("#panel-inicio")
    await panel.wait_for(timeout=10000)
    texto = await panel.inner_text()

    revisar("Faltan los datos de tu sucursal" in texto,
            "el panel dice lo que falta y no habla de primera vez")
    revisar("catálogo está intacto" in texto,
            "y aclara que el catalogo no se toco")
    revisar(await panel.locator("button", has_text="Leer mi carta").count() == 0,
            "no ofrece leer la carta: ya la tiene")
    revisar(await panel.locator("[data-clave='rappi_store_id']").count() == 1,
            "pero si pide los datos de la sucursal")

    # Se dejan puestos de nuevo para las pruebas que siguen.
    await panel.locator("[data-clave='pedidosya_menu_id']").fill(
        catalogo_ejemplo.SUCURSAL["pedidosya_menu_id"])
    await panel.locator("[data-clave='rappi_brand_id']").fill(
        catalogo_ejemplo.SUCURSAL["rappi_brand_id"])
    await panel.locator("[data-clave='rappi_store_id']").fill(
        catalogo_ejemplo.SUCURSAL["rappi_store_id"])
    await panel.locator("#btn-guardar-sucursal").click()

    await pagina.locator("#panel-inicio").wait_for(state="hidden", timeout=10000)
    revisar(True, "y al completarlos el panel se va")


async def probar_pausar_tienda(pagina):
    """Pausar una TIENDA entera: se puede apagar, no se puede prender.

    Pedido del 2026-08-04: "los jefes me piden desactivar Rappi Común".
    Apagarla toda no alcanza — el portal revive lo apagado por hoy, y un
    «Prender todo» de la mañana siguiente la vuelve a levantar entera.
    """
    print("\n== Pausar una tienda entera ==")
    await pagina.click("#btn-cierre")
    await pagina.wait_for_selector("#panel-cierre:visible", timeout=5000)
    await pagina.wait_for_selector(".fila-cierre", timeout=5000)

    fila_py = pagina.locator(".fila-cierre[data-destino='pedidosya']")
    fila_ambas = pagina.locator(".fila-cierre[data-destino='ambas']")
    revisar(await fila_py.locator("button", has_text="Pausar tienda").count() == 1,
            "cada tienda tiene su boton de pausa")
    revisar(await fila_ambas.locator("button", has_text="Pausar tienda")
            .count() == 0,
            "pero el combo no: pausar «los dos» de un boton son dos "
            "decisiones metidas en una")
    revisar(await fila_py.locator("button", has_text="Indefinido").count() == 1,
            "y se puede apagar toda la tienda indefinidamente sin ir a Ajustes")

    await fila_py.locator("button", has_text="Pausar tienda").click()
    await pagina.wait_for_selector(
        ".fila-cierre[data-destino='pedidosya'] button:has-text('Reactivar tienda')",
        timeout=10000)

    texto = await pagina.locator("#resultado-cierre").inner_text()
    revisar("en pausa" in texto, f"dice que quedo en pausa ({texto[:50]})")

    # Ahora «Prender todo» de esa tienda no tiene que hacer nada.
    await fila_py.locator("button", has_text="Prender todo").click()
    await pagina.wait_for_timeout(600)
    texto = await pagina.locator("#resultado-cierre").inner_text()
    revisar("en pausa" in texto,
            f"«Prender todo» avisa que la tienda esta en pausa ({texto[:60]})")

    # Y la pantalla principal lo tiene que decir, no solo este panel.
    await pagina.click("#btn-cierre")
    await pagina.wait_for_timeout(4000)
    revisar("en pausa" in await pagina.locator("#tiendas").inner_text(),
            "el badge de la tienda, arriba, dice que esta en pausa")

    fila = pagina.locator(".item").filter(has_text="Milanesa con pure").first
    revisar(await fila.locator(".pill[data-plat='pedidosya'] .marca-pausa")
            .count() == 1,
            "y el chip del producto tambien")
    prender = fila.locator("button", has_text="Prender")
    revisar("solo Rappi" in await prender.inner_text(),
            f"«Prender» deja afuera la tienda en pausa "
            f"({(await prender.inner_text()).strip()})")
    revisar("solo" not in await fila.locator("button", has_text="Apagar hoy")
            .inner_text(),
            "pero apagar sigue yendo a las dos: es lo que hace falta")

    # Que no sea solo la pantalla: el backend tambien tiene que negarse,
    # porque un click puede salir con los datos de hace tres segundos.
    r = await pagina.evaluate("""
        fetch('/api/productos').then(r => r.json()).then(ps => {
          const p = ps.find(p => p.estados.pedidosya);
          return fetch('/api/accion', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({producto_id: p.id, accion: 'prender',
                                  plataformas: ['pedidosya']}),
          }).then(r => r.json());
        })""")
    revisar(r["encoladas"] == [] and
            r["salteadas"][0]["motivo"] == "la tienda está en pausa",
            f"la API rechaza prender en una tienda en pausa ({r})")

    # Sacarla de la pausa.
    await pagina.click("#btn-cierre")
    await pagina.wait_for_selector(".fila-cierre", timeout=5000)
    await fila_py.locator("button", has_text="Reactivar tienda").click()
    await pagina.wait_for_selector(
        ".fila-cierre[data-destino='pedidosya'] button:has-text('Pausar tienda')",
        timeout=10000)
    await pagina.click("#btn-cierre")
    await pagina.wait_for_timeout(4000)
    revisar("en pausa" not in await pagina.locator("#tiendas").inner_text(),
            "y al reactivarla la pantalla vuelve a la normal")


async def probar_apagar_todo(pagina):
    """Apagar la carta de UNA plataforma, que es lo que pidio el usuario."""
    print("\n== Apagar todo ==")
    await pagina.click("#btn-cierre")
    await pagina.wait_for_selector("#panel-cierre:visible", timeout=5000)
    await pagina.wait_for_selector(".fila-cierre", timeout=5000)

    filas = pagina.locator(".fila-cierre")
    revisar(await filas.count() == 3,
            "hay un juego de botones para PedidosYa, otro para Rappi y otro "
            "para los dos: la plataforma opcional no esta configurada, asi "
            "que no aparece")

    fila_py = pagina.locator(".fila-cierre[data-destino='pedidosya']")
    revisar("para apagar" in await fila_py.inner_text(),
            "dice cuantos productos tocaria antes de apretar nada")

    antes = await pagina.evaluate("fetch('/api/historial?limite=500')"
                                  ".then(r => r.json())")
    ids = {o["id"] for o in antes}

    pagina.once("dialog", lambda d: asyncio.ensure_future(d.accept()))
    await fila_py.locator("button", has_text="Apagar todo").click()
    await pagina.wait_for_selector("#resultado-cierre:not(:empty)", timeout=20000)

    texto = await pagina.locator("#resultado-cierre").inner_text()
    revisar("PedidosYa" in texto and "encoladas" in texto,
            f"cuenta lo que encolo ({texto.strip()[:60]})")
    revisar("Rappi" not in texto, "y no menciona Rappi, que no se toco")

    despues = await pagina.evaluate("fetch('/api/historial?limite=500')"
                                    ".then(r => r.json())")
    nuevas = [o for o in despues if o["id"] not in ids]
    revisar(len(nuevas) > 5, f"encolo la carta entera de PedidosYa ({len(nuevas)})")
    revisar(all(o["plataforma"] == "pedidosya" for o in nuevas),
            "TODAS las operaciones nuevas son de PedidosYa: Rappi quedo intacto")
    revisar(all(o["accion"] == "apagar_hoy" for o in nuevas),
            "y usan el apagado por hoy, que es el default del cierre")


async def guardar_config(pagina, cambios: dict):
    """POST /api/config desde la pagina, como lo hace el panel de Ajustes."""
    return await pagina.evaluate(
        """cambios => fetch('/api/config', {
               method: 'POST',
               headers: {'Content-Type': 'application/json'},
               body: JSON.stringify({cambios}),
           }).then(r => r.json())""", cambios)


async def probar_carta_con_tres_columnas(pagina):
    """La pantalla Carta con las DOS tiendas de Rappi.

    Era lo que le faltaba a Rappi Común para estar terminada: la pantalla
    leia dos portales, asi que enganchar el catalogo a la tercera tienda no
    se podia hacer desde ningun lado.

    Lo que importa que se vea aca: que la tienda Común tenga su columna y su
    grupo, y que el emparejamiento dudoso ENTRE LAS DOS TIENDAS DE RAPPI
    venga destildado. Ese es el caso caro: "Empanada de carne chica" puntua
    0.91 contra "Empanada de carne" y es otro plato, asi que vincularlas de
    un click apagaria algo que se sigue vendiendo.
    """
    print("\n== La pantalla Carta con las dos tiendas de Rappi ==")

    await pagina.click("#btn-cierre")          # cerrar el panel de cierre
    await pagina.click("#btn-carta")
    await pagina.wait_for_selector("#panel-carta:visible", timeout=5000)
    await pagina.click("#btn-leer-carta")
    await pagina.wait_for_selector(".grupo", timeout=15000)

    cuerpo = pagina.locator("#carta-cuerpo")
    revisar(await pagina.locator("h3", has_text="Solo en Rappi Común").count() == 1,
            "la tienda Común tiene su propio grupo de sueltos")
    revisar("en Rappi Común" in await cuerpo.inner_text(),
            "y el pie dice cuantos leyo de esa tienda")

    # La fila de "Vincular a mano" tiene que ofrecer los tres portales, que
    # es lo unico que resuelve un nombre que no se parece en nada.
    manual = pagina.locator(".par.manual").first
    revisar(await manual.locator("select[data-plat='rappi_comun']").count() == 1,
            "«Vincular a mano» tiene un selector para la tienda Común")

    fila = fila_de(pagina, "Empanada de carne", "Empanada de carne chica")
    revisar(await esperar(fila), "la 'Empanada de carne chica' aparece propuesta")

    casilla = fila.locator("input[type=checkbox][data-plat='rappi_comun']")
    revisar(await casilla.count() == 1,
            "con una casilla para decidir si entra en el vinculo")
    revisar(not await casilla.is_checked(),
            "que viene DESTILDADA: 0.91 entre dos tiendas del mismo portal "
            "no alcanza para darlo por hecho")
    turbo = fila.locator("input[type=checkbox][data-plat='rappi']")
    revisar(await turbo.is_checked(),
            "y la de Rappi Turbo si, que esa se emparejo clavada")

    # Vincular sin tildarla: quedan las dos seguras y la dudosa afuera.
    await fila.locator("button", has_text="Vincular").click()
    await pagina.wait_for_timeout(1500)
    productos = await pagina.evaluate("fetch('/api/catalogo').then(r => r.json())")
    empanada = [p for p in productos["productos"]
                if p["plataformas"]["pedidosya"] == "Empanada de carne"]
    revisar(len(empanada) == 1 and
            empanada[0]["plataformas"]["rappi_comun"] is None,
            "vincular deja afuera la que no tildaste: la tienda Común no entra")
    revisar(len(empanada) == 1 and
            empanada[0]["plataformas"]["rappi"] == "Empanada de carne",
            "y si vincula las dos que estaban tildadas")

    await pagina.click("#btn-carta")           # cerrar el panel


async def probar_plataforma_opcional(pagina):
    """Rappi Común: existe en el codigo, pero solo si la configuras.

    EL BUG (2026-07-29): la lista de plataformas de la pantalla era fija con
    las tres, asi que todo local que NO vende por Rappi Común igual veia un
    chip "Rappi Común: —" en cada producto y una fila de mas en «Apagar
    todo». Y al reves: con la tercera configurada, el boton "los dos"
    seguia mandando solo a PedidosYa+Rappi, o sea que apagar todo al cierre
    no apagaba todo.
    """
    print("\n== La plataforma opcional solo aparece si la configuras ==")

    fila = pagina.locator(".item").first
    await fila.wait_for(timeout=10000)
    revisar(await pagina.locator(".pill[data-plat='rappi_comun']").count() == 0,
            "sin configurar, no hay ningun chip de Rappi Común")
    revisar("Rappi Común" not in await pagina.locator("#lista").inner_text(),
            "ni se la nombra en la lista de productos")

    # Y la API tampoco la acepta: una pantalla vieja podria mandarla.
    item = await pagina.evaluate(
        "fetch('/api/productos').then(r => r.json()).then(p => p[0])")
    r = await pagina.evaluate(
        """id => fetch('/api/accion', {
               method: 'POST',
               headers: {'Content-Type': 'application/json'},
               body: JSON.stringify({producto_id: id, accion: 'apagar_hoy',
                                     plataformas: ['rappi_comun']}),
           }).then(r => r.json())""", item["id"])
    revisar(r["encoladas"] == [] and r["salteadas"],
            f"y la API no encola nada para una plataforma apagada "
            f"({r['salteadas'][0]['motivo'] if r['salteadas'] else '?'})")

    print("\n== Y aparece entera en cuanto se configura ==")
    await guardar_config(pagina, {"rappi_comun_store_id": "9988"})
    await pagina.reload()
    await pagina.wait_for_selector(".item", timeout=10000)
    await pagina.wait_for_timeout(1500)

    revisar(await pagina.locator(".pill.na[data-plat='rappi_comun']").count() > 0
            or "Rappi Común" in await pagina.locator("#lista").inner_text(),
            "ahora si aparece en los productos")

    await pagina.click("#btn-cierre")
    await pagina.wait_for_selector("#panel-cierre:visible", timeout=5000)
    await pagina.wait_for_selector(".fila-cierre", timeout=5000)
    # Tres plataformas + «Ambos Rappi» + «Todas». Lo pidio asi el usuario
    # (2026-07-29): poder apagar solo Turbo, solo Comun, solo PedidosYa, las
    # dos de Rappi juntas, o las tres.
    revisar(await pagina.locator(".fila-cierre").count() == 5,
            "«Apagar todo» tiene las tres, el combo de Rappi y una para todas")
    ambos = pagina.locator(".fila-cierre[data-destino='rappi_todas']")
    revisar(await ambos.count() == 1,
            "hay una fila para apagar las dos tiendas de Rappi juntas")
    todas = pagina.locator(".fila-cierre[data-destino='ambas']")
    revisar("Todas" in await todas.inner_text(),
            "la fila de todas ya no dice «los dos», que dejaria una afuera")
    # Con las dos tiendas configuradas, «Rappi» a secas es ambiguo.
    revisar("Rappi Turbo" in await pagina.locator("#panel-cierre").inner_text(),
            "y la tienda principal pasa a llamarse «Rappi Turbo»")

    await probar_carta_con_tres_columnas(pagina)

    print("\n== Y se puede volver a apagar sin reiniciar la app ==")
    await guardar_config(pagina, {"rappi_comun_store_id": ""})
    await pagina.reload()
    await pagina.wait_for_selector(".item", timeout=10000)
    await pagina.wait_for_timeout(1500)
    revisar(await pagina.locator(".pill[data-plat='rappi_comun']").count() == 0,
            "borrar el storeId la saca de la pantalla")

    await pagina.click("#btn-cierre")
    await pagina.wait_for_selector("#panel-cierre:visible", timeout=5000)
    await pagina.wait_for_selector(".fila-cierre", timeout=5000)
    revisar(await pagina.locator(".fila-cierre").count() == 3,
            "y de «Apagar todo» tambien")
    await pagina.click("#btn-cierre")      # cerrar


async def probar_sin_platos_del_dia(pagina):
    """El panel de platos del dia se saco entero (2026-07-28)."""
    print("\n== Ya no hay platos del dia ==")
    revisar(await pagina.locator("#panel-platos").count() == 0,
            "no queda el panel en la pantalla")

    estado = await pagina.evaluate(
        "fetch('/api/platos-del-dia').then(r => r.status)")
    revisar(estado == 404, f"el endpoint ya no existe (dio {estado})")


async def main():
    servidor = levantar_app()
    for _ in range(100):                      # esperar a que levante
        await asyncio.sleep(0.1)
        if servidor.started:
            break

    async with async_playwright() as p:
        navegador = await abrir_navegador(p)
        pagina = await navegador.new_page()
        await pagina.goto(BASE)

        await probar_sin_platos_del_dia(pagina)
        await probar_buscador(pagina)
        await probar_vista_de_prendidos(pagina)
        await probar_seleccion_de_plataforma(pagina)
        await probar_aviso_de_apagado_sin_confirmar(pagina)

        print("\n== El icono de la pestaña ==")
        icono = await pagina.evaluate("""
            fetch('/favicon.ico').then(r => r.arrayBuffer().then(b => ({
                estado: r.status,
                tipo: r.headers.get('content-type'),
                bytes: b.byteLength,
                // Los .ico arrancan con 00 00 01 00
                cabecera: [...new Uint8Array(b).slice(0, 4)].join(','),
            })))""")
        revisar(icono["estado"] == 200, "/favicon.ico responde")
        revisar(icono["cabecera"] == "0,0,1,0",
                f"y lo que sirve es un .ico de verdad ({icono['bytes']} bytes)")
        revisar(await pagina.locator("link[rel='icon']").count() == 1,
                "la pagina lo declara con <link rel='icon'>")

        # Que sea un .ico valido no alcanza: tiene que poder decodificarlo
        # el navegador, que es lo unico que decide si se ve en la pestaña.
        medida = await pagina.evaluate("""
            new Promise(ok => {
                const img = new Image();
                img.onload  = () => ok(img.naturalWidth + 'x' + img.naturalHeight);
                img.onerror = () => ok('no se pudo decodificar');
                img.src = '/favicon.ico';
            })""")
        revisar("x" in medida, f"Chrome lo decodifica como imagen ({medida})")

        print("\n== Abrir la carta ==")
        await pagina.click("#btn-carta")
        await pagina.click("#btn-leer-carta")
        await pagina.wait_for_selector(".grupo", timeout=15000)

        # Los numeros salen del emparejador de verdad corriendo sobre las
        # cartas de pruebas/carta_ejemplo.json. Si cambia una lista, cambian.
        revisar(await pagina.locator("h3", has_text="A confirmar — 2").count() == 1,
                "muestra los pares a confirmar")
        revisar(await pagina.locator("h3", has_text="Solo en Rappi — 7").count() == 1,
                "muestra los que estan solo en Rappi")
        revisar("15 en PedidosYa" in await pagina.locator("#carta-cuerpo").inner_text(),
                "muestra cuantos leyo de cada portal")

        print("\n== Avisa cuando hay mas de un candidato ==")
        # Las dos gaseosas: la de 500 y la de 1 litro puntuan igual contra
        # la "Gaseosa cola" de PedidosYa. Apagar el tamaño que no era es una
        # venta perdida, asi que la decision tiene que ser del usuario.
        gaseosa = fila_de(pagina, "Gaseosa cola", "Gaseosa cola 500 ml")
        revisar("Gaseosa cola 1 L" in await gaseosa.inner_text(),
                "avisa que en Rappi tambien existe el otro tamaño")

        print("\n== Las dos tartas de verdura arrancan separadas ==")
        fila = fila_de(pagina, "Tarta de verdura chica", "Tarta de verdura porción")
        revisar(await fila.locator("button", has_text="Vincular").count() == 1,
                "el par que el usuario todavia no confirmo ofrece Vincular")

        print("\n== Vincular y separar ==")
        await fila.locator("button", has_text="Vincular").click()
        fila = fila_de(pagina, "Tarta de verdura chica", "Tarta de verdura porción")
        revisar(await esperar_boton(fila, "Separar"),
                "despues de vincular, la fila ofrece Separar")
        revisar("un solo botón" in await fila.inner_text(),
                "y avisa que los dos se apagan juntos")

        productos = await pagina.evaluate(
            "fetch('/api/catalogo').then(r => r.json())")
        vinculado = [p for p in productos["productos"]
                     if p["plataformas"]["pedidosya"] == "Tarta de verdura chica"]
        revisar(len(vinculado) == 1 and
                vinculado[0]["plataformas"]["rappi"] == "Tarta de verdura porción",
                "quedo un solo producto con los dos nombres")

        await fila.locator("button", has_text="Separar").click()
        fila = fila_de(pagina, "Tarta de verdura chica", "Tarta de verdura porción")
        revisar(await esperar_boton(fila, "Vincular"),
                "Separar los vuelve a dejar con un boton cada uno")

        print("\n== Agregar uno que solo esta en Rappi ==")
        fila_suelta = pagina.locator(".par:not(.manual)").filter(has_text="Guiso de garbanzos").first
        await fila_suelta.locator("button", has_text="Agregar").click()
        fila_suelta = pagina.locator(".par:not(.manual)").filter(has_text="Guiso de garbanzos").first
        await fila_suelta.locator(".hecho").wait_for(timeout=10000)
        revisar("cargado" in await fila_suelta.inner_text(),
                "queda marcado como cargado")

        # La lista se repinta despues de que la fila de la carta se marca
        # como cargada, asi que hay que esperarla a ella, no leer y ver.
        en_lista = pagina.locator("#lista .item").filter(has_text="Guiso de garbanzos")
        revisar(await esperar(en_lista),
                "y aparece en la lista de productos de la pantalla principal")

        await probar_aviso_de_novedad(pagina)
        await probar_vinculador_manual(pagina)
        await probar_pausa(pagina)
        await probar_renombrar_y_deshacer(pagina)
        await probar_ajustes(pagina)
        await probar_plataforma_opcional(pagina)
        await probar_pausar_tienda(pagina)

        # Al final: encola la carta entera, y en modo simulado cada operacion
        # tarda 2 segundos. Antes de las otras pruebas les dejaria el worker
        # ocupado y los estados en "apagando…" por varios minutos.
        await probar_apagar_todo(pagina)

        await navegador.close()

    shutil.rmtree(TEMPORAL, ignore_errors=True)
    print("\n" + ("TODO OK" if not fallos else f"{len(fallos)} FALLAS: {fallos}"))
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
