# Todo-Selector — traspaso de sesión (2026-07-28)

Pegá esto al arrancar la sesión nueva. Es todo lo que costó averiguar.

**Repo:** `guerrasur/todo-selector` (público) · todo mergeado a `main` hasta el
PR #19.

App local (FastAPI + Playwright) que apaga/prende productos en PedidosYa y
Rappi desde una pantalla. Corre en `127.0.0.1:8001`.

---

## Estado: EN USO, andando en el local

Las cuatro operaciones corren en vivo contra los dos portales. Confirmado en
el log del usuario del 2026-07-28 13:24: las dos sesiones OK, lectura inicial
de las dos cartas, y dos `prender` seguidos que terminaron en OK.

| | leer la carta | apagar | prender |
|---|---|---|---|
| **PedidosYa** | ✅ 29 productos, 3 categorías | ✅ | ✅ (op#17, op#63) |
| **Rappi** | ✅ 45 productos | ✅ | ✅ (op#18, op#64) |

Queda un `TODO-SELECTOR` en `plataformas/rappi.py`: el HTML completo de la
tarjeta y el selector de la pantalla de sesión expirada.

## Cómo se trabaja

- El usuario corre `iniciar_app.bat` en Windows. **Actualiza los archivos ANTES
  de levantar el server**: si deja la ventana abierta mientras se mergea, sigue
  con el código viejo. Verificar con `arrancado_en` en `/api/estado-sistema`.
- El auto-update baja de `main`: **hay que mergear a main** para que pueda
  probar. Se viene haciendo PR + merge en cada tanda.
- El entorno de desarrollo es Linux: **no se pueden correr el `.bat` ni el
  `.ps1`**. Sí se puede Playwright con
  `/opt/pw-browsers/chromium-1194/chrome-linux/chrome` (`executable_path=`).
- **Correr las pruebas antes de tocar nada.** Cubren casi todo sin navegador.
- Las pruebas con navegador levantan un server en un puerto fijo (8777, 8788):
  **no correr dos a la vez** ni dejar una colgada, o la siguiente falla con
  `Address already in use` y hay que esperar el TIME_WAIT.

## Las pruebas — usalas, valen oro

```
py pruebas/probar_pedidosya.py        selectores y clicks, contra una réplica
py pruebas/probar_catalogo.py         vincular / separar / deshacer / migración
py pruebas/probar_estados.py          cómo se guarda el estado leído del portal
py pruebas/probar_cierre.py           apagar todo por plataforma + ajustes
py pruebas/probar_pantalla_carta.py   la app entera en modo simulado
```

`pruebas/portal_pedidosya.html` replica el DOM real. Acepta
`?popup=cerrable|pegado` y `?handler=hijo|host`.

En modo simulado `/api/carta` devuelve `pruebas/carta_2026-07-27.json`, que es
la lectura **real** de los dos portales.

---

## Lo que se construyó en esta sesión (PR #19)

**Apagar todo, por plataforma** (`app/cierre.py`). Un juego de botones por
portal: PedidosYa, Rappi, los dos. Separados porque *"a veces PedidosYa tengo
que apagarlo antes que Rappi"*. No encola lo que ya está como quiere quedar,
lo pausado, ni lo que ya está en la cola; por defecto relee el portal antes.

**Ajustes** (`app/config.py`). 13 opciones en la tabla `preferencias` con
prefijo `cfg_`. Incluye **qué sucursal es** (id de menú de PedidosYa, storeId
y brandId de Rappi), que estaban clavados en el código. Todos los defaults son
lo que la app venía haciendo: una base sin ajustes se comporta igual que antes.

**`/api/alertas`**: lo que la app da por apagado y **no puede confirmar**.

**Arreglos:** el chip de plataforma se deseleccionaba solo con el repintado; la
operación que agarraba la sesión caída se moría en 6 segundos; doble click
duplicaba la cola; el worker trababa la cola si el producto había sido
absorbido por un vincular; `estado leído HH:MM` se sellaba aunque la lectura
hubiera fallado entera; y el log de uvicorn tapaba todo con el repintado.

---

## Trampas que ya costaron caro — NO repetirlas

1. **PedidosYa, el toggle.** El `<input>` tiene `cdk-visually-hidden`.
   Clickearlo tarda 30.0s exactos y falla. Hay que clickear
   `span.mat-slide-toggle-bar`.
2. **Un click por JS sobre un custom element puede no hacer nada.** El listener
   vive en un hijo y los eventos suben, no bajan. Para eso está
   `clickear(..., profundo=True)`. Confirmado otra vez en el log del 28:
   *"La categoria #1 no reacciono al click por JS; reintento sobre el hijo"* →
   *"por JS sobre `<div>`: cambio la lista"*.
3. **Después de recargar hay que rehacer la preparación.** El popup de sonido
   vuelve en cada carga y su backdrop se come los clicks. `_confirmar()` llama
   a `asegurar_sesion()`.
4. **Los nombres se buscan con `exact=True`.** Una tilde y no encuentra nada.
5. **Cuidado con los prefijos.** "Wrap caesar" vs "Wrap caesar con batatas".
6. **`con` y `sin` NO son ruido** en el emparejador.
7. **Una pestaña por plataforma, con `asyncio.Lock`.**
8. **Falso "revivió" es caro**: reencola un apagado que *prende* el producto.
   Por eso hay una segunda lectura de confirmación antes de acusar.
9. **La pantalla no se puede cachear.** `index.html` va con `no-store`.
10. **El `.bat` necesita CRLF** (`.gitattributes` con `*.bat -text`).
11. **El identity map de SQLAlchemy resucita lo borrado.** En `deshacer()`,
    `expunge_all()`.
12. **Nada que el usuario haya elegido puede vivir en una variable local del
    repintado.** La lista se repinta cada 3 s y se lo lleva puesto, sin que se
    note. Pasó con los chips de plataforma: volvían a quedar los dos puestos y
    la acción salía a los dos portales. Ver `excluidas` en `index.html`.
13. **No afirmar lo que no se está viendo.** Ver abajo.

## Datos del DOM confirmados

- **PedidosYa:** fila = `label.mat-slide-toggle-label`; estado = `aria-checked`
  del input; categorías = `wk-menu-list wk-menu-list-category-item` (el
  `wk-menu-list` importa). Popup: `Unavailable for today` /
  `Unavailable indefinitely` — **el portal está en inglés**. Prender NO abre
  popup.
- **Rappi:** toggle = `label[data-testid*="availability-switch-control"]`.
  Nombres = `alt` de `img[data-testid="catalog-item-image"]`. Estado = badge
  "Apagados" o `is_checked()`. Diálogos de apagado: radio "Sólo por hoy" →
  modal "¿Desactivar producto?" → botón "Sí, desactivar". Prender NO abre nada.
- **Rappi reescribe la URL** con los storeIds de las cinco tiendas, así que
  `en_el_menu()` compara por partes y no el string entero.

---

## LO QUE HAY QUE MIRAR PRIMERO: el pedido de algo apagado

**2026-07-28.** El usuario apagó un wrap, Todo-Selector lo mostró como
`apagado`, y **media hora después entró un pedido de PedidosYa con ese wrap**.
Es el peor fallo posible de esta app.

**Mecanismo identificado y tapado:** si la lectura de la carta no encuentra un
producto, la app *no pisa* el estado que tenía (correcto: una lectura mala no
puede borrar lo que sabíamos), pero el `apagado` viejo quedaba **congelado** y
la pantalla lo seguía afirmando en presente. Ahora `_guardar_estados()`
devuelve `no_encontrados`, y `/api/alertas` lo cruza con lo que la app da por
apagado: sale un cartel rojo con el nombre exacto que estaba buscando.

**PERO la causa raíz NO está confirmada.** En el log del 28 los dos portales
dieron **`0 del catalogo no aparecieron`**, así que en ese momento no había
ningún producto invisible para la app. O sea: el camino que tapamos existe y
era real, pero puede no ser el que causó *ese* pedido.

Hipótesis que quedan abiertas, en orden:

1. **Era `apagado (afuera)` y no `apagado por hoy`.** La app **no sostiene**
   `APAGADO_AJENO` a propósito (`_guardar_estados`, `sostener`): si el portal
   lo revive, la ronda actualiza la pantalla pero no lo vuelve a apagar. Si el
   usuario lo apagó desde el portal y no desde la app, esto explica todo.
   **Cómo confirmarlo:** preguntarle si lo apagó desde Todo-Selector o desde
   PedidosYa, y qué decía el chip exactamente (`apagado hoy` vs
   `apagado (afuera)`).
2. **El "apagado por hoy" de PedidosYa venció.** `Unavailable for today` lo
   revive el portal solo. Si el apagado era de la noche anterior, a la mañana
   está prendido: la ronda lo detecta y lo reencola, pero hay una ventana.
3. **La ronda no corrió** (app recién arrancada, o la ventana del `.bat`
   cerrada).

**Lo más útil que puede hacer la próxima sesión:** que la reverificación quede
registrada en algún lado que el usuario pueda mirar después. Hoy si la ronda
detecta un revivido lo dice en el log de la consola y lo reencola, pero si el
usuario cerró la ventana no queda rastro. `/api/historial` ya guarda las
operaciones con su `detalle`; falta mostrarlo en pantalla (pendiente viejo).

---

## Rendimiento medido en el log del 2026-07-28

Con los tiempos reales de dos operaciones seguidas:

| | op#63 prender (PedidosYa) | op#64 prender (Rappi) |
|---|---|---|
| duración total | **30 s** | **18 s** |
| de eso, click fallado | 10 s | 8 s |

**El click normal sobre el toggle falla SIEMPRE y va por el fallback JS**, en
los dos portales. Son 8-10 segundos tirados por operación. Esto ya estaba
anotado como pendiente, pero **ahora importa mucho más**: con "Apagar todo"
son ~26 productos por portal, o sea **~13 minutos** para PedidosYa, de los
cuales ~4 son puro timeout.

**Pista nueva del log**, que antes no teníamos:

```
click normal sobre toggle fallo (Locator.click: Timeout 10000ms exceeded.
Call log: - waiting for get_by_text("Caesar", exact=True).first.locat...)
```

El timeout es **esperando que el locator resuelva**, no "element is covered by
another element" ni "not enabled". Eso apunta a que `get_by_text(...).first`
está agarrando un elemento que **no es visible** (PedidosYa deja en el DOM
elementos de categorías cerradas), y Playwright espera a que se vuelva
accionable hasta agotar el timeout. El click por JS después funciona porque no
mira visibilidad — pero eso significa que **puede estar clickeando el elemento
equivocado**, y eso es exactamente el tipo de cosa que produce un "apagué X y
se apagó Y".

**Cómo investigarlo sin adivinar:** con la app corriendo,
`/api/diagnostico?plataforma=pedidosya&nombre=Caesar` devuelve el HTML crudo de
la fila, y `/api/esqueleto?plataforma=pedidosya` el árbol del DOM. Lo que hay
que contestar es **cuántos elementos matchean `get_by_text("Caesar",
exact=True)` y cuáles son visibles**. Si hay más de uno, `_fila()` tiene que
filtrar por visible antes del `.first`.

---

## Decisiones del usuario (no volver a preguntar)

- **"Wrap caesar con batatas" (PedidosYa) NO es "Wrap caesar con ensalada"
  (Rappi).** Son platos distintos.
- Los únicos 3 wraps activos en PedidosYa son los "con batatas", vinculados a
  mano con los de Rappi.
- **La Mexicana y los ~18 productos que están solo en Rappi no se cargan a
  mano.** El usuario los agrega desde la pantalla Carta si los necesita.
- **Los platos del día se sacaron** (estorbaban). No reimplementarlos.
- El catálogo está en modo manual (`CATALOGO_MANUAL`): `seed.py` ya **no** pisa
  los alias.

## Próximos pasos

1. **El click fallado del toggle** (arriba). Es el que más plata de tiempo
   cuesta ahora que existe "Apagar todo", y el que más riesgo esconde.
2. **Mostrar el historial en pantalla** (`/api/historial` ya lo devuelve). Es
   lo que falta para poder reconstruir qué pasó con un producto sin tener la
   ventana del `.bat` abierta. Ver la sección del pedido de algo apagado.
3. **Hacer la app genérica** — pedido explícito del usuario (2026-07-28), sin
   apuro. El repo es público y no quiere que quien lo baje se encuentre con su
   carta y los datos de su local. Ya está hecha la mitad: los ids de sucursal
   salen de Ajustes. Falta `app/seed.py`, que tiene los 31 productos con sus
   nombres en cada portal. La app **ya sabe** armar el catálogo sola (pantalla
   Carta), así que sería dejar `seed.py` vacío y que el primer arranque ofrezca
   "leé mi carta" en vez de venir con la de otro. Dos cosas a decidir con él:
   si quiere conservar su catálogo como archivo local fuera del repo, y que el
   historial de git **ya tiene** sus nombres y sus ids (sacarlos ahora los deja
   fuera de la versión actual, pero siguen en los commits viejos).
4. Terminar el `TODO-SELECTOR` de Rappi: HTML de la tarjeta y pantalla de
   sesión expirada.

## Diagnóstico disponible (todo GET, no modifican nada)

```
/api/estado-sistema                          arrancado_en, sesiones, ultima_lectura
/api/alertas                                 lo que da por apagado y no puede confirmar
/api/config                                  los ajustes y su valor actual
/api/catalogo                                qué nombre tiene cada producto en cada portal
/api/nombres?plataforma=                     la carta que muestra el portal
/api/carta[?releer=false]                    lee las dos y propone el cruce
/api/verificar-catalogo?plataforma=          qué nombres del catálogo no están
/api/diagnostico?plataforma=&nombre=         lee uno + HTML crudo de la fila
/api/buscar-texto?plataforma=&fragmento=     cómo está escrito realmente
/api/estructura?plataforma=                  dónde vive la navegación
/api/esqueleto?plataforma=                   árbol del DOM (tag/id/clases/texto)
/api/masivo/previo?accion=                   cuántos tocaría cada portal
```

`/api/esqueleto` es el que resuelve "no sé dónde está esto" sin depender del
idioma.

## Reglas del proyecto

Están en `CLAUDE.md` y son cortas: no cambiar el contrato de los 4 métodos de
`plataformas/base.py` (agregar sí), preferir selectores por texto o rol,
`exact=True` siempre, toda operación se confirma releyendo, probar en modo
simulado antes de tocar worker o API, nada elegido por el usuario vive en el
repintado, y no afirmar lo que no se está viendo.

## Nota sobre términos de servicio

Rappi y PedidosYa prohíben el acceso automatizado. Esto automatiza lo que el
usuario ya hace a mano con su propio login, pero la cuenta es del local y el
riesgo existe.
