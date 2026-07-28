# Todo-Selector

App local para apagar/prender productos en **PedidosYa** y **Rappi** desde una
sola pantalla, sin entrar a cada portal.

Corre en `http://127.0.0.1:8001/` (Suipacha Loader usa el 8000).

## Estado: EN USO

Las cuatro operaciones corrieron en vivo contra los dos portales.

| | leer la carta | apagar | prender |
|---|---|---|---|
| **PedidosYa** | ✅ 29 productos, las 3 categorías | ✅ | ✅ (op#17, 2026-07-27) |
| **Rappi** | ✅ 45 productos | ✅ | ✅ (op#18, 2026-07-27) |

Queda un `TODO-SELECTOR` en `plataformas/rappi.py`: falta el HTML completo de
la tarjeta y el selector de la pantalla de sesión expirada.

Hay pruebas que corren sin tocar los portales, ver `pruebas/LEEME.md`.

## Arranque

**Doble click en `iniciar_app.bat`.** No hace falta tener git, ni Python, ni
haber preparado nada: el `.bat` se encarga de todo en cualquier PC con Windows.

En cada arranque:

1. **Se autoactualiza.** Si la carpeta es un clon de git usa `git pull
   --ff-only`; si no lo es (bajaste el zip y listo) baja el zip del repo y
   copia solo los archivos que cambiaron. Sin internet, sigue con la version
   que ya tenias.
2. **Instala Python si falta** (via `winget`, sin pedir permisos de admin). Si
   la PC no tiene `winget`, te abre la pagina de descarga y te dice que tildes
   "Add python.exe to PATH".
3. **Instala las dependencias y Chromium**, pero solo la primera vez o cuando
   cambia `requirements.txt` — despues arranca directo.
4. **Levanta la app** en `http://127.0.0.1:8001/`.

La unica vez que hay que hacer algo a mano es la primera: bajar el zip desde
GitHub (botón verde **Code → Download ZIP**), descomprimirlo, y de ahi en mas
el `.bat` se actualiza solo.

Variantes:

```
iniciar_app.bat              arranque normal
iniciar_app.bat simulado     modo simulado, no toca las plataformas
iniciar_app.bat reinstalar   fuerza reinstalar dependencias y Chromium
```

A mano, si preferis:

```
py -m pip install -r requirements.txt
py -m playwright install chromium
py run.py
```

### Detalles del autoupdate

- La logica esta en `actualizar.ps1`. El `.bat` solo la invoca.
- La actualizacion por zip **agrega y pisa, nunca borra**: tus archivos locales
  (`.venv`, notas, lo que sea) quedan donde estan. Un archivo que se elimine en
  el repo no se elimina de tu carpeta.
- Un `.bat` no se puede sobrescribir mientras corre, asi que si el lanzador
  cambio se guarda como `iniciar_app.bat.nuevo` y un ayudante lo aplica al
  cerrar la ventana, reabriendo la app sola.
- Si la carpeta es un clon de git pero git no esta instalado, no se actualiza
  nada a proposito: pisar por zip borraria cambios locales sin aviso.
- Para probar una rama que no sea `main`:
  `powershell -ExecutionPolicy Bypass -File actualizar.ps1 -Rama nombre-de-la-rama`

### Modo simulado (sin tocar las plataformas)

```
set STOCKSWITCH_SIMULADO=1
py run.py
```

Las operaciones tardan 2 segundos y siempre dan OK. Sirve para ver la UI.

## Cómo funciona

- **Un navegador persistente** arranca con la app, con una pestaña por
  plataforma. Queda logueado en `%LOCALAPPDATA%\TodoSelector\chrome-profile`.
- **La UI no espera al navegador**: apretás un botón, se encola una operación,
  y la pantalla se actualiza sola cada 3 segundos.
- **Todo cambio se confirma releyendo**: después de clickear, recarga la página
  y verifica que el estado sea el esperado. Si no, reintenta (hasta 3 veces).
- **Verificación a los 2 minutos**: después de apagar un producto con éxito, se
  programa un chequeo. Si a los 2 minutos PedidosYa lo revivió, se reencola solo.
- **Ronda general cada 15 minutos** sobre todo lo que figura apagado, por si
  algo se revivió más tarde.
- **Refresco bajo demanda**: justo antes de cada operación, si la pestaña tiene
  más de 2 minutos, se recarga y se rechequea el login. No hay refresco
  periódico: el navegador se toca solo cuando hay trabajo. Esto cubre:
  - **Rappi se desloguea** por inactividad → se detecta antes de operar
  - **PedidosYa se pone rancio** tras un día → nunca se opera sobre página vieja
- **Botón "Revalidar sesión"** para forzar el chequeo cuando quieras.

## Elegir sobre qué plataforma actuar

Cada producto muestra dos chips (PedidosYa / Rappi). **Están los dos activos por
defecto**; clickeás uno para excluirlo y el botón actúa solo sobre el otro.
Sirve cuando una plataforma ya está bien y solo hay que corregir la otra.

## Platos del día

Al abrir la app, si todavía no se cargaron los platos de hoy, aparece un panel
arriba preguntándolos. Se escriben separados por coma. Si no hay, "Hoy no hay".

Los platos quedan asociados a la fecha: al día siguiente vuelve a preguntar y
los del día anterior desaparecen de la lista.

**Pendiente:** tomar este dato de Suipacha Loader en vez de preguntarlo dos
veces. Ver tareas pendientes.

## Qué está prendido: se lee del portal

Al arrancar, la app lee los dos portales y guarda cómo está cada producto.
Antes arrancaba sin saber nada: todo quedaba en "sin leer" hasta que tocabas
un botón, así que la pantalla no contestaba la pregunta más básica.

La lectura tarda un rato y corre en segundo plano; mientras tanto el cartel de
arriba dice "leyendo el estado real…" y después queda la hora de la lectura.
El botón **Leer estado real** la repite cuando quieras — sirve cuando alguien
apagó algo desde el portal y querés que la pantalla se entere.

Hay tres formas de estar apagado, y se distinguen a propósito:

| En pantalla | Qué significa |
|---|---|
| `apagado hoy` / `apagado` | Lo apagó la app. **Lo sostiene**: si el portal lo revive, lo vuelve a apagar sola. |
| `apagado (afuera)` | Estaba apagado en el portal y no fue la app. Lo muestra pero **no lo toca**. |
| `sin leer` | Todavía no se leyó (o el nombre del catálogo no coincide con el del portal). |

La diferencia importa: la ronda de reverificación reencola un apagado cuando
ve revivido algo que ella apagó. Si se apropiara de todo lo que el local apagó
por su cuenta, bastaría una lectura mala para volver a apagarlo sin que nadie
se lo pidiera.

## Cuando agregás un producto a la carta de un portal

Si un producto del catálogo figuraba como "no existe en PedidosYa" y el portal
ahora lo muestra, la app lo detecta en la lectura del estado y avisa arriba:

> **Locro del sabado** ahora también está en PedidosYa como
> **Locro del sábado** — [Es el mismo] [No, es otro]

"Es el mismo" lo engancha con el nombre exacto del portal (las tildes salen de
ahí, que es lo que necesita `exact=True`). "No, es otro" no vuelve a avisar.

El aviso es **conservador a propósito**: solo aparece cuando el nombre es el
mismo salvo tildes o mayúsculas, y solo para productos que ya están en el
catálogo. Con un umbral más flojo propondría vincular "Tarta de verdura con
guarnicion" con "Tarta de verdura individual", que son platos distintos. Lo dudoso
se decide en la pantalla Carta, con todo a la vista.

Un producto **completamente nuevo** (que no está en el catálogo en ninguna
plataforma) no genera aviso: aparece en la pantalla Carta, en "solo en…".

## La pantalla Carta

El botón **Carta** (arriba a la derecha) lee lo que muestran los dos portales
y lo cruza con lo que tiene cargado la app. Tarda como un minuto: recorre
todas las categorías de PedidosYa y la lista de Rappi.

Muestra cuatro grupos: **a confirmar** (el emparejamiento automático no está
seguro), **emparejados solos**, y los que están **solo en un portal**.

- **Vincular**: los dos nombres pasan a ser el mismo producto, con un solo
  botón de apagado. Si estaban cargados por separado, se fusionan.
- **Separar**: lo contrario. Cada portal queda con su propio botón.
- **Agregar**: carga en la app un producto que está en un portal y no en el
  catálogo.

El criterio es que **si no está claro que sea el mismo plato, van separados**,
y vincularlos es una decisión explícita tuya. Cuando la app no está segura
avisa qué otro producto parecido existe en el otro portal — que es justo el
caso del "Tarta de verdura chica", que en Rappi tiene dos candidatos.

**Importante:** en cuanto vinculás o separás algo, el catálogo pasa a
manejarse desde la app y `app/seed.py` deja de pisar los nombres en cada
arranque. Si no, un reinicio deshacía lo que acababas de decidir.

## Diagnóstico cuando algo "falla"

El motivo del fallo ahora sale en tres lugares: en la consola (`op#N fallo: ...`),
abajo del producto en la UI, y en `GET /api/historial`.

La causa más común es que el nombre del catálogo (`app/seed.py`) no coincida
**exactamente** con el del portal — los nombres se buscan con `exact=True`, así
que una mayúscula o un guión de diferencia y no encuentra nada. Para verlo,
con la app corriendo, pegá en el navegador:

```
http://127.0.0.1:8001/api/buscar-texto?plataforma=rappi&fragmento=Gaseosa
http://127.0.0.1:8001/api/diagnostico?plataforma=pedidosya&nombre=Gaseosa%20Cola
```

- **`buscar-texto`** devuelve todos los textos del portal que contienen el
  fragmento: ahí se ve cómo está escrito el producto de verdad.
- **`diagnostico`** prueba leer un producto por nombre exacto sin tocar nada, y
  devuelve la URL en la que está parada la pestaña (útil para detectar que
  quedaste logueado en otra sucursal).

Con el nombre real, se corrige el alias con `POST /api/alias` o directamente en
`app/seed.py`.

## Qué hacer si se cae una sesión

La UI muestra "Login pendiente: Rappi" (o PedidosYa) en rojo. Andá a la ventana
del navegador que abrió la app, logueate en la pestaña correspondiente, y
apretá "Revalidar sesión". No hace falta reiniciar nada.

## Primera vez

El navegador va a abrir sin sesión. Logueate a mano en las dos pestañas.
Queda guardado. La UI muestra "Login pendiente" mientras falte alguna.

## Estructura

```
run.py                    # arranque
app/
  main.py                 # FastAPI + endpoints
  database.py             # SQLite en %LOCALAPPDATA%\TodoSelector
  models.py               # Producto, AliasPlataforma, EstadoItem, Operacion
  seed.py                 # carga inicial de productos
  carta.py                # cruza la carta de los dos portales
  catalogo.py             # vincular / separar / agregar productos
  worker.py               # navegador persistente + cola + reverificación
plataformas/
  base.py                 # contrato: 4 métodos por plataforma
  pedidosya.py            # confirmado en vivo
  rappi.py                # TODO-SELECTOR (tarjeta y sesión expirada)
static/index.html         # UI
pruebas/                  # corren sin tocar los portales, ver pruebas/LEEME.md
```

## Modelo de nombres

Un producto tiene un **nombre canónico** (el que ves en la UI) y opcionalmente
un **alias por plataforma**, porque en Rappi algunos difieren:

| Canónico  | PedidosYa | Rappi              |
|-----------|-----------|--------------------|
| Ensalada mixta   | Ensalada mixta   | Ensalada mixta de hojas  |

Si no hay alias cargado, se usa el nombre canónico en ambas.

**Un producto con alias en las dos plataformas es un plato que se apaga con un
solo botón; uno con alias en una sola existe solo ahí** (la UI le muestra el
chip gris "—" en la otra). Eso se cambia desde la pantalla Carta, o por API:

```
POST /api/vincular   {"pedidosya": "Budín de pan", "rappi": "Budín de pan"}
POST /api/separar    {"producto_id": 12, "plataforma": "rappi"}
POST /api/agregar    {"plataforma": "rappi", "nombre_remoto": "Guiso de garbanzos"}
GET  /api/catalogo   qué nombre tiene cada producto en cada portal
```

---

# TAREAS PENDIENTES (para completar en Claude Code)

Con Chrome abierto en los dos portales, hay que:

## 0. PedidosYa solo expone una categoría a la vez  ← RESUELTO

Se recorren las categorías (`wk-menu-list wk-menu-list-category-item`) y se
recuerda en cuál apareció cada producto. Confirmado en vivo el 2026-07-27:
`/api/carta` leyó los 29 productos de las 3 categorías, y op#17 encontró
"Budín de pan" en "Platos".

**Cuidado con una trampa que ya mordió:** el fallback JS de `clickear()` no
sirve tal cual para las categorías. El listener no está en el custom element
sino en un hijo, y los eventos suben pero no bajan: un `el.click()` sobre
`<wk-menu-list-category-item>` no hace nada. Por eso existe el click
"profundo", que dispara sobre el descendiente más profundo del centro.
Está cubierto por `pruebas/probar_pedidosya.py`.

## 1. PedidosYa (`plataformas/pedidosya.py`)

URL: `https://web-ar.us.restaurant-partners.com/menus/PY_AR/MENU_ID`

- [x] `_fila()`: confirmado, es el `<label class="mat-slide-toggle-label">`
      de Angular Material (envuelve nombre + toggle). **Cuidado con los
      nombres que son prefijo de otros** ("Tarta de verdura" vs "Tarta de verdura con
      guarnicion") — por eso se usa `exact=True`.
- [x] `leer_estado()`: confirmado, el toggle es un `<mat-slide-toggle>` con
      `aria-checked="true"/"false"` sobre el `<input>`.
- [x] `asegurar_sesion()`: confirmado, PedidosYa no tiene pantalla de sesión
      expirada — se re-loguea solo. Se deja el chequeo de password como red
      de seguridad. El elemento que prueba que el menú cargó espera
      `input.mat-slide-toggle-input`.
- [x] `prender()`: **confirmado en vivo** (op#17, 2026-07-27). No abre ningún
      popup: el click sobre el toggle apagado lo prende y queda guardado. El
      popup de dos opciones es solo del lado de apagar, porque ahí hay que
      elegir "por hoy" o "indefinidamente".

El popup de apagado ya está confirmado por captura: al clickear el toggle de
un producto prendido aparece un único popup con "No disponible por hoy" y
"No disponible indefinidamente" (sin paso de confirmación extra).

**Reconfirmar después de recargar.** `_confirmar()` (en `base.py`, compartido
con Rappi) rehace la preparación del arranque después del reload: cierra el
popup de sonido —que vuelve en cada carga— y espera a que el menú exista.
Dormir 4 segundos no alcanzaba: la relectura caía sobre la página tapada y en
la primera categoría, no encontraba el producto, y daba por fallado un cambio
que sí había entrado (op#17 dio "fallo" y el reintento lo encontró prendido).

## 2. Rappi (`plataformas/rappi.py`)

URL: `https://partners.rappi.com/menu?brandId=BRAND_ID&storeIds=...`

**DECIDIDO:** se opera solo sobre **la tienda Turbo** (`STORE_ID`, confirmado).
Al apagar ahí, también se apaga en Rappi normal.

- [x] `_tarjeta()`: sin el HTML completo de la tarjeta, se resolvió subiendo
      desde el nombre hasta el primer ancestro que también contiene el
      toggle (localizado por su `data-testid`).
- [x] `leer_estado()`: badge "Apagados" confirmado (fuente 1); el toggle es
      un `<label data-testid="...-availability-switch-control">` con un
      `<input readonly>` oculto adentro, sin `aria-checked` (fuente 2, via
      `is_checked()`).
- [x] `apagar()`: confirmado por captura — el diálogo tiene 3 radios: "Sólo
      por hoy", "No disponible indefinidamente" y "Personalizar
      disponibilidad" (esta última no se usa, pide elegir fecha). Elegido
      el radio, aparece un segundo modal "¿Desactivar producto?" con
      botones "Cancelar" y "Sí, desactivar" — confirmado, el código
      clickea "Sí, desactivar".
- [ ] Pantalla de sesión expirada de Rappi: se sabe que existe (Rappi se
      desloguea por inactividad) pero falta confirmar el selector exacto
      para `asegurar_sesion()`.

## 3. Revisar el mapeo de nombres

`app/seed.py` tiene el catálogo cargado con los nombres de cada plataforma.

### Resuelto

- **Mixta**: ya no se usa, sacada del catálogo (queda comentada por si vuelve).
- **"Gaseosa cola cero"**: no es un typo de esta lista — se cargó mal en PedidosYa
  y quedó así en el portal. El nombre es correcto.
- **storeId de Rappi**: `STORE_ID` es la tienda Turbo. Confirmado.
- **Productos que aparecen solo en Rappi**: confirmado que "Ensalada con
  ñoquis", "Tarta de zapallo" (sin guarnición), "Tarta de choclo individual" y
  "Locro del sábado" no existen en PedidosYa. Quedan
  cargados solo para Rappi en `seed.py` (la UI los muestra con un chip gris
  "—" en PedidosYa).

### El catálogo está incompleto A PROPÓSITO

`/api/nombres?plataforma=rappi` devuelve **45 productos**; `seed.py` tiene 31.
Los ~18 que faltan (Wok de vegetales, Wok de pollo, los Bowls, Polenta con
Estofado, Tarta de acelga, Plato del dia, varias ensaladas, "Ensalda mixta"
con el typo del portal…) **no se cargan a mano**: el usuario decidió el
2026-07-27 dejar el catálogo como está y agregar desde la pantalla Carta lo
que necesite. `seed.py` es la carga inicial, no el catálogo definitivo.

Lo mismo con **"Ensalada mixta"**: está viva en los dos portales pero queda
fuera del catálogo por decisión del usuario. Si algún día la quiere, la
pantalla Carta la propone con 0.97 de confianza y alcanza con "Vincular".

Ojo con **"Ensalda mixta"**: el typo es del portal. Como los nombres se
buscan con `exact=True`, hay que copiarlo con el typo o no se encuentra. La
pantalla Carta ya toma el nombre tal cual lo escribe el portal, así que
agregándolo desde ahí no hay riesgo de equivocarse.

### "chica" vs "individual"  ← RESUELTO por el usuario (2026-07-27)

En PedidosYa los tartas con guarnición dicen "chica"; en Rappi "con
ensalada", y para el de verdura Rappi tiene **dos**: "en porcion" y "individual".

- **"Tarta de verdura chica" NO es ninguno de los dos.** Son platos
  distintos. Estaban vinculados a "Tarta de verdura individual": apagar uno
  apagaba el que no era. Ya está corregido en `seed.py`, y una base ya
  sembrada se corrige sola en el próximo arranque.
- **Los otros tres** (zapallo, cebolla, espinaca) siguen vinculados. El usuario
  dijo que le es indiferente y que prefiere decidirlo desde la app: si no son
  el mismo plato, el botón "Separar" de la pantalla Carta los desarma.

Ojo también: en Rappi existen "Tarta de zapallo" y "Tarta de zapallo individual"
como ítems separados; en PedidosYa solo figura "Tarta de zapallo chica".

### Categorías

En PedidosYa, los platos (Ensalada mixta, Tarta de jamon y queso, Guisos, fideos, Arroz
Empanada) están bajo **"Platos"**. En Rappi están bajo **"Plato del Día"**.
En Todo-Selector se agrupan en "Platos". Es solo visual, no afecta la búsqueda.

## 4. Integración con Suipacha Loader

Suipacha Loader también pregunta los platos del día al inicio de la jornada.
Hoy Todo-Selector los pregunta por separado — habría que tomarlos de ahí.

Suipacha Loader corre en `http://127.0.0.1:8000` con FastAPI y SQLite.
Opciones:

- [ ] **Leer su API** (si expone un endpoint con los platos del día), es lo
      más limpio: Todo-Selector consulta `localhost:8000` al arrancar.
- [ ] **Leer su base directo** (`%LOCALAPPDATA%\SuipachaLoader\el local.db`)
      en modo solo-lectura. Más frágil pero no requiere tocar la otra app.

Si Suipacha Loader no guarda hoy los platos del día de forma estructurada,
hay que agregarle ese modelo primero.

## 5. Pendientes de producto

- [ ] Botón de "apagar todo" al cierre.
- [x] Sincronizar el estado real al arrancar. Hecho: al levantar, la app lee
      los dos portales y guarda cómo está cada producto. Ver más arriba.
- [ ] Mostrar el historial en pantalla (la API ya lo devuelve).
- [ ] **Sacar del código el id de menú de PedidosYa (`MENU_ID`) y el `storeId`
      de Rappi (`STORE_ID`).** Hasta que sean configurables, "sirve para otro
      local" está a medias.

## Nota sobre términos de servicio

Rappi y PedidosYa prohíben el acceso automatizado en sus términos. Esto
automatiza lo que ya hacés a mano con tu propio login, pero la cuenta es del
local y el riesgo existe. Vale tenerlo presente.
