# 6.17.4 — relectura al superar el bloqueo de PedidosYa

La salida automática del CAPTCHA llamaba `terminar_verificacion(leer=False)`:
retomaba la cola sin confirmar la carta. Los apagados conservaban su fecha
vieja y `/api/alertas` seguía avisando «sin confirmar».

- Activa la lectura en background al desaparecer el desafío y volver el menú.
  Usa el bloqueo existente, después de liberar el sondeo, sin recargar la
  pestaña recién recuperada por antigüedad.
- Respeta operaciones en curso y el ajuste `sostener_apagados`; los revividos
  pasan por la confirmación y las guardas de última intención existentes.
- Si aparece otro CAPTCHA durante la lectura, vuelve a congelar PedidosYa
  sin guardar esa pasada ni actualizar su hora de lectura.
- Una carta sin categorías o sin productos leídos devuelve error; no se
  presenta como una lectura completa ni inventa faltantes del catálogo.
- Los avisos se resuelven al confirmar los productos. Un faltante real o un
  estado que no se pudo verificar conserva su advertencia.

Validación: 17 pruebas de CAPTCHA, cola y relectura, incluido el aviso real de
la API contra SQLite aislada; regresiones de estados, verificación manual,
última intención, alertas y UI de acciones/avisos. Sin dependencias nuevas.
No validado en el portal real. La prueba HTML con Chromium no pudo arrancar
porque el entorno impide crear el socket del navegador.
