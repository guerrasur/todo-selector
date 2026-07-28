"""Prueba la pantalla Carta de punta a punta, en modo simulado.

    py pruebas/probar_pantalla_carta.py

Levanta la app de verdad con STOCKSWITCH_SIMULADO=1 (no abre navegador ni
toca los portales: /api/carta devuelve la lectura real guardada del
2026-07-27) y la maneja con Playwright como lo haria el usuario: leer la
carta, vincular un par dudoso, separarlo y agregar uno suelto.
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

TEMPORAL = tempfile.mkdtemp(prefix="todoselector-pantalla-")
os.environ["HOME"] = TEMPORAL
os.environ["LOCALAPPDATA"] = TEMPORAL
os.environ["STOCKSWITCH_SIMULADO"] = "1"

import uvicorn                                                # noqa: E402
from playwright.async_api import async_playwright             # noqa: E402

from app.main import app                                      # noqa: E402

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
    """El caso del 2026-07-28: agregaron la Suprema a la carta de PedidosYa.

    El catalogo la tenia como exclusiva de Rappi, asi que la app la mostraba
    en gris con el chip "no existe ahi" y no habia forma de enterarse.
    """
    print("\n== Aviso: apareció en un portal donde no estaba ==")
    from app import catalogo
    from app.database import SessionLocal
    from app.worker import worker

    db = SessionLocal()
    try:
        leido = {"Suprema a la Crema de Limón con Puré": True}
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
    revisar("Suprema" in texto and "PedidosYa" in texto,
            "la pantalla avisa que apareció en PedidosYa")

    await panel.locator("button", has_text="Es el mismo").click()
    await pagina.wait_for_timeout(1500)

    catalogo_json = await pagina.evaluate("fetch('/api/catalogo').then(r => r.json())")
    suprema = [p for p in catalogo_json["productos"]
               if p["nombre"].startswith("Suprema")]
    revisar(len(suprema) == 1 and
            suprema[0]["plataformas"]["pedidosya"] == "Suprema a la Crema de Limón con Puré",
            "al aceptar, queda enganchada a PedidosYa con el nombre del portal")

    revisar(await pagina.locator("#panel-novedades").is_hidden(),
            "el aviso desaparece una vez resuelto")

    texto_lista = await pagina.locator("#lista").inner_text()
    revisar("PedidosYa: —" not in texto_lista.split("Suprema")[1][:80],
            "y el producto deja de figurar en gris en PedidosYa")


async def probar_vinculador_manual(pagina):
    """Vincular dos cualesquiera, sin esperar a que la app los proponga.

    El caso que lo pidio: el usuario sabe que el "Wrap caesar con batatas"
    de PedidosYa es el "Wrap caesar" de Rappi. Ninguna heuristica lo va a
    proponer, y ademas el de Rappi ya estaba emparejado con otro.
    """
    print("\n== Vincular a mano ==")
    await pagina.click("#btn-carta")
    await pagina.wait_for_selector("#panel-carta:visible", timeout=5000)

    seccion = pagina.locator(".grupo").filter(has_text="Vincular a mano").first
    await seccion.wait_for(timeout=10000)

    await seccion.locator("select[data-plat='pedidosya']").select_option(
        "Wrap caesar con batatas")
    await seccion.locator("select[data-plat='rappi']").select_option("Wrap caesar")
    await seccion.locator("button", has_text="Vincular").click()
    await pagina.wait_for_timeout(2000)

    datos = await pagina.evaluate("fetch('/api/catalogo').then(r => r.json())")
    productos = datos["productos"]

    nuevo = [p for p in productos
             if p["plataformas"]["pedidosya"] == "Wrap caesar con batatas"]
    revisar(len(nuevo) == 1 and nuevo[0]["plataformas"]["rappi"] == "Wrap caesar",
            "los dos que elegi quedan bajo el mismo boton")

    viejo = [p for p in productos
             if p["plataformas"]["pedidosya"] == "Wrap caesar"]
    revisar(len(viejo) == 1 and viejo[0]["plataformas"]["rappi"] is None,
            "el que estaba emparejado con ese de Rappi no se perdio: quedo suelto")


async def probar_pausa(pagina):
    """Temporalmente inactivo: al final, apagado de color, y sin sostener."""
    print("\n== Pausar un producto ==")
    await pagina.click("#btn-carta")          # cerrar el panel de la carta
    await pagina.wait_for_timeout(300)

    fila = pagina.locator(".item").filter(has_text="Guiso de lentejas").first
    await fila.locator("button", has_text="Pausar").click()
    await pagina.wait_for_selector(".item.pausado", timeout=10000)

    revisar(await pagina.locator(".categoria", has_text="En pausa").count() == 1,
            "aparece la seccion 'En pausa' al final")

    pausados = pagina.locator(".item.pausado")
    revisar(await pausados.count() == 1 and
            "Guiso de lentejas" in await pausados.first.inner_text(),
            "el producto pausado se va ahi y queda apagado de color")

    productos = await pagina.evaluate("fetch('/api/productos').then(r => r.json())")
    pausado = [p for p in productos if p["pausado"]]
    revisar(len(pausado) == 1 and pausado[0]["nombre"].startswith("Guiso"),
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

    pagina.once("dialog", lambda d: asyncio.ensure_future(d.accept("Cobb ensalada")))
    await pagina.locator(".item .nombre", has_text="Cobb").first.click()
    await pagina.wait_for_timeout(1500)

    productos = await pagina.evaluate("fetch('/api/productos').then(r => r.json())")
    revisar(any(p["nombre"] == "Cobb ensalada" for p in productos),
            "el producto queda con el nombre nuevo")

    await abrir_panel_carta(pagina)
    # El panel se muestra antes de terminar de traer /api/catalogo, asi que
    # hay que esperar al texto, no leerlo apenas aparece el boton.
    revisar(await esperar(pagina.locator("#btn-deshacer", has_text="renombrar")),
            "el boton dice que va a deshacer el renombre")

    await pagina.locator("#btn-deshacer").click()
    await pagina.wait_for_timeout(1500)

    productos = await pagina.evaluate("fetch('/api/productos').then(r => r.json())")
    revisar(any(p["nombre"] == "Cobb" for p in productos),
            "deshacer devuelve el nombre anterior")

    # Y el vinculo que se hizo a mano tiene que seguir donde estaba: deshacer
    # va de a un paso, no borra todo.
    datos = await pagina.evaluate("fetch('/api/catalogo').then(r => r.json())")
    caesar = [p for p in datos["productos"]
              if p["plataformas"]["pedidosya"] == "Wrap caesar con batatas"]
    revisar(len(caesar) == 1 and caesar[0]["plataformas"]["rappi"] == "Wrap caesar",
            "y no toca los cambios anteriores")


async def probar_buscador(pagina):
    """El buscador reemplazo al panel de platos del dia (2026-07-28)."""
    print("\n== Buscador ==")
    buscador = pagina.locator("#buscador")

    # La lista llega por fetch: contarla apenas carga la pagina da cero.
    await pagina.locator("#lista .item").first.wait_for(timeout=10000)
    todos = await pagina.locator("#lista .item").count()
    revisar(todos > 5, f"la lista arranca completa ({todos} productos)")

    await buscador.fill("wrap")
    await pagina.wait_for_timeout(800)
    visibles = await pagina.locator("#lista .item").count()
    revisar(0 < visibles < todos, f"filtra por nombre ({visibles} de {todos})")
    revisar("de" in await pagina.locator("#resultado-busqueda").inner_text(),
            "dice cuantos quedaron")

    # Sin tildes: los nombres de los portales las tienen y nadie las escribe.
    await buscador.fill("clasica")
    await pagina.wait_for_timeout(800)
    texto = await pagina.locator("#lista").inner_text()
    revisar("Clasica" in texto or "clásica" in texto.lower(),
            "encuentra 'Clásica' buscando 'clasica'")

    # Por el nombre del OTRO portal: es donde mas se pierde uno.
    await buscador.fill("villavicencio")
    await pagina.wait_for_timeout(800)
    texto = await pagina.locator("#lista").inner_text()
    revisar("Agua" in texto,
            "encuentra 'Agua con gas' buscando como se llama en Rappi")

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
    await buscador.fill("wrap")
    await pagina.wait_for_timeout(3500)
    revisar(await pagina.evaluate("document.activeElement.id") == "buscador",
            "sigue escribiendo aunque la lista se refresque sola")
    await pagina.click("#btn-limpiar")


async def probar_seleccion_de_plataforma(pagina):
    """El chip excluido tiene que sobrevivir al repintado automatico.

    EL BUG (2026-07-28): la seleccion vivia en una variable local de fila(),
    y la lista se repinta sola cada 3 segundos. Excluias PedidosYa, tardabas
    mas que el refresco en apretar el boton, y el chip volvia a quedar
    seleccionado sin ningun aviso: el click apagaba en los DOS portales.
    Es justo lo contrario de lo que el usuario habia pedido.
    """
    print("\n== Excluir una plataforma con el chip ==")
    fila = pagina.locator(".item").filter(has_text="Clasica").first
    await fila.wait_for(timeout=10000)

    chip_rappi = fila.locator(".pill[data-plat='rappi']")
    await chip_rappi.click()
    revisar("sel" not in (await chip_rappi.get_attribute("class")),
            "el chip queda deseleccionado al clickearlo")

    # Mas que el refresco de la pantalla: es el escenario del bug.
    await pagina.wait_for_timeout(4500)
    fila = pagina.locator(".item").filter(has_text="Clasica").first
    chip_rappi = fila.locator(".pill[data-plat='rappi']")
    revisar("sel" not in (await chip_rappi.get_attribute("class")),
            "y SIGUE deseleccionado despues de que la lista se repinte sola")

    antes = await pagina.evaluate("fetch('/api/historial').then(r => r.json())")
    await fila.locator("button", has_text="Apagar hoy").click()
    await pagina.wait_for_timeout(1500)
    despues = await pagina.evaluate("fetch('/api/historial').then(r => r.json())")

    ids = {o["id"] for o in antes}
    nuevas = [o for o in despues if o["id"] not in ids]
    revisar(len(nuevas) == 1 and nuevas[0]["plataforma"] == "pedidosya",
            f"la accion va solo a PedidosYa ({[o['plataforma'] for o in nuevas]})")

    # Y se puede volver a incluir.
    await chip_rappi.click()
    await pagina.wait_for_timeout(4500)
    fila = pagina.locator(".item").filter(has_text="Clasica").first
    revisar("sel" in (await fila.locator(".pill[data-plat='rappi']")
                      .get_attribute("class")),
            "volver a clickearlo la incluye de nuevo, y tambien queda")


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


async def probar_apagar_todo(pagina):
    """Apagar la carta de UNA plataforma, que es lo que pidio el usuario."""
    print("\n== Apagar todo ==")
    await pagina.click("#btn-cierre")
    await pagina.wait_for_selector("#panel-cierre:visible", timeout=5000)
    await pagina.wait_for_selector(".fila-cierre", timeout=5000)

    filas = pagina.locator(".fila-cierre")
    revisar(await filas.count() == 3,
            "hay un juego de botones para PedidosYa, otro para Rappi y otro "
            "para los dos")

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
        await probar_seleccion_de_plataforma(pagina)

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

        revisar(await pagina.locator("h3", has_text="A confirmar — 7").count() == 1,
                "muestra los 7 pares a confirmar")
        revisar(await pagina.locator("h3", has_text="Solo en Rappi — 18").count() == 1,
                "muestra los 18 que estan solo en Rappi")
        revisar("29 en PedidosYa" in await pagina.locator("#carta-cuerpo").inner_text(),
                "muestra cuantos leyo de cada portal")

        print("\n== Los dos wraps caesar arrancan separados ==")
        fila = fila_de(pagina, "Wrap caesar con batatas", "Wrap caesar con ensalada")
        revisar(await fila.locator("button", has_text="Vincular").count() == 1,
                "el par que el usuario dijo que NO es el mismo ofrece Vincular")
        revisar("Wrap caesar con papas" in await fila.inner_text(),
                "avisa que en Rappi tambien existe 'con papas'")

        print("\n== Vincular y separar ==")
        await fila.locator("button", has_text="Vincular").click()
        fila = fila_de(pagina, "Wrap caesar con batatas", "Wrap caesar con ensalada")
        revisar(await esperar_boton(fila, "Separar"),
                "despues de vincular, la fila ofrece Separar")
        revisar("un solo botón" in await fila.inner_text(),
                "y avisa que los dos se apagan juntos")

        productos = await pagina.evaluate(
            "fetch('/api/catalogo').then(r => r.json())")
        vinculado = [p for p in productos["productos"]
                     if p["plataformas"]["pedidosya"] == "Wrap caesar con batatas"]
        revisar(len(vinculado) == 1 and
                vinculado[0]["plataformas"]["rappi"] == "Wrap caesar con ensalada",
                "quedo un solo producto con los dos nombres")

        await fila.locator("button", has_text="Separar").click()
        fila = fila_de(pagina, "Wrap caesar con batatas", "Wrap caesar con ensalada")
        revisar(await esperar_boton(fila, "Vincular"),
                "Separar los vuelve a dejar con un boton cada uno")

        print("\n== Agregar uno que solo esta en Rappi ==")
        fila_bowl = pagina.locator(".par:not(.manual)").filter(has_text="Bowl Huerta").first
        await fila_bowl.locator("button", has_text="Agregar").click()
        fila_bowl = pagina.locator(".par:not(.manual)").filter(has_text="Bowl Huerta").first
        await fila_bowl.locator(".hecho").wait_for(timeout=10000)
        revisar("cargado" in await fila_bowl.inner_text(),
                "queda marcado como cargado")

        # La lista se repinta despues de que la fila de la carta se marca
        # como cargada, asi que hay que esperarla a ella, no leer y ver.
        en_lista = pagina.locator("#lista .item").filter(has_text="Bowl Huerta")
        revisar(await esperar(en_lista),
                "y aparece en la lista de productos de la pantalla principal")

        await probar_aviso_de_novedad(pagina)
        await probar_vinculador_manual(pagina)
        await probar_pausa(pagina)
        await probar_renombrar_y_deshacer(pagina)
        await probar_ajustes(pagina)

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
