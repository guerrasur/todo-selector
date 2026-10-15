"""Lectura de diagnóstico del DOM de Portal Aliados, sin tocar productos."""


class CartaRappi:
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
