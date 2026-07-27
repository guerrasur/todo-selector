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

from .database import SessionLocal, PERFIL_CHROME
from .models import Producto, AliasPlataforma, EstadoItem, Operacion

log = logging.getLogger("worker")

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

            exito, detalle = await self._ejecutar(
                op.plataforma, op.accion, nombre_remoto
            )

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
            return False, str(e)

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

            listo, _ = await self._preparar(plataforma)
            if not listo:
                return

            nombre_remoto = self._nombre_remoto(db, producto, plataforma)
            try:
                real = await plat.leer_estado(nombre_remoto)
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
            log.info("Refrescando %s antes de operar...", plataforma)
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
            self.ultimo_refresco.pop(nombre, None)  # fuerza el refresco
            await self._preparar(nombre)

        return self.sesion_ok

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

                listo, _ = await self._preparar(est.plataforma)
                if not listo:
                    continue

                producto = db.query(Producto).get(est.producto_id)
                nombre_remoto = self._nombre_remoto(db, producto, est.plataforma)

                try:
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
