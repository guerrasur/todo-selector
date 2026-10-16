# 6.17 — Un producto, una fila y estado de tiendas Rappi

- Las filas con plataformas sin vincular o publicaciones repetidas se muestran
  en Vínculos pendientes. Desde ahí se completan en Carta, sin botones de
  disponibilidad separados para cada copia.
- Las propuestas y la vinculación manual reúnen todas las plataformas activas.
  Se puede indicar un nombre común; el borrador se conserva al repintar.
- Renombrar mantiene los nombres exactos usados para buscar cada publicación.
  Una misma publicación no se elige silenciosamente entre varias filas; los
  cambios de vínculos se serializan para evitar creaciones simultáneas.
- Carta permite reiniciar opcionalmente con vista previa, backup y deshacer.
  Es una limpieza inicial si se necesita; actualizar no borra ni reinicia datos.
- Rappi vuelve a informar el estado de sus tiendas desde Gestión de tiendas.
  Lee nombre exacto, badge y checkbox, sin tocar los interruptores. Las
  consultas esperan a que termine la tanda y respetan la verificación manual.
- La cabecera muestra «abierta» o «cerrada» junto al indicador de cada tienda.

Verificado con SQLite aislado, DOM de prueba y regresiones de catálogo,
duplicados, cola y verificación. La nueva lectura de tiendas requiere
validación en el portal real.
