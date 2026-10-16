"""Lectura de Gestión de tiendas del Portal Aliados; nunca pulsa toggles."""
import logging
import time
from urllib.parse import parse_qs, urlencode, urlsplit

from .base import ResultadoTienda

log = logging.getLogger('rappi')


class EstadoTiendaPortalRappi:
    JS_TABLA_ESTADOS = r'''nombre => {
      const texto = el => (el?.textContent || '').replace(/\s+/g, ' ').trim();
      const visible = el => {
        const s = getComputedStyle(el);
        return s.display !== 'none' && s.visibility !== 'hidden' &&
          !el.closest('[hidden], [aria-hidden="true"]');
      };
      const tablas = [...document.querySelectorAll('table[data-slot="table-content"]')]
        .filter(visible).filter(t => {
          const h = [...t.querySelectorAll('thead th')].map(texto);
          return h[0] === 'Nombre tienda' && h[1] === 'Estado';
        });
      if (tablas.length !== 1) return {motivo:'No hay una única tabla de Gestión de tiendas', tablas:tablas.length};
      const filas = [...tablas[0].querySelectorAll('tbody > tr')].filter(visible);
      const coinciden = filas.filter(f => texto(f.querySelector('td')) === nombre);
      if (coinciden.length !== 1) return {
        motivo:'El nombre de tienda no identifica una única fila', coincidencias:coinciden.length,
        tiendas:filas.map(f => texto(f.querySelector('td')))
      };
      const celdas = coinciden[0].querySelectorAll('td');
      const badges = celdas[1]?.querySelectorAll('[data-slot="badge"]') || [];
      const inputs = celdas[2]?.querySelectorAll('label[data-component="Toggle"] input[type="checkbox"]') || [];
      if (badges.length !== 1 || inputs.length !== 1) return {motivo:'Estado o toggle de tienda ambiguo'};
      const badge = texto(badges[0]), checked = inputs[0].checked;
      const esperado = badge === 'Activo' ? true : badge === 'Inactivo' ? false : null;
      if (esperado === null || typeof checked !== 'boolean' || checked !== esperado)
        return {motivo:'El estado y el toggle no confirman la misma disponibilidad', badge, checked};
      return {abierta:checked, badge, observaciones:texto(celdas[3]), nombre};
    }'''

    def _en_gestion_tienda(self):
        url = urlsplit(self.page.url)
        ids = parse_qs(url.query).get('storeIds', [])
        return (url.scheme == 'https' and url.hostname == 'restaurantes.rappi.com'
                and url.path.rstrip('/') == '/stores' and ids == [self.store_id])

    async def _leer_estado_tienda_nuevo(self):
        cache = getattr(self.page, '_todo_tienda', None)
        nombre = (cache['nombre'] if cache and cache['store_id'] == self.store_id
                  else self.nombre_tienda)
        if not nombre:
            self.diagnostico_tienda = {'motivo':'No se confirmó el nombre de esta tienda en el menú'}
            return None
        if await self.en_verificacion():
            self.diagnostico_tienda = {'motivo':'Rappi está en verificación; se conserva la pantalla'}
            return None
        resultado = None
        try:
            url = 'https://restaurantes.rappi.com/stores?' + urlencode({'storeIds':self.store_id})
            await self.page.goto(url, wait_until='domcontentloaded')
            limite = time.monotonic() + 15
            while True:
                if not self._en_gestion_tienda():
                    self.diagnostico_tienda = {'motivo':'Gestión de tiendas redirigió fuera de la tienda solicitada', 'url':self.page.url}
                    break
                dato = await self.page.evaluate(self.JS_TABLA_ESTADOS, ' '.join(nombre.split()))
                if isinstance(dato.get('abierta'), bool):
                    detalle = ' · '.join(t for t in (dato['badge'], dato.get('observaciones')) if t)
                    resultado = ResultadoTienda(abierta=dato['abierta'], detalle=detalle)
                    self.diagnostico_tienda = {}
                    break
                self.diagnostico_tienda = dato
                if dato.get('coincidencias', 0) > 1 or time.monotonic() >= limite:
                    break
                await self.page.wait_for_timeout(200)
        except Exception as e:
            self.diagnostico_tienda = {'motivo':f'Error leyendo Gestión de tiendas: {str(e)[:160]}'}
            log.warning('%s: %s', self.nombre, self.diagnostico_tienda['motivo'])
        finally:
            # No invalidar un código de verificación que apareció al navegar.
            if not await self.en_verificacion():
                try:
                    await self.ir_al_menu()
                except Exception as e:
                    log.warning('%s: no pude volver al menú tras leer la tienda: %s', self.nombre, e)
        return resultado
