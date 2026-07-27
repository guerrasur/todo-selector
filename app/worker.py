"""Worker en background: mantiene el navegador abierto y procesa la cola.

Diseño:
  - UN navegador persistente, con UNA pestaña por plataforma, siempre logueado.
  - La UI nunca espera al navegador: encola una Operacion y devuelve enseguida.
  - Cada 5 min se revisa todo lo apagado (PedidosYa a veces lo revive solo).
"""

import asyncio
import logging
from datetime import datetime, timedelta

from playwright.async_api import async_playwright

from .carta import emparejar, resumen
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

INTERVALO_COLA = 2               # segundos entre chequeos de la cola
VERIFICACION_RAPIDA = 120        # 2 min: confirma lo recien apagado
INTERVALO_REVERIFICACION = 900   # 15 min: ronda general de lo apagado
FRESCURA_MAX = 120               # seg: si la pestaña es mas vieja, refrescar
MAX_INTENTOS = 3


class Worker:
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.plataformas = {}       # nombre -> instancia
        self.sesion_ok = {}         # nombre -> bool
        self.ultimo_refresco = {}   # nombre -> datetime del ultimo reload
        self.corriendo = False
        self.ultimo_chequeo = None
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
        log.info("Worker iniciado (simulado=%s)", modo_simulado)

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

        self.plataformas["pedidosya"] = PedidosYa(pag_py)
        self.plataformas["rappi"] = Rappi(pag_rappi)

        for nombre, plat in self.plataformas.items():
            try:
                ok = await plat.asegurar_sesion()
                self.sesion_ok[nombre] = ok
                log.info("Sesion %s: %s", nombre, "OK" if ok else "REQUIERE LOGIN")
            except Exception as e:
                self.sesion_ok[nombre] = False
                log.error("Error verificando sesion %s: %s", nombre, e)

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
            op = (
                db.query(Operacion)
                .filter(Operacion.estado == Operacion.PENDIENTE)
                .order_by(Operacion.creada_en)
                .first()
            )
            if not op:
                return

            op.estado = Operacion.EN_CURSO
            op.intentos += 1
            db.commit()

            producto = db.query(Producto).get(op.producto_id)
            nombre_remoto = self._nombre_remoto(db, producto, op.plataforma)

            log.info("op#%s %s '%s' en %s (intento %s/%s)",
                     op.id, op.accion, nombre_remoto, op.plataforma,
                     op.intentos, MAX_INTENTOS)

            exito, detalle = await self._ejecutar(
                op.plataforma, op.accion, nombre_remoto
            )

            if exito:
                log.info("op#%s OK", op.id)
            elif op.intentos < MAX_INTENTOS:
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
                if op.accion != "prender":
                    asyncio.create_task(
                        self._verificar_luego(op.producto_id, op.plataforma,
                                              op.accion, VERIFICACION_RAPIDA)
                    )
            elif op.intentos < MAX_INTENTOS:
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
        if self.modo_simulado:
            await asyncio.sleep(2)
            return True, "simulado"

        plat = self.plataformas.get(plataforma)
        if plat is None:
            return False, f"plataforma desconocida: {plataforma}"

        async with self.bloqueo(plataforma):
            return await self._ejecutar_sin_turno(plat, plataforma, accion, nombre_remoto)

    async def _ejecutar_sin_turno(self, plat, plataforma, accion, nombre_remoto):
        # Refresca y verifica sesion justo antes de operar
        listo, motivo = await self._preparar(plataforma)
        if not listo:
            return False, motivo

        try:
            if accion == "apagar_hoy":
                ok = await plat.apagar(nombre_remoto, por_hoy=True)
            elif accion == "apagar_indef":
                ok = await plat.apagar(nombre_remoto, por_hoy=False)
            elif accion == "prender":
                ok = await plat.prender(nombre_remoto)
            else:
                return False, f"accion desconocida: {accion}"

            if not ok:
                # Puede que haya fallado por deslogueo en el medio
                sigue_ok = await plat.asegurar_sesion()
                self.sesion_ok[plataforma] = sigue_ok
                if not sigue_ok:
                    return False, "se cayo la sesion durante la operacion"

            return ok, "" if ok else "no se pudo confirmar el cambio"
        except Exception as e:
            log.exception("Excepcion en %s.%s('%s')", plataforma, accion, nombre_remoto)
            return False, _resumen(e)

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

        ultimo = self.ultimo_refresco.get(plataforma)
        vieja = (ultimo is None or
                 (datetime.now() - ultimo).total_seconds() > FRESCURA_MAX)

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

        return True, ""

    async def revalidar_sesion(self, plataforma: str = None) -> dict:
        """Fuerza refresco y chequeo de sesion. La UI lo llama con un boton."""
        if self.modo_simulado:
            return self.sesion_ok

        objetivo = ([plataforma] if plataforma
                    else list(self.plataformas.keys()))

        for nombre in objetivo:
            async with self.bloqueo(nombre):
                self.ultimo_refresco.pop(nombre, None)  # fuerza el refresco
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

    async def leer_carta(self) -> dict:
        """Lee la carta de las dos plataformas y las cruza.

        Es el reemplazo del catalogo a mano de seed.py: cada portal dice
        como se llaman SUS productos y aca se decide cuales son el mismo.
        No toca la base: propone, y la confirmacion es del usuario.
        """
        if self.modo_simulado:
            return {"error": "modo simulado: no hay navegador"}

        cartas, errores = {}, {}
        for nombre in ("pedidosya", "rappi"):
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

        pares = emparejar(cartas.get("pedidosya", []), cartas.get("rappi", []))
        salida = resumen(pares)
        salida["leidos"] = {k: len(v) for k, v in cartas.items()}
        if errores:
            salida["errores"] = errores

        log.info("Carta: %s en PedidosYa, %s en Rappi, %s emparejados solos, "
                 "%s a confirmar",
                 len(cartas.get("pedidosya", [])), len(cartas.get("rappi", [])),
                 salida["emparejados"], len(salida["a_confirmar"]))
        return salida

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
        """PedidosYa a veces revive productos apagados. Chequeamos periodicamente."""
        while self.corriendo:
            await asyncio.sleep(INTERVALO_REVERIFICACION)
            try:
                await self._reverificar()
            except Exception as e:
                log.exception("Error reverificando: %s", e)

    async def _reverificar(self):
        if self.modo_simulado:
            return

        db = SessionLocal()
        try:
            apagados = (
                db.query(EstadoItem)
                .filter(EstadoItem.estado.in_([
                    EstadoItem.APAGADO_HOY, EstadoItem.APAGADO_INDEF
                ]))
                .all()
            )

            for est in apagados:
                plat = self.plataformas.get(est.plataforma)
                if plat is None:
                    continue

                producto = db.query(Producto).get(est.producto_id)
                nombre_remoto = self._nombre_remoto(db, producto, est.plataforma)

                try:
                    async with self.bloqueo(est.plataforma):
                        listo, _ = await self._preparar(est.plataforma)
                        if not listo:
                            continue
                        real = await plat.leer_estado(nombre_remoto)
                except Exception:
                    continue

                est.verificado_en = datetime.now()

                if real is not None and real.disponible:
                    # Se revivio solo: lo reencolamos
                    log.warning("%s revivio en %s, reencolando",
                                producto.nombre, est.plataforma)
                    accion = ("apagar_hoy" if est.estado == EstadoItem.APAGADO_HOY
                              else "apagar_indef")
                    db.add(Operacion(
                        producto_id=est.producto_id,
                        plataforma=est.plataforma,
                        accion=accion,
                        detalle="reintento automatico: se habia revivido",
                    ))

            db.commit()
            self.ultimo_chequeo = datetime.now()
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
