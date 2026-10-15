"""Selección del Portal Aliados por ids observados en los radios del filtro.

Dos adaptadores comparten la misma Page y el worker serializa TODO acceso.
La marca se busca por las tiendas que realmente contiene; no se supone que
Turbo y Común compartan brandId. No se guardan ids/nombres de locales aquí.
"""
import re
from urllib.parse import urlsplit


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

    async def _abrir_filtro(self):
        panel = self._panel_tiendas()
        if not await panel.count():
            await self.page.locator('[data-component="store-select"]').click()
        await panel.wait_for(state="visible", timeout=10000)
        return panel

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
        selector = self.page.locator('[data-component="store-select"]')
        if await selector.count() != 1:
            return False
        return ' '.join((await selector.inner_text()).split()) == dato['nombre']

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
                                  and ' '.join((await self.page.locator(
                                      '[data-component="store-select"]').inner_text()).split()) == nombre)
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
                await panel.get_by_role('button', name='Close', exact=True).click()
            else:
                await panel.get_by_role('button', name='Aplicar filtro', exact=True).click()
            await panel.wait_for(state='hidden', timeout=15000)
            if not sin_cambio:
                # Una URL/header nuevos pueden preceder a la respuesta de
                # productos. Recargar evita aceptar las filas de la tienda anterior.
                await self.page.reload(wait_until='domcontentloaded')
            await self.page.wait_for_function(
                """d => { const u = new URL(location.href);
                    const b = document.querySelector('[data-component="store-select"]');
                    return u.pathname.replace(/\\/$/, '') === '/menu'
                      && u.searchParams.getAll('storeIds').length === 1
                      && u.searchParams.get('storeIds') === d.id
                      && b && b.innerText.replace(/\\s+/g,' ').trim() === d.nombre;
                }""", arg={'id': self.store_id, 'nombre': nombre}, timeout=15000)
            await self.page.wait_for_selector(self.SELECTOR_TOGGLE_PRODUCTO, timeout=15000)
            self.page._todo_tienda = {'store_id': self.store_id, 'nombre': nombre}
        except Exception:
            self.page._todo_tienda = None
            # No aplicar un filtro parcial ni dejar el panel tapando productos.
            panel = self._panel_tiendas()
            if await panel.count():
                await panel.get_by_role('button', name='Close', exact=True).click()
            raise
