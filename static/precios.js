/* Estado fuera del repintado: ni la lectura periódica ni navegar borran ediciones. */
const preciosUI = { tiendas: [], elegidas: new Set(), lectura: null,
  seleccion: new Set(), individuales: {}, modo: 'individual', alcance: 'toda',
  cantidad: '', redondeo: 'centavos', buscar: '', plan: null, lote: null,
  ocupado: false, error: '', historial: [], temporizador: null, listo: false };

async function apiPrecios(url, cuerpo) {
  const r = await fetch('/api/precios/' + url, cuerpo === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cuerpo) });
  const datos = await r.json();
  if (!r.ok) throw new Error(typeof datos.detail === 'string' ? datos.detail : 'No se pudo completar la operación');
  return datos;
}

function precioDinero(valor) {
  return valor === null ? 'Sin leer' : '$ ' + Number(valor).toLocaleString('es-AR', { maximumFractionDigits: 2 });
}

async function abrirPrecios() {
  mostrarPantalla('precios');
  pintarPrecios();
  if (!preciosUI.listo) {
    await tareaPrecios(async () => {
      const datos = await apiPrecios('tiendas');
      preciosUI.tiendas = datos.tiendas;
      preciosUI.historial = datos.historial;
      preciosUI.listo = true;
      // El usuario elige explícitamente las tiendas de esta función beta.
      const activo = datos.historial.find(l => l.estado === 'ejecutando');
      if (activo) { preciosUI.lote = activo; vigilarPrecios(); }
    });
  }
}

async function tareaPrecios(fn) {
  if (preciosUI.ocupado) return;
  preciosUI.ocupado = true; preciosUI.error = ''; pintarPrecios();
  try { await fn(); } catch (e) { preciosUI.error = e.message; }
  finally { preciosUI.ocupado = false; pintarPrecios(); }
}

function invalidarPlanPrecios() { preciosUI.plan = null; }

function pintarPrecios() {
  if (pantallaActual !== 'precios') return;
  const s = preciosUI, panel = document.getElementById('panel-precios');
  const corriendo = s.lote && s.lote.estado === 'ejecutando';
  panel.innerHTML = `<h2>Precios <small>(beta)</small></h2>
    <button id="precios-carta">Volver a carta</button>
    <div id="precios-tiendas" class="opciones-precios"></div>
    <button id="precios-leer" ${s.ocupado || corriendo || !s.elegidas.size ? 'disabled' : ''}>${s.ocupado ? 'Procesando…' : 'Leer precios'}</button>
    <div class="opciones-precios">
      <label class="campo-precios">Cambio<select id="precios-modo"><option value="pesos">Aumentar en $</option><option value="porcentaje">Aumentar en %</option><option value="individual">Editar uno por uno</option></select></label>
      <label class="campo-precios" id="precios-alcance-label">Productos<select id="precios-alcance"><option value="toda">Toda la carta</option><option value="seleccionados">Solo seleccionados</option></select></label>
      <label class="campo-precios" id="precios-cantidad-label">Aumento<input id="precios-cantidad" type="text" inputmode="decimal" placeholder="Ej.: 500 o 10,5"></label>
      <label class="campo-precios" id="precios-redondeo-label">Redondeo<select id="precios-redondeo"><option value="centavos">Centavos</option><option value="1">$1 más cercano</option><option value="10">$10 más cercano</option><option value="50">$50 más cercano</option><option value="100">$100 más cercano</option></select></label>
    </div>
    <input id="precios-buscar" type="search" placeholder="Buscar producto" aria-label="Buscar producto">
    <button id="precios-seleccionar">Seleccionar visibles</button><button id="precios-limpiar">Quitar selección</button>
    <div id="precios-error" role="alert" class="error-precios"></div>
    <div id="precios-lectura" class="resumen-precios"></div>
    <div id="precios-tabla" class="tabla-precios"></div>
    <span id="precios-modificados" class="resumen-precios" aria-live="polite"></span>
    <button id="precios-previo" ${!s.lectura || s.ocupado || corriendo ? 'disabled' : ''}>Revisar cambios</button>
    <div id="precios-plan" class="tabla-precios"></div>
    <div id="precios-lote" class="tabla-precios" aria-live="polite"></div>
    <details><summary>Resultados anteriores</summary><div id="precios-historial"></div></details>`;
  const q = id => document.getElementById(id);
  q('precios-carta').onclick = () => { mostrarPantalla('carta'); refrescarCarta(); };
  for (const tienda of s.tiendas) {
    const label = document.createElement('label'), check = document.createElement('input');
    check.type = 'checkbox'; check.checked = s.elegidas.has(tienda); check.disabled = !!(s.ocupado || corriendo);
    check.dataset.tienda = tienda;
    check.onchange = () => {
      check.checked ? s.elegidas.add(tienda) : s.elegidas.delete(tienda);
      invalidarPlanPrecios(); pintarPrecios();
    };
    label.append(check, document.createTextNode(NOMBRE_PLAT[tienda] || tienda)); q('precios-tiendas').append(label);
  }
  q('precios-error').textContent = s.error;
  if (s.listo && !s.tiendas.length) q('precios-error').textContent = 'Configurá una tienda de Rappi en Ajustes.';
  q('precios-leer').onclick = () => tareaPrecios(async () => {
    s.plan = null;
    s.lectura = await apiPrecios('leer', { tiendas: [...s.elegidas] });
    s.seleccion.clear(); s.individuales = {}; s.plan = null;
  });
  for (const clave of ['modo', 'alcance', 'cantidad', 'redondeo', 'buscar']) {
    const campo = q('precios-' + clave); campo.value = s[clave]; campo.disabled = !!(s.ocupado || corriendo);
    campo.oninput = () => {
      s[clave] = campo.value;
      if (clave !== 'buscar') { invalidarPlanPrecios(); q('precios-plan').replaceChildren(); }
      if (clave === 'modo' || clave === 'alcance') pintarPrecios();
      else if (clave === 'buscar') pintarFilasPrecios();
    };
  }
  const individual = s.modo === 'individual';
  for (const id of ['alcance', 'cantidad', 'redondeo']) q('precios-' + id + '-label').style.display = individual ? 'none' : '';
  for (const id of ['seleccionar', 'limpiar']) q('precios-' + id).hidden = individual;
  if (s.lectura) {
    q('precios-lectura').textContent = `${s.lectura.filas.length} productos · ${s.lectura.leida_en}${s.lectura.simulado ? ' · Simulación' : ''}`;
    for (const [tienda, error] of Object.entries(s.lectura.errores)) {
      const p = document.createElement('p'); p.className = 'error-precios';
      p.textContent = (NOMBRE_PLAT[tienda] || tienda) + ': ' + error; q('precios-lectura').append(p);
    }
  }
  q('precios-seleccionar').disabled = q('precios-limpiar').disabled = !!(s.ocupado || corriendo);
  q('precios-seleccionar').onclick = () => { filasPreciosVisibles().filter(f => !f.error).forEach(f => s.seleccion.add(f.clave)); invalidarPlanPrecios(); pintarPrecios(); };
  q('precios-limpiar').onclick = () => { s.seleccion.clear(); invalidarPlanPrecios(); pintarPrecios(); };
  q('precios-previo').onclick = () => tareaPrecios(async () => {
    const visibles = new Set((s.lectura?.filas || []).filter(f => s.elegidas.has(f.tienda)).map(f => f.clave));
    s.plan = await apiPrecios('previo', { lectura: s.lectura.lectura, tiendas: [...s.elegidas],
      modo: s.modo, alcance: s.alcance, cantidad: s.cantidad || '0', redondeo: s.redondeo,
      seleccionados: [...s.seleccion].filter(k => visibles.has(k)),
      individuales: individualesPrecios() });
  });
  pintarFilasPrecios(); pintarPlanPrecios(); pintarLotePrecios();
  for (const lote of s.historial) {
    const b = document.createElement('button'); b.textContent = `${lote.creado_en} · ${lote.estado}`;
    b.onclick = () => tareaPrecios(async () => {
      s.lote = await apiPrecios('lote/' + lote.id); pintarLotePrecios();
      if (s.lote.estado === 'ejecutando') vigilarPrecios();
    });
    q('precios-historial').append(b);
  }
}

function filasPreciosVisibles() {
  return (preciosUI.lectura?.filas || []).filter(f => preciosUI.elegidas.has(f.tienda)
    && plano(f.nombre).includes(plano(preciosUI.buscar)));
}

function cambioIndividualPrecios(f, valor) {
  return !!valor?.trim() && Number(valor.trim().replace(',', '.')) !== Number(f.precio);
}

function individualesPrecios() {
  const s = preciosUI;
  return Object.fromEntries((s.lectura?.filas || [])
    .filter(f => s.elegidas.has(f.tienda) && cambioIndividualPrecios(f, s.individuales[f.clave]))
    .map(f => [f.clave, s.individuales[f.clave]]));
}

function pintarModificadosPrecios() {
  const cont = document.getElementById('precios-modificados'); if (!cont) return;
  const cantidad = Object.keys(individualesPrecios()).length;
  cont.textContent = preciosUI.modo === 'individual' ? `${cantidad} precio${cantidad === 1 ? '' : 's'} modificado${cantidad === 1 ? '' : 's'} · ` : '';
}

function tablaPrecios(contenedor, cabeceras) {
  const tabla = document.createElement('table'), head = document.createElement('thead'), tr = document.createElement('tr');
  for (const texto of cabeceras) { const th = document.createElement('th'); th.textContent = texto; tr.append(th); }
  head.append(tr); tabla.append(head); const cuerpo = document.createElement('tbody'); tabla.append(cuerpo);
  contenedor.replaceChildren(tabla); return cuerpo;
}

function celdaPrecios(fila, contenido) {
  const td = document.createElement('td');
  typeof contenido === 'string' ? td.textContent = contenido : td.append(contenido);
  fila.append(td); return td;
}

function pintarFilasPrecios() {
  const cont = document.getElementById('precios-tabla'); if (!cont) return;
  const s = preciosUI, individual = s.modo === 'individual', filas = filasPreciosVisibles();
  const cuerpo = tablaPrecios(cont, individual ? ['Producto', 'Tienda', 'Precio actual', 'Nuevo precio'] : ['Elegir', 'Producto', 'Tienda', 'Precio actual']);
  for (const f of filas) {
    const tr = document.createElement('tr'), input = document.createElement('input'); input.dataset.clave = f.clave;
    input.disabled = !!(f.error || s.ocupado || (s.lote && s.lote.estado === 'ejecutando'));
    if (individual) {
      input.type = 'text'; input.inputMode = 'decimal'; input.value = s.individuales[f.clave] ?? f.precio ?? '';
      input.classList.toggle('precio-modificado', cambioIndividualPrecios(f, input.value));
      input.placeholder = f.precio || ''; input.setAttribute('aria-label', 'Nuevo precio de ' + f.nombre + ' en ' + (NOMBRE_PLAT[f.tienda] || f.tienda));
      input.oninput = () => {
        s.individuales[f.clave] = input.value;
        input.classList.toggle('precio-modificado', cambioIndividualPrecios(f, input.value));
        invalidarPlanPrecios(); document.getElementById('precios-plan').replaceChildren(); pintarModificadosPrecios();
      };
    } else {
      input.type = 'checkbox'; input.checked = s.seleccion.has(f.clave);
      input.setAttribute('aria-label', 'Elegir ' + f.nombre + ' en ' + (NOMBRE_PLAT[f.tienda] || f.tienda));
      input.onchange = () => { input.checked ? s.seleccion.add(f.clave) : s.seleccion.delete(f.clave); invalidarPlanPrecios(); document.getElementById('precios-plan').replaceChildren(); };
    }
    if (!individual) celdaPrecios(tr, input);
    celdaPrecios(tr, f.nombre || 'Sin nombre'); celdaPrecios(tr, NOMBRE_PLAT[f.tienda] || f.tienda);
    const precio = celdaPrecios(tr, f.error || precioDinero(f.precio)); if (f.error) precio.className = 'error-precios';
    if (individual) celdaPrecios(tr, input);
    cuerpo.append(tr);
  }
  pintarModificadosPrecios();
}

function pintarPlanPrecios() {
  const s = preciosUI, cont = document.getElementById('precios-plan'); if (!cont) return;
  cont.replaceChildren(); if (!s.plan) return;
  const titulo = document.createElement('h3'); titulo.textContent = `Vista previa · ${s.plan.filas.length} cambios${s.plan.simulado ? ' · Simulación' : ''}`;
  const tablas = document.createElement('div'); const cuerpo = tablaPrecios(tablas, ['Producto', 'Tienda', 'Actual', 'Nuevo']);
  for (const f of s.plan.filas) {
    const tr = document.createElement('tr'); [f.nombre, NOMBRE_PLAT[f.tienda] || f.tienda, precioDinero(f.antes), precioDinero(f.despues)].forEach(c => celdaPrecios(tr, c)); cuerpo.append(tr);
  }
  const ejecutar = document.createElement('button'); ejecutar.textContent = s.plan.simulado ? 'Confirmar y ejecutar simulación' : 'Confirmar y ejecutar';
  ejecutar.id = 'precios-ejecutar'; ejecutar.disabled = !!(s.ocupado || s.lote?.estado === 'ejecutando');
  ejecutar.onclick = () => tareaPrecios(async () => { s.lote = await apiPrecios('ejecutar', { plan: s.plan.plan }); s.plan = null; vigilarPrecios(); });
  cont.append(titulo, tablas, ejecutar);
}

function pintarLotePrecios() {
  const s = preciosUI, cont = document.getElementById('precios-lote'); if (!cont || !s.lote) return;
  cont.replaceChildren();
  const l = s.lote, titulo = document.createElement('h3');
  const hechos = l.filas.filter(f => !['pendiente','en_curso'].includes(f.estado)).length;
  titulo.textContent = `${l.simulado ? 'Simulación' : 'Resultados'} · ${hechos}/${l.filas.length} · ${l.estado}`;
  const tablas = document.createElement('div'), cuerpo = tablaPrecios(tablas, ['Producto', 'Tienda', 'Actual → Nuevo', 'Resultado']);
  for (const f of l.filas) {
    const tr = document.createElement('tr'); tr.className = 'estado-' + f.estado;
    [f.nombre, NOMBRE_PLAT[f.tienda] || f.tienda, `${precioDinero(f.antes)} → ${precioDinero(f.despues)}`,
      f.estado.replaceAll('_', ' ') + (f.detalle ? ': ' + f.detalle : '')].forEach(c => celdaPrecios(tr, c)); cuerpo.append(tr);
  }
  cont.append(titulo, tablas);
  if (l.estado === 'ejecutando') {
    const cancelar = document.createElement('button'); cancelar.textContent = l.cancelar ? 'Cancelando…' : 'Cancelar pendientes'; cancelar.disabled = l.cancelar;
    cancelar.onclick = () => tareaPrecios(async () => { s.lote = await apiPrecios('lote/' + l.id + '/cancelar', {}); }); cont.append(cancelar);
  }
}

function vigilarPrecios() {
  clearTimeout(preciosUI.temporizador);
  if (!preciosUI.lote || preciosUI.lote.estado !== 'ejecutando') return;
  preciosUI.temporizador = setTimeout(async () => {
    try {
      preciosUI.lote = await apiPrecios('lote/' + preciosUI.lote.id);
      if (preciosUI.lote.estado === 'ejecutando') pintarLotePrecios();
      else {
        preciosUI.historial = (await apiPrecios('tiendas')).historial; pintarPrecios();
      }
    } catch (e) {
      preciosUI.error = 'No pude consultar el resultado: ' + e.message;
      const aviso = document.getElementById('precios-error'); if (aviso) aviso.textContent = preciosUI.error;
    }
    vigilarPrecios();
  }, 1500);
}

if (location.pathname === '/precios') abrirPrecios();
