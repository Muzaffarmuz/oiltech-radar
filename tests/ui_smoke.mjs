// Optional browser smoke test: start Chrome with --remote-debugging-port=9223, then run `node tests/ui_smoke.mjs`.
import assert from 'node:assert/strict';
import { writeFile } from 'node:fs/promises';
import { join } from 'node:path';

const targets = await fetch('http://127.0.0.1:9223/json').then((response) => response.json());
const page = targets.find((target) => target.type === 'page' && target.url.startsWith('http://127.0.0.1:8083/'));
assert(page, 'Open http://127.0.0.1:8083/ in the debug browser first');
const socket = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener('open', resolve, { once: true });
  socket.addEventListener('error', reject, { once: true });
});

let sequence = 0;
const pending = new Map();
socket.addEventListener('message', (event) => {
  const message = JSON.parse(event.data);
  if (!message.id || !pending.has(message.id)) return;
  const { resolve, reject } = pending.get(message.id);
  pending.delete(message.id);
  message.error ? reject(new Error(message.error.message)) : resolve(message.result);
});
function command(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++sequence;
    pending.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, method, params }));
  });
}
async function evaluate(expression) {
  const result = await command('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
  return result.result.value;
}
async function waitUntil(expression, timeout = 6000) {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    if (await evaluate(expression)) return;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Timed out: ${expression}`);
}

try {
  await command('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
  await command('Page.navigate', { url: 'http://127.0.0.1:8083/' });
  await waitUntil('document.querySelectorAll("#sourceRows .source-row").length === 6');
  const home = await evaluate(`({
    title: document.querySelector('.intro-hero h1').innerText,
    flows: [...document.querySelectorAll('.stream-card .stream-type')].map((element) => element.innerText),
    iks: [...document.querySelectorAll('#sourceRows .iks-value')].map((element) => element.innerText),
    mapWidth: Math.round(document.querySelector('.map-stage').getBoundingClientRect().width),
    mapCities: document.querySelectorAll('.map-zone').length,
    geoRows: document.querySelectorAll('#geoList .geo-row').length
  })`);
  assert.match(home.title, /Принимать решения вовремя/);
  assert.equal(home.flows.length, 4);
  assert.deepEqual(home.iks.map((value) => Number(value.replace(/\D/g, ''))).sort((a, b) => a - b), [140, 300, 550, 1480, 1810, 2250]);
  assert(home.mapWidth > 650);
  assert.equal(home.mapCities, 29);
  assert.equal(home.geoRows, 9);
  assert.equal(await evaluate('!!document.querySelector(`[data-geo-city="Нефтекамск"]`)'), true);
  assert.equal(await evaluate('document.querySelector(`[data-geo-city="Нефтекамск"]`).classList.contains("is-featured")'), false);
  await evaluate('document.querySelector(`[data-geo-city="Нефтекамск"]`).dispatchEvent(new MouseEvent("mouseenter", { clientX: 500, clientY: 500 }))');
  assert.match(await evaluate('document.querySelector("#mapTooltip").innerText'), /Нефтекамск/);
  const neftekamskDetail = await evaluate('document.querySelector("#mapDetail").innerText');
  assert.match(neftekamskDetail, /НКМЗ-Групп/);
  assert.match(neftekamskDetail, /Арланнефть/);
  assert.match(neftekamskDetail, /Нефтекамский нефтяной колледж/);
  assert.match(neftekamskDetail, /РН-Ремонт НПО/);
  assert.match(neftekamskDetail, /Татнефть-АЗС Центр/);
  assert.equal(await evaluate('document.querySelectorAll("#mapDetail a").length'), 0);
  const neftekamskPress = await evaluate(`(() => { const node = document.querySelector('[data-geo-city="Нефтекамск"]'); node.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: 500, clientY: 500 })); return { animated: node.classList.contains('is-pressed'), outline: getComputedStyle(node).outlineStyle }; })()`);
  assert.equal(neftekamskPress.animated, true);
  assert.equal(neftekamskPress.outline, 'none');
  await evaluate('document.querySelector(`[data-geo-city="Нефтекамск"]`).dispatchEvent(new MouseEvent("mouseleave"))');
  await evaluate('document.querySelector(".map-zone").dispatchEvent(new MouseEvent("mouseenter", { clientX: 500, clientY: 500 }))');
  assert.equal(await evaluate('document.querySelector("#mapTooltip").hidden'), false);
  assert.match(await evaluate('document.querySelector("#mapTooltip").innerText'), /Москва/);
  await evaluate('document.querySelector(".map-zone").dispatchEvent(new MouseEvent("mouseleave"))');
  await evaluate('document.querySelector("#mapFilters [data-layer=sci]").click()');
  assert.equal(await evaluate('document.querySelector("#geoLayerLabel").innerText'), 'Наука');
  assert.equal(await evaluate('document.querySelector("#geoList .geo-row b").innerText.replace(/\D/g, "")'), '286');
  await evaluate('document.querySelector("[data-open-taxonomy]").click()');
  assert.equal(await evaluate('document.querySelector("#taxonomy").hidden'), false);
  assert.equal(await evaluate('!!document.querySelector(".taxonomy-group.active-taxonomy")'), true);
  await evaluate('document.querySelector(`[data-geo-city="Нефтекамск"]`).dispatchEvent(new MouseEvent("mouseenter", { clientX: 500, clientY: 500 })); document.querySelector(`[data-geo-city="Нефтекамск"]`).dispatchEvent(new MouseEvent("mouseleave"))');

  const screenshotDir = process.argv[2];
  if (screenshotDir) {
    for (const theme of ['dusk', 'dark']) {
      await evaluate(`document.documentElement.dataset.theme = '${theme}'`);
      const shot = await command('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true, clip: { x: 0, y: 0, width: 1440, height: 3200, scale: 1 } });
      await writeFile(join(screenshotDir, `oiltech-${theme}.png`), Buffer.from(shot.data, 'base64'));
    }
    const bottom = await command('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true, clip: { x: 0, y: 2800, width: 1440, height: 1700, scale: 1 } });
    await writeFile(join(screenshotDir, 'oiltech-dark-bottom.png'), Buffer.from(bottom.data, 'base64'));
  }

  await evaluate(`(() => { document.querySelector('#settingsOpen').click();
    const select = document.querySelector('#themeSelect'); select.value = 'dusk';
    select.dispatchEvent(new Event('change', { bubbles: true })); })()`);
  assert.equal(await evaluate('localStorage.getItem("oiltech-theme")'), 'dusk');
  await evaluate(`(() => {
    const select = document.querySelector('#themeSelect'); select.value = 'dark';
    select.dispatchEvent(new Event('change', { bubbles: true })); })()`);
  assert.equal(await evaluate('document.documentElement.dataset.theme'), 'dark');
  assert.equal(await evaluate('localStorage.getItem("oiltech-theme")'), 'dark');
  await command('Page.navigate', { url: 'http://127.0.0.1:8083/audit' });
  await waitUntil('document.querySelector("#showAllEvents")?.textContent.includes("Показать все")');
  const audit = await evaluate(`({
    theme: document.documentElement.dataset.theme,
    initial: document.querySelectorAll('#evidenceEvents .evidence-event').length,
    button: document.querySelector('#showAllEvents').textContent
  })`);
  assert.equal(audit.theme, 'dark');
  assert.equal(audit.initial, 5);
  await evaluate('document.querySelector(".technical-details").open = true');
  await waitUntil('document.querySelectorAll("#scatter .scatterlayer .trace").length > 10');
  assert((await evaluate('document.querySelectorAll("#scatter .scatterlayer .trace").length')) > 50);
  assert.match(await evaluate('document.querySelector("#scatter").data.find((trace) => trace.mode === "markers").hovertemplate'), /точек/);
  await evaluate(`(() => { const graph=document.querySelector('#scatter'); const curveNumber=graph.data.findIndex((trace)=>trace.mode==='markers'); Plotly.Fx.hover(graph,[{curveNumber,pointNumber:0}]); })()`);
  await waitUntil('document.querySelector("#scatter .hovertext") !== null');
  assert.match(await evaluate('document.querySelector("#scatter .hovertext").textContent'), /точек/);
  await evaluate('document.querySelector("#showAllEvents").click()');
  const expanded = await evaluate('document.querySelectorAll("#evidenceEvents .evidence-event").length');
  assert(expanded > 5);
  assert.equal(await evaluate('document.querySelectorAll(".method-flow article").length'), 6);
  if (screenshotDir) {
    const shot = await command('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true, clip: { x: 0, y: 0, width: 1440, height: 1800, scale: 1 } });
    await writeFile(join(screenshotDir, 'oiltech-dark-data.png'), Buffer.from(shot.data, 'base64'));
    const technicalY = await evaluate('Math.max(0, Math.floor(document.querySelector(".technical-details").offsetTop - 20))');
    const technicalShot = await command('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true, clip: { x: 0, y: technicalY, width: 1440, height: 760, scale: 1 } });
    await writeFile(join(screenshotDir, 'oiltech-dark-clusters.png'), Buffer.from(technicalShot.data, 'base64'));
  }
  for (const flow of ['science', 'investments', 'policy']) {
    await command('Page.navigate', { url: `http://127.0.0.1:8083/flows/${flow}` });
    await waitUntil('document.querySelectorAll("#flowMetrics .flow-metric").length === 4');
    assert.equal(await evaluate('document.body.dataset.flow'), flow);
    assert((await evaluate('document.querySelectorAll("#flowContent .panel").length')) >= 2);
    if (screenshotDir) {
      const shot = await command('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true, clip: { x: 0, y: 0, width: 1440, height: 1800, scale: 1 } });
      await writeFile(join(screenshotDir, `oiltech-${flow}.png`), Buffer.from(shot.data, 'base64'));
    }
  }
  assert.equal(await evaluate('document.querySelectorAll(".policy-event").length'), 5);
  await command('Page.navigate', { url: 'http://127.0.0.1:8083/flows/news/digital' });
  await waitUntil('document.querySelector(".flow-topbar") !== null');
  assert.equal(await evaluate('document.documentElement.dataset.theme'), 'dark');
  if (screenshotDir) {
    const shot = await command('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true, clip: { x: 0, y: 0, width: 1440, height: 1500, scale: 1 } });
    await writeFile(join(screenshotDir, 'oiltech-dark-flow.png'), Buffer.from(shot.data, 'base64'));
  }
  await evaluate('localStorage.setItem("oiltech-theme", "light")');
  console.log(JSON.stringify({ home, audit, expanded }, null, 2));
} finally {
  socket.close();
}
