# Todo-Selector 6.11.1 — lectura de precios

La captura del usuario mostró 28 filas con `Precio:` como nombre y un supuesto
nombre repetido. El lector elegía el primer ancestro del toggle con precio:
en Rappi ese elemento puede ser el footer, separado de la foto y el nombre.

La búsqueda ahora sigue hasta encontrar identidad del producto y un único
control de disponibilidad. Usa el alt de la foto ya observado en el DOM o el
nombre asociado al SKU cuando no hay foto. Nunca toma el rótulo Precio como
identidad. La misma búsqueda ubica la tarjeta del lápiz para la edición.
Se mantienen los controles de nombres duplicados, id, tienda, precio previo
y verificación por recarga. PedidosYa sigue excluido de precios beta.

La lectura agrega un resumen y hasta diez diagnósticos de filas al log. Un
HTTP 200 puede contener resultados parciales o filas con errores; esos errores
ahora también quedan visibles en la terminal.

La réplica local admite encabezado y footer separados, y el lápiz en otro
contenedor. La regresión reprodujo el defecto antes del arreglo. Validación:
14 pruebas de adaptador con Chromium, 21 de planes/lotes y pantalla/API completas
en modo simulado. No se escribió ningún precio en cuentas reales.

Actualizar cerrando y abriendo `iniciar_app.bat`, comprobar versión 6.11.1 y
volver a **Actualizar carta → Precios (beta) → Leer precios**.
