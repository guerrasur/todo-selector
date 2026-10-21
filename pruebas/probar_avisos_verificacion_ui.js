// node pruebas/probar_avisos_verificacion_ui.js — sin portales ni dependencias.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../static/index.html'), 'utf8');
const avisos = [], notas = [], timers = new Map(), frecuencias = [];
let id = 0;
class AudioContext {
  constructor() { this.currentTime = 0; }
  createOscillator() { return {frequency: {set value(f) { frecuencias.push(f); }}, connect() {}, start() {}, stop() {}}; }
  createGain() { return {gain: {setValueAtTime() {}, exponentialRampToValueAtTime() {}}, connect() {}}; }
}
class Notification {
  static permission = 'granted';
  constructor(title, options) { notas.push({title, ...options}); }
}
const c = {
  document: {title: 'Todo-Selector'}, window: {AudioContext}, Notification,
  NOMBRE_PLAT: {pedidosya: 'PedidosYa', rappi: 'Rappi'}, PLATS: ['pedidosya', 'rappi'],
  setInterval(fn) { timers.set(++id, fn); return id; },
  clearInterval(key) { timers.delete(key); },
};
vm.createContext(c);
vm.runInContext(html.slice(html.indexOf('const TITULO_NORMAL ='), html.indexOf('// producto_id')), c);
const actualizar = (verificacion = {}, sesiones = {}, extra = {}) =>
  c.actualizarAvisosSistema({verificacion, sesiones, ...extra});
const humana = {pedidosya: {origen: 'captcha'}};
actualizar(humana, {pedidosya: false});
assert.equal(notas.length, 1);
assert.match(notas[0].title, /PedidosYa.*humano/);
assert.match(notas[0].body, /Press & Hold/);
assert.doesNotMatch(notas[0].body, /loguear|código/);
assert.deepEqual(frecuencias, [523.25, 659.25, 783.99]);
actualizar(humana, {pedidosya: false});
assert.equal(notas.length, 1, 'el sondeo no repite el aviso');
[...timers.values()][0]();
assert.match(c.document.title, /verificación humana/);
actualizar(humana, {pedidosya: false, rappi: false});
assert.equal(notas.length, 2);
assert.match(notas[1].title, /sesión caída/);
assert.match(notas[1].body, /Rappi/);
assert.deepEqual(frecuencias.slice(3), [880, 880]);
[...timers.values()][0]();
[...timers.values()][0]();
assert.match(c.document.title, /Verificación humana.*Login pendiente/);
actualizar({}, {rappi: false});
[...timers.values()][0]();
[...timers.values()][0]();
assert.match(c.document.title, /Login pendiente/);
assert.doesNotMatch(c.document.title, /humana/);
actualizar();
assert.equal(timers.size, 0);
assert.equal(c.document.title, 'Todo-Selector');
actualizar(humana);
assert.equal(notas.length, 3, 'una nueva verificación vuelve a avisar');
actualizar();
actualizar({rappi: {origen: 'manual'}}, {rappi: false});
actualizar({}, {pedidosya: false}, {falta_sucursal: ['pedidosya']});
actualizar(humana, {rappi: false}, {simulado: true});
assert.equal(notas.length, 3, 'sin alertas falsas por 2FA, configuración o simulación');
Notification.permission = 'denied';
actualizar(humana);
assert.equal(notas.length, 3);
assert.equal(timers.size, 1, 'sin permiso siguen el sonido y el título');
actualizar();
c.Notification = class { static permission = 'granted'; constructor() { throw Error('no disponible'); } };
assert.doesNotThrow(() => actualizar(humana));
assert.equal(timers.size, 1, 'un fallo de notificación no corta la actualización');
console.log('Avisos distintos, sonido, transiciones, permisos y título OK');
