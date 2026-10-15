"""Lectura de diagnóstico del DOM de Portal Aliados, sin tocar productos."""


class CartaRappi:
    # HTML confirmado: el título usa aria-expanded y span.font-body-medium.
    # Los switches y el menú more también tienen aria-expanded: excluirlos.
    SELECTOR_CATEGORIA_CARTA = (
        'button[aria-expanded]:not([role="switch"]):not([aria-haspopup])'
        ':has(> div > span.font-body-medium)')
    JS_CATEGORIAS_CARTA = r"""selector => [...document.querySelectorAll(selector)].map(b => ({
      nombre: b.querySelector('span.font-body-medium').textContent.trim(),
      abierta: b.getAttribute('aria-expanded') === 'true'
    }))"""

    async def _categorias_carta_nueva(self):
        return await self.page.evaluate(self.JS_CATEGORIAS_CARTA, self.SELECTOR_CATEGORIA_CARTA)

    async def _abrir_categorias_carta_nueva(self):
        """Desplegar títulos; nunca pulsar disponibilidad de la categoría."""
        await self._exigir_tienda()
        if not await self.page.locator(self.SELECTOR_CATEGORIA_CARTA).count():
            raise RuntimeError('No encontré encabezados de categorías del nuevo menú')
        cerradas = self.page.locator(self.SELECTOR_CATEGORIA_CARTA + '[aria-expanded="false"]')
        for _ in range(100):
            antes = await cerradas.count()
            if not antes:
                return await self._categorias_carta_nueva()
            await self._exigir_tienda()
            # Clic normal y acotado: si no cambia el estado, detenerse.
            await cerradas.first.click(timeout=5000)
            await self.page.wait_for_function(
                "({selector, antes}) => document.querySelectorAll(selector).length < antes",
                arg={'selector': self.SELECTOR_CATEGORIA_CARTA + '[aria-expanded="false"]',
                     'antes': antes}, timeout=5000)
            await self.page.wait_for_timeout(500)
        raise RuntimeError('No se pudieron desplegar todas las categorías de Rappi')

    JS_CAPTURAR_CARTA = r"""() => {
      const SWITCH = '[data-component="menu-item-availability-switch"] button[role="switch"]';
      const nombres = [...document.querySelectorAll('p.font-body-medium')].filter(
        p => !p.closest('[data-component="menu-product-description"], [data-component="menu-product-tags"]'));
      const filas = [], vistas = new Set();
      for (const p of nombres) {
        const nombre = (p.textContent || '').trim();
        if (!nombre) continue;
        let fila = p.parentElement;
        while (fila && fila !== document.body) {
          const toggles = fila.querySelectorAll(SWITCH);
          if (toggles.length > 1) break;
          if (toggles.length === 1 && fila.querySelector('button[aria-label="Editar"]')) {
            const titulos = [...fila.querySelectorAll('p.font-body-medium')].filter(
              n => !n.closest('[data-component="menu-product-description"], [data-component="menu-product-tags"]'));
            if (titulos.length !== 1 || vistas.has(fila)) break;
            vistas.add(fila);
            const aria = toggles[0].getAttribute('aria-checked');
            filas.push({nombre, aria,
              disponible: aria === 'true' ? true : aria === 'false' ? false : null});
            break;
          }
          fila = fila.parentElement;
        }
      }
      return {nombres_dom: nombres.map(p => (p.textContent || '').trim()),
              switches_dom: document.querySelectorAll(SWITCH).length, filas};
    }"""

    async def _capturar_carta_nueva(self):
        self._diagnostico_dom = await self.page.evaluate(self.JS_CAPTURAR_CARTA)
        return self._diagnostico_dom['filas']
