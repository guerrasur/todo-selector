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
                 nombre: str = None, nombre_tienda: str = None):
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
        # columna "Tienda". Sale de Ajustes (rappi_nombre_tienda /
        # rappi_comun_nombre_tienda) porque el storeId NO aparece en ese DOM
        # (ver leer_estado_tienda): sin este dato no hay como saber cual de
        # las tarjetas de esa pantalla es la nuestra.
        self.nombre_tienda = nombre_tienda or ""

    @property
    def configurado(self) -> bool:
        return bool(self.store_id and self.brand_id)

    def configurar(self, store_id: str = None, brand_id: str = None,
                   nombre_tienda: str = None):
        """Cambia de tienda/marca sin reiniciar la app (viene de Ajustes)."""
        if store_id and store_id != self.store_id:
            log.info("Rappi pasa a la tienda %s (antes %s)", store_id, self.store_id)
            self.store_id = store_id
        if brand_id and brand_id != self.brand_id:
            log.info("Rappi pasa a la marca %s (antes %s)", brand_id, self.brand_id)
            self.brand_id = brand_id
        if nombre_tienda is not None and nombre_tienda != self.nombre_tienda:
            self.nombre_tienda = nombre_tienda

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
    #  TODO-SELECTOR: pendiente de confirmar en vivo (2026-07-30)
    # =====================================================================
    # Por captura de /api/esqueleto en Administracion > Conectividad: cada
    # tienda de la marca tiene su propia tabla, con filas etiqueta/valor:
    #
    #   Tienda:  "Lima Ba - Gurruchaga - Turbo"
    #   Pais:    Argentina
    #   Estado:  Activa | Cerrada | Suspendida
    #
    # NO hay storeId visible en ese DOM (ni id, ni data-testid, ni href): la
    # unica forma de saber cual tarjeta es la nuestra es por el nombre EXACTO
    # de la columna "Tienda", de ahi que haga falta el ajuste nombre_tienda
    # (rappi_nombre_tienda / rappi_comun_nombre_tienda). Sin ese dato, "no
    # se" (None) es la unica respuesta honesta -- misma regla que
    # leer_estado(): no afirmar un estado que no se pudo leer.
    #
    # "Cerrada" no es necesariamente un problema (vimos el motivo "it is out
    # of regular hours", o sea fuera de horario configurado); "Suspendida" si
    # lo es (la corta Rappi). Cualquier otro texto que no reconozcamos
    # tambien devuelve None en vez de adivinar.
    NAV_CONECTIVIDAD = "Conectividad"
    ESTADOS_TIENDA_ABIERTA = {"activa"}
    ESTADOS_TIENDA_CERRADA = {"cerrada", "suspendida"}

    async def leer_estado_tienda(self) -> Optional[ResultadoTienda]:
        if not self.nombre_tienda:
            return None

        await self.ir_al_menu()  # asegura sesion antes de irnos a otra pantalla

        try:
            nav = self.page.get_by_text(self.NAV_CONECTIVIDAD, exact=True)
            if await nav.count() == 0:
                return None
            await self.clickear(nav, que="nav Conectividad")

            valor_tienda = self.page.get_by_text(self.nombre_tienda, exact=True)
            if await valor_tienda.count() == 0:
                return None

            tarjeta = valor_tienda.locator("xpath=ancestor::table[1]").first
            valor_estado = tarjeta.locator(
                "xpath=.//td[normalize-space(text())='Estado']"
                "/following-sibling::td[1]"
            )
            if await valor_estado.count() == 0:
                return None
            texto = (await valor_estado.inner_text()).strip()
        except Exception as e:
            log.warning("%s: no pude leer el estado de la tienda en "
                        "Conectividad: %s", self.nombre,
                        " ".join(str(e).split())[:120])
            return None
        finally:
            # Nos fuimos del menu a proposito: volvemos para que la proxima
            # lectura de productos no se encuentre en otra pantalla.
            await self.ir_al_menu()

        t = texto.lower()
        if t in self.ESTADOS_TIENDA_ABIERTA:
            return ResultadoTienda(abierta=True, detalle=texto)
        if t in self.ESTADOS_TIENDA_CERRADA:
            return ResultadoTienda(abierta=False, detalle=texto)
        return None
