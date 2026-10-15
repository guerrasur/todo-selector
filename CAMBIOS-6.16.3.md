# v6.16.3 — Secuencia de Marca, Tienda y Aplicar filtro

El log de 6.16.2 fallaba al pedir por segunda vez la lista de Marca, antes
de alcanzar Aplicar filtro. No se verificaba el cierre por Escape: el
siguiente click podía cerrar una lista que aún estaba abierta.

La apertura ahora es idempotente y reutiliza listas abiertas. Para cerrar,
se pulsa el disparador de ese campo y se confirma que la lista desapareció.
Se distingue el dropdown de Marca del que contiene store-list. Después de
verificar una única tienda elegida, se pulsa Aplicar filtro una vez,
incluso si ya era la tienda actual. La confirmación sigue exigiendo URL,
nombre visible y carga de productos; solo se recarga al cambiar de tienda.

Verificación: flujo de alternancia de ambas tiendas con opciones que cierran
el dropdown y con opciones que lo dejan abierto, cierre sin Escape,
reutilización de lista y aplicación de la tienda actual. Suites de selección
y geometría, compilación y diff aprobados. Falta validación en el portal real.
