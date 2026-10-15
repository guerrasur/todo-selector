# v6.16 — Rappi con tienda compartida y cola por tandas

- Una pestaña para Turbo y Común; todos los accesos usan el mismo lock,
  incluidos diagnósticos, lecturas y precios. No cierra la pestaña al quitar Común.
- Selección por ids de los radios del filtro de marca/tienda. Busca la tienda
  exacta en las marcas disponibles, sin elegir por nombre parcial ni posición.
- Confirma una sola tienda elegida, URL y nombre del selector. Recarga después
  de cambiar para no aceptar productos cargados de la tienda anterior.
- Antes de los clics de disponibilidad vuelve a comprobar tienda y selector.
- Tandas finitas: pendientes de Turbo primero, luego Común. Órdenes nuevas
  esperan la siguiente tanda; fallos, cancelaciones y reintentos demorados no
  bloquean los restantes. Se conserva la última intención por producto/tienda.

Validación: 5 pruebas de tanda/pestaña/lock con SQLite temporal; 6 de selección
con filtro controlado; 17 regresiones de cancelaciones, última intención y
reverificación; suite de verificación en dos pasos; prueba de URLs y compilación.
No se operó sobre tiendas reales. La prueba visual de navegador no se pudo
realizar: la descarga de Chromium del entorno no entrega un archivo válido.
El diálogo de duración del apagado aún necesita confirmación en vivo.

Actualizar cerrando la app y volviendo a abrir iniciar_app.bat. Comprobar 6.16.
No se borra catálogo ni configuración y no se copian ids de locales al repo.
