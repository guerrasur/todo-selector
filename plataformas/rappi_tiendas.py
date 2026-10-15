"""Selección del Portal Aliados por ids observados en los radios del filtro.

Dos adaptadores comparten la misma Page y el worker serializa TODO acceso.
La marca se busca por las tiendas que realmente contiene; no se supone que
Turbo y Común compartan brandId. No se guardan ids/nombres de locales aquí.
"""
import logging
import re
import time
from urllib.parse import urlsplit


log = logging.getLogger("rappi")


class SeleccionTiendaRappi:
    @staticmethod
    def _id_filtro(ident):
        m = re.fullmatch(r"(?:[A-Za-z]{2})?(\d+)", str(ident))
        if not m:
            raise ValueError("El identificador de Rappi no tiene un formato válido")
        return m.group(1)

    def _portal_nuevo(self):
        return urlsplit(self.page.url).hostname == "restaurantes.rappi.com"

    def _panel_tiendas(self):
        return self.page.locator('aside:visible').filter(
            has=self.page.get_by_text("Filtrar Marca y Tienda", exact=True))

    # :visible también incluye drawers cerrados con translateX(-100%).
    # La caja debe intersectar el viewport; no basta con tener tamaño.
    JS_PANELES_EN_PANTALLA = """els => els.flatMap((el, i) => {
        const r = el.getBoundingClientRect();
        const estilo = getComputedStyle(el);
        const ancho = Math.min(r.right, innerWidth) - Math.max(r.left, 0);
        const alto = Math.min(r.bottom, innerHeight) - Math.max(r.top, 0);
        return !el.closest('[inert], [aria-hidden="true"]') &&
            estilo.display !== 'none' && estilo.visibility !== 'hidden' &&
            ancho > 1 && alto > 1 ? [i] : [];
    })"""

    async def _panel_abierto(self):
        paneles = self._panel_tiendas()
        indices = await paneles.evaluate_all(self.JS_PANELES_EN_PANTALLA)
        if len(indices) > 1:
            raise RuntimeError("Hay más de un filtro de tiendas abierto en Rappi")
        return paneles.nth(indices[0]) if indices else None

    async def _esperar_panel(self, abierto, timeout=10000):
        limite = time.monotonic() + timeout / 1000
        while True:
            panel = await self._panel_abierto()
            if (panel is not None) == abierto:
                return panel
            if time.monotonic() >= limite:
                accion = "abrió" if abierto else "cerró"
                raise RuntimeError(f"El filtro de tiendas de Rappi no se {accion}")
            await self.page.wait_for_timeout(100)

    async def _selector_tienda(self):
        botones = self.page.locator('[data-component="store-select"]')
        indices = await botones.evaluate_all(self.JS_PANELES_EN_PANTALLA)
        if len(indices) > 1:
            raise RuntimeError("Hay más de un selector de tienda de Rappi en pantalla")
        return botones.nth(indices[0]) if indices else None

    async def _nombre_tienda_actual(self):
        boton = await self._selector_tienda()
        return (' '.join((await boton.inner_text()).split())
                if boton is not None else None)

    async def _esperar_tienda_actual(self, nombre, timeout=15000):
        limite = time.monotonic() + timeout / 1000
        while True:
            if self.en_el_menu() and await self._nombre_tienda_actual() == nombre:
                return
            if time.monotonic() >= limite:
                raise RuntimeError("Rappi no confirmó la tienda en la URL y el selector visible")
            await self.page.wait_for_timeout(100)

    async def _abrir_filtro(self):
        panel = await self._panel_abierto()
        if panel is None:
            boton = await self._selector_tienda()
            if boton is None:
                raise RuntimeError("No hay un selector de tiendas de Rappi en pantalla")
            await boton.click(timeout=5000)
            panel = await self._esperar_panel(abierto=True)
        return panel

    async def _cerrar_filtro(self):
        panel = await self._panel_abierto()
        if panel is None:
            return
        boton = panel.get_by_role('button', name='Close', exact=True)
        if await boton.count() != 1:
            raise RuntimeError("No identifiqué un único botón para cerrar el filtro de Rappi")
        try:
            await boton.click(timeout=2000)
        except Exception:
            # Close solo descarta el panel. Su handler no necesita coordenadas;
            # evita bloquear 30 s por un layout que lo dejó fuera del viewport.
            await boton.evaluate("""el => {
                if (el.disabled || el.getAttribute('aria-disabled') === 'true')
                    throw new Error('El cierre del filtro está deshabilitado');
                el.click();
            }""", timeout=2000)
        await self._esperar_panel(abierto=False, timeout=5000)

    async def _lista_filtro(self, campo):
        panel = await self._abrir_filtro()
        boton = panel.get_by_text(campo, exact=True).locator(
            'xpath=following-sibling::button[1]')
        await boton.click()
        selector = ('[data-component="store-list"]:visible' if campo == "Tienda"
                    else '[data-component="dropdown-content"]:visible')
        lista = self.page.locator(selector)
        await lista.wait_for(state="visible", timeout=10000)
        return lista

    def _opcion_id(self, lista, ident):
        # El botón radio está dentro de pointer-events:none: clic en la fila.
        return lista.get_by_role('menuitemradio').filter(
            has=self.page.locator(f'button[role="radio"][value="{ident}"]'))

    async def _cerrar_lista_filtro(self):
        if await self.page.locator(
            '[data-component="dropdown-content"]:visible, '
            '[data-component="store-list"]:visible').count():
            await self.page.keyboard.press("Escape")

    async def _tienda_verificada(self):
        dato = getattr(self.page, '_todo_tienda', None)
        if not dato or dato['store_id'] != self.store_id or not self.en_el_menu():
            return False
        return await self._nombre_tienda_actual() == dato['nombre']

    async def _exigir_tienda(self):
        if self._portal_nuevo() and not await self._tienda_verificada():
            raise RuntimeError("Rappi cambió de tienda durante la operación; no se tocó el producto")

    async def ir_al_menu(self):
        await super().ir_al_menu()
        if self._portal_nuevo() and await self.page.locator(
                '[data-component="store-select"]').count():
            if not await self._tienda_verificada():
                await self._seleccionar_tienda()

    async def _seleccionar_tienda(self, forzar=False):
        if not self._portal_nuevo():
            return
        if not forzar and await self._tienda_verificada():
            return
        self.page._todo_tienda = None
        objetivo = self._id_filtro(self.store_id)
        try:
            marcas = await self._lista_filtro("Marca")
            seleccion_original = marcas.get_by_role('menuitemradio', checked=True)
            marca_original = (await seleccion_original.locator('button[role="radio"]').get_attribute('value')
                              if await seleccion_original.count() == 1 else None)
            valores = await marcas.locator('button[role="radio"]').evaluate_all(
                'els => els.map(e => e.value)')
            # Primero el brandId configurado para esta tienda. Si era el
            # compartido del portal viejo, buscar la tienda en las demás.
            preferida = self._id_filtro(self.brand_id_conectividad or self.brand_id)
            orden = sorted(dict.fromkeys(valores), key=lambda x: x != preferida)
            await self._cerrar_lista_filtro()
            nombre = None
            sin_cambio = False
            for marca in orden:
                if not re.fullmatch(r'\d+', marca):
                    continue
                marcas = await self._lista_filtro("Marca")
                opcion = self._opcion_id(marcas, marca)
                if await opcion.count() != 1:
                    raise RuntimeError("La marca de Rappi no es única")
                await opcion.click()
                await self._cerrar_lista_filtro()
                tiendas = await self._lista_filtro("Tienda")
                opcion = self._opcion_id(tiendas, objetivo)
                if await opcion.count() == 1:
                    nombre = ' '.join((await opcion.inner_text()).split())
                    sin_cambio = (marca == marca_original and self.en_el_menu()
                                  and await opcion.get_attribute('aria-checked') == 'true'
                                  and await self._nombre_tienda_actual() == nombre)
                    await opcion.click()
                    await self._cerrar_lista_filtro()
                    break
                if await opcion.count() > 1:
                    raise RuntimeError("El identificador de tienda aparece más de una vez")
                await self._cerrar_lista_filtro()
            if not nombre:
                raise RuntimeError("No encontré la tienda configurada en las marcas de Rappi")

            # Reabrir y comprobar el radio seleccionado antes de Aplicar.
            tiendas = await self._lista_filtro("Tienda")
            opcion = self._opcion_id(tiendas, objetivo)
            seleccionadas = tiendas.get_by_role('menuitemradio', checked=True)
            if (await opcion.count() != 1
                    or await opcion.get_attribute('aria-checked') != 'true'
                    or await seleccionadas.count() != 1):
                raise RuntimeError("Rappi no confirmó una única tienda seleccionada")
            await self._cerrar_lista_filtro()
            panel = await self._abrir_filtro()
            if sin_cambio:
                await self._cerrar_filtro()
            else:
                await panel.get_by_role('button', name='Aplicar filtro', exact=True).click()
            await self._esperar_panel(abierto=False, timeout=15000)
            if not sin_cambio:
                # Una URL/header nuevos pueden preceder a la respuesta de
                # productos. Recargar evita aceptar las filas de la tienda anterior.
                await self.page.reload(wait_until='domcontentloaded')
            await self._esperar_tienda_actual(nombre)
            await self.page.wait_for_selector(self.SELECTOR_TOGGLE_PRODUCTO, timeout=15000)
            self.page._todo_tienda = {'store_id': self.store_id, 'nombre': nombre}
        except Exception:
            self.page._todo_tienda = None
            # El cierre es limpieza: si falla, conservar el error de selección.
            log.exception("%s: falló la selección de tienda en Rappi", self.nombre)
            try:
                await self._cerrar_filtro()
            except Exception as cierre:
                log.warning("%s: tampoco pude cerrar el filtro: %s", self.nombre, cierre)
            raise
