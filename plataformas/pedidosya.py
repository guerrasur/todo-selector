"""PedidosYa Partner.

FLUJO OBSERVADO (capturas del usuario):
  1. Lista de productos agrupados por categoria (Ensaladas, Wraps, ...)
  2. Cada producto tiene un toggle a la izquierda del nombre
  3. Al clickear el toggle de un producto PRENDIDO, se abre un popup con:
       - titulo = nombre del producto
       - "Unavailable for today"      (punto amarillo)
       - "Unavailable indefinitely"   (punto gris)
     OJO: el portal esta EN INGLES, aunque las capturas iniciales se
     hubieran leido en castellano. Ver TXT_POR_HOY.
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
        <p class="... item-name">Guiso de lentejas</p>
      </span>
    </label>

El <label class="mat-slide-toggle-label"> envuelve tanto el nombre del
producto como el toggle: es la fila. El estado se lee 100% de
aria-checked ("true"/"false") sobre el <input>.

=========================================================================
 SELECTORES PENDIENTES DE CONFIRMAR EN VIVO  ->  buscar "TODO-SELECTOR"
=========================================================================
"""

import logging
import re
from typing import Optional

from .base import PlataformaBase, ResultadoEstado

log = logging.getLogger("pedidosya")


class PedidosYa(PlataformaBase):
    nombre = "pedidosya"

    # El id del menu es el de la sucursal: si te logueas en otra, la app
    # navega de vuelta a esta.
    MENU_ID = "460348"
    url_menu = f"https://web-ar.us.restaurant-partners.com/menus/PY_AR/{MENU_ID}"

    # --- Opciones del popup de disponibilidad ---
    # CONFIRMADO POR LOG (2026-07-27): el portal esta EN INGLES. El popup
    # dice "Coca Cola | Unavailable for today | Unavailable indefinitely".
    # Buscabamos el texto en castellano, no lo encontrabamos, y por eso
    # fallaba el apagado aunque el click estuviera entrando bien.
    # Se aceptan los dos idiomas por si el portal cambia de locale.
    TXT_POR_HOY = re.compile(r"(no disponible por hoy|unavailable for today)", re.I)
    TXT_INDEFINIDO = re.compile(
        r"(no disponible indefinidamente|unavailable indefinitely)", re.I)

    # Popup de "Let's make sure the application can play sounds" que sale
    # al reloguear (una vez por dia).
    RE_PLAY_SOUND = re.compile(r"play\s*sound", re.I)

    async def _cerrar_popups(self) -> bool:
        """Cierra el popup de sonido que PedidosYa muestra al reloguear.

        Aparece una vez por dia. Mientras esta abierto tapa parte de la
        lista, y un click sobre lo que quede debajo falla con "intercepts
        pointer events" hasta el timeout.

        OJO: esto NO explica el "element is not enabled" que se vio el
        2026-07-27. Ese mensaje solo lo produce un `disabled`, un
        `aria-disabled="true"` o un <fieldset disabled> padre (verificado
        contra Playwright 1.61). Ver inspeccionar().
        """
        boton = self.page.get_by_role("button", name=self.RE_PLAY_SOUND)
        if await boton.count() > 0:
            try:
                await boton.first.click(timeout=5000)
                await self.page.wait_for_timeout(1000)
                log.info("Popup de sonido cerrado")
                return True
            except Exception as e:
                log.warning("No pude cerrar el popup de sonido: %s", e)

        # Puede haber quedado colgado el popup de disponibilidad de un
        # intento anterior. Si no se cierra, el proximo click cae sobre el
        # backdrop y el reintento nace muerto.
        if await self._hay_overlay():
            texto = await self.texto_overlay()
            log.warning("Cierro un dialogo que quedo abierto: %s", texto or "(sin texto)")
            await self.page.keyboard.press("Escape")
            await self.page.wait_for_timeout(800)
            return True

        return False

    async def _hay_overlay(self) -> bool:
        """Queda algun dialogo tapando el menu? Solo para avisar en el log."""
        try:
            return await self.page.locator(".cdk-overlay-backdrop").count() > 0
        except Exception:
            return False

    async def asegurar_sesion(self) -> bool:
        await self.ir_al_menu()

        # Antes que nada: si hay un popup abierto, tapa parte de la lista
        # y los clicks que caigan debajo van a fallar por timeout.
        await self._cerrar_popups()
        if await self._hay_overlay():
            log.warning("Hay un dialogo abierto en la pestaña de PedidosYa "
                        "que no supe cerrar: los clicks pueden fallar")

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

    async def _click_toggle(self, fila):
        """Clickea el toggle de la fila.

        OJO: el <input> tiene la clase cdk-visually-hidden de Angular
        Material y clickearlo directo NO funciona. Verificado contra una
        pagina de prueba con este mismo HTML: el click al input tarda
        30.0s exactos y falla. Hay que clickear la barra visible.
        """
        barra = fila.locator("span.mat-slide-toggle-bar").first
        # El <label> entero tambien togglea (semantica de label).
        objetivo = barra if await barra.count() > 0 else fila
        await self.clickear(objetivo, timeout=10000, que="toggle")

    def _fila(self, nombre_remoto: str):
        """Devuelve el locator de la fila del producto.

        CONFIRMADO: cada fila es el <label class="mat-slide-toggle-label">
        de Angular Material, que envuelve nombre + toggle. Buscamos el
        texto exacto (exact=True, cuidado con nombres que son prefijo de
        otros: 'Wrap caesar' vs 'Wrap caesar con batatas') y subimos al
        label ancestro.
        """
        texto = self.page.get_by_text(nombre_remoto, exact=True).first
        return texto.locator(
            "xpath=ancestor::label[contains(@class,'mat-slide-toggle-label')][1]"
        )

    async def listar_productos(self) -> list[str]:
        await self.ir_al_menu()
        filas = self.page.locator("label.mat-slide-toggle-label")
        nombres = []
        for i in range(await filas.count()):
            try:
                texto = await filas.nth(i).inner_text()
            except Exception:
                continue
            texto = " ".join(texto.split())
            if texto:
                nombres.append(texto)
        return nombres

    async def inspeccionar(self, nombre_remoto: str) -> dict:
        await self.ir_al_menu()
        datos = await self._html_de(self._fila(nombre_remoto))
        datos["popup_abierto"] = await self._hay_overlay()
        return datos

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
            log.info("'%s' ya estaba apagado, no toco nada", nombre_remoto)
            return True

        fila = self._fila(nombre_remoto)
        await self._click_toggle(fila)
        await self.page.wait_for_timeout(1500)

        # El popup ofrece las dos opciones
        opcion = self.TXT_POR_HOY if por_hoy else self.TXT_INDEFINIDO
        try:
            await self.clickear(self.page.get_by_text(opcion),
                                que=f"opcion {opcion.pattern}")
        except Exception:
            # No sirve saber que no encontramos el texto: lo que hace falta
            # es saber que decia el popup que si se abrio.
            log.error("No encontre %s en el popup. Lo que hay abierto dice: %s",
                      opcion.pattern, await self.texto_overlay() or "(nada abierto)")
            await self.page.keyboard.press("Escape")
            return False

        await self.page.wait_for_timeout(3000)
        return await self._confirmar(nombre_remoto, esperado_disponible=False)

    async def prender(self, nombre_remoto: str) -> bool:
        estado = await self.leer_estado(nombre_remoto)
        if estado is None:
            return False
        if estado.disponible:
            log.info("'%s' ya estaba prendido, no toco nada", nombre_remoto)
            return True

        fila = self._fila(nombre_remoto)
        await self._click_toggle(fila)
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
