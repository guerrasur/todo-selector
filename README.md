# StockSwitch

App local para apagar/prender productos en **PedidosYa** y **Rappi** desde una
sola pantalla, sin entrar a cada portal.

Corre en `http://127.0.0.1:8001/` (Suipacha Loader usa el 8000).

## Estado: PROTOTIPO

El esqueleto está completo y probado en modo simulado. **Faltan los selectores
reales** de las dos plataformas — están marcados como `TODO-SELECTOR` en
`plataformas/rappi.py` y `plataformas/pedidosya.py`.

## Arranque

```
py -m pip install -r requirements.txt
py -m playwright install chromium
py run.py
```

O doble click en `iniciar_app.bat`. Si la carpeta es un clon de git (usar
`git clone`, no bajar el zip), el `.bat` corre `git pull --ff-only` antes de
arrancar para traer la ultima version del repo automaticamente. Si no hay
conexion o hay cambios locales que generen conflicto, sigue con la version
que ya tenias.

### Modo simulado (sin tocar las plataformas)

```
set STOCKSWITCH_SIMULADO=1
py run.py
```

Las operaciones tardan 2 segundos y siempre dan OK. Sirve para ver la UI.

## Cómo funciona

- **Un navegador persistente** arranca con la app, con una pestaña por
  plataforma. Queda logueado en `%LOCALAPPDATA%\StockSwitch\chrome-profile`.
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
  database.py             # SQLite en %LOCALAPPDATA%\StockSwitch
  models.py               # Producto, AliasPlataforma, EstadoItem, Operacion
  seed.py                 # carga inicial de productos
  worker.py               # navegador persistente + cola + reverificación
plataformas/
  base.py                 # contrato: 4 métodos por plataforma
  pedidosya.py            # TODO-SELECTOR
  rappi.py                # TODO-SELECTOR
static/index.html         # UI
```

## Modelo de nombres

Un producto tiene un **nombre canónico** (el que ves en la UI) y opcionalmente
un **alias por plataforma**, porque en Rappi algunos difieren:

| Canónico  | PedidosYa | Rappi              |
|-----------|-----------|--------------------|
| Risotto   | Risotto   | Risotto de Hongos  |

Si no hay alias cargado, se usa el nombre canónico en ambas. Los alias se
editan por `POST /api/alias`.

---

# TAREAS PENDIENTES (para completar en Claude Code)

Con Chrome abierto en los dos portales, hay que:

## 1. PedidosYa (`plataformas/pedidosya.py`)

URL: `https://web-ar.us.restaurant-partners.com/menus/PY_AR/460348`

- [x] `_fila()`: confirmado, es el `<label class="mat-slide-toggle-label">`
      de Angular Material (envuelve nombre + toggle). **Cuidado con los
      nombres que son prefijo de otros** ("Wrap caesar" vs "Wrap caesar con
      batatas") — por eso se usa `exact=True`.
- [x] `leer_estado()`: confirmado, el toggle es un `<mat-slide-toggle>` con
      `aria-checked="true"/"false"` sobre el `<input>`.
- [ ] `asegurar_sesion()`: falta confirmar cómo se ve la pantalla cuando la
      sesión de **PedidosYa** expiró (la captura que se mandó era la de
      Rappi). El resto (elemento que prueba que el menú cargó) ya se ajustó
      a esperar `input.mat-slide-toggle-input`.
- [ ] `prender()`: verificar si al prender aparece un popup de confirmación
      o si es directo.

El popup de apagado ya está confirmado por captura: al clickear el toggle de
un producto prendido aparecen "No disponible por hoy" y "No disponible
indefinidamente".

## 2. Rappi (`plataformas/rappi.py`)

URL: `https://partners.rappi.com/menu?brandId=AR75000&storeIds=...`

**DECIDIDO:** se opera solo sobre **Carabelas - Turbo** (`AR221056`, confirmado).
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

- **Mexicana**: ya no se usa, sacada del catálogo (queda comentada por si vuelve).
- **"Coca Coca Zero"**: no es un typo de esta lista — se cargó mal en PedidosYa
  y quedó así en el portal. El nombre es correcto.
- **storeId de Rappi**: `AR221056` es Carabelas - Turbo. Confirmado.
- **Productos que aparecen solo en Rappi**: confirmado que "Ensalada con
  Peras", "Wrap de atun" (sin guarnición), "Wrap Brie con ensalada" y
  "Suprema a la Crema de Limón con Puré" no existen en PedidosYa. Quedan
  cargados solo para Rappi en `seed.py` (la UI los muestra con un chip gris
  "—" en PedidosYa).

### Pendiente de decisión del usuario

**"con batatas" vs "con ensalada".** En PedidosYa los wraps con guarnición
dicen "con batatas"; en Rappi dicen "con ensalada". Están mapeados como el
mismo producto:

| Canónico | PedidosYa | Rappi |
|---|---|---|
| Wrap caesar con batatas | Wrap caesar con batatas | Wrap caesar con ensalada |
| Wrap de Atun con batatas | Wrap de Atun con batatas | Wrap de atun con ensalada |
| Wrap hummus con batatas | Wrap hummus con batatas | Wrap Hummus con ensalada |
| Wrap toscano con batatas | Wrap toscano con batatas | Wrap Toscano con ensalada |

**Si son platos distintos, hay que separarlos.** Preguntarle al usuario.

Ojo también: en Rappi existen "Wrap de atun" y "Wrap de atun con ensalada"
como ítems separados; en PedidosYa solo figura "Wrap de Atun con batatas".

### Categorías

En PedidosYa, los platos (Risotto, Pastel de papa, Guisos, Ravioles, Arroz
Chaufa) están bajo **"Ensaladas"**. En Rappi están bajo **"Plato del Día"**.
En StockSwitch se agrupan en "Platos". Es solo visual, no afecta la búsqueda.

## 4. Integración con Suipacha Loader

Suipacha Loader también pregunta los platos del día al inicio de la jornada.
Hoy StockSwitch los pregunta por separado — habría que tomarlos de ahí.

Suipacha Loader corre en `http://127.0.0.1:8000` con FastAPI y SQLite.
Opciones:

- [ ] **Leer su API** (si expone un endpoint con los platos del día), es lo
      más limpio: StockSwitch consulta `localhost:8000` al arrancar.
- [ ] **Leer su base directo** (`%LOCALAPPDATA%\SuipachaLoader\carabelas.db`)
      en modo solo-lectura. Más frágil pero no requiere tocar la otra app.

Si Suipacha Loader no guarda hoy los platos del día de forma estructurada,
hay que agregarle ese modelo primero.

## 5. Pendientes de producto

- [ ] Botón de "apagar todo" al cierre.
- [ ] Sincronizar el estado real al arrancar (hoy arranca en "desconocido"
      hasta que se toque algo).
- [ ] Mostrar el historial en pantalla (la API ya lo devuelve).

## Nota sobre términos de servicio

Rappi y PedidosYa prohíben el acceso automatizado en sus términos. Esto
automatiza lo que ya hacés a mano con tu propio login, pero la cuenta es del
local y el riesgo existe. Vale tenerlo presente.
