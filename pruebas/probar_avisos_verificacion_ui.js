// node pruebas/probar_avisos_verificacion_ui.js — sin portales ni dependencias.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../static/index.html'), 'utf8');
const notas = [], timers = new Map(), frecuencias = [], eventos = {};
let contextos = 0, reanudaciones = 0;
let id = 0;
class AudioContext {
  constructor() { this.currentTime = 0; this.state = "suspended"; contextos++; }
  resume() { this.state = "running"; reanudaciones++; return Promise.resolve(); }
  createOscillator() { return {frequency: {set value(f) { frecuencias.push(f); }}, connect() {}, start() {}, stop() {}}; }
  createGain() { return {gain: {setValueAtTime() {}, exponentialRampToValueAtTime() {}}, connect() {}}; }
}
class Notification {
  static permission = 'granted';
  constructor(title, options) { notas.push({title, ...options}); }
}
const c = {
  document: {title: 'Todo-Selector', addEventListener: (tipo, fn) => { eventos[tipo] = fn; }}, window: {AudioContext}, Notification,
  NOMBRE_PLAT: {pedidosya: 'PedidosYa', rappi: 'Rappi'}, PLATS: ['pedidosya', 'rappi'],
  setInterval(fn) { timers.set(++id, fn); return id; },
  clearInterval(key) { timers.delete(key); },
};
vm.createContext(c);
vm.runInContext(html.slice(html.indexOf('const TITULO_NORMAL ='), html.indexOf('// producto_id')), c);
const actualizar = (verificacion = {}, sesiones = {}, extra = {}) =>
  c.actualizarAvisosSistema({verificacion, sesiones, ...extra});
const humana = {pedidosya: {origen: 'captcha'}};
eventos.pointerdown();
assert.equal(contextos, 1);
assert.equal(reanudaciones, 1);
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
actualizar({}, {pedidosya: false}, {motivos_sesion: {pedidosya: 'menu_no_cargo'}});
assert.equal(notas.length, 3, 'un menú sin cargar no pide iniciar sesión');
assert.equal(contextos, 1, 'se reutiliza el contexto de audio');
Notification.permission = 'denied';
actualizar(humana);
assert.equal(notas.length, 3);
assert.equal(timers.size, 1, 'sin permiso siguen el sonido y el título');
actualizar();
c.Notification = class { static permission = 'granted'; constructor() { throw Error('no disponible'); } };
assert.doesNotThrow(() => actualizar(humana));
assert.equal(timers.size, 1, 'un fallo de notificación no corta la actualización');
console.log('Avisos distintos, sonido, transiciones, permisos y título OK');

// Ejercita también el badge real del dashboard, no solo el emisor de avisos.
const elementos = new Map();
c.document.getElementById = key => {
  if (!elementos.has(key)) elementos.set(key, {textContent: '', classList: {toggle() {}}});
  return elementos.get(key);
};
Object.assign(c, {
  arrastrando: false, colaAbierta: false,
  nombrarPlataformas() {}, actualizarBotonVerificacion() {}, pintarTiendas() {},
});
vm.runInContext(html.slice(html.indexOf('function pintarSistema(s)'), html.indexOf('function hora(iso)')), c);
const pintar = (verificacion, sesiones = {}, motivos_sesion = {}) => c.pintarSistema({
  verificacion, sesiones, motivos_sesion, plataformas: ['pedidosya', 'rappi'],
});
pintar(humana, {pedidosya: false});
assert.match(elementos.get('estado-sistema').textContent, /Verificación humana pendiente: PedidosYa/);
assert.doesNotMatch(elementos.get('estado-sistema').textContent, /código/);
pintar({...humana, rappi: {origen: 'manual'}});
assert.match(elementos.get('estado-sistema').textContent, /humana.*PedidosYa.*código.*Rappi/);
pintar({}, {pedidosya: false}, {pedidosya: 'menu_no_cargo'});
assert.match(elementos.get('estado-sistema').textContent, /No cargó el menú: PedidosYa/);
assert.doesNotMatch(elementos.get('estado-sistema').textContent, /Conectado|Login/);
pintar({}, {rappi: false});
assert.match(elementos.get('estado-sistema').textContent, /Login pendiente: Rappi/);
pintar({});
assert.equal(elementos.get('estado-sistema').textContent, 'Conectado');
console.log('Badge del dashboard: CAPTCHA, código, menú sin cargar y sesión caída OK');
