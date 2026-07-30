"""Rappi Partners.

FLUJO OBSERVADO (captura del usuario):
  - Cada producto es una tarjeta con imagen, nombre, SKU, badge de estado
    ("Apagados"), descripcion, precio, un toggle a la derecha y un lapiz.
  - El badge de estado da una segunda fuente para leer disponibilidad.

OJO CON LAS TIENDAS:
  La URL trae varios storeIds y cada tienda es INDEPENDIENTE: apagar en
  una no apaga en la otra, y ni siquiera tienen la misma carta
  (confirmado 2026-07-29). Una instancia de esta clase = UNA tienda. Para
  operar sobre dos (Turbo y Común) el worker crea DOS instancias con dos
  pestañas y dos store_id, no una que va cambiando la URL: asi cada
  tienda tiene su lock, su sesion y su estado, y una lectura no pisa a la
  otra. Ver worker._abrir_rappi_comun().

CONFIRMADO POR HTML (DevTools, 2026-07-27): el toggle de disponibilidad es

    <label data-testid="menu-category-170882-product-3469515-
                        availability-switch-control"
           class="sc-iYsgxs bwYJnl">
      <input id="switch-hidden-input" readonly type="checkbox"
             class="sc-bIStaS jdqCkz">
      <span class="sc-dGBNLl hjUoHd"></span>
    </label>

El data-testid trae "menu-category-{id}-product-{id}-availability-
switch-control": estable y sirve para ubicar el control sin depender de
clases generadas por styled-components (que sí cambian, hay que verlas:
"cyknSV" prendido vs "hjUoHd" apagado en las capturas). El <input> es
"readonly" y esta oculto (id="switch-hidden-input", sin tamaño visible):
HAY QUE CLICKEAR EL <label>, no el input. No trae aria-checked, asi que
leer_estado depende del badge "Apagados" (fuente 1) o de is_checked()
sobre el input (fuente 2).

CONFIRMADO POR CAPTURA: al elegir "Sólo por hoy" o "No disponible
indefinidamente" aparece un SEGUNDO modal de confirmacion,
"¿Desactivar producto?", con botones "Cancelar" y "Sí, desactivar"
(rojo). apagar() clickea "Sí, desactivar" para confirmar.

=========================================================================
 SELECTORES PENDIENTES DE CONFIRMAR EN VIVO  ->  buscar "TODO-SELECTOR"
=========================================================================
"""

import logging
from typing import Optional

from .base import PlataformaBase, ResultadoEstado, ResultadoTienda

log = logging.getLogger("rappi")


class Rappi(PlataformaBase):
    nombre = "rappi"

    # La marca y la tienda son las TUYAS: salen de Ajustes y no tienen
    # default. Cualquier valor puesto aca seria el de otro local, y apagar
    # productos en la tienda de otro es el peor error posible de esta app.
    BRAND_ID = ""
    STORE_ID = ""

    # SI TENES VARIAS TIENDAS: cada una es una instancia de esta clase, con
    # su store_id y su pestaña. Las tiendas son independientes y su carta no
    # es la misma, asi que que producto de una es cual de la otra lo decide
    # el usuario en la pantalla Carta y queda guardado en el catalogo.

    BADGE_APAGADO = "Apagados"

    # CONFIRMADO POR CAPTURA (2026-07-27): al clickear el toggle prendido
    # aparece un dialogo con 3 radios: "No disponible indefinidamente",
    # "Sólo por hoy" y "Personalizar disponibilidad" (esta ultima NO se
    # usa, requiere elegir una fecha).
    TXT_POR_HOY = "Sólo por hoy"
    TXT_INDEFINIDO = "No disponible indefinidamente"

    def __init__(self, page, store_id: str = None, brand_id: str = None,
                 nombre: str = None, nombre_tienda: str = None,
                 brand_id_conectividad: str = None):
        super().__init__(page)
        self.store_id = store_id or self.STORE_ID
        self.brand_id = brand_id or self.BRAND_ID
        # Rappi Turbo y Rappi Común son la MISMA plataforma (mismo portal,
        # mismo login) pero tiendas independientes: una segunda instancia de
        # esta clase con otro store_id es "rappi_comun". El nombre es solo
        # para que los logs digan cual es cual.
        if nombre:
            self.nombre = nombre
        # Nombre EXACTO tal cual figura en Administracion > Conectividad,
        # columna "Tienda". Sirve de desempate si la URL directa (ver
        # leer_estado_tienda) igual muestra mas de una tarjeta.
        self.nombre_tienda = nombre_tienda or ""
        # CONFIRMADO EN VIVO (2026-07-30): Rappi Comun tiene su PROPIO
        # brandId, distinto del de Turbo (AR72021 contra AR75000 en la
        # cuenta de prueba) -- el supuesto "mismo brandId, otro storeId" de
        # mas abajo resulto ser falso para Conectividad. Esto NO toca
        # self.brand_id (el que usa url_menu para el menu de productos, que
        # ya viene andando en produccion); es solo para construir la URL de
        # Conectividad. Sin este ajuste, cae a self.brand_id.
        self.brand_id_conectividad = brand_id_conectividad or self.brand_id

    @property
    def configurado(self) -> bool:
        return bool(self.store_id and self.brand_id)

    def configurar(self, store_id: str = None, brand_id: str = None,
                   nombre_tienda: str = None, brand_id_conectividad: str = None):
        """Cambia de tienda/marca sin reiniciar la app (viene de Ajustes)."""
        if store_id and store_id != self.store_id:
            log.info("Rappi pasa a la tienda %s (antes %s)", store_id, self.store_id)
            self.store_id = store_id
        if brand_id and brand_id != self.brand_id:
            log.info("Rappi pasa a la marca %s (antes %s)", brand_id, self.brand_id)
            self.brand_id = brand_id
        if nombre_tienda is not None and nombre_tienda != self.nombre_tienda:
            self.nombre_tienda = nombre_tienda
        if brand_id_conectividad and brand_id_conectividad != self.brand_id_conectividad:
            self.brand_id_conectividad = brand_id_conectividad

    @property
    def url_menu(self) -> str:
        return (
            f"https://partners.rappi.com/menu"
            f"?brandId={self.brand_id}&storeIds={self.store_id}"
            f"&storeId={self.store_id}"
        )

    def en_el_menu(self) -> bool:
        # Rappi reescribe la URL con los storeIds de TODAS las tiendas, asi
        # que la nuestra nunca coincide entera. Alcanza con estar en /menu
        # y con la tienda correcta seleccionada.
        u = self.page.url
        return "partners.rappi.com/menu" in u and f"storeId={self.store_id}" in u

    async def asegurar_sesion(self) -> bool:
        await self.ir_al_menu()

        if await self.page.locator('input[type="password"]').count() > 0:
            return False

        # CONFIRMADO: los toggles de disponibilidad tienen un data-testid
        # con el patron "...-availability-switch-control". Esperar a que
        # aparezca al menos uno es buena evidencia de que el menu cargo.
        try:
            await self.page.wait_for_selector(
                '[data-testid*="availability-switch-control"]', timeout=15000
            )
            return True
        except Exception:
            return False

    def _tarjeta(self, nombre_remoto: str):
        """Locator de la tarjeta del producto.

        TODO-SELECTOR: no tenemos el HTML completo de la tarjeta todavia.
        En vez de asumir una profundidad fija de ancestros, subimos desde
        el nombre exacto hasta el primer ancestro que TAMBIEN contenga el
        toggle de disponibilidad (data-testid confirmado). Asi evitamos
        depender de cuantos <div> hay entre el nombre y el resto de la
        tarjeta.
        """
        texto = self.page.get_by_text(nombre_remoto, exact=True).first
        return texto.locator(
            "xpath=ancestor::*"
            "[.//*[contains(@data-testid,'availability-switch-control')]][1]"
        )

    def _toggle_clickeable(self, tarjeta):
        """El elemento que hay que clickear para togglear disponibilidad.

        CONFIRMADO: es el <label data-testid="...-availability-switch-
        control">. El <input> interno es readonly y esta oculto
        (id="switch-hidden-input"), asi que clickear el input directo
        puede fallar por no ser interactuable.
        """
        control = tarjeta.locator('[data-testid*="availability-switch-control"]').first
        return control

    def _toggle_input(self, tarjeta):
        """El <input> para leer el estado real (is_checked)."""
        return tarjeta.locator(
            '[data-testid*="availability-switch-control"] input, '
            'input[type="checkbox"], [role="switch"], button[aria-checked]'
        ).first

    async def listar_productos(self) -> list[str]:
        """Los nombres salen del alt de la foto del producto.

        CONFIRMADO POR HTML (2026-07-27): cada tarjeta arranca con
        <img data-testid="catalog-item-image" alt="Nombre del producto
        500 ml">. Es mas simple y mas estable que subir desde el nombre.
        OJO: un producto sin foto no va a aparecer aca.
        """
        await self.ir_al_menu()
        imgs = self.page.locator('img[data-testid="catalog-item-image"]')
        nombres = []
        for i in range(await imgs.count()):
            alt = await imgs.nth(i).get_attribute("alt")
            if alt and alt.strip():
                nombres.append(alt.strip())
        return nombres

    async def inspeccionar(self, nombre_remoto: str) -> dict:
        # De paso resuelve el TODO-SELECTOR de _tarjeta(): con esto vemos
        # por fin el HTML completo de la tarjeta de Rappi.
        await self.ir_al_menu()
        return await self._html_de(self._tarjeta(nombre_remoto))

    async def leer_estado(self, nombre_remoto: str) -> Optional[ResultadoEstado]:
        await self.ir_al_menu()
        tarjeta = self._tarjeta(nombre_remoto)

        if await tarjeta.count() == 0:
            return None

        # Fuente 1: el badge de texto (mas confiable, no depende de
        # clases generadas por styled-components).
        texto = await tarjeta.inner_text()
        if self.BADGE_APAGADO.lower() in texto.lower():
            return ResultadoEstado(disponible=False, detalle="badge Apagados")

        # Fuente 2: el input del toggle. No tiene aria-checked
        # (confirmado); is_checked() lee el estado real igual, aunque
        # el input sea readonly y este oculto.
        toggle = self._toggle_input(tarjeta)
        if await toggle.count() > 0:
            aria = await toggle.get_attribute("aria-checked")
            if aria is not None:
                return ResultadoEstado(disponible=(aria == "true"), detalle=f"aria={aria}")
            try:
                return ResultadoEstado(disponible=await toggle.is_checked(),
                                       detalle="checkbox")
            except Exception:
                pass

        return ResultadoEstado(disponible=True, detalle="sin badge de apagado")

    async def apagar(self, nombre_remoto: str, por_hoy: bool = True) -> bool:
        estado = await self.leer_estado(nombre_remoto)
        if estado is None:
            return False
        if not estado.disponible:
            log.info("'%s' ya estaba apagado, no toco nada", nombre_remoto)
            return True

        tarjeta = self._tarjeta(nombre_remoto)
        await self.clickear(self._toggle_clickeable(tarjeta), que="toggle")
        await self.page.wait_for_timeout(1500)

        # El dialogo ofrece 2 radios utiles (la 3ra, "Personalizar
        # disponibilidad", no se usa: pide elegir una fecha).
        opcion = self.TXT_POR_HOY if por_hoy else self.TXT_INDEFINIDO
        try:
            await self.clickear(self.page.get_by_text(opcion, exact=True),
                                que=f"radio '{opcion}'")
            await self.page.wait_for_timeout(1000)
        except Exception:
            return False

        # CONFIRMADO POR CAPTURA (2026-07-27): cualquiera de las 2 opciones
        # abre un segundo modal "¿Desactivar producto?" con botones
        # "Cancelar" y "Sí, desactivar" (rojo). Hay que confirmar ahi.
        for txt in ["Sí, desactivar", "Guardar", "Confirmar", "Aceptar", "Aplicar"]:
            btn = self.page.get_by_role("button", name=txt)
            if await btn.count() > 0:
                await self.clickear(btn, que=f"boton '{txt}'")
                break

        await self.page.wait_for_timeout(3000)
        return await self._confirmar(nombre_remoto, esperado_disponible=False)

    async def prender(self, nombre_remoto: str) -> bool:
        estado = await self.leer_estado(nombre_remoto)
        if estado is None:
            return False
        if estado.disponible:
            log.info("'%s' ya estaba prendido, no toco nada", nombre_remoto)
            return True

        # CONFIRMADO EN VIVO (2026-07-27, op#18): prender no
        # abre ningun dialogo. El click sobre el toggle apagado lo prende y
        # la relectura despues de recargar lo confirmo. Los dos modales
        # ("Sólo por hoy" y "¿Desactivar producto?") son solo de apagar.
        tarjeta = self._tarjeta(nombre_remoto)
        await self.clickear(self._toggle_clickeable(tarjeta), que="toggle")
        await self.page.wait_for_timeout(2500)

        return await self._confirmar(nombre_remoto, esperado_disponible=True)

    # =====================================================================
    #  Estado de tienda via Conectividad (reactivado 2026-07-30, v2)
    # =====================================================================
    # El primer intento clickeaba el nav "Conectividad" y terminaba en
    # cualquier marca de la cuenta (ver commit anterior): el click no
    # respeta la marca de la pestaña actual. Esta version navega DIRECTO
    # por URL con el brandId y storeId de ESTA instancia (confirmado en
    # vivo que /home/real-time acepta brandId+storeIds+brandIds+storeId
    # igual que /menu), y ademas verifica que la navegacion se haya
    # quedado en nuestro storeId antes de leer nada: si el portal
    # redirige a otro lado, "no se" (None) en vez de leer una tienda
    # ajena.
    #
    # Con la URL apuntando a un solo storeId debería quedar UNA tarjeta;
    # nombre_tienda queda como desempate por si igual aparece mas de una.
    #
    # LA PANTALLA NO ES UNA TABLA (confirmado por DevTools del usuario,
    # 2026-07-30). La version anterior buscaba <td>Estado</td> + la celda
    # siguiente, leido de una captura, y encontraba CERO celdas siempre: por
    # eso las dos tiendas de Rappi decian "sin datos" mientras PedidosYa
    # andaba. El estado es un div suelto de styled-components:
    #
    #     <div class="sc-papXJ iobIXi rcf-typography-caption2 portal207"
    #          color="neutrals.grays.gray50"
    #          data-testid="test-typography">Cerrada</div>
    #
    # Las clases son generadas (sc-papXJ, iobIXi) y el data-testid es
    # generico: lo comparte TODO texto del portal, no es el estado. Lo unico
    # estable es el TEXTO, asi que se busca por texto (regla 2 de CLAUDE.md)
    # y se desempata por el nombre de la tienda.
    #
    # Estados vistos: "Activa", "Cerrada" (fuera de horario, normal) y
    # "Suspendida" (la corta Rappi, alerta real). Cualquier otro texto
    # devuelve None en vez de adivinar, y el diagnostico dice cual fue.
    ESTADOS_TIENDA_ABIERTA = {"activa"}
    ESTADOS_TIENDA_CERRADA = {"cerrada", "suspendida"}

    # Cuantas veces mirar antes de rendirse. La pantalla de Conectividad es
    # un SPA: el primer render puede no tener todavia el estado. Esperar un
    # rato fijo y decidir ahi es lo que ya nos mordio en _confirmar().
    INTENTOS_ESTADO_TIENDA = 5
    ESPERA_ENTRE_INTENTOS = 1500

    # Busca en el DOM los textos que son un estado de tienda, y para cada uno
    # el contexto (la tarjeta/fila donde vive) para poder desempatar por
    # nombre de tienda. Devuelve tambien una muestra de textos cortos de la
    # pantalla: si no reconocemos ningun estado, eso es lo unico que dice
    # como los escribe el portal de verdad.
    JS_ESTADOS_TIENDA = """
        ([estados, nombreTienda]) => {
            const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
            // Solo el texto PROPIO: si no, cada ancestro cuenta como otro
            // candidato y una tienda parece cinco.
            const propio = el => {
                let t = '';
                for (const n of el.childNodes) if (n.nodeType === 3) t += n.textContent;
                return norm(t);
            };

            const candidatos = [], muestra = [];
            for (const el of document.querySelectorAll('body *')) {
                const t = propio(el);
                if (!t) continue;
                if (t.length <= 40 && !muestra.includes(t)) muestra.push(t);
                if (!estados.includes(t.toLowerCase())) continue;

                // A cuantos niveles esta el nombre de la tienda. OJO: no
                // alcanza con "algun ancestro lo contiene". Subiendo lo
                // suficiente se llega al contenedor de TODAS las tarjetas, y
                // ahi el estado de la tienda B tambien "contiene" el nombre
                // de la A: con dos tiendas las dos daban positivo y no se
                // podia desempatar. Lo que distingue es la DISTANCIA — el
                // estado de una tarjeta tiene su propio nombre mas cerca —
                // asi que se guarda el nivel y decide el mas cercano.
                let contexto = '', nivel = null;
                for (let p = el, i = 0; p && i < 10; p = p.parentElement, i++) {
                    const texto = norm(p.innerText || p.textContent);
                    if (texto.length > 600) break;
                    contexto = texto;
                    if (nombreTienda && texto.includes(nombreTienda)) {
                        nivel = i;
                        break;
                    }
                }
                candidatos.push({texto: t, contexto: contexto.slice(0, 200),
                                 nivel: nivel});
            }
            return {candidatos: candidatos, muestra: muestra.slice(0, 60)};
        }
    """

    def _url_conectividad(self) -> str:
        marca = self.brand_id_conectividad
        return (
            f"https://partners.rappi.com/home/real-time"
            f"?brandId={marca}&storeIds={self.store_id}"
            f"&brandIds={marca}&storeId={self.store_id}"
        )

    async def _buscar_estado_en_pantalla(self) -> tuple[Optional[ResultadoTienda], dict]:
        """Lee el estado de la pantalla que ya esta abierta. No navega.

        Separado de leer_estado_tienda() a proposito: asi la parte que
        depende del DOM se puede probar contra una replica local sin portal
        ni login (pruebas/probar_rappi_conectividad.py), que es lo que
        faltaba cuando esto se escribio mirando una captura.

        Devuelve (resultado, diagnostico). El diagnostico es lo que se
        muestra cuando NO se pudo afirmar nada: sin eso, un "sin datos" no
        distingue "no encontre el texto" de "hay tres tiendas y no se cual
        sos", que son arreglos distintos.
        """
        estados = sorted(self.ESTADOS_TIENDA_ABIERTA | self.ESTADOS_TIENDA_CERRADA)

        hallazgo = {"candidatos": [], "muestra": []}
        for intento in range(self.INTENTOS_ESTADO_TIENDA):
            hallazgo = await self.page.evaluate(
                self.JS_ESTADOS_TIENDA, [estados, self.nombre_tienda or ""])
            if hallazgo["candidatos"]:
                break
            if intento < self.INTENTOS_ESTADO_TIENDA - 1:
                await self.page.wait_for_timeout(self.ESPERA_ENTRE_INTENTOS)

        candidatos = hallazgo["candidatos"]
        diag = {"url": self.page.url, "candidatos": len(candidatos)}

        if not candidatos:
            diag["motivo"] = ("no encontre ningun texto de estado conocido "
                              f"({', '.join(estados)}) en Conectividad")
            diag["textos_en_pantalla"] = hallazgo["muestra"]
            return None, diag

        elegido = None
        if len(candidatos) == 1:
            elegido = candidatos[0]
        else:
            # El mas cercano al nombre gana; si empatan dos, no se sabe.
            con_nombre = [c for c in candidatos if c["nivel"] is not None]
            cerca = min((c["nivel"] for c in con_nombre), default=None)
            propios = [c for c in con_nombre if c["nivel"] == cerca]
            if len(propios) == 1:
                elegido = propios[0]
            elif not self.nombre_tienda:
                # Adivinar cual de las tiendas de la cuenta sos es peor que
                # no decir nada: el badge quedaria afirmando el estado de
                # otro local.
                diag["motivo"] = (
                    f"la pantalla muestra {len(candidatos)} tiendas y no hay "
                    "nombre de tienda cargado en Ajustes para saber cual sos")
                diag["vistos"] = [c["texto"] for c in candidatos[:10]]
                return None, diag
            else:
                diag["motivo"] = (
                    f"'{self.nombre_tienda}' no identifica una sola tienda "
                    f"entre las {len(candidatos)} de la pantalla "
                    f"({len(propios)} coincidencias)")
                diag["contextos"] = [c["contexto"] for c in candidatos[:10]]
                return None, diag

        texto = elegido["texto"]
        diag["texto"] = texto
        t = texto.lower()
        if t in self.ESTADOS_TIENDA_ABIERTA:
            return ResultadoTienda(abierta=True, detalle=texto), diag
        if t in self.ESTADOS_TIENDA_CERRADA:
            return ResultadoTienda(abierta=False, detalle=texto), diag

        # No deberia pasar (el JS ya filtro por los conocidos), pero si el
        # dia de mañana se agranda la lista, no adivinar.
        diag["motivo"] = f"no se que significa el estado '{texto}'"
        return None, diag

    async def leer_estado_tienda(self) -> Optional[ResultadoTienda]:
        """Navega a Conectividad, lee el estado y vuelve al menu.

        El diagnostico de la ultima lectura queda en self.diagnostico_tienda
        (lo muestra /api/estado-tienda). No se levanta una excepcion ni se
        devuelve un estado inventado en ningun camino: si no se pudo
        confirmar, es None y el motivo explica cual de los pasos fallo.
        """
        self.diagnostico_tienda = {}

        if not self.brand_id_conectividad or not self.store_id:
            self.diagnostico_tienda = {
                "motivo": "faltan el brandId o el storeId de esta tienda en Ajustes"}
            return None

        try:
            await self.page.goto(self._url_conectividad(), wait_until="domcontentloaded")
            await self.page.wait_for_timeout(2500)

            # Si el portal nos mando a otro lado, no seguimos: mejor "no se"
            # que leer el estado de una tienda que no es la nuestra.
            if self.store_id not in self.page.url:
                log.warning("%s: la navegacion a Conectividad no se quedo en "
                            "la tienda configurada (termino en %s)",
                            self.nombre, self.page.url)
                self.diagnostico_tienda = {
                    "url": self.page.url,
                    "motivo": (f"Conectividad no se quedo en la tienda "
                               f"{self.store_id}: el brandId puede ser otro "
                               "(ver el ajuste de brandId en Conectividad)")}
                return None

            resultado, self.diagnostico_tienda = await self._buscar_estado_en_pantalla()
        except Exception as e:
            resumen = " ".join(str(e).split())[:120]
            log.warning("%s: no pude leer el estado de la tienda en "
                        "Conectividad: %s", self.nombre, resumen)
            self.diagnostico_tienda = {"motivo": f"error leyendo Conectividad: {resumen}"}
            return None
        finally:
            # Nos fuimos del menu a proposito: volvemos para que la proxima
            # lectura de productos no se encuentre en otra pantalla.
            await self.ir_al_menu()

        if resultado is None:
            log.info("%s: estado de tienda sin confirmar (%s)", self.nombre,
                     self.diagnostico_tienda.get("motivo", "sin motivo"))
        return resultado
