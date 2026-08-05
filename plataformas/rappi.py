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
import time
from typing import Optional

from .base import PlataformaBase, ResultadoEstado, ResultadoTienda, plano

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

    # CONFIRMADO POR LOG (2026-08-03): cada opcion del dialogo es un
    # elemento con data-testid "menu-item-availability-switch-option-N"
    # dentro de un portal de floating-ui. El N es la POSICION, no dice cual
    # es cual: elegir por numero seria apagar "indefinido" cuando el usuario
    # pidio "solo por hoy". Se usa para ENCONTRAR las opciones; cual es cual
    # lo sigue diciendo el texto.
    SELECTOR_OPCION = '[data-testid*="availability-switch-option"]'

    # CONFIRMADO POR LOG (2026-08-03): el toggle fallaba SIEMPRE con
    # "<div data-testid='menu-categories-hoverable-gap-5'> intercepts
    # pointer events", incluso con el elemento centrado en pantalla. Es una
    # franja invisible de ayuda al hover del menu de categorias: no tiene
    # nada que clickear, solo se come el click del de abajo. Se le sacan
    # los pointer-events y el click normal entra (ver neutralizar_estorbos).
    #
    # A proposito NO entra aca el "collapsible-panel-header", que tambien
    # aparecio en el log: ese es un elemento de verdad (role="button"), y
    # desactivarlo seria romper la UI del portal.
    #
    # CONFIRMADO POR LOG (2026-08-05): la franja dejo de ser la que tapa y
    # aparecieron el <ul> de las categorias y el <div> de una categoria, que
    # son ANCESTROS del toggle. A un ancestro no se le pueden sacar los
    # clicks de una (pointer-events se hereda y el toggle se quedaria sin
    # ellos), pero si a sus pseudo-elementos, que es de donde sale el
    # estorbo: ::before/::after se reportan como el elemento que los
    # origina, que es justo lo que hacia que elementFromPoint contestara el
    # <ul>. Esto es la defensa barata; la general es el peldaño de
    # "destapar" de base.clickear().
    SELECTORES_ESTORBO = (
        '[data-testid^="menu-categories-hoverable-gap"]',
        'ul[data-testid="menu-categories"]::before',
        'ul[data-testid="menu-categories"]::after',
        'div[data-testid="menu-category"]::before',
        'div[data-testid="menu-category"]::after',
    )

    # Del nombre del producto se sube al primer ancestro que TAMBIEN tenga
    # el toggle: esa es la tarjeta. El data-testid del toggle trae el id de
    # producto del portal, asi que identifica la tarjeta sin ambiguedad
    # (ej: menu-category-101536-product-1148962-availability-switch-control).
    XPATH_TARJETA = ("xpath=ancestor::*"
                     "[.//*[contains(@data-testid,'availability-switch-control')]][1]")
    SELECTOR_ID_TARJETA = '[data-testid*="availability-switch-control"]'
    ATRIBUTO_ID_TARJETA = "data-testid"

    def __init__(self, page, store_id: str = None, brand_id: str = None,
                 nombre: str = None, nombre_tienda: str = None,
                 brand_id_conectividad: str = None):
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
        # columna "Tienda". Sirve de desempate si la URL directa (ver
        # leer_estado_tienda) igual muestra mas de una tarjeta.
        self.nombre_tienda = nombre_tienda or ""
        # CONFIRMADO EN VIVO (2026-07-30): Rappi Comun tiene su PROPIO
        # brandId, distinto del de Turbo (AR72021 contra AR75000 en la
        # cuenta de prueba) -- el supuesto "mismo brandId, otro storeId" de
        # mas abajo resulto ser falso para Conectividad. Esto NO toca
        # self.brand_id (el que usa url_menu para el menu de productos, que
        # ya viene andando en produccion); es solo para construir la URL de
        # Conectividad. Sin este ajuste, cae a self.brand_id.
        self.brand_id_conectividad = brand_id_conectividad or self.brand_id
        # Los textos de las opciones que vio el ultimo _opcion_del_dialogo().
        # Es lo que se muestra cuando no se pudo elegir ninguna.
        self.opciones_vistas: list[str] = []

    @property
    def configurado(self) -> bool:
        return bool(self.store_id and self.brand_id)

    def configurar(self, store_id: str = None, brand_id: str = None,
                   nombre_tienda: str = None, brand_id_conectividad: str = None):
        """Cambia de tienda/marca sin reiniciar la app (viene de Ajustes)."""
        if store_id and store_id != self.store_id:
            log.info("Rappi pasa a la tienda %s (antes %s)", store_id, self.store_id)
            self.store_id = store_id
        if brand_id and brand_id != self.brand_id:
            log.info("Rappi pasa a la marca %s (antes %s)", brand_id, self.brand_id)
            self.brand_id = brand_id
        if nombre_tienda is not None and nombre_tienda != self.nombre_tienda:
            self.nombre_tienda = nombre_tienda
        if brand_id_conectividad and brand_id_conectividad != self.brand_id_conectividad:
            self.brand_id_conectividad = brand_id_conectividad

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
        except Exception:
            return False

        # El menu ya esta: recien ahora existe la franja que se come los
        # clicks. Va aca y no en apagar()/prender() porque asegurar_sesion()
        # es lo que se rehace despues de cada recarga (base._confirmar) y en
        # cada _preparar, y el <style> no sobrevive a una navegacion.
        await self.neutralizar_estorbos()
        return True

    def _tarjeta(self, nombre_remoto: str):
        """Locator de la tarjeta del producto.

        TODO-SELECTOR: no tenemos el HTML completo de la tarjeta todavia.
        En vez de asumir una profundidad fija de ancestros, subimos desde
        el nombre exacto hasta el primer ancestro que TAMBIEN contenga el
        toggle de disponibilidad (data-testid confirmado). Asi evitamos
        depender de cuantos <div> hay entre el nombre y el resto de la
        tarjeta.
        """
        return self.texto_exacto(nombre_remoto).first.locator(self.XPATH_TARJETA)

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

    def _opciones_abiertas(self):
        """Las opciones del dialogo de disponibilidad que se estan viendo."""
        return self.visible(self.page.locator(self.SELECTOR_OPCION))

    def _dialogo_abierto(self):
        """El dialogo, este montado del todo o a medias.

        CONFIRMADO (2026-08-05): el CONTENEDOR del portal de floating-ui
        aparece antes que sus opciones —las monta ~1 s despues— y ya tapa la
        pantalla entera (position:fixed; inset:0). Mirando solo las opciones,
        cerrar_dialogo() contestaba "no hay nada que cerrar" con el portal
        adelante, y el click siguiente fallaba con "div.portal-flotante
        intercepts pointer events". Ese es medio camino andado del "se
        encadenan operaciones que fallan todas igual".
        """
        return self.visible(self.page.locator(
            f"{self.SELECTOR_OPCION}, [data-floating-ui-portal]"))

    # Cuantas veces mandar Escape antes de avisar que quedo algo abierto.
    INTENTOS_DE_CIERRE = 2

    async def cerrar_dialogo(self):
        """Cierra el dialogo de disponibilidad si quedo abierto.

        CONFIRMADO POR LOG (2026-08-03): cuando apagar() no encontraba la
        opcion, se iba dejando el dialogo ABIERTO. El intento 2 empezaba con
        ese popup adelante ("menu-item-availability-switch-option-3 ...
        intercepts pointer events"), asi que fallaba por una razon distinta
        de la primera, y el 3 igual. Los tres intentos del worker eran, en
        realidad, uno solo.

        Escape y nada mas: cerrar clickeando "Cancelar" seria clickear a
        ciegas en un dialogo que no sabemos como esta.
        """
        for _ in range(self.INTENTOS_DE_CIERRE):
            try:
                if await self._dialogo_abierto().count() == 0:
                    return
                await self.page.keyboard.press("Escape")
                await self.page.wait_for_timeout(500)
            except Exception:
                return

        try:
            if await self._dialogo_abierto().count() > 0:
                # No es fatal (el que llama sigue igual), pero si el click
                # siguiente falla "porque algo lo tapa", esta linea dice que.
                log.warning("%s: quedo un dialogo abierto que Escape no cerro",
                            self.nombre)
        except Exception:
            pass

    async def _opcion_del_dialogo(self, frase: str, timeout: int = 10000):
        """El elemento del dialogo que dice `frase`, o None.

        Dos caminos, y en este orden:

          1. El texto exacto visible. Es el que ya venia andando, y lo de
             "visible" no es un detalle: hay un elemento con el mismo texto
             ESCONDIDO en el DOM, y el `.first` de antes agarraba ese
             fantasma y se comia el timeout entero.

          2. Las opciones por su data-testid, comparando el texto SIN
             TILDES. Este es el que faltaba: el 2026-08-03 el dialogo se
             abria (el log lo muestra tapando el toggle del intento
             siguiente) y aun asi el paso 1 no encontraba nada, porque el
             texto del portal no es caracter por caracter el nuestro.

        Nunca elige por posicion: si el texto no identifica UNA sola
        opcion, devuelve None. Entre "solo por hoy" e "indefinidamente" no
        hay adivinanza posible que sea aceptable.
        """
        self.opciones_vistas: list[str] = []
        buscado = plano(frase)
        limite = time.monotonic() + timeout / 1000

        while True:
            exacto = self.visible(self.page.get_by_text(frase, exact=True))
            if await exacto.count() > 0:
                return exacto.first

            opciones = self._opciones_abiertas()
            cuantas = await opciones.count()
            if cuantas:
                textos = []
                for i in range(cuantas):
                    try:
                        textos.append(await opciones.nth(i).inner_text())
                    except Exception:
                        textos.append("")
                self.opciones_vistas = [" ".join(t.split()) for t in textos]

                iguales = [i for i, t in enumerate(textos) if buscado in plano(t)]
                if len(iguales) == 1:
                    return opciones.nth(iguales[0])
                if len(iguales) > 1:
                    log.error("%s: '%s' matchea %s opciones del dialogo (%s). "
                              "No elijo ninguna.", self.nombre, frase,
                              len(iguales), self.opciones_vistas)
                    return None

            if time.monotonic() >= limite:
                return None
            await self.page.wait_for_timeout(250)

    async def apagar(self, nombre_remoto: str, por_hoy: bool = True) -> bool:
        # Va ANTES de leer: con un nombre que llega a dos productos, la
        # lectura tampoco vale (leer_estado usa el mismo `.first`).
        await self.revisar_ambiguedad(nombre_remoto)
        estado = await self.leer_estado(nombre_remoto)
        if estado is None:
            return False
        if not estado.disponible:
            log.info("'%s' ya estaba apagado, no toco nada", nombre_remoto)
            return True

        # Un dialogo que quedo abierto de un intento anterior tapa el toggle
        # de este. Se cierra ANTES de tocar nada.
        await self.cerrar_dialogo()

        tarjeta = self._tarjeta(nombre_remoto)
        # profundo=True (regla 6, y el log del 2026-08-05 lo confirmo): el
        # handler que abre el popup de "hasta cuando" vive ADENTRO del
        # <label>, y los eventos suben pero no bajan. Con el click por JS
        # disparado en el label, prender andaba (lo dispara el `change` del
        # <input>, que la activacion nativa del label si propaga) y apagar
        # no abria nada nunca. profundo=True clickea el descendiente mas
        # profundo, asi que el evento sube por todos los niveles.
        click_real = await self.clickear(self._toggle_clickeable(tarjeta),
                                         que="toggle", profundo=True)

        # El dialogo ofrece 2 opciones utiles (la 3ra, "Personalizar
        # disponibilidad", no se usa: pide elegir una fecha).
        opcion = self.TXT_POR_HOY if por_hoy else self.TXT_INDEFINIDO
        radio = await self._opcion_del_dialogo(opcion)
        if radio is None:
            # Lo unico util no es "no encontre el texto" sino QUE decia el
            # dialogo que si se abrio: si el portal cambio el texto de la
            # opcion, esta linea lo dice y el arreglo es de una.
            log.error("No aparecio '%s' en el dialogo. Opciones que vi: %s. "
                      "Lo que hay abierto dice: %s. %s", opcion,
                      self.opciones_vistas or "(ninguna)",
                      await self.texto_overlay() or "(nada)",
                      await self._por_que_no_hubo_dialogo(tarjeta, click_real))
            await self.cerrar_dialogo()
            # El intento siguiente del worker viene a los 2 s: sin esto lo
            # hace contra el MISMO DOM que ya fallo, que es lo que convertia
            # los 3 intentos en uno solo repetido (log del 2026-08-05).
            await self.recargar_y_preparar(por_que=f"reintentar '{nombre_remoto}'")
            return False

        await self.clickear(radio, que=f"radio '{opcion}'")
        await self.page.wait_for_timeout(1000)

        # CONFIRMADO POR CAPTURA (2026-07-27): cualquiera de las 2 opciones
        # abre un segundo modal "¿Desactivar producto?" con botones
        # "Cancelar" y "Sí, desactivar" (rojo). Hay que confirmar ahi.
        if not await self._confirmar_en_el_modal():
            log.warning("%s: no encontre el boton de confirmar del modal. Lo "
                        "que hay abierto dice: %s", self.nombre,
                        await self.texto_overlay() or "(nada)")

        await self.page.wait_for_timeout(3000)
        ok = await self._confirmar(nombre_remoto, esperado_disponible=False)
        if not ok:
            # Si termino mal, que no arrastre el dialogo al proximo intento.
            # _confirmar() ya recargo, asi que la pagina esta limpia.
            await self.cerrar_dialogo()
        return ok

    async def _por_que_no_hubo_dialogo(self, tarjeta, click_real: bool) -> str:
        """Diagnostico para cuando el popup de disponibilidad no aparecio.

        "Opciones que vi: (ninguna). Lo que hay abierto dice: (nada)" no
        distingue los dos casos que tienen arreglos opuestos: que el click
        no haya entrado (hay que mirar el click) o que el portal haya
        cambiado los data-testid del popup (hay que mirar los selectores).
        Esto contesta cual de los dos es.
        """
        partes = ["el click sobre el toggle "
                  + ("fue real" if click_real else "tuvo que ir por JS")]

        # Opciones en el DOM SIN filtrar por visibilidad: si hay y no se ven,
        # el popup se abrio y el problema es otro.
        try:
            en_el_dom = await self.page.locator(self.SELECTOR_OPCION).count()
        except Exception:
            en_el_dom = "?"
        partes.append(f"opciones en el DOM (visibles o no): {en_el_dom}")

        # Si el toggle no se movio, el portal ni se entero del click.
        try:
            entrada = self._toggle_input(tarjeta)
            partes.append("el toggle quedo "
                          + ("prendido" if await entrada.is_checked() else "apagado"))
        except Exception:
            partes.append("no pude leer el toggle")

        return "; ".join(partes) + "."

    # Los textos del boton de confirmar, por orden de preferencia. Se
    # comparan sin tildes por lo mismo que las opciones: "Sí, desactivar" y
    # "Si, desactivar" se ven iguales y no son el mismo string.
    TXT_CONFIRMAR = ("Sí, desactivar", "Guardar", "Confirmar", "Aceptar", "Aplicar")

    async def _confirmar_en_el_modal(self) -> bool:
        botones = self.visible(self.page.get_by_role("button"))
        try:
            cuantos = await botones.count()
        except Exception:
            return False

        textos = []
        for i in range(cuantos):
            try:
                textos.append(plano(await botones.nth(i).inner_text()))
            except Exception:
                textos.append("")

        for txt in self.TXT_CONFIRMAR:
            for i, t in enumerate(textos):
                if plano(txt) in t:
                    await self.clickear(botones.nth(i), que=f"boton '{txt}'")
                    return True
        return False

    async def prender(self, nombre_remoto: str) -> bool:
        await self.revisar_ambiguedad(nombre_remoto)
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
        #
        # Igual se cierra lo que haya quedado abierto: un dialogo de otro
        # producto tapa este toggle lo mismo que tapaba el de apagar().
        await self.cerrar_dialogo()

        tarjeta = self._tarjeta(nombre_remoto)
        # Mismo profundo=True que en apagar(): aca el camino viejo andaba,
        # pero el toggle es el mismo elemento y no hay motivo para que los
        # dos lados usen fallbacks distintos.
        await self.clickear(self._toggle_clickeable(tarjeta), que="toggle",
                            profundo=True)
        await self.page.wait_for_timeout(2500)

        return await self._confirmar(nombre_remoto, esperado_disponible=True)

    # =====================================================================
    #  Estado de tienda via Conectividad (reactivado 2026-07-30, v2)
    # =====================================================================
    # El primer intento clickeaba el nav "Conectividad" y terminaba en
    # cualquier marca de la cuenta (ver commit anterior): el click no
    # respeta la marca de la pestaña actual. Esta version navega DIRECTO
    # por URL con el brandId y storeId de ESTA instancia (confirmado en
    # vivo que /home/real-time acepta brandId+storeIds+brandIds+storeId
    # igual que /menu), y ademas verifica que la navegacion se haya
    # quedado en nuestro storeId antes de leer nada: si el portal
    # redirige a otro lado, "no se" (None) en vez de leer una tienda
    # ajena.
    #
    # Con la URL apuntando a un solo storeId debería quedar UNA tarjeta;
    # nombre_tienda queda como desempate por si igual aparece mas de una.
    #
    # LA PANTALLA NO ES UNA TABLA (confirmado por DevTools del usuario,
    # 2026-07-30). La version anterior buscaba <td>Estado</td> + la celda
    # siguiente, leido de una captura, y encontraba CERO celdas siempre: por
    # eso las dos tiendas de Rappi decian "sin datos" mientras PedidosYa
    # andaba. El estado es un div suelto de styled-components:
    #
    #     <div class="sc-papXJ iobIXi rcf-typography-caption2 portal207"
    #          color="neutrals.grays.gray50"
    #          data-testid="test-typography">Cerrada</div>
    #
    # Las clases son generadas (sc-papXJ, iobIXi) y el data-testid es
    # generico: lo comparte TODO texto del portal, no es el estado. Lo unico
    # estable es el TEXTO, asi que se busca por texto (regla 2 de CLAUDE.md)
    # y se desempata por el nombre de la tienda.
    #
    # Estados vistos: "Activa", "Cerrada" (fuera de horario, normal) y
    # "Suspendida" (la corta Rappi, alerta real). Cualquier otro texto
    # devuelve None en vez de adivinar, y el diagnostico dice cual fue.
    ESTADOS_TIENDA_ABIERTA = {"activa"}
    ESTADOS_TIENDA_CERRADA = {"cerrada", "suspendida"}

    # Cuantas veces mirar antes de rendirse. La pantalla de Conectividad es
    # un SPA: el primer render puede no tener todavia el estado. Esperar un
    # rato fijo y decidir ahi es lo que ya nos mordio en _confirmar().
    INTENTOS_ESTADO_TIENDA = 5
    ESPERA_ENTRE_INTENTOS = 1500

    # Busca en el DOM los textos que son un estado de tienda, y para cada uno
    # el contexto (la tarjeta/fila donde vive) para poder desempatar por
    # nombre de tienda. Devuelve tambien una muestra de textos cortos de la
    # pantalla: si no reconocemos ningun estado, eso es lo unico que dice
    # como los escribe el portal de verdad.
    JS_ESTADOS_TIENDA = """
        ([estados, nombreTienda]) => {
            const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
            // Solo el texto PROPIO: si no, cada ancestro cuenta como otro
            // candidato y una tienda parece cinco.
            const propio = el => {
                let t = '';
                for (const n of el.childNodes) if (n.nodeType === 3) t += n.textContent;
                return norm(t);
            };

            const candidatos = [], muestra = [];
            for (const el of document.querySelectorAll('body *')) {
                const t = propio(el);
                if (!t) continue;
                if (t.length <= 40 && !muestra.includes(t)) muestra.push(t);
                if (!estados.includes(t.toLowerCase())) continue;

                // A cuantos niveles esta el nombre de la tienda. OJO: no
                // alcanza con "algun ancestro lo contiene". Subiendo lo
                // suficiente se llega al contenedor de TODAS las tarjetas, y
                // ahi el estado de la tienda B tambien "contiene" el nombre
                // de la A: con dos tiendas las dos daban positivo y no se
                // podia desempatar. Lo que distingue es la DISTANCIA — el
                // estado de una tarjeta tiene su propio nombre mas cerca —
                // asi que se guarda el nivel y decide el mas cercano.
                let contexto = '', nivel = null;
                for (let p = el, i = 0; p && i < 10; p = p.parentElement, i++) {
                    const texto = norm(p.innerText || p.textContent);
                    if (texto.length > 600) break;
                    contexto = texto;
                    if (nombreTienda && texto.includes(nombreTienda)) {
                        nivel = i;
                        break;
                    }
                }
                candidatos.push({texto: t, contexto: contexto.slice(0, 200),
                                 nivel: nivel});
            }
            return {candidatos: candidatos, muestra: muestra.slice(0, 60)};
        }
    """

    def _url_conectividad(self) -> str:
        marca = self.brand_id_conectividad
        return (
            f"https://partners.rappi.com/home/real-time"
            f"?brandId={marca}&storeIds={self.store_id}"
            f"&brandIds={marca}&storeId={self.store_id}"
        )

    async def _buscar_estado_en_pantalla(self) -> tuple[Optional[ResultadoTienda], dict]:
        """Lee el estado de la pantalla que ya esta abierta. No navega.

        Separado de leer_estado_tienda() a proposito: asi la parte que
        depende del DOM se puede probar contra una replica local sin portal
        ni login (pruebas/probar_rappi_conectividad.py), que es lo que
        faltaba cuando esto se escribio mirando una captura.

        Devuelve (resultado, diagnostico). El diagnostico es lo que se
        muestra cuando NO se pudo afirmar nada: sin eso, un "sin datos" no
        distingue "no encontre el texto" de "hay tres tiendas y no se cual
        sos", que son arreglos distintos.
        """
        estados = sorted(self.ESTADOS_TIENDA_ABIERTA | self.ESTADOS_TIENDA_CERRADA)

        hallazgo = {"candidatos": [], "muestra": []}
        for intento in range(self.INTENTOS_ESTADO_TIENDA):
            hallazgo = await self.page.evaluate(
                self.JS_ESTADOS_TIENDA, [estados, self.nombre_tienda or ""])
            if hallazgo["candidatos"]:
                break
            if intento < self.INTENTOS_ESTADO_TIENDA - 1:
                await self.page.wait_for_timeout(self.ESPERA_ENTRE_INTENTOS)

        candidatos = hallazgo["candidatos"]
        diag = {"url": self.page.url, "candidatos": len(candidatos)}

        if not candidatos:
            diag["motivo"] = ("no encontre ningun texto de estado conocido "
                              f"({', '.join(estados)}) en Conectividad")
            diag["textos_en_pantalla"] = hallazgo["muestra"]
            return None, diag

        elegido = None
        if len(candidatos) == 1:
            elegido = candidatos[0]
        else:
            # El mas cercano al nombre gana; si empatan dos, no se sabe.
            con_nombre = [c for c in candidatos if c["nivel"] is not None]
            cerca = min((c["nivel"] for c in con_nombre), default=None)
            propios = [c for c in con_nombre if c["nivel"] == cerca]
            if len(propios) == 1:
                elegido = propios[0]
            elif not self.nombre_tienda:
                # Adivinar cual de las tiendas de la cuenta sos es peor que
                # no decir nada: el badge quedaria afirmando el estado de
                # otro local.
                diag["motivo"] = (
                    f"la pantalla muestra {len(candidatos)} tiendas y no hay "
                    "nombre de tienda cargado en Ajustes para saber cual sos")
                diag["vistos"] = [c["texto"] for c in candidatos[:10]]
                return None, diag
            else:
                diag["motivo"] = (
                    f"'{self.nombre_tienda}' no identifica una sola tienda "
                    f"entre las {len(candidatos)} de la pantalla "
                    f"({len(propios)} coincidencias)")
                diag["contextos"] = [c["contexto"] for c in candidatos[:10]]
                return None, diag

        texto = elegido["texto"]
        diag["texto"] = texto
        t = texto.lower()
        if t in self.ESTADOS_TIENDA_ABIERTA:
            return ResultadoTienda(abierta=True, detalle=texto), diag
        if t in self.ESTADOS_TIENDA_CERRADA:
            return ResultadoTienda(abierta=False, detalle=texto), diag

        # No deberia pasar (el JS ya filtro por los conocidos), pero si el
        # dia de mañana se agranda la lista, no adivinar.
        diag["motivo"] = f"no se que significa el estado '{texto}'"
        return None, diag

    async def leer_estado_tienda(self) -> Optional[ResultadoTienda]:
        """Navega a Conectividad, lee el estado y vuelve al menu.

        El diagnostico de la ultima lectura queda en self.diagnostico_tienda
        (lo muestra /api/estado-tienda). No se levanta una excepcion ni se
        devuelve un estado inventado en ningun camino: si no se pudo
        confirmar, es None y el motivo explica cual de los pasos fallo.
        """
        self.diagnostico_tienda = {}

        if not self.brand_id_conectividad or not self.store_id:
            self.diagnostico_tienda = {
                "motivo": "faltan el brandId o el storeId de esta tienda en Ajustes"}
            return None

        try:
            await self.page.goto(self._url_conectividad(), wait_until="domcontentloaded")
            await self.page.wait_for_timeout(2500)

            # Si el portal nos mando a otro lado, no seguimos: mejor "no se"
            # que leer el estado de una tienda que no es la nuestra.
            if self.store_id not in self.page.url:
                log.warning("%s: la navegacion a Conectividad no se quedo en "
                            "la tienda configurada (termino en %s)",
                            self.nombre, self.page.url)
                self.diagnostico_tienda = {
                    "url": self.page.url,
                    "motivo": (f"Conectividad no se quedo en la tienda "
                               f"{self.store_id}: el brandId puede ser otro "
                               "(ver el ajuste de brandId en Conectividad)")}
                return None

            resultado, self.diagnostico_tienda = await self._buscar_estado_en_pantalla()
        except Exception as e:
            resumen = " ".join(str(e).split())[:120]
            log.warning("%s: no pude leer el estado de la tienda en "
                        "Conectividad: %s", self.nombre, resumen)
            self.diagnostico_tienda = {"motivo": f"error leyendo Conectividad: {resumen}"}
            return None
        finally:
            # Nos fuimos del menu a proposito: volvemos para que la proxima
            # lectura de productos no se encuentre en otra pantalla.
            await self.ir_al_menu()

        if resultado is None:
            log.info("%s: estado de tienda sin confirmar (%s)", self.nombre,
                     self.diagnostico_tienda.get("motivo", "sin motivo"))
        return resultado
