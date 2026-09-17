// Ejecutar: node pruebas/probar_accion_ui.js (sin navegador ni dependencias).
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../static/index.html'), 'utf8');
const begin = html.indexOf('async function accion(producto_id, accion, plataformas)');
const end = html.indexOf('\n}\n', begin) + 2;
const source = html.slice(begin, end);
let checks = 0;
async function test(response, expected, refreshFails = false) {
  const alerts = [];
  let refreshed = false;
  const context = {
    NOMBRE_PLAT: {rappi: 'Rappi'},
    alert: text => alerts.push(text),
    cargar: async () => { refreshed = true; if (refreshFails) throw new Error('offline'); },
    fetch: async () => { if (response instanceof Error) throw response; return response; },
  };
  vm.createContext(context);
  vm.runInContext(source, context);
  await context.accion(1, 'apagar_hoy', ['rappi']);
  if (expected) assert.match(alerts.join(' '), expected);
  else assert.equal(alerts.length, 0);
  checks++;
  return refreshed;
}
(async () => {
  assert.equal(await test({ok:false, json:async () => ({detail:'producto no encontrado'})}, /producto no encontrado/), false);
  await test(new Error('offline'), /Revisá la cola/);
  await test({ok:true, json:async () => ({encoladas:[], salteadas:[{plataforma:'rappi', motivo:'la tienda está en pausa'}]})}, /Rappi: la tienda está en pausa/);
  await test({ok:true, json:async () => ({encoladas:[], salteadas:[{plataforma:'rappi', motivo:'ya estaba encolada'}]})});
  assert.equal(await test({ok:true, json:async () => ({encoladas:['rappi'], salteadas:[]})}), true);
  await test({ok:true, json:async () => ({encoladas:['rappi']})}, /fue recibida.*refrescar/, true);
  console.log(`${checks} casos UI OK`);
})().catch(error => { console.error(error); process.exitCode = 1; });
