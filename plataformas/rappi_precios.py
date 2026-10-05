"""Beta de precios para Rappi. UI observada en capturas, sin API de escritura.

Los atributos del lápiz y del editor siguen pendientes de confirmar en vivo.
Se buscan controles semánticos y se exige unicidad antes de escribir. Nunca
se elige un botón por posición ni se toca un toggle de disponibilidad.
"""

import re
import time
from .precios import importe, serializar


class PreciosRappi:
    TIEMPO_GUARDAR_PRECIO = 8000
    JS_GUARDAR_PRECIO = r"""campo => {
      const normal = t => (t || '').replace(/\s+/g, ' ').trim();
      const visible = e => !!e.getClientRects().length &&
        !['hidden', 'collapse'].includes(getComputedStyle(e).visibility);
      // El formulario/modal del campo validado tiene prioridad sobre otros
      // Guardar de la página. El portal también usa una pantalla sin form.
      const raiz = campo.closest('form, [role="dialog"], main') || document.body;
      const selector = 'button, [role="button"], a, input[type="submit"], input[type="button"]';
      const esGuardar = e => normal(e.getAttribute('aria-label')) === 'Guardar' ||
        normal(e.matches('input') ? e.value : e.textContent) === 'Guardar';
      let candidatos = [...raiz.querySelectorAll(selector)].filter(e => visible(e) && esGuardar(e));
      // Algunos componentes dibujan un div clickeable sin role=button.
      // Texto exacto + cursor interactivo; nunca usar una posición ni un
      // contenedor con otros controles. Un span y su wrapper son uno solo.
      {
        const encontrados = new Set(candidatos);
        for (const texto of raiz.querySelectorAll('span, div, p')) {
          if (!visible(texto) || !esGuardar(texto) || texto.closest(selector)) continue;
          let control = texto;
          while (control.parentElement && control.parentElement !== raiz &&
                 esGuardar(control.parentElement)) control = control.parentElement;
          if (getComputedStyle(control).cursor === 'pointer' &&
              !control.querySelector('input, select, textarea, ' + selector)) encontrados.add(control);
        }
        candidatos = [...encontrados];
      }
      document.querySelectorAll('[data-todo-selector-guardar-precio]').forEach(
        e => e.removeAttribute('data-todo-selector-guardar-precio'));
      const habilitado = e => !e.matches(':disabled') &&
        !e.closest('[aria-disabled="true"], [inert]') && getComputedStyle(e).pointerEvents !== 'none';
      if (candidatos.length === 1 && habilitado(candidatos[0]))
        candidatos[0].setAttribute('data-todo-selector-guardar-precio', 'actual');
      return {cantidad: candidatos.length,
        listo: candidatos.length === 1 && habilitado(candidatos[0]),
        controles: candidatos.map(e => e.tagName.toLowerCase() +
          (habilitado(e) ? ' habilitado' : ' deshabilitado')).join(', ')};
    }"""

    async def _guardar_precio(self, campo, puede_tocar):
        limite = time.monotonic() + self.TIEMPO_GUARDAR_PRECIO / 1000
        while True:
            self._comprobar_precio(puede_tocar)
            estado = await campo.evaluate(self.JS_GUARDAR_PRECIO)
            if estado['listo']:
                return self.page.locator('[data-todo-selector-guardar-precio="actual"]')
            if estado['cantidad'] > 1 or time.monotonic() >= limite:
                raise ValueError('No pude identificar un único botón Guardar habilitado: '
                                 f"{estado['cantidad']} controles visibles"
                                 + (f" ({estado['controles']})" if estado['controles'] else ''))
            await self.page.wait_for_timeout(250)

    # Un footer puede contener Precio + toggle sin foto/nombre/lápiz.
    # Se exige identidad además del precio y un único control de producto.
    # Lectura y edición usan la MISMA delimitación para no volver a tomar
    # el footer al buscar el lápiz de una tarjeta ya identificada.
    JS_TARJETA_PRECIO = r"""control => {
      const selector = '[data-testid*="-product-"][data-testid*="availability-switch-control"]';
      const normal = t => (t || '').trim();
      const nombreValido = t => !!t && !/^(?:Precio\s*:?(?:\s|$)|\$|SKU\b|Apagados$|Sin toppings$)/i.test(t);
      for (let tarjeta = control && control.parentElement; tarjeta; tarjeta = tarjeta.parentElement) {
        if (tarjeta.querySelectorAll(selector).length !== 1) break;
        const texto = tarjeta.innerText || '';
        if (!/Precio\s*:?\s*\$/i.test(texto)) continue;
        const fotos = [...tarjeta.querySelectorAll('img[data-testid="catalog-item-image"]')];
        if (fotos.length > 1) return null;
        if (fotos.length === 1) {
          const nombre = normal(fotos[0].alt);
          if (nombreValido(nombre)) return {tarjeta, nombre};
        }
        // Sin foto, el rótulo SKU del encabezado relaciona el nombre con
        // este producto. Un bloque con solo Precio nunca aporta identidad.
        const lineas = texto.split(/\n/).map(normal).filter(Boolean);
        const nombres = new Set();
        for (let i=0; i<lineas.length; i++) {
          const junto = lineas[i].match(/^(.+?)\s+SKU\b/);
          const nombre = junto ? normal(junto[1])
            : /^SKU\b/.test(lineas[i]) && i>0 ? lineas[i-1] : '';
          if (nombreValido(nombre)) nombres.add(nombre);
        }
        if (nombres.size === 1) return {tarjeta, nombre: [...nombres][0]};
        if (nombres.size > 1) return null;
      }
      return null;
    }"""

    JS_CARTA_PRECIOS = r"""() => {
      const ubicar = """ + JS_TARJETA_PRECIO + r""";
      const controles = [...document.querySelectorAll(
        '[data-testid*="-product-"][data-testid*="availability-switch-control"]')];
      return controles.map(control => {
        const hallazgo = ubicar(control);
        if (!hallazgo)
          return {nombre: '', id_remoto: control.dataset.testid,
            error: 'No pude identificar el nombre dentro de la tarjeta del producto'};
        const {tarjeta, nombre} = hallazgo;
        const texto = tarjeta.innerText || '';
        const precios = [...texto.matchAll(/Precio\s*:?\s*(\$\s*[\d.,]+)/gi)];
        return {nombre, id_remoto: control.dataset.testid,
          precio_texto: precios.length === 1 ? precios[0][1] : null,
          error: precios.length === 1 ? '' : 'No pude identificar un único precio'};
      });
    }"""

    JS_MARCAR_TARJETA_PRECIO = r"""id => {
      const ubicar = """ + JS_TARJETA_PRECIO + r""";
      const controles = [...document.querySelectorAll(
        '[data-testid*="-product-"][data-testid*="availability-switch-control"]')]
        .filter(e => e.dataset.testid === id);
      if (controles.length !== 1) return null;
      const hallazgo = ubicar(controles[0]);
      if (!hallazgo) return null;
      document.querySelectorAll('[data-todo-selector-tarjeta-precio]').forEach(
        e => e.removeAttribute('data-todo-selector-tarjeta-precio'));
      hallazgo.tarjeta.setAttribute('data-todo-selector-tarjeta-precio', 'actual');
      return hallazgo.nombre;
    }"""

    @staticmethod
    def _comprobar_precio(puede_tocar):
        if not puede_tocar():
            raise ValueError("La tienda cambió o está en verificación manual; se detuvo la edición")

    async def abrir_categorias_precios(self, puede_tocar=lambda: True):
        self._comprobar_precio(puede_tocar)
        # Reutiliza el atributo de expansión observado en el DOM de Rappi.
        # Abrir las categorías evita ofrecer como carta entera solo la primera.
        headers = self.page.locator('[data-testid="collapsible-panel-header"][aria-expanded="false"]')
        for _ in range(100):
            antes = await headers.count()
            if not antes:
                break
            self._comprobar_precio(puede_tocar)
            await self.clickear(headers.first, que="abrir categoría para leer precios")
            await self.page.wait_for_function("""antes => document.querySelectorAll(
              '[data-testid="collapsible-panel-header"][aria-expanded="false"]').length < antes""",
              arg=antes,
              timeout=10000)
        if await headers.count():
            raise ValueError("No se pudieron abrir todas las categorías")

    async def listar_precios(self, puede_tocar=lambda: True):
        self._comprobar_precio(puede_tocar)
        await self.ir_al_menu()
        await self.abrir_categorias_precios(puede_tocar)
        self._comprobar_precio(puede_tocar)
        filas = await self.page.evaluate(self.JS_CARTA_PRECIOS)
        for fila in filas:
            fila["precio"] = None
            if fila.get("precio_texto"):
                try:
                    fila["precio"] = serializar(importe(fila["precio_texto"], portal=True))
                except ValueError as e:
                    fila["error"] = str(e)
        nombres = [f["nombre"] for f in filas]
        for fila in filas:
            if fila["nombre"] and nombres.count(fila["nombre"]) != 1:
                fila["error"] = "Nombre repetido; no se puede editar con seguridad"
            elif not fila["nombre"] and not fila["error"]:
                fila["error"] = "No se pudo leer el nombre del producto"
        return filas

    async def leer_precio(self, nombre_remoto, id_remoto=None, puede_tocar=lambda: True):
        filas = [f for f in await self.listar_precios(puede_tocar) if f["nombre"] == nombre_remoto]
        if len(filas) != 1 or filas[0]["error"]:
            raise ValueError("No pude identificar un único producto y precio: " + nombre_remoto)
        fila = filas[0]
        if id_remoto is not None and fila["id_remoto"] != id_remoto:
            raise ValueError("Cambió el producto del portal; volvé a leer la carta")
        return importe(fila["precio"])

    async def _lapiz_precio(self, tarjeta):
        semanticos = self.visible(tarjeta.get_by_role(
            "button", name=re.compile(r"editar|edit|l[aá]piz|pencil", re.I)))
        if await semanticos.count() == 1:
            return semanticos
        # TODO-SELECTOR: captura = un único botón de icono a la derecha del
        # toggle. Se admite SOLO un botón SVG sin texto fuera del control.
        botones = self.visible(tarjeta.locator('button, a, [role="button"]'))
        candidatos = []
        for i in range(await botones.count()):
            boton = botones.nth(i)
            es_icono = await boton.evaluate("""e => !e.closest(
              '[data-testid*="availability-switch-control"]') &&
              !e.matches('[role="switch"], [aria-checked]') &&
              !e.querySelector('input, [data-testid*="availability-switch-control"]') &&
              !!e.querySelector('svg') && !(e.textContent || '').trim()""")
            if es_icono:
                candidatos.append(boton)
        if await semanticos.count() == 0 and len(candidatos) == 1:
            return candidatos[0]
        raise ValueError("No pude identificar un único lápiz para este producto")

    async def _campo_editor(self, nombre):
        campos = self.visible(self.page.get_by_label(re.compile(r"^" + nombre + r"\s*\*?$", re.I)))
        if await campos.count() == 1:
            return campos
        # TODO-SELECTOR: los labels de la captura pueden ser texto flotante
        # sin for. Relacionamos texto EXACTO y un único input en su contenedor.
        ids = await self.page.evaluate(r"""nombre => {
          const normal = t => (t || '').trim().replace(/\*$/, '').trim().toLowerCase();
          const vistos = new Set();
          for (const el of document.querySelectorAll('label, span, div, p')) {
            if (el.children.length || normal(el.textContent) !== nombre.toLowerCase()) continue;
            let p = el.parentElement;
            for (let i=0; p && i<3; i++, p=p.parentElement) {
              const inputs = [...p.querySelectorAll('input')].filter(e => e.getClientRects().length);
              if (inputs.length === 1) { vistos.add(inputs[0]); break; }
              if (inputs.length > 1) break;
            }
          }
          const lista = [...vistos];
          if (lista.length === 1) lista[0].setAttribute('data-todo-selector-campo', nombre);
          return lista.length;
        }""", nombre)
        if ids != 1:
            raise ValueError("No pude identificar el campo " + nombre)
        return self.page.locator('[data-todo-selector-campo="' + nombre + '"]')

    async def volver_del_editor_precio(self, puede_tocar=lambda: True):
        self._comprobar_precio(puede_tocar)
        if await self.page.get_by_text("Editar producto", exact=True).count():
            # El editor observado conserva /menu en la URL. ir_al_menu()
            # solo miraría la URL y dejaría el formulario abierto.
            await self.page.goto(self.url_menu, wait_until="domcontentloaded")
        else:
            await self.ir_al_menu()

    async def cambiar_precio(self, nombre_remoto, esperado, nuevo, id_remoto,
                             puede_tocar=lambda: True):
        def comprobar():
            if not puede_tocar():
                raise ValueError("Verificación manual en curso; se detuvo la edición")

        comprobar()
        actual = await self.leer_precio(nombre_remoto, id_remoto, puede_tocar)
        if actual != esperado:
            raise ValueError("El precio cambió desde la vista previa; volvé a leer la carta")
        await self.revisar_ambiguedad(nombre_remoto)
        # Delimita la MISMA tarjeta por el id leído, sin profundidad fija.
        # No se usa el padre del nombre si el lápiz quedó en otro wrapper.
        encontrado = await self.page.evaluate(self.JS_MARCAR_TARJETA_PRECIO, id_remoto)
        if encontrado != nombre_remoto:
            raise ValueError("No se pudo delimitar la tarjeta para editar")
        tarjeta = self.page.locator('[data-todo-selector-tarjeta-precio="actual"]')
        lapiz = await self._lapiz_precio(tarjeta)
        comprobar()
        await self.clickear(lapiz, que="lápiz de precio")
        await self.page.get_by_text("Editar producto", exact=True).wait_for(timeout=15000)
        campo_nombre = await self._campo_editor("Nombre")
        if (await campo_nombre.input_value()).strip() != nombre_remoto:
            raise ValueError("El editor abrió otro producto; no se guardó")
        campo = await self._campo_editor("Precio")
        if importe(await campo.input_value(), portal=True) != esperado:
            raise ValueError("El editor muestra otro precio; no se guardó")
        comprobar()
        await campo.fill(serializar(nuevo))
        comprobar()
        await campo.press("Tab")
        if importe(await campo.input_value(), portal=True) != nuevo:
            raise ValueError("El campo no aceptó el precio solicitado")
        guardar = await self._guardar_precio(campo, puede_tocar)
        comprobar()
        await self.clickear(guardar, que="Guardar precio")
        # Espera la salida del editor para no interrumpir un guardado lento.
        try:
            await self.page.locator(self.SELECTOR_TOGGLE_PRODUCTO).first.wait_for(state="attached", timeout=20000)
        except Exception:
            # Puede seguir en el editor; la confirmación siempre lee una
            # página recargada, y nunca vuelve a guardar ni sumar el aumento.
            pass
        for _ in range(3):
            comprobar()
            if await self.en_verificacion():
                raise ValueError("Rappi pidió verificación; no se pudo confirmar el precio")
            await self.page.reload(wait_until="domcontentloaded")
            comprobar()
            if await self.en_verificacion():
                raise ValueError("Rappi pidió verificación; no se pudo confirmar el precio")
            await self.abrir_categorias_precios(puede_tocar)
            comprobar()
            if not await self.asegurar_sesion():
                raise ValueError("No se pudo preparar el menú para verificar el precio")
            if await self.leer_precio(nombre_remoto, id_remoto, puede_tocar) == nuevo:
                return True
        return False
