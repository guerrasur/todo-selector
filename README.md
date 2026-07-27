# Todo-Selector

App local para apagar/prender productos en **PedidosYa** y **Rappi** desde una
sola pantalla, sin entrar a cada portal.

Corre en `http://127.0.0.1:8001/` (Suipacha Loader usa el 8000).

## Estado: PROTOTIPO

El esqueleto está completo y probado en modo simulado. **Faltan los selectores
reales** de las dos plataformas — están marcados como `TODO-SELECTOR` en
`plataformas/rappi.py` y `plataformas/pedidosya.py`.

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
| Ensalada mixta   | Ensalada mixta   | Ensalada mixta de hojas  |

Si no hay alias cargado, se usa el nombre canónico en ambas. Los alias se
editan por `POST /api/alias`.

---

# TAREAS PENDIENTES (para completar en Claude Code)

Con Chrome abierto en los dos portales, hay que:

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
- [ ] `prender()`: sigue sin confirmar si al prender aparece un popup de
      confirmación o si es directo (todavía no se probó en vivo).

El popup de apagado ya está confirmado por captura: al clickear el toggle de
un producto prendido aparece un único popup con "No disponible por hoy" y
"No disponible indefinidamente" (sin paso de confirmación extra).

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

### Pendiente de decisión del usuario

**"chica" vs "individual".** En PedidosYa los tartas con guarnición
dicen "chica"; en Rappi dicen "individual". Están mapeados como el
mismo producto:

| Canónico | PedidosYa | Rappi |
|---|---|---|
| Tarta de verdura chica | Tarta de verdura chica | Tarta de verdura individual |
| Tarta de zapallo chica | Tarta de zapallo chica | Tarta de zapallo individual |
| Tarta de cebolla chica | Tarta de cebolla chica | Tarta de cebolla individual |
| Tarta de espinaca chica | Tarta de espinaca chica | Tarta de espinaca individual |

**Si son platos distintos, hay que separarlos.** Preguntarle al usuario.

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
- [ ] Sincronizar el estado real al arrancar (hoy arranca en "desconocido"
      hasta que se toque algo).
- [ ] Mostrar el historial en pantalla (la API ya lo devuelve).

## Nota sobre términos de servicio

Rappi y PedidosYa prohíben el acceso automatizado en sus términos. Esto
automatiza lo que ya hacés a mano con tu propio login, pero la cuenta es del
local y el riesgo existe. Vale tenerlo presente.
