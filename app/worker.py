"""Worker en background: mantiene el navegador abierto y procesa la cola.

Diseño:
  - UN navegador persistente, con UNA pestaña por plataforma, siempre logueado.
  - La UI nunca espera al navegador: encola una Operacion y devuelve enseguida.
  - Cada 5 min se revisa todo lo apagado (PedidosYa a veces lo revive solo).
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from playwright.async_api import async_playwright

from . import config
from .carta import emparejar_n, resumen
from .database import SessionLocal, PERFIL_CHROME
from .models import Producto, AliasPlataforma, EstadoItem, Operacion

log = logging.getLogger("worker")


def _resumen(e: Exception, largo: int = 300) -> str:
    """Mensaje de error en una linea, para guardar en la base y mostrar en la UI.

    Los timeouts de Playwright traen varios parrafos de contexto; el log
    completo queda igual en la consola via log.exception().
    """
    texto = " ".join(str(e).split())
    return texto[:largo] + ("…" if len(texto) > largo else "")

MUESTRA_CARTA = (Path(__file__).resolve().parent.parent
                 / "pruebas" / "carta_ejemplo.json")


def _carta_de_muestra() -> dict:
    """Una carta inventada, para probar la pantalla sin navegador.

    En modo simulado no hay portales que leer, y la pantalla Carta es la
    que mas conviene poder probar sin depender de estar en un local. Antes
    aca vivia la lectura real de un local de verdad; ahora es un ejemplo
    armado para reproducir las mismas trampas (ver pruebas/carta_ejemplo.json).

    El archivo guarda las CARTAS CRUDAS de cada plataforma y el cruce lo
    hace el emparejador de verdad, igual que contra los portales. Antes
    guardaba el resultado ya cruzado, escrito a mano, y se habia despegado
    de lo que el codigo produce: la pantalla simulada mostraba pares que el
    emparejador ni siquiera propone.
    """
    try:
        with open(MUESTRA_CARTA, encoding="utf-8") as f:
            leidas = json.load(f)
    except Exception as e:
        return {"error": f"modo simulado y no pude leer la muestra: {e}"}

    # Solo las plataformas que esta instalacion usa: si no tiene la tienda
    # Rappi Común configurada, la pantalla simulada tampoco tiene por que
    # mostrarle una columna de mas.
    activas = config.plataformas_activas()
    cartas = {plat: leidas[plat] for plat in activas
              if isinstance(leidas.get(plat), list)}

    salida = resumen(emparejar_n(cartas), list(cartas))
    salida["leidos"] = {plat: len(nombres) for plat, nombres in cartas.items()}
    salida["simulado"] = True
    return salida


INTERVALO_COLA = 2               # segundos entre chequeos de la cola

# Cuanto se espera antes de volver a intentar una plataforma deslogueada.
# Reintentar cada 2 segundos no la va a reloguear (el login es a mano, a
# proposito) y solo llena el log.
ESPERA_SIN_SESION = 60

# Motivo por el que fallo una operacion, cuando importa distinguirlo.
SIN_SESION = "sin_sesion"
# La plataforma no esta activa en esta instalacion (no tiene pestaña). No se
# arregla reintentando: reintentar tres veces por producto solo llena la cola
# de errores identicos.
NO_ACTIVA = "no_activa"

# Lo que antes eran constantes hoy sale de Ajustes (app/config.py). Los
# valores por defecto son estos mismos, asi que sin tocar nada la app se
# comporta igual que siempre:
#   verificacion_rapida  120   2 min: confirma lo recien apagado
#   minutos_ronda         15   ronda general de lo apagado
#   frescura_pestana     120   si la pestaña es mas vieja, refrescar
#   max_intentos           3


class Worker:
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.plataformas = {}       # nombre -> instancia
        self.sesion_ok = {}         # nombre -> bool
        self.ultimo_refresco = {}   # nombre -> datetime del ultimo reload
        self.corriendo = False
        self.ultimo_chequeo = None
        self.ultima_lectura = None   # ultima vez que leimos el estado real
        self.novedades = {}          # plataforma -> productos que aparecieron
        self.ultima_carta = None     # ultimo cruce de las dos cartas
        # plataforma -> productos del catalogo que la ultima lectura NO vio
        # en el portal. Es lo que hace que un "apagado" viejo se congele.
        self.no_encontrados = {}
        # plataforma -> hasta cuando no vale la pena reintentar la cola
        # porque la sesion esta caida y hay que loguearse a mano.
        self.reintentar_desde = {}
        # Una pestaña por plataforma = un solo usuario a la vez. Sin esto,
        # el worker y los endpoints de diagnostico navegan la misma pagina
        # al mismo tiempo y se cancelan entre si (net::ERR_ABORTED en el
        # log del 2026-07-27, que dio un verificar-catalogo con 22 falsos
        # "no encontrado").
        self.bloqueos = {}

    def bloqueo(self, plataforma: str) -> asyncio.Lock:
        """Turno exclusivo sobre la pestaña de una plataforma."""
        if plataforma not in self.bloqueos:
            self.bloqueos[plataforma] = asyncio.Lock()
        return self.bloqueos[plataforma]

    # ---------- Ciclo de vida ----------

    async def iniciar(self, modo_simulado: bool = False):
        """Arranca el navegador. En modo simulado no abre nada."""
        self.modo_simulado = modo_simulado
        self.corriendo = True

        if not modo_simulado:
            await self._abrir_navegador()

        asyncio.create_task(self._loop_cola())
        asyncio.create_task(self._loop_reverificacion())

        # Arrancar sin saber que hay prendido era la queja mas directa que
        # se le podia hacer a la pantalla. Va en background para no demorar
        # el arranque: la UI se actualiza sola cuando termina.
        if not modo_simulado:
            asyncio.create_task(self._lectura_inicial())

        log.info("Worker iniciado (simulado=%s)", modo_simulado)

    async def _lectura_inicial(self):
        try:
            log.info("Leyendo el estado real de las dos plataformas...")
            await self.sincronizar_estados()
        except Exception as e:
            log.exception("Error en la lectura inicial de estados: %s", e)

    async def _abrir_navegador(self):
        from plataformas.rappi import Rappi
        from plataformas.pedidosya import PedidosYa

        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=str(PERFIL_CHROME),
            headless=False,
            channel="chrome",
            args=["--start-maximized", "--no-first-run"],
            ignore_default_args=["--enable-automation"],
            no_viewport=True,
        )

        # Una pestaña fija por plataforma
        pag_py = self.browser.pages[0] if self.browser.pages else await self.browser.new_page()
        pag_rappi = await self.browser.new_page()

        # Que sucursal es sale de Ajustes: el id de menu de PedidosYa y el
        # storeId de Rappi estaban hardcodeados, y hasta que fueran
        # configurables "sirve para otro local" estaba a medias.
        self.plataformas["pedidosya"] = PedidosYa(
            pag_py, menu_id=config.texto("pedidosya_menu_id"))
        self.plataformas["rappi"] = Rappi(
            pag_rappi,
            store_id=config.texto("rappi_store_id"),
            brand_id=config.texto("rappi_brand_id"))

        # Rappi Común es una tienda de Rappi aparte (mismo brandId, otro
        # storeId) que funciona independiente de Rappi Turbo, y es OPCIONAL:
        # a diferencia de las otras dos, la mayoria de los locales no la
        # usa. Si no esta configurada ni se le abre pestaña, para no dejar
        # una sesion "caida" fantasma que alerte de algo que nadie pidio.
        if "rappi_comun" in config.plataformas_activas():
            await self._abrir_rappi_comun()

        for nombre, plat in self.plataformas.items():
            # Primer arranque: todavia no dijo que sucursal es. Navegar con
            # el id vacio carga cualquier cosa y el error que sale despues
            # ("sesion caida") lo manda a loguearse, que no es el problema.
            if not plat.configurado:
                # None y no False: "todavia no dijiste que sucursal sos" no
                # es "se te cayo la sesion". Marcandolo como sesion caida, el
                # primer arranque te saludaba con el aviso de login (sonido,
                # notificacion y titulo parpadeando) mandandote a loguearte
                # cuando lo que faltaba era completar los ids.
                self.sesion_ok[nombre] = None
                log.warning("Falta configurar la sucursal de %s: la pantalla "
                            "lo va a pedir antes de poder leer nada", nombre)
                continue
            try:
                ok = await plat.asegurar_sesion()
                self.sesion_ok[nombre] = ok
                log.info("Sesion %s: %s", nombre, "OK" if ok else "REQUIERE LOGIN")
            except Exception as e:
                self.sesion_ok[nombre] = False
                log.error("Error verificando sesion %s: %s", nombre, e)

    async def _abrir_rappi_comun(self):
        """Le abre la pestaña a Rappi Común (la plataforma opcional)."""
        from plataformas.rappi import Rappi

        pagina = await self.browser.new_page()
        self.plataformas["rappi_comun"] = Rappi(
            pagina,
            store_id=config.texto("rappi_comun_store_id"),
            brand_id=config.texto("rappi_brand_id"),
            nombre="rappi_comun")

    async def _cerrar_plataforma(self, nombre: str):
        """Saca una plataforma opcional que el usuario acaba de desactivar.

        Sin esto, borrar el storeId en Ajustes dejaba la pestaña abierta
        operando sobre la tienda vieja: seguia entrando en las lecturas y en
        la revalidacion de sesion, y con el aviso de sesion caida podia
        ponerse a sonar por una tienda que el usuario acababa de apagar.
        """
        plat = self.plataformas.pop(nombre, None)
        self.sesion_ok.pop(nombre, None)
        self.ultimo_refresco.pop(nombre, None)
        self.reintentar_desde.pop(nombre, None)
        self.novedades.pop(nombre, None)
        self.no_encontrados.pop(nombre, None)
        self.bloqueos.pop(nombre, None)

        if plat is None:
            return
        try:
            await plat.page.close()
        except Exception as e:
            log.warning("No pude cerrar la pestaña de %s: %s", nombre, e)
        log.info("%s quedo desactivada: se cerro su pestaña", nombre)

    async def detener(self):
        self.corriendo = False
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    # ---------- Cola ----------

    async def _loop_cola(self):
        while self.corriendo:
            try:
                await self._procesar_pendientes()
            except Exception as e:
                log.exception("Error en loop de cola: %s", e)
            await asyncio.sleep(INTERVALO_COLA)

    async def _procesar_pendientes(self):
        db = SessionLocal()
        try:
            # Una plataforma deslogueada no se arregla reintentando: el login
            # es a mano a proposito. Sus operaciones esperan ahi, sin gastar
            # intentos, hasta que vuelva la sesion.
            ahora = datetime.now()
            en_espera = [p for p, hasta in self.reintentar_desde.items()
                         if ahora < hasta]

            consulta = (db.query(Operacion)
                        .filter(Operacion.estado == Operacion.PENDIENTE))
            if en_espera:
                consulta = consulta.filter(~Operacion.plataforma.in_(en_espera))

            op = consulta.order_by(Operacion.creada_en).first()
            if not op:
                return

            op.estado = Operacion.EN_CURSO
            op.intentos += 1
            db.commit()

            producto = db.query(Producto).get(op.producto_id)
            if producto is None:
                # El producto se borro (lo absorbio un vincular). Sin esto el
                # worker revienta al tomarla y la cola se traba.
                op.estado = Operacion.ERROR
                op.detalle = "el producto ya no existe"
                op.finalizada_en = datetime.now()
                db.commit()
                return

            max_intentos = config.entero("max_intentos")
            nombre_remoto = self._nombre_remoto(db, producto, op.plataforma)

            log.info("op#%s %s '%s' en %s (intento %s/%s)",
                     op.id, op.accion, nombre_remoto, op.plataforma,
                     op.intentos, max_intentos)

            exito, detalle, motivo = await self._ejecutar(
                op.plataforma, op.accion, nombre_remoto
            )

            # Sesion caida: la operacion NO se gasta un intento ni termina en
            # error. Antes se moria despues de 3 reintentos de 2 segundos, y
            # cuando el usuario terminaba de loguearse a mano ya no quedaba
            # nada encolado: lo que habia pedido se habia perdido en silencio.
            # Ahora espera ahi y sale sola apenas vuelve la sesion.
            if motivo == SIN_SESION:
                op.estado = Operacion.PENDIENTE
                op.intentos = max(0, op.intentos - 1)
                op.detalle = detalle
                self.reintentar_desde[op.plataforma] = (
                    datetime.now() + timedelta(seconds=ESPERA_SIN_SESION))
                log.warning("op#%s en espera: %s esta deslogueado. Logueate en "
                            "la ventana del navegador y sale sola.",
                            op.id, op.plataforma)
                db.commit()
                return

            # Plataforma apagada en Ajustes (o base traida de otra
            # instalacion): la operacion no tiene a donde ir. Termina ahi,
            # sin gastar los 3 intentos en el mismo error.
            if motivo == NO_ACTIVA:
                op.estado = Operacion.ERROR
                op.detalle = detalle
                op.finalizada_en = datetime.now()
                self._marcar_fallo(db, op.producto_id, op.plataforma, detalle)
                log.warning("op#%s cancelada: %s", op.id, detalle)
                db.commit()
                return

            if exito:
                log.info("op#%s OK", op.id)
            elif op.intentos < max_intentos:
                log.warning("op#%s fallo: %s", op.id, detalle)
            else:
                log.error("op#%s ERROR definitivo tras %s intentos: %s",
                          op.id, op.intentos, detalle)

            if exito:
                op.estado = Operacion.OK
                op.finalizada_en = datetime.now()
                self._set_estado(db, op.producto_id, op.plataforma, op.accion)

                # Verificacion rapida: a los 2 min confirmamos que siga asi.
                # PedidosYa a veces revive el item unos minutos despues.
                demora = config.entero("verificacion_rapida")
                if op.accion != "prender" and demora > 0:
                    asyncio.create_task(
                        self._verificar_luego(op.producto_id, op.plataforma,
                                              op.accion, demora)
                    )
            elif op.intentos < max_intentos:
                op.estado = Operacion.PENDIENTE   # reintenta despues
                op.detalle = detalle
            else:
                op.estado = Operacion.ERROR
                op.detalle = detalle
                op.finalizada_en = datetime.now()
                self._marcar_fallo(db, op.producto_id, op.plataforma, detalle)

            db.commit()
        finally:
            db.close()

    async def _ejecutar(self, plataforma: str, accion: str, nombre_remoto: str):
        """(exito, detalle, motivo). `motivo` distingue el caso sin sesion."""
        if self.modo_simulado:
            await asyncio.sleep(2)
            return True, "simulado", ""

        plat = self.plataformas.get(plataforma)
        if plat is None:
            return False, (f"{plataforma} no está activa en esta instalación "
                           f"(revisá Ajustes)"), NO_ACTIVA

        async with self.bloqueo(plataforma):
            return await self._ejecutar_sin_turno(plat, plataforma, accion, nombre_remoto)

    async def _ejecutar_sin_turno(self, plat, plataforma, accion, nombre_remoto):
        # Refresca y verifica sesion justo antes de operar
        listo, motivo = await self._preparar(plataforma)
        if not listo:
            # Sin los ids de la sucursal no hay a donde ir: reintentar no lo
            # arregla y "sesion caida" manda al usuario a loguearse, que no
            # es el problema.
            if not plat.configurado:
                return False, motivo, NO_ACTIVA
            sin_sesion = self.sesion_ok.get(plataforma) is False
            return False, motivo, (SIN_SESION if sin_sesion else "")

        try:
            if accion == "apagar_hoy":
                ok = await plat.apagar(nombre_remoto, por_hoy=True)
            elif accion == "apagar_indef":
                ok = await plat.apagar(nombre_remoto, por_hoy=False)
            elif accion == "prender":
                ok = await plat.prender(nombre_remoto)
            else:
                return False, f"accion desconocida: {accion}", ""

            if not ok:
                # Puede que haya fallado por deslogueo en el medio
                sigue_ok = await plat.asegurar_sesion()
                self.sesion_ok[plataforma] = sigue_ok
                if not sigue_ok:
                    return False, "se cayo la sesion durante la operacion", SIN_SESION

            return ok, "" if ok else "no se pudo confirmar el cambio", ""
        except Exception as e:
            log.exception("Excepcion en %s.%s('%s')", plataforma, accion, nombre_remoto)
            return False, _resumen(e), ""

    async def _verificar_luego(self, producto_id: int, plataforma: str,
                               accion: str, demora: int):
        """Espera y confirma que el item siga apagado. Si revivio, reencola."""
        await asyncio.sleep(demora)
        if not self.corriendo or self.modo_simulado:
            return

        db = SessionLocal()
        try:
            producto = db.query(Producto).get(producto_id)
            if producto is None:
                return

            # Si lo pausaron entre el apagado y este chequeo, no lo sostenemos.
            if producto.pausado:
                return

            plat = self.plataformas.get(plataforma)
            if plat is None:
                return

            nombre_remoto = self._nombre_remoto(db, producto, plataforma)
            try:
                async with self.bloqueo(plataforma):
                    listo, _ = await self._preparar(plataforma)
                    if not listo:
                        return
                    real = await plat.leer_estado(nombre_remoto)

                    # Un falso "revivio" no es gratis: reencola un apagado que
                    # va a clickear el toggle, y si el producto en realidad
                    # estaba apagado, lo PRENDE. Antes de acusar, releemos:
                    # la primera lectura puede caer sobre la pagina a medio
                    # renderizar despues del reload.
                    if real is not None and real.disponible:
                        await plat.page.wait_for_timeout(2500)
                        segunda = await plat.leer_estado(nombre_remoto)
                        if segunda is not None and not segunda.disponible:
                            log.info("%s: la primera lectura dijo disponible y la "
                                     "segunda no. Me quedo con la segunda.",
                                     producto.nombre)
                            real = segunda
            except Exception as e:
                log.error("Error verificando %s: %s", producto.nombre, e)
                return

            est = (db.query(EstadoItem)
                   .filter_by(producto_id=producto_id, plataforma=plataforma)
                   .first())
            if est:
                est.verificado_en = datetime.now()

            if real is not None and real.disponible:
                log.warning("%s revivio en %s a los %ss, reencolando",
                            producto.nombre, plataforma, demora)
                db.add(Operacion(
                    producto_id=producto_id,
                    plataforma=plataforma,
                    accion=accion,
                    detalle=f"reintento: revivio a los {demora}s",
                ))
            else:
                log.info("%s confirmado apagado en %s", producto.nombre, plataforma)

            db.commit()
        finally:
            db.close()

    # ---------- Preparacion bajo demanda ----------

    async def _preparar(self, plataforma: str) -> tuple[bool, str]:
        """Deja la pestaña lista JUSTO ANTES de operar.

        Refresca si la pagina esta vieja y verifica la sesion. Esto reemplaza
        al keepalive periodico: no molestamos al navegador si no hay trabajo.

        Cubre los dos problemas conocidos:
          - Rappi se desloguea por inactividad
          - PedidosYa se pone rancio despues de un dia
        """
        plat = self.plataformas.get(plataforma)
        if plat is None:
            return False, f"plataforma desconocida: {plataforma}"

        # Sin los datos de la sucursal no hay a donde navegar: la URL sale
        # con los ids vacios y carga cualquier cosa. Y la sesion queda en
        # None (no configurada), que NO es lo mismo que caida.
        if not plat.configurado:
            self.sesion_ok[plataforma] = None
            return False, f"falta configurar la sucursal de {plataforma}"

        ultimo = self.ultimo_refresco.get(plataforma)
        vieja = (ultimo is None or
                 (datetime.now() - ultimo).total_seconds()
                 > config.entero("frescura_pestana"))

        if vieja:
            # La URL importa: si quedaste logueado en otra sucursal, el
            # portal puede haberte llevado a otro menu y los productos no
            # van a aparecer.
            log.info("Refrescando %s antes de operar (%s)...",
                     plataforma, plat.page.url)
            try:
                await plat.page.reload(wait_until="domcontentloaded")
                await plat.page.wait_for_timeout(3000)
                self.ultimo_refresco[plataforma] = datetime.now()
            except Exception as e:
                return False, f"no pude refrescar: {e}"

        try:
            ok = await plat.asegurar_sesion()
        except Exception as e:
            ok = False
            log.error("Error verificando sesion %s: %s", plataforma, e)

        self.sesion_ok[plataforma] = ok
        if not ok:
            return False, "sesion caida: logueate en la ventana del navegador"

        # Volvio la sesion: lo que estaba esperando puede salir ya.
        self.reintentar_desde.pop(plataforma, None)
        return True, ""

    async def aplicar_config(self) -> dict:
        """Le pasa a las pestañas los ids de sucursal que se acaban de guardar.

        Sin esto, cambiar de local en Ajustes no hacia nada hasta reiniciar
        la app, que es justo lo que un ajuste no deberia pedir. Al cambiar
        se fuerza el refresco: la pestaña esta parada en el menu viejo y
        `en_el_menu()` va a decir que no, asi que la proxima operacion
        navega sola al nuevo.
        """
        py = self.plataformas.get("pedidosya")
        if py is not None:
            py.configurar(menu_id=config.texto("pedidosya_menu_id"))

        rappi = self.plataformas.get("rappi")
        if rappi is not None:
            rappi.configurar(store_id=config.texto("rappi_store_id"),
                             brand_id=config.texto("rappi_brand_id"))

        # Rappi Común es opcional y se prende y se apaga desde Ajustes, sin
        # reiniciar: si recien ahora le cargaron el storeId hay que abrirle
        # la pestaña aca (al arrancar no existia), y si lo BORRARON hay que
        # cerrarla. Dejarla abierta era peor que no tenerla: seguia leyendo
        # y alertando por una tienda que el usuario ya no queria tocar.
        activa = "rappi_comun" in config.plataformas_activas()
        rappi_comun = self.plataformas.get("rappi_comun")
        if activa and rappi_comun is not None:
            rappi_comun.configurar(
                store_id=config.texto("rappi_comun_store_id"),
                brand_id=config.texto("rappi_brand_id"))
        elif activa and self.browser is not None:
            await self._abrir_rappi_comun()
            log.info("Rappi Común recien configurada: se le abre la pestaña")
        elif not activa and rappi_comun is not None:
            await self._cerrar_plataforma("rappi_comun")

        for nombre, plat in self.plataformas.items():
            if not plat.en_el_menu():
                self.ultimo_refresco.pop(nombre, None)

        return {nombre: plat.url_menu
                for nombre, plat in self.plataformas.items()}

    async def revalidar_sesion(self, plataforma: str = None) -> dict:
        """Fuerza refresco y chequeo de sesion. La UI lo llama con un boton."""
        if self.modo_simulado:
            return self.sesion_ok

        objetivo = ([plataforma] if plataforma
                    else list(self.plataformas.keys()))

        for nombre in objetivo:
            async with self.bloqueo(nombre):
                self.ultimo_refresco.pop(nombre, None)  # fuerza el refresco
                # Que el boton sirva para lo que el usuario lo aprieta: acaba
                # de loguearse y quiere que salga AHORA, no cuando venza la
                # espera.
                self.reintentar_desde.pop(nombre, None)
                await self._preparar(nombre)

        return self.sesion_ok

    # ---------- Diagnostico ----------

    async def buscar_textos(self, plataforma: str, fragmento: str) -> dict:
        """Que textos del portal contienen 'fragmento'. Para arreglar alias."""
        plat = self.plataformas.get(plataforma)
        if self.modo_simulado or plat is None:
            return {"error": f"no hay pestaña de {plataforma} (simulado={self.modo_simulado})"}

        async with self.bloqueo(plataforma):
            listo, motivo = await self._preparar(plataforma)
            if not listo:
                return {"error": motivo}

            return {"url": plat.page.url,
                    "textos": await plat.buscar_textos(fragmento)}

    async def listar_productos(self, plataforma: str) -> dict:
        """Que productos muestra el portal ahora mismo."""
        plat = self.plataformas.get(plataforma)
        if self.modo_simulado or plat is None:
            return {"error": f"no hay pestaña de {plataforma} (simulado={self.modo_simulado})"}

        async with self.bloqueo(plataforma):
            listo, motivo = await self._preparar(plataforma)
            if not listo:
                return {"error": motivo}
            try:
                nombres = await plat.listar_productos()
            except Exception as e:
                log.exception("Listando productos de %s", plataforma)
                return {"url": plat.page.url, "error": _resumen(e)}

        return {"url": plat.page.url, "total": len(nombres), "nombres": nombres}

    async def estructura(self, plataforma: str) -> dict:
        """Como esta armada la pantalla del menu (navegacion de categorias)."""
        plat = self.plataformas.get(plataforma)
        if self.modo_simulado or plat is None:
            return {"error": f"no hay pestaña de {plataforma} (simulado={self.modo_simulado})"}

        async with self.bloqueo(plataforma):
            listo, motivo = await self._preparar(plataforma)
            if not listo:
                return {"error": motivo}
            try:
                datos = await plat.estructura()
            except Exception as e:
                log.exception("Leyendo estructura de %s", plataforma)
                return {"url": plat.page.url, "error": _resumen(e)}

        return {"url": plat.page.url, "elementos": datos}

    async def esqueleto(self, plataforma: str) -> dict:
        """El arbol del DOM, para ubicar algo sin depender del idioma."""
        plat = self.plataformas.get(plataforma)
        if self.modo_simulado or plat is None:
            return {"error": f"no hay pestaña de {plataforma} (simulado={self.modo_simulado})"}

        async with self.bloqueo(plataforma):
            listo, motivo = await self._preparar(plataforma)
            if not listo:
                return {"error": motivo}
            try:
                lineas = await plat.esqueleto()
            except Exception as e:
                log.exception("Leyendo esqueleto de %s", plataforma)
                return {"url": plat.page.url, "error": _resumen(e)}

        return {"url": plat.page.url, "nodos": len(lineas), "arbol": lineas}

    async def leer_carta(self, releer: bool = True) -> dict:
        """Lee la carta de las dos plataformas y las cruza.

        Es el reemplazo del catalogo a mano de seed.py: cada portal dice
        como se llaman SUS productos y aca se decide cuales son el mismo.
        No toca la base: propone, y la confirmacion es del usuario.
        """
        # Leer las dos cartas tarda como un minuto. Guardamos la ultima para
        # que abrir la pantalla no la dispare de nuevo: recargar el navegador
        # obligaba a esperar otra vez, y la carta no cambia tan seguido.
        if not releer:
            return self.ultima_carta      # None si todavia no se leyo nunca

        if self.modo_simulado:
            self.ultima_carta = _carta_de_muestra()
            return self.ultima_carta

        # Todas las que esta instalacion usa, no las dos de siempre: con las
        # dos tiendas de Rappi son tres cartas, y la de la tienda Común es
        # justamente la que no se podia vincular desde la pantalla.
        objetivo = config.plataformas_activas()

        cartas, errores = {}, {}
        for nombre in objetivo:
            plat = self.plataformas.get(nombre)
            if plat is None:
                errores[nombre] = "no hay pestaña"
                continue

            async with self.bloqueo(nombre):
                listo, motivo = await self._preparar(nombre)
                if not listo:
                    errores[nombre] = motivo
                    continue
                try:
                    cartas[nombre] = await plat.listar_productos()
                except Exception as e:
                    log.exception("Leyendo la carta de %s", nombre)
                    errores[nombre] = _resumen(e)

        if errores:
            log.warning("Carta incompleta: %s", errores)

        # `objetivo` y no `cartas`: una plataforma cuya lectura fallo tiene
        # que seguir teniendo su columna en la pantalla, con el error a la
        # vista. Si desapareciera, la carta parecería completa.
        salida = resumen(emparejar_n(cartas), objetivo)
        salida["leidos"] = {k: len(v) for k, v in cartas.items()}
        if errores:
            salida["errores"] = errores

        log.info("Carta: %s, %s emparejados solos, %s a confirmar",
                 ", ".join(f"{len(v)} en {k}" for k, v in cartas.items()),
                 salida["emparejados"], len(salida["a_confirmar"]))

        salida["leida_en"] = datetime.now().isoformat(timespec="seconds")
        self.ultima_carta = salida
        return salida

    async def sincronizar_estados(self, plataforma: str = None,
                                  sostener: bool = False) -> dict:
        """Lee la carta de los portales y guarda como esta cada producto.

        Sin esto la app arrancaba sin saber nada: todo en "desconocido"
        hasta que tocaras un boton. Ahora la pantalla contesta de entrada
        cual esta prendido y cual no.

        Lo que NO hace: apropiarse de lo que apago el local por su cuenta.
        Eso queda como APAGADO_AJENO y la ronda de reverificacion lo deja
        en paz; solo sostiene lo que apago la app.
        """
        if self.modo_simulado:
            return {"error": "modo simulado: no hay navegador"}

        objetivo = [plataforma] if plataforma else list(self.plataformas.keys())
        salida = {}

        for nombre in objetivo:
            plat = self.plataformas.get(nombre)
            if plat is None:
                salida[nombre] = {"error": "no hay pestaña"}
                continue

            async with self.bloqueo(nombre):
                listo, motivo = await self._preparar(nombre)
                if not listo:
                    salida[nombre] = {"error": motivo}
                    continue
                try:
                    leidos = await plat.leer_todos()
                except Exception as e:
                    log.exception("Leyendo el estado de %s", nombre)
                    salida[nombre] = {"error": _resumen(e)}
                    continue

            salida[nombre] = self._guardar_estados(nombre, leidos, sostener)
            log.info("Estado real de %s: %s prendidos, %s apagados, "
                     "%s del catalogo no aparecieron",
                     nombre, salida[nombre]["prendidos"],
                     salida[nombre]["apagados"], salida[nombre]["no_estan"])

            # Los que la app no encuentra en el portal. Se guardan para
            # poder avisarlo en la pantalla: si encima la app los da por
            # apagados, esta afirmando algo que no puede ver.
            self.no_encontrados[nombre] = salida[nombre]["no_encontrados"]
            ciegos = [n for n in self.no_encontrados[nombre]
                      if n["estado"] in EstadoItem.APAGADOS_PROPIOS]
            if ciegos:
                log.warning(
                    "%s: %s producto(s) que la app da por APAGADOS no "
                    "aparecieron en la lectura, asi que no puede confirmar "
                    "que sigan apagados: %s", nombre, len(ciegos),
                    ", ".join(c["nombre_remoto"] for c in ciegos))

            self.novedades[nombre] = self._buscar_novedades(nombre, leidos)
            salida[nombre]["novedades"] = len(self.novedades[nombre])

        # Solo si algo se leyo de verdad. Antes se sellaba la hora igual, asi
        # que con la sesion caida la pantalla decia "estado leído 20:14" sin
        # haber leido nada: el peor cartel posible, porque el usuario decide
        # mirando eso si lo que ve esta al dia.
        if any(isinstance(d, dict) and "error" not in d for d in salida.values()):
            self.ultima_lectura = datetime.now()
        return salida

    @staticmethod
    def _buscar_novedades(plataforma: str, leidos: dict) -> list:
        """Que apareció en el portal y el catalogo tenia como inexistente."""
        from .catalogo import detectar_novedades

        db = SessionLocal()
        try:
            return detectar_novedades(db, plataforma, leidos)
        except Exception as e:
            log.exception("Buscando novedades en %s: %s", plataforma, e)
            return []
        finally:
            db.close()

    @staticmethod
    def _guardar_estados(plataforma: str, leidos: dict,
                         sostener: bool = False) -> dict:
        """Vuelca al catalogo lo que se leyo del portal.

        `sostener` cambia que pasa con lo que la app apago y el portal
        muestra disponible:

          False (lectura del arranque): gana el portal. Es lo correcto al
            empezar el dia, porque un "apagado por hoy" de ayer ya vencio
            solo y volver a apagarlo seria repetir la decision de ayer.

          True (ronda de cada 15 min): no se pisa, se devuelve en
            'revividos' para que el que llama confirme y lo reencole. Eso
            es un producto que se revivio solo, que es justamente lo que la
            ronda viene a cazar.
        """
        from .catalogo import nombre_remoto as remoto_de

        db = SessionLocal()
        try:
            prendidos = apagados = en_curso = 0
            revividos = []
            no_encontrados = []

            for producto in db.query(Producto).all():
                remoto = remoto_de(producto, plataforma)
                if remoto is None:
                    continue

                est = next((e for e in producto.estados
                            if e.plataforma == plataforma), None)
                if est is None:
                    continue

                # Una operacion en vuelo manda sobre la lectura.
                if est.estado in EstadoItem.EN_CURSO:
                    en_curso += 1
                    continue

                if remoto not in leidos:
                    # No aparecio en el portal. Seguimos sin pisar lo que ya
                    # sabiamos (el nombre puede no coincidir), PERO esto se
                    # avisa: era un agujero grande. Un producto que la app
                    # no encuentra queda con su ultimo estado PARA SIEMPRE, y
                    # si ese estado era "apagado", la pantalla lo sigue
                    # afirmando en presente mientras el portal lo vende.
                    # verificado_en NO se toca: es justo lo que delata que
                    # esto es viejo.
                    no_encontrados.append({
                        "producto_id": producto.id,
                        "producto": producto.nombre,
                        "plataforma": plataforma,
                        "nombre_remoto": remoto,
                        "estado": est.estado,
                        "verificado_en": (est.verificado_en.isoformat(
                            timespec="seconds") if est.verificado_en else None),
                    })
                    continue

                disponible = leidos[remoto]
                est.verificado_en = datetime.now()

                if disponible:
                    # Un producto en pausa se lee igual (la lectura trae la
                    # carta entera de todos modos) pero no se sostiene: es
                    # justamente lo que el usuario pidio sacarse de encima.
                    if (sostener and not producto.pausado
                            and est.estado in EstadoItem.APAGADOS_PROPIOS):
                        # Lo apagamos nosotros y esta prendido: se revivio.
                        # No lo pisamos: primero hay que confirmarlo.
                        revividos.append({
                            "producto_id": producto.id,
                            "producto": producto.nombre,
                            "plataforma": plataforma,
                            "nombre_remoto": remoto,
                            "estado": est.estado,
                        })
                        continue
                    est.estado = EstadoItem.PRENDIDO
                    est.detalle = ""
                    prendidos += 1
                else:
                    # Si lo apago la app, se respeta el tipo de apagado que
                    # eligio el usuario (por hoy / indefinido).
                    if est.estado not in EstadoItem.APAGADOS_PROPIOS:
                        est.estado = EstadoItem.APAGADO_AJENO
                        est.detalle = ""
                    apagados += 1

            db.commit()
            return {"leidos": len(leidos), "prendidos": prendidos,
                    "apagados": apagados, "no_estan": len(no_encontrados),
                    "en_curso": en_curso, "revividos": revividos,
                    "no_encontrados": no_encontrados}
        finally:
            db.close()

    async def verificar_catalogo(self, plataforma: str) -> dict:
        """Busca TODOS los productos del catalogo en el portal, sin tocar nada.

        Dice de una cuales nombres de app/seed.py no coinciden con el portal,
        en vez de ir producto por producto con /api/buscar-texto.
        """
        plat = self.plataformas.get(plataforma)
        if self.modo_simulado or plat is None:
            return {"error": f"no hay pestaña de {plataforma} (simulado={self.modo_simulado})"}

        async with self.bloqueo(plataforma):
            return await self._verificar_catalogo_sin_turno(plat, plataforma)

    async def _verificar_catalogo_sin_turno(self, plat, plataforma: str) -> dict:
        listo, motivo = await self._preparar(plataforma)
        if not listo:
            return {"error": motivo}

        db = SessionLocal()
        try:
            productos = (db.query(Producto)
                         .filter(Producto.activo == True)  # noqa: E712
                         .order_by(Producto.orden).all())

            items = []
            for p in productos:
                # Sin EstadoItem, el producto no existe en esa plataforma
                if not any(e.plataforma == plataforma for e in p.estados):
                    continue

                buscado = self._nombre_remoto(db, p, plataforma)
                fila = {"canonico": p.nombre, "buscado": buscado}
                try:
                    estado = await plat.leer_estado(buscado)
                except Exception as e:
                    fila.update(encontrado=False, error=_resumen(e, 120))
                    items.append(fila)
                    continue

                fila["encontrado"] = estado is not None
                if estado is not None:
                    fila["disponible"] = estado.disponible
                items.append(fila)
        finally:
            db.close()

        faltantes = [i for i in items if not i["encontrado"]]
        log.info("Catalogo %s: %s/%s encontrados", plataforma,
                 len(items) - len(faltantes), len(items))

        return {
            "url": plat.page.url,
            "total": len(items),
            "encontrados": len(items) - len(faltantes),
            "faltantes": [i["buscado"] for i in faltantes],
            "items": items,
        }

    async def diagnosticar(self, plataforma: str, nombre_remoto: str) -> dict:
        """Prueba leer un producto por su nombre exacto, sin tocar nada."""
        plat = self.plataformas.get(plataforma)
        if self.modo_simulado or plat is None:
            return {"error": f"no hay pestaña de {plataforma} (simulado={self.modo_simulado})"}

        async with self.bloqueo(plataforma):
            return await self._diagnosticar_sin_turno(plat, plataforma, nombre_remoto)

    async def _diagnosticar_sin_turno(self, plat, plataforma, nombre_remoto) -> dict:
        listo, motivo = await self._preparar(plataforma)
        if not listo:
            return {"error": motivo}

        try:
            estado = await plat.leer_estado(nombre_remoto)
        except Exception as e:
            log.exception("Diagnostico %s '%s'", plataforma, nombre_remoto)
            return {"url": plat.page.url, "error": _resumen(e)}

        try:
            html = await plat.inspeccionar(nombre_remoto)
        except Exception as e:
            html = {"error": _resumen(e, 120)}

        if estado is None:
            return {"url": plat.page.url, "encontrado": False,
                    "ayuda": "el nombre no aparece tal cual en el portal; "
                             "probá /api/buscar-texto con una parte del nombre",
                    "inspeccion": html}

        return {"url": plat.page.url, "encontrado": True,
                "disponible": estado.disponible, "detalle": estado.detalle,
                "inspeccion": html}

    # ---------- Reverificacion ----------

    async def _loop_reverificacion(self):
        """PedidosYa a veces revive productos apagados. Chequeamos periodicamente.

        Se duerme de a un minuto en vez de los 15 de una: asi cambiar el
        intervalo desde Ajustes (o ponerlo en 0) tiene efecto en el minuto,
        y no despues de esperar la ronda vieja entera.
        """
        proxima = self._proxima_ronda()
        while self.corriendo:
            await asyncio.sleep(60)

            minutos = config.entero("minutos_ronda")
            if minutos <= 0:
                proxima = None          # ronda apagada desde Ajustes
                continue

            if proxima is None:
                proxima = datetime.now() + timedelta(minutes=minutos)
                continue

            if datetime.now() < proxima:
                continue

            proxima = datetime.now() + timedelta(minutes=minutos)
            try:
                await self._reverificar()
            except Exception as e:
                log.exception("Error reverificando: %s", e)

    @staticmethod
    def _proxima_ronda():
        minutos = config.entero("minutos_ronda")
        if minutos <= 0:
            return None
        return datetime.now() + timedelta(minutes=minutos)

    async def _reverificar(self):
        """Relee las dos cartas enteras y actualiza todo lo que se ve.

        Antes leia SOLO lo que la app tenia apagado, producto por producto.
        Eso dejaba desactualizado el resto de la pantalla y, en PedidosYa,
        significaba cambiar de categoria una vez por producto.

        Leer las dos cartas de una sale mas barato que eso y ademas mantiene
        al dia lo que el local apago o prendio desde el portal, que era lo
        que faltaba: ahora "apagado (afuera)" tambien se confirma cada
        ronda, y si alguien lo prendio a mano la pantalla se entera.
        """
        if self.modo_simulado:
            return

        # Con `sostener_apagados` en off la ronda sigue leyendo (que es lo que
        # mantiene la pantalla al dia) pero no se mete a reencolar nada.
        sostener = config.activo("sostener_apagados")
        resultado = await self.sincronizar_estados(sostener=sostener)

        revividos = []
        for datos in resultado.values():
            if isinstance(datos, dict):
                revividos.extend(datos.get("revividos", []))

        for caso in revividos:
            await self._reencolar_si_revivio(caso)

        self.ultimo_chequeo = datetime.now()

    async def _reencolar_si_revivio(self, caso: dict):
        """Confirma con una segunda lectura antes de acusar que revivio.

        Un falso "revivio" no es gratis: reencola un apagado. Hoy apagar()
        relee antes de clickear, asi que en el peor caso no hace nada, pero
        la lectura de confirmacion es barata (es un solo producto) y evita
        llenar el historial de operaciones que no hacian falta.
        """
        plataforma = caso["plataforma"]
        plat = self.plataformas.get(plataforma)
        if plat is None:
            return

        try:
            async with self.bloqueo(plataforma):
                listo, _ = await self._preparar(plataforma)
                if not listo:
                    return
                real = await plat.leer_estado(caso["nombre_remoto"])
        except Exception as e:
            log.error("Error confirmando si '%s' revivio en %s: %s",
                      caso["producto"], plataforma, e)
            return

        db = SessionLocal()
        try:
            est = (db.query(EstadoItem)
                   .filter_by(producto_id=caso["producto_id"],
                              plataforma=plataforma)
                   .first())
            if est is None:
                return

            est.verificado_en = datetime.now()

            if real is None or not real.disponible:
                log.info("%s: la lectura de la carta lo dio prendido y la "
                         "confirmacion no. Me quedo con la confirmacion.",
                         caso["producto"])
                db.commit()
                return

            log.warning("%s revivio en %s, reencolando", caso["producto"],
                        plataforma)
            est.estado = EstadoItem.PRENDIDO
            db.add(Operacion(
                producto_id=caso["producto_id"],
                plataforma=plataforma,
                accion=("apagar_hoy" if caso["estado"] == EstadoItem.APAGADO_HOY
                        else "apagar_indef"),
                detalle="reintento automatico: se habia revivido",
            ))
            db.commit()
        finally:
            db.close()

    # ---------- Helpers ----------

    @staticmethod
    def _nombre_remoto(db, producto: Producto, plataforma: str) -> str:
        alias = (
            db.query(AliasPlataforma)
            .filter_by(producto_id=producto.id, plataforma=plataforma)
            .first()
        )
        return alias.nombre_remoto if alias else producto.nombre

    @staticmethod
    def _set_estado(db, producto_id: int, plataforma: str, accion: str):
        est = (
            db.query(EstadoItem)
            .filter_by(producto_id=producto_id, plataforma=plataforma)
            .first()
        )
        if est is None:
            est = EstadoItem(producto_id=producto_id, plataforma=plataforma)
            db.add(est)

        est.estado = {
            "apagar_hoy": EstadoItem.APAGADO_HOY,
            "apagar_indef": EstadoItem.APAGADO_INDEF,
            "prender": EstadoItem.PRENDIDO,
        }[accion]
        est.detalle = ""
        est.verificado_en = datetime.now()

    @staticmethod
    def _marcar_fallo(db, producto_id: int, plataforma: str, detalle: str):
        est = (
            db.query(EstadoItem)
            .filter_by(producto_id=producto_id, plataforma=plataforma)
            .first()
        )
        if est is None:
            est = EstadoItem(producto_id=producto_id, plataforma=plataforma)
            db.add(est)
        est.estado = EstadoItem.FALLO
        est.detalle = detalle


worker = Worker()
