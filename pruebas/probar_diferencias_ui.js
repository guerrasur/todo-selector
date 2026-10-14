// node pruebas/probar_diferencias_ui.js — botón y repintado durante el envío.
const fs = require('node:fs'), vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync(require('node:path').join(__dirname, '../static/index.html'), 'utf8');
const start = html.indexOf('let prendiendoDiferencias =');
const end = html.indexOf('\nfunction ', html.indexOf('function pintarAlertas(alertas)') + 1);
class Element {
  constructor() { this.children = []; this.style = {}; this.textContent = ''; }
  append(...elements) { this.children.push(...elements); }
  appendChild(element) { this.children.push(element); }
  set innerHTML(value) { this.children = []; }
}
const panel = new Element();
function find(e, id) {
  if (e.id === id) return e;
  for (const child of e.children || []) {
    const found = find(child, id); if (found) return found;
  }
}
let finish, calls = 0, refreshed = 0;
const alerts = [];
const ctx = {
  document: {getElementById: id => id === 'panel-alertas' ? panel : find(panel, id),
             createElement: () => new Element()},
  NOMBRE_PLAT: {pedidosya: 'PedidosYa', rappi: 'Rappi'},
  fetch: async (url, options) => {
    calls++; assert.equal(url, '/api/prender-diferencias');
    assert.equal(options.method, 'POST');
    return new Promise(resolve => { finish = () => resolve({ok: true, json: async () => ({salteadas: []})}); });
  },
  cargar: async () => { refreshed++; }, alert: text => alerts.push(text),
};
vm.createContext(ctx); vm.runInContext(html.slice(start, end), ctx);
const data = {sin_espejo: [{producto_id: 1, producto: 'Ensalada',
  apagada_en: 'pedidosya', prendida_en: 'rappi', nombre_remoto: 'Ensalada'}]};
(async () => {
  ctx.pintarAlertas(data);
  const button = find(panel, 'btn-prender-diferencias');
  assert.equal(button.textContent, 'Prender los que tienen diferencia');
  const pending = button.onclick();
  assert(button.disabled);
  ctx.pintarAlertas(data);
  const repainted = find(panel, 'btn-prender-diferencias');
  assert(repainted.disabled);
  await repainted.onclick(); assert.equal(calls, 1);
  finish(); await pending;
  assert.equal(refreshed, 1); assert.deepEqual(alerts, []);
  ctx.pintarAlertas(data); assert(!find(panel, 'btn-prender-diferencias').disabled);
  ctx.pintarAlertas({}); assert.equal(panel.style.display, 'none');
  ctx.pintarAlertas({sesiones_caidas: ['rappi']});
  assert(!find(panel, 'btn-prender-diferencias'));
  console.log('UI OK: botón, bloqueo durante repintado, envío único y resolución');
})().catch(error => { console.error(error); process.exitCode = 1; });
