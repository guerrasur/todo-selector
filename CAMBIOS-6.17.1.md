# 6.17.1 — pausa ante la verificación humana de PedidosYa

- Detecta el aviso «Before we continue… / Press & Hold», incluso si el
  iframe interior está oculto y el contenedor sigue visible.
- Conserva la pestaña para que la persona complete la verificación: no
  recarga, navega, cierra el aviso ni intenta resolverlo automáticamente.
- Si interrumpe una operación, la conserva pendiente sin gastar intentos.
- Muestra instrucciones específicas y retoma la cola cuando desaparece el
  desafío y vuelve el menú visible. Cada operación relee el producto al
  ejecutarse mediante el flujo existente de prender/apagar.
- Mantiene la salida manual de las verificaciones por código de Rappi.

Validado con 12 pruebas de bloqueo/cola, regresiones de verificación y
alertas, e instrucciones y sintaxis del frontend. Falta validar en el portal
real. No se agregaron dependencias de producción.
