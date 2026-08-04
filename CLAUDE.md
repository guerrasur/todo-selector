# Todo-Selector — contexto para Claude Code

App local que apaga/prende productos en PedidosYa y Rappi desde una sola
pantalla. Reemplaza el trabajo manual de entrar a cada portal.

## Estado actual

**En uso.** Las cuatro operaciones (leer la carta, apagar y prender) corrieron
en vivo contra los dos portales el 2026-07-27. Queda un `TODO-SELECTOR` en
`plataformas/rappi.py`: el HTML completo de la tarjeta y la pantalla de sesión
expirada.

El catálogo ya no se mantiene a mano: la pantalla **Carta** lee los dos
portales y el usuario vincula o separa desde ahí (`app/catalogo.py`). En
cuanto toca algo, `seed.py` deja de pisar los alias.

**`app/seed.py` viene VACÍO a propósito** (2026-07-29). El repo es público y
una instalación nueva no puede arrancar con la carta ni con la sucursal de
otro local: arranca sin nada y la pantalla ofrece los dos pasos de primer
arranque (decir qué local sos → leer tu carta). Los ids de sucursal tampoco
tienen default. Las pruebas traen su propia carta inventada, en
`pruebas/catalogo_ejemplo.py` y `pruebas/carta_ejemplo.json`.

**Apagar todo** (`app/cierre.py`) apaga o prende la carta entera de **las
plataformas que elijas**, con un botón por destino: a veces PedidosYa tiene
que apagarse antes que Rappi. Con las dos tiendas de Rappi los destinos son
cinco (cada una sola, «Ambos Rappi» y «Todas»). Nunca encola lo que ya está
como quiere quedar, lo pausado, ni lo que ya está en la cola. **«Apagado» no
es un solo estado**: lo que está apagado *por hoy* SÍ se reencola cuando lo
que se pide es indefinido — el portal lo revive solo mañana, y saltearlo
dejaba media tienda prendida justo cuando se la quería desactivar.

**Una tienda entera se puede pausar** (2026-08-04, `cfg_tienda_pausada_*`):
la app deja de **prenderla** —ni de a un producto ni con «Prender todo»—
hasta que la reactives. Sigue **activa**: se lee, se puede apagar (que es lo
que hace falta para dejarla apagada) y se ve en la pantalla; sacarla de
`plataformas_activas()` la volvería invisible y entonces no habría ni cómo
apagarla. El corte va en el backend (`cierre.planificar` y `/api/accion`),
no solo en la pantalla: la pantalla se repinta sola, pero un click puede
salir con los datos de hace tres segundos. Una tienda en pausa tampoco
entra en el aviso de «apagado acá y prendido en la hermana»: el usuario ya
dijo que esa no va.

**Lo que se apaga es lo que elegiste, y nada más.** No hay espejos ni
propagación automática entre plataformas: si un producto está en las dos
tiendas de Rappi, un botón apaga las dos porque es el MISMO producto del
catálogo, no porque algo propague por atrás.

**Los chips ACOTAN, no habilitan** (2026-08-03). Arrancan sin marcar y el
botón actúa sobre **todos** los portales del producto, que es el caso de
todos los días. Clickeás un chip y la acción va **solo ahí** (el chip queda
con contorno y brillo, y el botón dice «· solo PedidosYa»); lo clickeás de
nuevo y lo soltás. Antes venían los tres marcados y el click sacaba: marcar
de arranque lo que iba a pasar igual no informa nada. Lo marcado **no** se
suelta solo al mandar la acción — si se soltara, el botón siguiente saldría
a los tres portales sin que se note.

**Rappi Común** (2026-07-29) es una tercera plataforma **opcional**: la
segunda tienda de Rappi, independiente de Turbo, que solo existe si le cargás
`rappi_comun_store_id` en Ajustes. Con el ajuste vacío no se nota en ningún
lado. Ya está completa: pestaña propia, chip propio, columna propia en la
pantalla Carta, fila propia en «Apagar todo» (más los combos «Ambos Rappi» y
«Todas»), cola y reverificación.

**Las dos tiendas de Rappi NO comparten la carta.** Apagar en una no apaga en
la otra, y un plato puede estar en una y no en la otra. Que producto de una es
cuál de la otra lo dice el catálogo (un `Producto` con alias en las dos), y lo
confirma el usuario una vez en la pantalla Carta. La app **no** empareja sola
lo dudoso: entre dos tiendas del mismo portal el umbral es 0.95 y no 0.82
(`carta.TIENDAS_DEL_MISMO_PORTAL`), porque ahí los nombres se parecen
muchísimo y emparejar de más es apagar un plato que se sigue vendiendo.

**Los ajustes** (`app/config.py`) viven en la tabla `preferencias`, con el
prefijo `cfg_`. Ahí salen el ritmo del worker y **qué sucursal es** (el id de
menú de PedidosYa y el storeId de Rappi, que antes estaban clavados en el
código). Todos los defaults son lo que la app venía haciendo, así que una
base sin ajustes guardados se comporta igual que antes.

## Tu tarea

Lo que siga en el README, sección "TAREAS PENDIENTES".

**Antes de tocar los selectores, corré las pruebas** (`pruebas/LEEME.md`):
funcionan sin los portales y en cualquier máquina.

## Migraciones

No hay Alembic, pero `init_db()` agrega solas las columnas nuevas del modelo
a las tablas ya creadas (`ALTER TABLE ADD COLUMN`). Se pueden agregar campos
sin romperle la base al usuario. **Solo agrega**: renombrar o borrar una
columna sigue sin estar cubierto.

## Reglas importantes

1. **No cambies el contrato de `plataformas/base.py`.** El worker depende de
   esos 4 métodos. Si necesitás algo más, agregalo sin romper los existentes.

2. **Preferí selectores por texto visible o rol** antes que clases CSS
   generadas. Estos portales cambian de UI seguido.

3. **Cuidado con nombres que son prefijo de otros.** "Tarta de verdura" vs
   "Tarta de verdura chica" — usar `exact=True` o el script apaga el
   equivocado. Esto ya mordió una vez.

8. **No afirmar lo que no se está viendo.** Si la lectura de la carta no
   encuentra un producto, su estado NO se pisa (una lectura mala no puede
   borrar lo que sabíamos) — pero entonces ese estado quedó viejo y la
   pantalla no puede seguir mostrándolo como un hecho de ahora. Ya costó
   un pedido de algo apagado (2026-07-28). Ver `/api/alertas`.

4. **Toda operación se confirma releyendo.** Los métodos `apagar()` y
   `prender()` devuelven True solo si el cambio se verificó recargando la
   página. No confiar en que el click alcanzó — PedidosYa a veces no guarda.
   Ojo: después de recargar hay que rehacer la preparación (cerrar el popup
   de sonido, esperar el menú). Dormir un rato fijo no alcanza y da por
   fallados cambios que sí entraron.

6. **Un click por JS sobre un custom element puede no hacer nada.** Si el
   listener vive en un hijo, el evento no le llega: los eventos suben, no
   bajan. Para eso está `clickear(..., profundo=True)`.

5. **Probá con modo simulado primero** (`STOCKSWITCH_SIMULADO=1`) si tocás
   worker o API, para no depender del navegador.

7. **La lista de la pantalla se repinta sola cada pocos segundos.** Nada que
   el usuario haya elegido puede vivir en una variable local del repintado:
   se borra sola y no se nota. Ya pasó con los chips de plataforma, que
   volvían solos a como estaban y mandaban la acción a donde el usuario no
   había pedido. Si el usuario lo eligió, va afuera del repintado (ver
   `elegidas` en `static/index.html`).

9. **Qué plataformas hay lo dice `config.plataformas_activas()`, no una
   lista escrita a mano.** `catalogo.PLATAFORMAS` es la lista de nombres
   VÁLIDOS; la de las que esta instalación usa de verdad es la otra, y las
   opcionales entran solo si el usuario las configuró. La pantalla la
   recibe en `/api/estado-sistema` → `plataformas` (ahí sale `PLATS`).
   Escribirla a mano ya hizo que a todo el mundo le apareciera un chip de
   «Rappi Común» que no usaba, y que el botón "los dos" dejara afuera a la
   tercera justo al cerrar el local (2026-07-29).

10. **Una intención vieja no se sostiene contra una nueva.** Todo lo que se
    programa para "más tarde" (la verificación a los 2 min, la ronda de 15)
    lleva congelada la acción de cuando se programó, y entre medio el
    usuario pudo haber cambiado de idea. Antes de sostener nada hay que
    mirar `est.estado`: si ya no está en `APAGADOS_PROPIOS`, no es asunto
    nuestro. Sin eso, la app le apagó al usuario algo que acababa de
    prender a mano (2026-08-03).

11. **Si el nombre llega a dos productos, no se toca ninguno.** Los
    localizadores arrancan en `get_by_text(nombre, exact=True)` y siguen
    con `.first`. Dos matches en la misma tarjeta da igual; dos matches en
    dos tarjetas es elegir al azar cuál apagar. Ahí `revisar_ambiguedad()`
    tira `NombreAmbiguo` y la operación termina en rojo con un mensaje. Un
    apagado que no ocurre y se ve es mejor que uno que cae en el plato
    equivocado.

## Datos del local

No metas en el repo la carta ni los ids de un local de verdad — ni en el
código, ni en los comentarios, ni en las pruebas. Para los ejemplos está la
carta inventada de `pruebas/catalogo_ejemplo.py`, que además reproduce las
trampas reales (prefijos, tildes, variantes que no son el mismo plato).

## Cómo probar

```
py run.py
```

Abre en `localhost:8001`. La primera vez hay que loguearse a mano en las dos
pestañas del navegador que abre la app.

## Arquitectura en una línea

UI encola una `Operacion` → worker la toma → prepara la pestaña (refresca +
verifica login) → llama al método de la plataforma → confirma releyendo →
programa una reverificación a los 2 minutos.
