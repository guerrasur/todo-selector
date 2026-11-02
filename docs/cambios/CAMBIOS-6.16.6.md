# 6.16.6 — Diagnóstico con todas las categorías desplegadas

El diagnóstico anterior leía correctamente 13 ensaladas de cada tienda.
Las otras categorías estaban plegadas: sus productos no estaban disponibles
para esa lectura. El HTML aportado permite identificar el botón del título
mediante aria-expanded, excluyendo switches y menús de disponibilidad.

Esta versión despliega las categorías cerradas antes de capturar la carta.
No modifica disponibilidad ni precios; conserva la pausa de Rappi y sus
órdenes pendientes sin gastar intentos. PedidosYa sigue funcionando.

El log agrega DIAG_RAPPI_ANTES con las categorías y los productos iniciales.
DIAG_RAPPI_RESUMEN muestra luego las categorías abiertas y todos los productos
detectados; DIAG_RAPPI_FILA conserva la comparación de ambos lectores.
Si un clic no reduce las categorías cerradas, se detiene y registra error
sin seguir pulsando. La apertura no requiere recargar ni aplicar filtros.

Actualizar, reiniciar y enviar desde RAPPI DIAGNOSTICO hasta ambos
DIAG_RAPPI_FIN, incluyendo cualquier DIAG_RAPPI_ERROR. No es necesario abrir
las categorías a mano ni enviar operaciones de prueba.

Validación local: selectores ejecutados sobre HTML de encabezados con título,
switch, personalización y menú more; flujo idempotente, parada por falta de
progreso o cambio de tienda; captura del DOM y guardas de la cola. Falta
validar el resultado de esta apertura en el navegador del usuario.
