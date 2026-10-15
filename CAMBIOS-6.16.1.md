# v6.16.1 — Apertura y cierre del filtro de Rappi

El drawer cerrado sigue en el DOM con tamaño y Playwright lo considera
visible aunque esté desplazado fuera de la pantalla. La versión anterior
intentaba operar dentro de ese drawer sin abrirlo y podía perder el error
original al intentar cerrar su botón Close durante 30 segundos.

Ahora se comprueba la intersección del panel con el viewport antes de usarlo;
se abre con store-select cuando está desplazado. Se confirma el cierre por
su posición, y Close tiene espera breve y un fallback al handler del botón.
Si falla la limpieza se conserva y registra la excepción original de selección.

Verificación: 7 regresiones de geometría/apertura/cierre/errores y 6 pruebas
del flujo de selección aprobadas; compilación Python y diff correctos.
No se realizó una operación contra el portal real.
