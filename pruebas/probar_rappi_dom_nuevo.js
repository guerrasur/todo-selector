// Recibe JSON de selectores exportados de la clase Rappi como primer argumento.
const {chromium} = require(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES + '/playwright');
const fs = require('fs');
const assert = require('assert/strict');
(async()=>{
 const sel=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
 const browser=await chromium.launch({headless:true, executablePath:process.env.CHROME_PRUEBA});
 try {
 const page=await browser.newPage();
 const fila=(nombre,estado)=>`<div class="fila"><div><div><div><p>${nombre}</p></div><div data-component="menu-product-description"><p>Descripción</p></div><div data-component="menu-product-tags"><span>Sin toppings</span></div></div></div><div><span>Precio</span><span>$100</span><div data-component="menu-item-availability-switch"><button role="switch" aria-checked="${estado}" data-state="closed"><span data-state="${estado==='true'?'checked':'unchecked'}"></span></button></div><button aria-label="Editar"></button></div></div>`;
 await page.setContent('<button role="switch" aria-checked="true">Activa</button>'+fila('Ensalada de prueba','true')+fila('Ensalada de prueba chica','false'));
 assert.equal(await page.locator(sel.toggle).count(),2,'excluye categoría');
 const row=page.getByText('Ensalada de prueba',{exact:true}).locator(sel.row);
 assert.equal(await row.count(),1);
 assert.equal(await row.locator(sel.toggle).getAttribute('aria-checked'),'true');
 assert.equal(await page.getByText('Ensalada de prueba chica',{exact:true}).locator(sel.row).locator(sel.toggle).getAttribute('aria-checked'),'false');
 const nombres=page.locator('[data-component="menu-product-description"]').locator('xpath=preceding-sibling::div//p');
 assert.deepEqual(await nombres.allTextContents(),['Ensalada de prueba','Ensalada de prueba chica']);
 await page.locator(sel.toggle).first().evaluate(el=>el.onclick=()=>el.setAttribute('aria-checked','false'));
 await row.locator(sel.toggle).click();
 assert.equal(await row.locator(sel.toggle).getAttribute('aria-checked'),'false');
 await page.setContent(fila('Duplicado','true')+fila('Duplicado','false'));
 const duplicados=page.locator('[data-component="menu-product-description"]').locator('xpath=preceding-sibling::div//p').filter({hasText:/^Duplicado$/}).locator(sel.newrow);
 assert.equal(await duplicados.evaluateAll(els=>new Set(els).size),2);
 await page.setContent('<label data-testid="menu-category-1-availability-switch-control"></label><div><p>Anterior</p><label data-testid="menu-category-1-product-2-availability-switch-control"><input type="checkbox" checked></label></div>');
 assert.equal(await page.locator(sel.toggle).count(),1,'compatibilidad anterior');
 assert.equal(await page.getByText('Anterior',{exact:true}).locator(sel.row).count(),1);
 console.log('OK: filas, nombres sin imagen, estados, clic, prefijos, duplicados, categoría y diseño anterior');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
