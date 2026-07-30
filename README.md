# Todo-Selector

App local para apagar/prender productos en **PedidosYa** y **Rappi** desde una
sola pantalla, sin entrar a cada portal.

Corre en `http://127.0.0.1:8001/` (Suipacha Loader usa el 8000).

## ⚠️ Aviso importante — leer antes de usar

Esta app **no es una integración oficial** de PedidosYa ni de Rappi. Automatiza
un navegador (Chromium vía Playwright) que se loguea con tu cuenta de partner
y clickea los mismos botones que clickearías vos a mano.

**Ambas plataformas prohíben expresamente el acceso automatizado en sus
Términos de Servicio.** Usar esta herramienta contra cuentas reales puede
resultar en:

- Suspensión o baneo de la cuenta de partner del local.
- Pérdida de acceso a pedidos, historial y facturación asociados a esa cuenta.
- Detección de patrones de automatización (sesiones persistentes, clicks
  regulares, reintentos) aunque el comportamiento imite a un humano.

**No hay garantía de que la app refleje el estado real de la carta en todo
momento.** Un producto puede figurar como apagado en pantalla y estar
disponible en el portal (o viceversa) si hay un fallo de lectura o el portal
lo revive por su cuenta. Revisar siempre `/api/alertas` y el grupo "Sin
confirmar" antes de asumir que algo está apagado.

**Se recomienda usar la app en modo simulado**
(`iniciar_app.bat simulado`), que no toca ningún portal real y sirve solo
para conocer la interfaz con fines educativos/de prueba. El modo que opera
en vivo contra PedidosYa y Rappi queda a criterio y responsabilidad de quien
lo ejecute.

**Quién asume el riesgo:** quien instala y ejecuta esta app lo hace bajo su
propia responsabilidad y con su propia cuenta. El autor de este repositorio
no se responsabiliza por baneos, suspensiones, pérdidas de pedidos, o
cualquier otro perjuicio derivado de su uso. Este proyecto se comparte con
fines educativos/personales, no como producto soportado, y puede dejar de
funcionar en cualquier momento si Rappi o PedidosYa cambian su sitio.

## Estado: EN USO

Las cuatro operaciones (leer, apagar, prender en cada portal) fueron
confirmadas en vivo contra los dos portales.

| | leer la carta | apagar | prender |
|---|---|---|---|
| **PedidosYa** | ✅ la carta entera, recorriendo las categorías | ✅ | ✅ |
| **Rappi** | ✅ la carta entera | ✅ | ✅ |

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

**Acceso directo.** La primera vez que arranca, la app deja en el escritorio un
acceso directo **TODO-SELECTOR** con el icono de `todo2.ico`. Se hace una sola
vez: queda una marca en `%LOCALAPPDATA%\TodoSelector\acceso-directo.ok`, así que
si lo borrás no vuelve a aparecer. El mismo icono es el de la pestaña del
navegador (se sirve en `/favicon.ico`).

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

## Apagar un producto en un solo portal

Cada producto muestra dos chips (PedidosYa / Rappi). **Están los dos activos por
defecto**; clickeás uno para excluirlo y el botón actúa solo sobre el otro.
Sirve cuando hay que apagar en un portal antes que en el otro, o cuando una
plataforma ya está bien y solo hay que corregir la otra.

**El botón dice a dónde va**: con los dos chips puestos dice `Apagar hoy`, y
sacando uno pasa a decir `Apagar hoy · solo PedidosYa`. El chip excluido queda
tachado. Antes había que interpretar la opacidad de los chips para saberlo, así
que la función existía pero no se veía.

La exclusión **se queda puesta** hasta que vuelvas a clickear el chip. Antes se
perdía sola: la lista se repinta cada pocos segundos y con eso el chip volvía a
quedar seleccionado, así que si tardabas más que el refresco en apretar el
botón, la acción salía a los dos portales sin decir nada.

## Cuando la app no puede confirmar un apagado

El mecanismo: si la lectura de la carta **no encuentra** un producto —porque el
nombre del catálogo no coincide con el del portal, o porque no se pudo abrir la
categoría— la app *no pisa* el estado que tenía. Eso está bien (una lectura mala
no debería borrar lo que sabíamos), pero el efecto es que un `apagado` viejo
puede quedar **congelado** y la pantalla lo sigue afirmando en presente, sin nada
que lo delate.

La app no puede prometer que el portal no reviva algo por su cuenta. Lo que sí
puede es **dejar de afirmar lo que no está viendo**. Por eso:

- un producto que figura apagado y que la última lectura **no encontró** en el
  portal aparece marcado en rojo, con el nombre exacto con el que lo estaba
  buscando (que es lo que hay que corregir, normalmente desde la Carta);
- lo mismo si hace **más de dos rondas** que nadie lo confirma;
- arriba de todo sale un cartel rojo con la lista y dos atajos: releer los
  portales, o ir a la Carta a arreglar el nombre.

Se ve en `GET /api/alertas`.

## Si se cae la sesión, no se pierde lo que pediste

Rappi se desloguea por inactividad. Antes, una operación que agarraba la sesión
caída se moría: tres reintentos de dos segundos contra un login que **solo
vuelve a mano**, y después ERROR. Para cuando terminabas de loguearte, lo que
habías pedido ya no estaba encolado.

Ahora una operación que falla por sesión caída **no gasta intentos y no termina
en error**: queda esperando y sale sola apenas vuelve la sesión, sin que tengas
que volver a pedirla. La otra plataforma sigue trabajando normal mientras tanto,
y el cartel rojo de arriba te dice en cuál hay que loguearse.

## Apagar todo (el botón de cierre)

El botón **Apagar todo** de arriba abre un panel con **un juego de botones por
destino**:

| | |
|---|---|
| **PedidosYa** | Apagar todo · Prender todo |
| **Rappi** | Apagar todo · Prender todo |
| **Los dos** | Apagar todo · Prender todo |

Que estén separados es el punto: a veces **PedidosYa tiene que apagarse antes
que Rappi**. Apretás PedidosYa, y cuando quieras, Rappi. La cola respeta el
orden en que apretaste.

Con la **tienda Rappi Común** configurada (ver Ajustes) son cinco, porque son
tres tiendas y no dos:

| | |
|---|---|
| **PedidosYa** | Apagar todo · Prender todo |
| **Rappi Turbo** | Apagar todo · Prender todo |
| **Rappi Común** | Apagar todo · Prender todo |
| **Ambos Rappi** | Apagar todo · Prender todo |
| **Todas** | Apagar todo · Prender todo |

«Ambos Rappi» es el de todos los días: las dos tiendas de Rappi cierran juntas
y PedidosYa no siempre. Y «Rappi» pasa a llamarse **Rappi Turbo** en toda la
pantalla: con dos tiendas, un botón que dice «Rappi» a secas no dice cuál.

Antes de encolar nada dice cuántos productos va a tocar cada portal, y pide
confirmación: apagar la carta entera es de las pocas cosas de esta app que no se
deshacen con un click.

**No encola de más**, que es lo que hace que esto sea usable:

- lo que **ya figura como querés que quede** no se toca (apagar toda la carta son
  ~30 operaciones por portal y cada una recarga la página);
- lo que **está en pausa** tampoco;
- lo que **ya está en la cola** tampoco, así que apretarlo dos veces no duplica
  nada;
- **Prender todo** no toca lo que está `apagado (afuera)`: si lo apagó alguien
  desde el portal, fue a propósito.

Por defecto **relee el portal antes de decidir** (~35 s), para que "ya está
apagado" sea un hecho y no una suposición sobre una lectura vieja. Todo esto se
cambia en Ajustes.

## Ajustes

El engranaje de arriba a la derecha abre la configuración. Se guarda en la base,
que vive afuera de la carpeta de la app: **un autoupdate no se la lleva puesta**.
Todos los valores por defecto son exactamente lo que la app venía haciendo, así
que sin tocar nada se comporta igual que siempre.

| Grupo | Qué se puede cambiar |
|---|---|
| **Apagar todo** | Si el cierre apaga *por hoy* o *indefinido*; si relee el portal antes; si incluye los pausados; si "Prender todo" toca lo apagado desde afuera. |
| **Ritmo** | Cada cuántos minutos se releen las cartas (0 = nunca); si se vuelve a apagar lo que el portal revive; a los cuántos segundos se confirma un apagado; cuándo se considera vieja la pestaña; reintentos por operación; cada cuánto se repinta la pantalla. |
| **Sucursal** | El **id de menú de PedidosYa** y el **storeId / brandId de Rappi**. Estaban clavados en el código: hasta que fueran configurables, "sirve para otro local" estaba a medias. |
| **Rappi Común** | El **storeId de la segunda tienda de Rappi**, si tu local tiene una. Vacío (el default) = la app ni la nombra. Ver «Las dos tiendas de Rappi». |

Cambiar de sucursal **no pide reiniciar**: las pestañas se enteran y navegan
solas al menú nuevo en la próxima operación.

## Buscador

Arriba de la lista hay un campo de búsqueda. Filtra a medida que escribís y
busca **por el nombre de los dos portales**, no solo por el que ves: buscando
`gaseosa` aparece "Coca-Cola 500 ml". Ignora tildes y mayúsculas, así que
`bondiola` encuentra "Bondiola al malbec".

La cruz (o la tecla `Esc`) borra la búsqueda y vuelve la lista completa.

## Vista: juntar arriba lo que está prendido

Con la carta entera en pantalla, lo prendido queda desparramado entre las
categorías y hay que ir a buscarlo. Abajo del buscador hay tres vistas:

- **Por categoría** — la de siempre.
- **Prendidos primero** — ordena por estado en vez de por categoría: los
  prendidos arriba, los apagados abajo. **No esconde nada.**
- **Solo los prendidos** — deja únicamente lo que está prendido.

Al lado dice cuántos hay prendidos en total. La vista elegida queda guardada
en el navegador: si preferís entrar siempre a "solo los prendidos", entrás
siempre a eso.

En las dos vistas por estado aparece un grupo del medio, **Sin confirmar**,
con lo que la app no puede asegurar que esté apagado: lo que la última lectura
no encontró en el portal, lo que falló, lo que todavía no se leyó y lo que
está en curso. Ese grupo **no se esconde ni siquiera en "solo los prendidos"**,
porque es justo el que puede estar vendiéndose sin que la pantalla lo avise.
Y cuando la vista esconde apagados, dice cuántos: esconder cosas sin decir
cuántas es como se llega a creer que la carta está más prendida de lo que está.

## Qué está prendido: se lee del portal

Al arrancar, la app lee los dos portales y guarda cómo está cada producto.
Antes arrancaba sin saber nada: todo quedaba en "sin leer" hasta que tocabas
un botón, así que la pantalla no contestaba la pregunta más básica.

La lectura tarda un rato y corre en segundo plano; mientras tanto el cartel de
arriba dice "leyendo el estado real…" y después queda la hora de la lectura.
El botón **Leer estado real** la repite cuando quieras — sirve cuando alguien
apagó algo desde el portal y querés que la pantalla se entere.

**Cada 15 minutos se releen las dos cartas enteras**, así que lo que apagaste
desde el portal también se mantiene al día. Antes esa ronda leía solo lo que la
app tenía apagado, producto por producto; leer las dos cartas de una sale más
barato que eso (~35 s de navegador cada 15 min) y actualiza toda la pantalla.
Mientras corre, una operación que encoles espera a que termine.

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

> **Milanesa napolitana** ahora también está en PedidosYa como
> **Milanesa a la napolitana** — [Es el mismo] [No, es otro]

"Es el mismo" lo engancha con el nombre exacto del portal (las tildes salen de
ahí, que es lo que necesita `exact=True`). "No, es otro" no vuelve a avisar.

El aviso es **conservador a propósito**: solo aparece cuando el nombre es el
mismo salvo tildes o mayúsculas, y solo para productos que ya están en el
catálogo. Con un umbral más flojo propondría vincular "Empanada de carne
chica" con "Empanada de carne porción", que son platos distintos. Lo dudoso
se decide en la pantalla Carta, con todo a la vista.

Un producto **completamente nuevo** (que no está en el catálogo en ninguna
plataforma) no genera aviso: aparece en la pantalla Carta, en "solo en…".

## Productos en pausa

Un producto que está en la carta del portal pero **este mes no se vende** se
puede marcar con **Pausar**. Se va al final de la pantalla, a una sección "En
pausa", apagado de color, y **la app deja de sostenerlo**: si figura apagado,
no lo reencola nunca más. Los botones le siguen funcionando, y el estado se le
sigue leyendo — eso sale gratis, porque la lectura trae la carta entera igual.

Sirve para que lo que no se toca no estorbe arriba. **Reactivar** lo devuelve.

## Las dos tiendas de Rappi (Turbo y Común)

Un local puede vender por **dos tiendas de Rappi**: la «Turbo» y la común. Son
tiendas **independientes** del mismo portal y del mismo login:

- apagar un producto en una **no** lo apaga en la otra;
- **no tienen la misma carta**: hay platos que están en una y no en la otra, y
  el mismo plato puede estar escrito distinto en cada una.

Por defecto la app usa una sola. Si cargás el **storeId de Rappi Común** en
Ajustes, pasa a ser una tercera plataforma completa: su pestaña, su chip en
cada producto, su columna en la pantalla Carta, su fila en «Apagar todo», su
cola y su reverificación. Con el ajuste vacío no se nota en ningún lado.

**Cómo se engancha tu carta.** Una vez, en la pantalla **Carta**: la app lee
las tres cartas, propone qué producto de una tienda es cuál de la otra, y vos
confirmás. Eso queda guardado. **Desde ese momento un solo botón apaga las dos
tiendas**, porque son el mismo producto de la app.

**Lo que la app no hace, a propósito:** apagar en la otra tienda algo que
todavía no confirmaste. Entre dos tiendas del mismo portal los nombres se
parecen muchísimo —"Empanada de carne" y "Empanada de carne chica" puntúan
0.91— y emparejar de más significa **apagar un plato que se sigue vendiendo**.
Por eso ahí el listón es más alto que entre PedidosYa y Rappi (0.95 contra
0.82): lo que no llega queda propuesto, con la casilla destildada, para que lo
decidas vos.

**Si algo queda apagado en una tienda y prendido en la otra**, sale un cartel
rojo arriba de todo con el nombre y en cuál quedó prendido. Es el único caso
que la app puede afirmar sin adivinar: las dos están vinculadas, las dos se
leyeron, y no coinciden.

## La pantalla Carta

El botón **Actualizar carta** (arriba a la derecha) muestra lo que dicen los
dos portales, cruzado con lo que tiene cargado la app. Al abrirse muestra la
última lectura guardada; **Volver a leer los portales** va a buscarla de nuevo
y tarda como un minuto (recorre todas las categorías de PedidosYa y la lista
de Rappi).

Muestra cuatro grupos: **a confirmar** (el emparejamiento automático no está
seguro), **emparejados solos**, y los que están **solo en un portal**.

- **Vincular**: los dos nombres pasan a ser el mismo producto, con un solo
  botón de apagado. Si estaban cargados por separado, se fusionan.
- **Separar**: lo contrario. Cada portal queda con su propio botón.
- **Agregar**: carga en la app un producto que está en un portal y no en el
  catálogo.
- **Vincular a mano**: dos listas desplegables, una por portal, para juntar dos
  que la app no propuso. Es para lo que ninguna heurística va a sacar. Cada
  opción muestra con qué está vinculada hoy, y antes de apretar el botón la
  pantalla avisa qué vínculo vas a romper. Si el que elegís ya estaba
  vinculado con otro, **ese otro no se pierde**: queda como producto suelto,
  con su propio botón (pausalo si no lo usás).
- **Deshacer**: vuelve el catálogo a como estaba antes del último cambio, y
  dice cuál va a deshacer. Vincular toca varios productos a la vez, así que
  revertirlo a mano es un rompecabezas. Guarda los últimos 20 pasos.

**Renombrar:** el nombre que ves en la pantalla es solo tuyo — los portales se
buscan por los alias. Se cambia clickeándolo. Sirve cuando dos productos se
llamaban igual y hubo que desempatarlos: el que se separa queda como
"Empanada de carne (PedidosYa)".

El criterio es que **si no está claro que sea el mismo plato, van separados**,
y vincularlos es una decisión explícita tuya. Cuando la app no está segura
avisa qué otro producto parecido existe en el otro portal — que es justo el
caso de la "Empanada de carne chica", que en Rappi tiene dos candidatos.

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
http://127.0.0.1:8001/api/buscar-texto?plataforma=rappi&fragmento=Empanada
http://127.0.0.1:8001/api/diagnostico?plataforma=pedidosya&nombre=Empanada%20de%20carne
```

- **`buscar-texto`** devuelve todos los textos del portal que contienen el
  fragmento: ahí se ve cómo está escrito el producto de verdad.
- **`diagnostico`** prueba leer un producto por nombre exacto sin tocar nada, y
  devuelve la URL en la que está parada la pestaña (útil para detectar que
  quedaste logueado en otra sucursal).

Con el nombre real, se corrige el alias con `POST /api/alias`, o vinculando
los dos nombres desde la pantalla Carta, que es lo mismo sin tocar código.

## Qué hacer si se cae una sesión

La UI muestra "Login pendiente: Rappi" (o PedidosYa) en rojo. Andá a la ventana
del navegador que abrió la app, logueate en la pestaña correspondiente, y
apretá "Revalidar sesión". No hace falta reiniciar nada.

## Primera vez

**La app no viene con ninguna carta cargada, a propósito.** Arranca vacía y
te arma el catálogo leyendo TUS portales. Son dos pasos, y la pantalla te los
pide sola la primera vez que la abrís:

1. **Qué local sos.** El id de menú de PedidosYa y el `brandId` / `storeId` de
   Rappi. Están en la URL del menú de cada portal, y la pantalla dice dónde
   mirar. Quedan guardados en tu base, que vive fuera de la carpeta de la app:
   un autoupdate no se los lleva puestos.
2. **Leer tu carta.** La app entra a los dos portales, lee lo que tenés
   publicado y te propone qué producto de uno es cuál del otro. Lo que no es
   obviamente el mismo plato queda separado y lo confirmás vos.

Antes de leer, el navegador va a abrir sin sesión: logueate a mano en las dos
pestañas. Queda guardado. La UI muestra "Login pendiente" mientras falte
alguna.

Hasta que no cargues los datos de la sucursal, la app **no navega a ningún
menú**: con el id de otro local entraría a una carta ajena, que es peor que no
arrancar.

## Estructura

```
run.py                    # arranque
app/
  main.py                 # FastAPI + endpoints
  database.py             # SQLite en %LOCALAPPDATA%\TodoSelector
  models.py               # Producto, AliasPlataforma, EstadoItem, Operacion
  seed.py                 # carga inicial: viene VACÍA (ver «Primera vez»)
  carta.py                # cruza la carta de los dos portales
  catalogo.py             # vincular / separar / agregar productos
  cierre.py               # apagar/prender la carta entera de una plataforma
  config.py               # los ajustes de la pantalla, guardados en la base
  worker.py               # navegador persistente + cola + reverificación
plataformas/
  base.py                 # contrato: 4 métodos por plataforma
  pedidosya.py            # confirmado en vivo
  rappi.py                # TODO-SELECTOR (tarjeta y sesión expirada)
static/index.html          # UI
todo2.ico                 # icono: pestaña del navegador y acceso directo
pruebas/                  # corren sin tocar los portales, ver pruebas/LEEME.md
```

## Modelo de nombres

Un producto tiene un **nombre canónico** (el que ves en la UI) y opcionalmente
un **alias por plataforma**, porque en Rappi algunos difieren:

| Canónico       | PedidosYa      | Rappi Turbo              | Rappi Común             |
|----------------|----------------|--------------------------|-------------------------|
| Ensalada mixta | Ensalada mixta | Ensalada mixta de hojas  | Ensalada mixta de hojas |

Las plataformas son las que **esta instalación** usa (`config.plataformas_activas()`),
no una lista fija: con la tienda Rappi Común sin configurar son dos columnas.

Si no hay alias cargado, se usa el nombre canónico en ambas.

**Un producto con alias en las dos plataformas es un plato que se apaga con un
solo botón; uno con alias en una sola existe solo ahí** (la UI le muestra el
chip gris "—" en la otra). Eso se cambia desde la pantalla Carta, o por API:

```
POST /api/vincular   {"pedidosya": "Agua sin gas 500 ml", "rappi": "Agua mineral 500 ml"}
POST /api/vincular   {"nombres": {"pedidosya": "...", "rappi": "...", "rappi_comun": "..."}}
POST /api/separar    {"producto_id": 12, "plataforma": "rappi"}
POST /api/agregar    {"plataforma": "rappi", "nombre_remoto": "Wok de vegetales"}
GET  /api/catalogo   qué nombre tiene cada producto en cada portal
```

## API del cierre y de los ajustes

```
POST /api/masivo          {"accion": "apagar_hoy", "plataformas": ["pedidosya"]}
GET  /api/masivo/previo?accion=apagar_hoy    cuántos tocaría cada portal
GET  /api/config          los ajustes con su definición y su valor actual
POST /api/config          {"cambios": {"minutos_ronda": 30}}
POST /api/config/restablecer
GET  /api/alertas         lo que la app da por apagado y no puede confirmar,
                          y lo que quedó apagado en una tienda de Rappi y
                          prendido en la otra (`sin_espejo`)
```

`/api/masivo` acepta además `releer`, `incluir_pausados` y `solo_propios` para
forzar el comportamiento sin tocar la configuración guardada.

---

# TAREAS PENDIENTES (para completar en Claude Code)

Con Chrome abierto en los dos portales, hay que:

## 0. PedidosYa solo expone una categoría a la vez  ← RESUELTO

Se recorren las categorías (`wk-menu-list wk-menu-list-category-item`) y se
recuerda en cuál apareció cada producto. Confirmado en vivo: `/api/carta` leyó
todos los productos de las categorías existentes, incluyendo un producto que
estaba en una categoría que no había sido abierta todavía.

**Cuidado con una trampa que ya mordió:** el fallback JS de `clickear()` no
sirve tal cual para las categorías. El listener no está en el custom element
sino en un hijo, y los eventos suben pero no bajan: un `el.click()` sobre
`<wk-menu-list-category-item>` no hace nada. Por eso existe el click
"profundo", que dispara sobre el descendiente más profundo del centro.
Está cubierto por `pruebas/probar_pedidosya.py`.

## 1. PedidosYa (`plataformas/pedidosya.py`)

URL: `https://web-ar.us.restaurant-partners.com/menus/PY_AR/<tu-id-de-menú>`
(el id sale de Ajustes; ver «Primera vez»)

- [x] `_fila()`: confirmado, es el `<label class="mat-slide-toggle-label">`
      de Angular Material (envuelve nombre + toggle). **Cuidado con los
      nombres que son prefijo de otros** ("Empanada de carne" vs "Empanada de
      carne chica") — por eso se usa `exact=True`.
- [x] `leer_estado()`: confirmado, el toggle es un `<mat-slide-toggle>` con
      `aria-checked="true"/"false"` sobre el `<input>`.
- [x] `asegurar_sesion()`: confirmado, PedidosYa no tiene pantalla de sesión
      expirada — se re-loguea solo. Se deja el chequeo de password como red
      de seguridad. El elemento que prueba que el menú cargó espera
      `input.mat-slide-toggle-input`.
- [x] `prender()`: **confirmado en vivo**. No abre ningún popup: el click
      sobre el toggle apagado lo prende y queda guardado. El popup de dos
      opciones es solo del lado de apagar, porque ahí hay que elegir "por
      hoy" o "indefinidamente".

El popup de apagado ya está confirmado por captura: al clickear el toggle de
un producto prendido aparece un único popup con "No disponible por hoy" y
"No disponible indefinidamente" (sin paso de confirmación extra).

**Reconfirmar después de recargar.** `_confirmar()` (en `base.py`, compartido
con Rappi) rehace la preparación del arranque después del reload: cierra el
popup de sonido —que vuelve en cada carga— y espera a que el menú exista.
Dormir 4 segundos no alcanzaba: la relectura caía sobre la página tapada y en
la primera categoría, no encontraba el producto, y daba por fallado un cambio
que sí había entrado (se detectó un caso donde la operación dio "fallo" y el
reintento lo encontró prendido).

## 2. Rappi (`plataformas/rappi.py`)

URL: `https://partners.rappi.com/menu?brandId=<tu-brand>&storeIds=<tu-tienda>`
(los dos salen de Ajustes; ver «Primera vez»)

**Una instancia de la clase = UNA tienda.** Si tu local tiene las dos tiendas
de Rappi, el worker abre **dos pestañas** con dos `storeId` distintos (ver
«Las dos tiendas de Rappi»), y no una sola que va cambiando el `storeId` en la
URL: así cada tienda tiene su lock, su sesión y su estado, y la lectura de una
no pisa la de la otra. Son tiendas independientes y su carta **no** es la
misma.

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

### Estado de tienda de Rappi (badge 🟢/🔴 del header) — FALTA UN PASO TUYO

El 2026-07-30 las dos tiendas de Rappi mostraban «sin datos» mientras
PedidosYa andaba. **Causa encontrada:** la pantalla de Conectividad no es una
tabla. El código buscaba `<td>Estado</td>` + la celda siguiente (leído de una
captura) y encontraba **cero** celdas siempre. El DOM real es un div suelto:

```html
<div class="sc-papXJ iobIXi rcf-typography-caption2 portal207"
     color="neutrals.grays.gray50" data-testid="test-typography">Cerrada</div>
```

Las clases son generadas y el `data-testid` lo comparte **todo** texto del
portal, así que ahora se busca por **texto** («Activa» / «Cerrada» /
«Suspendida») y se desempata por el nombre de la tienda, midiendo cuál está
más cerca — no alcanza con «algún ancestro contiene el nombre», porque
subiendo lo suficiente se llega al contenedor de todas las tarjetas y con dos
tiendas las dos daban positivo. Cubierto sin portal por
`pruebas/probar_rappi_conectividad.py` (14 casos, contra una réplica del DOM
real).

**Lo que falta, y lo tenés que hacer vos** (no se puede confirmar sin entrar
al portal con tu cuenta):

1. Actualizá (`actualizar.ps1` o el `.bat`) y abrí
   `localhost:8001/api/estado-tienda?plataforma=rappi` y lo mismo con
   `plataforma=rappi_comun`.
2. Si sale `{"abierta": true/false}`, listo: el badge del header ya anda.
3. Si sale `{"abierta": null, ...}`, **ahora viene con `motivo`**, que dice
   cuál de los pasos falló, y con `diagnostico`. Los tres casos:
   - *«no encontré ningún texto de estado conocido»* → Rappi los escribe de
     otra forma. El diagnóstico trae `textos_en_pantalla`: buscá ahí cómo
     figura el estado y hay que agregarlo a `ESTADOS_TIENDA_ABIERTA` /
     `ESTADOS_TIENDA_CERRADA` en `plataformas/rappi.py`.
   - *«la pantalla muestra N tiendas y no hay nombre de tienda cargado»* →
     cargá en Ajustes → «Estado de tienda» el nombre EXACTO de la tienda tal
     cual figura en Administración → Conectividad.
   - *«Conectividad no se quedó en la tienda …»* → el `brandId` de esa
     pantalla es otro. Entrá a Conectividad, copiá el `brandId` de la URL y
     ponelo en el ajuste correspondiente (hay uno para Turbo y otro para
     Común; ver «brandId … en Conectividad»).

El badge nunca inventa: ante cualquier duda queda ⚪ «sin datos», y ahora el
tooltip dice el motivo.

## 3. El mapeo de nombres

El mismo plato casi nunca se llama igual en los dos portales, y ahí es donde
se rompen las cosas. Esto no es una lista para completar: es lo que ya mordió,
para que no vuelva a morder.

`app/seed.py` viene **vacío**: el catálogo lo arma la app leyendo los portales
(ver «Primera vez»), y desde la pantalla Carta se vincula y se separa. Lo que
sigue vale igual, porque el problema es de los nombres, no de dónde salen.

### Las trampas confirmadas

- **Los nombres son prefijo de otros.** "Empanada de carne" es prefijo de
  "Empanada de carne chica": buscar sin `exact=True` apaga el que no era. Ya
  pasó de verdad. Por eso todo se busca exacto.
- **Las tildes cuentan.** Los nombres se buscan con `exact=True`, así que
  "Budin de pan" no encuentra a "Budín de pan". El nombre hay que copiarlo
  **tal cual lo escribe el portal** — que es lo que hace la pantalla Carta, y
  por eso conviene cargar desde ahí y no a mano.
- **Los typos del portal son parte del nombre.** Si el portal tiene un
  producto mal escrito, ese es su nombre: copiarlo "bien" hace que no se
  encuentre nunca.
- **Dos variantes parecidas pueden ser platos distintos.** "chica",
  "individual", "porción" puntúan altísimo entre sí y no son lo mismo. Por eso
  lo dudoso queda **separado** en la pantalla Carta, con un botón cada uno, y
  lo vincula el usuario. Un emparejado automático de más significa apagar un
  plato que se sigue vendiendo.
- **`con` y `sin` no son ruido.** Son lo único que distingue "Agua con gas" de
  "Agua sin gas".
- **Un producto puede existir en un portal y en el otro no.** La UI lo muestra
  con un chip gris "—" en el que falta. Si un día aparece en el otro, la app
  avisa (ver «Cuando agregás un producto a la carta de un portal»).
- **Entre las dos tiendas de Rappi el mismo parecido significa otra cosa.**
  Las dos se cargan desde el mismo panel, así que el mismo plato suele estar
  escrito **igual**: una diferencia de texto es más probable que sea otro
  plato y no la misma cosa dicha distinto. Por eso ahí se exige 0.95 y no
  0.82. La trampa concreta: "Empanada de carne" contra "Empanada de carne
  chica" puntúa 0.91 — entre PedidosYa y Rappi eso se empareja solo y está
  bien; entre las dos tiendas de Rappi sería apagar la grande creyendo que
  apagás la chica, y con el agravante de que la carta de la segunda tienda se
  mira mucho menos.

### Las categorías no coinciden

Cada portal agrupa a su manera: lo que en uno está bajo "Platos" en el otro
puede estar bajo "Plato del Día". Todo-Selector usa su propia categoría, que es
solo visual y no afecta la búsqueda.

Ojo con PedidosYa: expone **una categoría a la vez**, así que para llegar a la
carta entera hay que recorrerlas (ver el punto 0).

## 4. Pendientes de producto

- [x] Botón de "apagar todo" al cierre. Hecho, y **por plataforma**: a veces
      PedidosYa tiene que apagarse antes que Rappi. Ver "Apagar todo".
- [x] Sincronizar el estado real al arrancar. Hecho: al levantar, la app lee
      los dos portales y guarda cómo está cada producto. Ver más arriba.
- [ ] Mostrar el historial en pantalla (la API ya lo devuelve).
- [x] **Sacar del código los datos del local.** Hecho: el id de menú de
      PedidosYa y el `brandId`/`storeId` de Rappi salen de Ajustes (cambiarlos
      no pide reiniciar la app), y `app/seed.py` quedó vacío — una instalación
      nueva arranca sin catálogo y lee el suyo. Ver «Primera vez».
- [x] **Rappi Común, además de Rappi Turbo.** Hecho (2026-07-29). Es una
      tercera plataforma opcional: se prende cargando `rappi_comun_store_id`
      en Ajustes y de ahí para adelante es una plataforma como las otras
      (pestaña propia, chip propio, fila propia en «Apagar todo», cola y
      reverificación). **Vacío —el default— es como si no existiera.**
      La pantalla Carta lee las tres y deja vincular las tres, que era lo
      que le faltaba. Ver «Las dos tiendas de Rappi».
- [x] **Ajustes y Carta como pantallas propias, no desplegables.** Hecho
      (2026-07-30). Tapan todo el dashboard mientras están abiertas y
      tienen su propia URL (`/ajustes`, `/carta`, vía `history.pushState`),
      con un botón "← Volver". "Apagar todo" no se tocó, sigue como panel
      de siempre.
- [ ] **Rediseñar la estética de la aplicación.** Pedido del usuario
      (2026-07-30), para más adelante: **recién cuando lo funcional esté
      terminado**. No tocar esto todavía.

## Nota sobre términos de servicio

Rappi y PedidosYa prohíben el acceso automatizado en sus términos. Esto
automatiza lo que ya hacés a mano con tu propio login, pero la cuenta es del
local y el riesgo existe.
