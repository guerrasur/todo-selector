"""PedidosYa Partner.

FLUJO OBSERVADO (capturas del usuario):
  1. Lista de productos agrupados por categoria (Platos, Tartas, ...)
  2. Cada producto tiene un toggle a la izquierda del nombre
  3. Al clickear el toggle de un producto PRENDIDO, se abre un popup con:
       - titulo = nombre del producto
       - "No disponible por hoy"          (punto amarillo)
       - "No disponible indefinidamente"  (punto gris)
  4. Al clickear el toggle de un producto APAGADO, presumiblemente lo
     prende directo (VERIFICAR en vivo).

CONFIRMADO POR HTML (DevTools, 2026-07-27): los toggles son
<mat-slide-toggle> de Angular Material:

    <label class="mat-slide-toggle-label" for="mat-slide-toggle-22-input">
      <span class="mat-slide-toggle-bar">
        <input type="checkbox" role="switch"
               class="mat-slide-toggle-input cdk-visually-hidden"
               id="mat-slide-toggle-22-input" aria-checked="false">
        ...
      </span>
      <span class="mat-slide-toggle-content">
        <p class="... item-name">Pollo al horno</p>
      </span>
    </label>

El <label class="mat-slide-toggle-label"> envuelve tanto el nombre del
producto como el toggle: es la fila. El estado se lee 100% de
aria-checked ("true"/"false") sobre el <input>.

=========================================================================
 SELECTORES PENDIENTES DE CONFIRMAR EN VIVO  ->  buscar "TODO-SELECTOR"
=========================================================================
"""

from typing import Optional

from .base import PlataformaBase, ResultadoEstado


class PedidosYa(PlataformaBase):
    nombre = "pedidosya"
    url_menu = "https://web-ar.us.restaurant-partners.com/menus/PY_AR/MENU_ID"

    # --- Textos del popup (confirmados por captura) ---
    TXT_POR_HOY = "No disponible por hoy"
    TXT_INDEFINIDO = "No disponible indefinidamente"

    async def asegurar_sesion(self) -> bool:
        await self.ir_al_menu()

        # CONFIRMADO: PedidosYa no muestra pantalla de sesion expirada,
        # se re-loguea solo. Dejamos el chequeo de password como red de
        # seguridad por si en el futuro llegara a pedir login manual.
        if await self.page.locator('input[type="password"]').count() > 0:
            return False

        # CONFIRMADO: el menu usa toggles Angular Material
        # (mat-slide-toggle-input). Esperar a que aparezca al menos uno
        # es mejor evidencia de que el menu cargo que buscar una
        # categoria por nombre (puede no estar si no hay stock ese dia).
        try:
            await self.page.wait_for_selector(
                "input.mat-slide-toggle-input", timeout=15000
            )
            return True
        except Exception:
            return False

    def _fila(self, nombre_remoto: str):
        """Devuelve el locator de la fila del producto.

        CONFIRMADO: cada fila es el <label class="mat-slide-toggle-label">
        de Angular Material, que envuelve nombre + toggle. Buscamos el
        texto exacto (exact=True, cuidado con nombres que son prefijo de
        otros: 'Tarta de verdura' vs 'Tarta de verdura chica') y subimos al
        label ancestro.
        """
        texto = self.page.get_by_text(nombre_remoto, exact=True).first
        return texto.locator(
            "xpath=ancestor::label[contains(@class,'mat-slide-toggle-label')][1]"
        )

    async def leer_estado(self, nombre_remoto: str) -> Optional[ResultadoEstado]:
        await self.ir_al_menu()
        fila = self._fila(nombre_remoto)

        if await fila.count() == 0:
            return None

        # CONFIRMADO: el toggle es <input type="checkbox" role="switch"
        # aria-checked="true|false">. aria-checked es la fuente de verdad.
        toggle = fila.locator(
            'input[type="checkbox"], [role="switch"], button[aria-checked]'
        ).first

        if await toggle.count() == 0:
            return ResultadoEstado(disponible=False, detalle="toggle no encontrado")

        aria = await toggle.get_attribute("aria-checked")
        if aria is not None:
            return ResultadoEstado(disponible=(aria == "true"), detalle=f"aria={aria}")

        try:
            marcado = await toggle.is_checked()
            return ResultadoEstado(disponible=marcado, detalle="checkbox")
        except Exception:
            clases = await toggle.get_attribute("class") or ""
            return ResultadoEstado(disponible=False, detalle=f"class={clases}")

    async def apagar(self, nombre_remoto: str, por_hoy: bool = True) -> bool:
        estado = await self.leer_estado(nombre_remoto)
        if estado is None:
            return False
        if not estado.disponible:
            return True  # ya estaba apagado

        fila = self._fila(nombre_remoto)
        toggle = fila.locator(
            'input[type="checkbox"], [role="switch"], button[aria-checked]'
        ).first
        await toggle.click()
        await self.page.wait_for_timeout(1500)

        # El popup ofrece las dos opciones
        opcion = self.TXT_POR_HOY if por_hoy else self.TXT_INDEFINIDO
        try:
            await self.page.get_by_text(opcion, exact=False).first.click(timeout=8000)
        except Exception:
            return False

        await self.page.wait_for_timeout(3000)
        return await self._confirmar(nombre_remoto, esperado_disponible=False)

    async def prender(self, nombre_remoto: str) -> bool:
        estado = await self.leer_estado(nombre_remoto)
        if estado is None:
            return False
        if estado.disponible:
            return True

        fila = self._fila(nombre_remoto)
        toggle = fila.locator(
            'input[type="checkbox"], [role="switch"], button[aria-checked]'
        ).first
        await toggle.click()
        await self.page.wait_for_timeout(2000)

        # TODO-SELECTOR: verificar si al prender tambien aparece un popup
        # de confirmacion. Si aparece, clickear el boton correspondiente aca.

        return await self._confirmar(nombre_remoto, esperado_disponible=True)

    async def _confirmar(self, nombre_remoto: str, esperado_disponible: bool) -> bool:
        """Recarga y relee: no confiamos en que el click alcanzo."""
        await self.page.reload(wait_until="domcontentloaded")
        await self.page.wait_for_timeout(4000)
        estado = await self.leer_estado(nombre_remoto)
        return estado is not None and estado.disponible == esperado_disponible
