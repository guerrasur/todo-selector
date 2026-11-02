# v6.15 — Portal Aliados de Rappi

- Navegación a restaurantes.rappi.com/menu con storeIds de la tienda configurada.
- Validación exacta de tienda; conserva reconocimiento del portal anterior.
- Detecta los botones role=switch dentro de menu-item-availability-switch.
- Lee nombres desde el texto de la fila, incluso con imágenes sin alt.
- Detecta filas duplicadas sin depender de ids que el nuevo portal ya no publica.
- Lee aria-checked; no confunde data-state=closed del popup con disponibilidad.
- Reconoce diálogos semánticos al limpiar un popup pendiente.

Validación: prueba de URLs y comprobación XPath de una réplica estructural
con nombres ficticios. Compilación Python correcta. La prueba de navegador
incluida no pudo ejecutarse en el entorno de desarrollo: Chromium falla al
arrancar. Pendiente validar en vivo el diálogo de duración y la confirmación
del apagado. No se inventaron selectores de esos diálogos. Categorías, precios
y Conectividad mantienen sus lectores anteriores y requieren HTML del nuevo
portal para adaptarlos cuando corresponda.
