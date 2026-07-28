"""Rappi Partners.

FLUJO OBSERVADO (captura del usuario):
  - Cada producto es una tarjeta con imagen, nombre, SKU, badge de estado
    ("Apagados"), descripcion, precio, un toggle a la derecha y un lapiz.
  - El badge de estado da una segunda fuente para leer disponibilidad.

OJO CON LAS TIENDAS:
  La URL trae varios storeIds. Si hay que apagar en TODAS, este modulo
  tiene que iterar cambiando storeId en la URL. Ver STORE_IDS abajo.

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

from .base import PlataformaBase, ResultadoEstado

log = logging.getLogger("rappi")


class Rappi(PlataformaBase):
    nombre = "rappi"

    # Defaults del local para el que se escribio esto. Se cambian desde
    # Ajustes sin tocar codigo (era lo que faltaba para que sirva en otro
    # local); estos valores son solo el punto de partida.
    BRAND_ID = "BRAND_ID"
    # CONFIRMADO: STORE_ID es la tienda Turbo.
    # Al apagar en Turbo tambien se apaga en Rappi normal, asi que
    # con esta sola tienda alcanza.
    STORE_ID_TURBO = "STORE_ID"
    STORE_IDS = [STORE_ID_TURBO]
    TODAS_LAS_TIENDAS = ["STORE_ID_2", "STORE_ID_3", "STORE_ID", "STORE_ID_4", "STORE_ID_5"]

    BADGE_APAGADO = "Apagados"

    # CONFIRMADO POR CAPTURA (2026-07-27): al clickear el toggle prendido
    # aparece un dialogo con 3 radios: "No disponible indefinidamente",
    # "Sólo por hoy" y "Personalizar disponibilidad" (esta ultima NO se
    # usa, requiere elegir una fecha).
    TXT_POR_HOY = "Sólo por hoy"
    TXT_INDEFINIDO = "No disponible indefinidamente"

    def __init__(self, page, store_id: str = None, brand_id: str = None):
        super().__init__(page)
        self.store_id = store_id or self.STORE_IDS[0]
        self.brand_id = brand_id or self.BRAND_ID

    def configurar(self, store_id: str = None, brand_id: str = None):
        """Cambia de tienda/marca sin reiniciar la app (viene de Ajustes)."""
        if store_id and store_id != self.store_id:
            log.info("Rappi pasa a la tienda %s (antes %s)", store_id, self.store_id)
            self.store_id = store_id
        if brand_id and brand_id != self.brand_id:
            log.info("Rappi pasa a la marca %s (antes %s)", brand_id, self.brand_id)
            self.brand_id = brand_id

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
        <img data-testid="catalog-item-image" alt="Gaseosa cola sabor original
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

        # CONFIRMADO EN VIVO (2026-07-27, op#18 'Budín de pan'): prender no
        # abre ningun dialogo. El click sobre el toggle apagado lo prende y
        # la relectura despues de recargar lo confirmo. Los dos modales
        # ("Sólo por hoy" y "¿Desactivar producto?") son solo de apagar.
        tarjeta = self._tarjeta(nombre_remoto)
        await self.clickear(self._toggle_clickeable(tarjeta), que="toggle")
        await self.page.wait_for_timeout(2500)

        return await self._confirmar(nombre_remoto, esperado_disponible=True)
