const $ = (id) => document.getElementById(id);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = (v) => new Intl.NumberFormat('ru-RU').format(Number(v) || 0);
let portalData = null;
let customSources = [];

async function jsonRequest(url, options) {
  const response = await fetch(url, options);
  const value = await response.json();
  if (!response.ok) throw new Error(value.detail || `Ошибка ${response.status}`);
  return value;
}

function renderMetrics(data) {
  const k = data.kpis || {};
  const companies = new Set((data.audit?.members || []).map((m) => m.company).filter(Boolean));
  const items = [
    ['Технологические темы', k.topics, 'Кластеры действующего потока', '◈'],
    ['События и упоминания', k.events, 'Новостные события корпуса', '↗'],
    ['Источники', k.sources, 'Подключённые издания', '◉'],
    ['Компании с метками', companies.size, 'Для конкурентного анализа', '◎'],
  ];
  $('metricGrid').innerHTML = items.map(([title, value, foot, icon]) => `<div class="metric-card"><div class="metric-top"><span>${esc(title)}</span><i>${icon}</i></div><div class="metric-value">${fmt(value)}</div><div class="metric-foot">${esc(foot)}</div></div>`).join('');
  const date = new Date(data.generated_at);
  $('dataDate').textContent = Number.isNaN(date.valueOf()) ? 'Срез данных' : `Срез данных · ${date.toLocaleDateString('ru-RU')}`;
}

function renderSignals(data) {
  const byId = new Map((data.clusters || []).map((c) => [c.id, c]));
  const growing = (data.growing || []).map((g) => byId.get(g.id)).filter(Boolean);
  const fallback = [...(data.clusters || [])].sort((a,b) => (b.mentions || 0) - (a.mentions || 0));
  const selected = (growing.length ? growing : fallback).slice(0, 3);
  $('signalList').innerHTML = selected.length ? selected.map((c) => {
    const company = (c.companies || [])[0]?.name;
    const brief = String(c.description || '').slice(0, 150);
    return `<article class="signal-item"><div class="signal-top"><span class="signal-count">${growing.length ? '↑ Рост упоминаний' : '● Заметная тема'}</span><span class="signal-count">${fmt(c.mentions)} фактов</span></div><h3>${esc(c.title)}</h3><p>${esc(brief)}${brief.length === 150 ? '…' : ''}</p>${company ? `<span class="signal-company">Компания: ${esc(company)}</span>` : ''}</article>`;
  }).join('') : '<p class="empty-message">Сигналы появятся после обновления потока.</p>';
}

function uniqueMembers(data) {
  const seen = new Set();
  return (data.audit?.members || []).filter((m) => {
    if (!m.event_id || seen.has(m.event_id)) return false;
    seen.add(m.event_id);
    return true;
  });
}

function renderCompanies(data) {
  const members = uniqueMembers(data).filter((m) => m.company);
  const counts = new Map();
  members.forEach((m) => counts.set(m.company, (counts.get(m.company) || 0) + 1));
  const rows = [...counts.entries()].sort((a,b) => b[1]-a[1]).slice(0, 5);
  const maximum = rows[0]?.[1] || 1;
  $('companyList').innerHTML = rows.length ? rows.map(([name, count]) => `<div class="company-row"><span>${esc(name)}</span><span>${fmt(count)}</span><div class="company-bar"><i style="width:${Math.round(count / maximum * 100)}%"></i></div></div>`).join('') : '<p class="empty-message">Пока нет событий с меткой компании.</p>';
  const latest = members.filter((m) => /^https?:\/\//.test(m.link || '')).sort((a,b) => String(b.datatime || '').localeCompare(String(a.datatime || ''))).slice(0, 3);
  $('companyEvents').innerHTML = latest.length ? latest.map((m) => `<a class="company-event" href="${esc(m.link)}" target="_blank" rel="noopener noreferrer"><strong>${esc(m.topic_label || 'Событие')}</strong><small><span class="event-co">${esc(m.company)}</span> · ${esc((m.datatime || '').slice(0,10))} · ${esc(m.source || '')}</small></a>`).join('') : '<p class="empty-message">События появятся после разметки компаний.</p>';
}

function renderSources(data, iksSnapshot) {
  const members = uniqueMembers(data);
  const counts = new Map();
  const breadth = new Map();
  for (const m of members) {
    if (!m.source) continue;
    counts.set(m.source, (counts.get(m.source) || 0) + 1);
    if (!breadth.has(m.source)) breadth.set(m.source, new Set());
    if (m.cluster_id) breadth.get(m.source).add(m.cluster_id);
  }
  const sources = [...new Set([...(data.sources || []), ...counts.keys()])].map((name) => ({name, count: counts.get(name) || 0, breadth: breadth.get(name)?.size || 0})).sort((a,b) => b.count-a.count);
  const maxCount = sources[0]?.count || 1;
  const maxBreadth = Math.max(1, ...sources.map((s) => s.breadth));
  $('sourceRows').innerHTML = sources.length ? sources.map((s) => {
    const weight = Math.round(70 * s.count/maxCount + 30 * s.breadth/maxBreadth);
    const iks = iksSnapshot?.values?.[s.name];
    const iksCell = Number.isFinite(iks)
      ? `<span class="iks-value" title="Яндекс ИКС · снимок ${esc(iksSnapshot.checked_at || '')} · raskruty.ru">${fmt(iks)}</span>`
      : '<span class="pending">Нет данных</span>';
    return `<div class="source-row"><strong>${esc(s.name)}</strong><span class="source-type">Новостной</span><span>${fmt(s.count)}</span><span class="coverage-cell"><span class="coverage-bar"><i style="width:${weight}%"></i></span><strong>${weight}</strong></span>${iksCell}</div>`;
  }).join('') : '<p class="empty-message">Источники пока не подключены.</p>';
  if (iksSnapshot?.checked_at) $('iksDate').textContent = iksSnapshot.checked_at.split('-').reverse().join('.');
}

const taxonomy = [
  ['Недра и строительство скважин', ['Геология','Геофизика','Разведка','Бурение','Строительство скважин','ГРП','Нефтесервис']],
  ['Добыча и инфраструктура', ['Добыча нефти','Добыча газа','EOR','Промысловое оборудование','Транспортировка','Трубопроводы']],
  ['Переработка и энергия', ['Переработка нефти','Переработка газа','Нефтехимия','СПГ','Энергетика','Водород']],
  ['Устойчивость и материалы', ['Промышленная безопасность','Экология','CCUS','Новые материалы']],
  ['ИТ и автоматизация · действующий поток', ['Роботизация','Автоматизация','Промышленный IoT','Искусственный интеллект','Машинное обучение','Компьютерное зрение','Цифровые двойники','Автономные системы','Беспилотные технологии','Predictive maintenance','Кибербезопасность']],
];
$('taxonomyGroups').innerHTML = taxonomy.map(([title, items], index) => {
  const live = index === taxonomy.length - 1;
  return `<div class="taxonomy-group${live ? ' active-taxonomy' : ' flow-uncalculated'}"><strong>${esc(title)}</strong>${live ? '' : '<span class="uncalculated-mark">ПЛАНИРУЕМЫЙ ОХВАТ</span>'}${items.map((x) => `<span>${esc(x)}</span>`).join('')}${live ? '<a href="/flows/news/digital">Открыть действующий поток ↗</a>' : ''}</div>`;
}).join('');
document.querySelector('[data-open-taxonomy]').addEventListener('click', () => { const root = $('taxonomy'); const button = document.querySelector('[data-open-taxonomy]'); root.hidden = !root.hidden; button.setAttribute('aria-expanded', String(!root.hidden)); button.textContent = root.hidden ? 'Все события и направления →' : 'Свернуть ↑'; if (!root.hidden) root.scrollIntoView({behavior:'smooth',block:'start'}); });

let geoCities = [];
let mapLayer='all';
let mapCoordinates={};
let mapPath='';
let mapBox = {x:0,y:0,w:1000,h:538};
const layerValue=(city)=>{
  if(mapLayer==='all') return Number(city.inv||0);
  if(mapLayer==='inv') return Number(city.inv||0);
  if(mapLayer==='sci') return Number(city.sci||0);
  return Number(city.news||0);
};
const layerLabels={all:'Все (по компаниям)',news:'Метка news',sci:'Метка science',inv:'События с компанией'};
function applyMapBox() { $('russiaMap').setAttribute('viewBox', `${mapBox.x} ${mapBox.y} ${mapBox.w} ${mapBox.h}`); }
function zoomMap(multiplier) { const nw=Math.max(260,Math.min(1000,mapBox.w*multiplier)); const nh=nw*.538; mapBox.x+=(mapBox.w-nw)/2; mapBox.y+=(mapBox.h-nh)/2; mapBox.w=nw; mapBox.h=nh; applyMapBox(); }
function setGeoHighlight(name,on=true){document.querySelectorAll(`[data-geo-city="${CSS.escape(name)}"]`).forEach((node)=>node.classList.toggle('is-highlighted',on));}
function animateGeoCity(node){node.classList.remove('is-pressed');void node.getBoundingClientRect();node.classList.add('is-pressed');setTimeout(()=>node.classList.remove('is-pressed'),520);}
function renderGeoLayer(){
  if(!geoCities.length){
    $('mapOutline').innerHTML=mapPath?`<path class="country-shape" d="${mapPath}"></path>`:'';
    $('mapPoints').innerHTML='';
    $('geoList').innerHTML='<p class="empty-message">Нет событий с компаниями из справочника.</p>';
    $('mapDetail').textContent='География строится по company→город из событий корпуса.';
    return;
  }
  const max=Math.max(...geoCities.map(layerValue),1);
  const sorted=[...geoCities].filter((city)=>layerValue(city)>0).sort((a,b)=>layerValue(b)-layerValue(a));
  const drawList=sorted.length?sorted:[...geoCities].sort((a,b)=>b.inv-a.inv);
  $('mapOutline').innerHTML=`<path class="country-shape" d="${mapPath}"></path>`;
  $('mapPoints').innerHTML=drawList.map((city,index)=>{const point=mapCoordinates[city.name];if(!point)return '';const value=Math.max(layerValue(city),1);const radius=5+Math.sqrt(value/max)*39;const major=index<5?' is-major':'';const visualLayer=mapLayer==='all'||mapLayer==='inv'?'inv':mapLayer;return `<g class="map-zone layer-${visualLayer}${major}" data-geo-city="${esc(city.name)}" tabindex="0" role="button" aria-label="${esc(city.name)}: ${fmt(layerValue(city))} событий"><circle class="outer" cx="${point[0]}" cy="${point[1]}" r="${radius.toFixed(1)}"></circle><circle class="center" cx="${point[0]}" cy="${point[1]}" r="3.5"></circle><text class="map-label" x="${point[0]+7}" y="${point[1]-7}">${esc(city.name)}</text></g>`;}).join('');
  $('geoLayerLabel').textContent=layerLabels[mapLayer];
  $('geoList').innerHTML=drawList.slice(0,9).map((city,index)=>`<button type="button" class="geo-row" data-geo-city="${esc(city.name)}"><span class="geo-rank">${String(index+1).padStart(2,'0')}</span><span class="geo-name"><strong>${esc(city.name)}</strong><i><span style="width:${(layerValue(city)/max*100).toFixed(0)}%"></span></i></span><b>${fmt(layerValue(city))}</b></button>`).join('');
  const tooltip=$('mapTooltip');
  const showCity=(city,e,node)=>{if(!city)return;const stage=$('mapStage').getBoundingClientRect();const box=node?.getBoundingClientRect();const x=e?.clientX??box?.left??stage.left;const y=e?.clientY??box?.top??stage.top;tooltip.innerHTML=`<strong>${esc(city.name)}</strong><span>${fmt(layerValue(city))} · ${esc(layerLabels[mapLayer].toLowerCase())}</span><small>Компании ${fmt(city.inv)} · science ${fmt(city.sci)} · news ${fmt(city.news)}</small>`;tooltip.hidden=false;tooltip.style.left=`${Math.max(8,Math.min(stage.width-235,x-stage.left+14))}px`;tooltip.style.top=`${Math.max(8,Math.min(stage.height-105,y-stage.top-70))}px`;$('mapDetail').innerHTML=`<strong>${esc(city.name)}</strong> · ${fmt(city.inv)} событий с компаниями. <span>${esc(city.org)}</span>`;setGeoHighlight(city.name,true);};
  $('mapPoints').querySelectorAll('.map-zone').forEach((node)=>{const city=geoCities.find((item)=>item.name===node.dataset.geoCity);node.addEventListener('mouseenter',(e)=>showCity(city,e,node));node.addEventListener('mousemove',(e)=>showCity(city,e,node));node.addEventListener('mouseleave',()=>{tooltip.hidden=true;if(city)setGeoHighlight(city.name,false);});node.addEventListener('focus',(e)=>showCity(city,e,node));node.addEventListener('blur',()=>{tooltip.hidden=true;if(city)setGeoHighlight(city.name,false);});node.addEventListener('click',(e)=>{showCity(city,e,node);animateGeoCity(node);});node.addEventListener('keydown',(e)=>{if(e.key!=='Enter'&&e.key!==' ')return;e.preventDefault();showCity(city,e,node);animateGeoCity(node);});});
  $('geoList').querySelectorAll('.geo-row').forEach((row)=>{const city=geoCities.find((item)=>item.name===row.dataset.geoCity);row.addEventListener('mouseenter',()=>city&&setGeoHighlight(city.name,true));row.addEventListener('mouseleave',()=>city&&setGeoHighlight(city.name,false));row.addEventListener('focus',()=>city&&setGeoHighlight(city.name,true));row.addEventListener('blur',()=>city&&setGeoHighlight(city.name,false));row.addEventListener('click',()=>{const node=$('mapPoints').querySelector(`[data-geo-city="${CSS.escape(city.name)}"]`);node?.focus();$('mapDetail').innerHTML=`<strong>${esc(city.name)}</strong> · ${fmt(city.inv)} событий с компаниями. <span>${esc(city.org)}</span>`;});});
}
async function renderMap() {
  try { [mapPath,mapCoordinates]=await Promise.all([fetch('/static/russia-map-path.txt').then((r)=>r.text()),fetch('/static/russia-cities.json').then((r)=>r.json())]); renderGeoLayer(); }
  catch (_) { $('mapDetail').textContent='Карта временно недоступна; рейтинг городов будет восстановлен после загрузки данных.'; }
}
$('mapFilters').addEventListener('click',(e)=>{const button=e.target.closest('button[data-layer]');if(!button)return;mapLayer=button.dataset.layer;$('mapFilters').querySelectorAll('button').forEach((item)=>item.setAttribute('aria-pressed',String(item===button)));renderGeoLayer();});
$('mapZoomIn').addEventListener('click',()=>zoomMap(.72)); $('mapZoomOut').addEventListener('click',()=>zoomMap(1.3)); $('mapReset').addEventListener('click',()=>{mapBox={x:0,y:0,w:1000,h:538};applyMapBox();});
$('russiaMap').addEventListener('wheel',(e)=>{e.preventDefault();zoomMap(e.deltaY>0?1.13:.87);},{passive:false});
let dragStart=null; $('russiaMap').addEventListener('pointerdown',(e)=>{if(e.target.closest('.map-zone'))return;dragStart={x:e.clientX,y:e.clientY,bx:mapBox.x,by:mapBox.y};$('russiaMap').setPointerCapture(e.pointerId);}); $('russiaMap').addEventListener('pointermove',(e)=>{if(!dragStart)return;const rect=$('russiaMap').getBoundingClientRect();mapBox.x=dragStart.bx-(e.clientX-dragStart.x)*mapBox.w/rect.width;mapBox.y=dragStart.by-(e.clientY-dragStart.y)*mapBox.h/rect.height;applyMapBox();}); $('russiaMap').addEventListener('pointerup',()=>dragStart=null);

const infoText = {
  source:'Планируемый общий score объединит цитируемость, популярность и авторитетность. Пока все внешние метрики не подключены, общий score не рассчитывается. Яндекс ИКС показан отдельно.',
  coverage:'Внутренний вес покрытия: 70% — число уникальных событий источника относительно лидера корпуса; 30% — число разных кластеров относительно максимума. Шкала 0–100. Показатель не оценивает достоверность или качество сайта.',
  iks:'Яндекс ИКС — оценка полезности и удобства сайта для пользователей. Яндекс учитывает аудиторию, удовлетворённость и доверие; точную формулу не раскрывает. Значения перепроверяются отдельно и не заменяют оценку достоверности публикаций.'
};
document.querySelectorAll('[data-info]').forEach((button)=>{const show=()=>{const pop=$('infoPopover');pop.textContent=infoText[button.dataset.info]||'';const rect=button.getBoundingClientRect();pop.hidden=false;pop.style.left=`${Math.min(rect.left,innerWidth-300)}px`;pop.style.top=`${Math.min(rect.bottom+8,innerHeight-pop.offsetHeight-10)}px`;};button.addEventListener('mouseenter',show);button.addEventListener('focus',show);button.addEventListener('mouseleave',()=>$('infoPopover').hidden=true);button.addEventListener('blur',()=>$('infoPopover').hidden=true);button.addEventListener('click',(e)=>{e.stopPropagation();$('infoPopover').hidden?show():$('infoPopover').hidden=true;});});
document.addEventListener('click',()=>$('infoPopover').hidden=true);

function setMessage(message, error=false){const el=$('settingsMessage');el.hidden=false;el.classList.toggle('error',error);el.textContent=message;}
function openSettings(){ $('settingsBackdrop').hidden=false; document.body.style.overflow='hidden'; $('settingsClose').focus(); refreshSettings().catch((e)=>setMessage(e.message,true)); }
function closeSettings(){ $('settingsBackdrop').hidden=true; document.body.style.overflow=''; $('settingsOpen').focus(); }
$('settingsOpen').addEventListener('click',openSettings); $('settingsClose').addEventListener('click',closeSettings); $('settingsBackdrop').addEventListener('click',(e)=>{if(e.target===$('settingsBackdrop'))closeSettings();}); document.addEventListener('keydown',(e)=>{if(e.key==='Escape'&&!$('settingsBackdrop').hidden)closeSettings();});
$('themeSelect').value = document.documentElement.dataset.theme || 'light';
$('themeSelect').addEventListener('change', (e) => { const theme=e.target.value; if(!['light','dusk','dark'].includes(theme))return; document.documentElement.dataset.theme=theme; try { localStorage.setItem('oiltech-theme',theme); } catch (_) {} });
async function refreshSettings(){const [status,sources]=await Promise.all([jsonRequest('/api/status'),jsonRequest('/api/custom-sources')]);$('updateMode').value=status.update_mode||'weekly';customSources=sources.items||[];$('sourceCount').textContent=String(customSources.length);$('customSources').innerHTML=customSources.length?customSources.map((s)=>`<div class="custom-source"><span title="${esc(s.start_url||'')}">${esc(s.domain||s.source_id)} ${s.enabled?'':'· выключен'}</span><span class="custom-source-actions"><button type="button" data-act="toggle" data-id="${esc(s.source_id)}">${s.enabled?'Выключить':'Включить'}</button><button type="button" data-act="delete" data-id="${esc(s.source_id)}">Удалить</button></span></div>`).join(''):'<p class="empty-message">Дополнительных сайтов пока нет.</p>';}
$('customSources').addEventListener('click',async(e)=>{const button=e.target.closest('button[data-act]');if(!button)return;button.disabled=true;try{const id=encodeURIComponent(button.dataset.id);if(button.dataset.act==='toggle'){const item=customSources.find((s)=>String(s.source_id)===button.dataset.id);await jsonRequest(`/api/custom-sources/${id}/enabled`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:!item.enabled})});}else if(confirm('Удалить этот источник из потока?')){await jsonRequest(`/api/custom-sources/${id}`,{method:'DELETE'});}setMessage('Источники обновлены.');await refreshSettings();}catch(err){setMessage(err.message,true);}finally{button.disabled=false;}});
$('addSourceBtn').addEventListener('click',async()=>{const input=$('customSourceUrl');const url=input.value.trim();if(!url){setMessage('Введите адрес сайта.',true);return;}const button=$('addSourceBtn');button.disabled=true;setMessage('Обходим домен, ищем ленты и проверяем тематику…');try{await jsonRequest('/api/custom-sources',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url})});input.value='';setMessage('Сайт добавлен. Запустите обновление потока, чтобы получить публикации.');await refreshSettings();}catch(err){setMessage(err.message,true);}finally{button.disabled=false;}});
$('updateMode').addEventListener('change',async(e)=>{try{await jsonRequest('/api/update-mode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:e.target.value})});setMessage('Частота обновления сохранена.');}catch(err){setMessage(err.message,true);refreshSettings();}});
$('refreshBtn').addEventListener('click',async()=>{const button=$('refreshBtn');button.disabled=true;try{if(window.OilRadarCache)await window.OilRadarCache.clear();await jsonRequest('/api/refresh',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scrape:true})});setMessage('Обновление запущено. Следите за статусом здесь.');const timer=setInterval(async()=>{try{const state=await jsonRequest('/api/status');if(state.pipeline?.state==='running'){setMessage(`Обновление: ${state.pipeline.stage||'обработка данных'}…`);return;}clearInterval(timer);button.disabled=false;if(state.pipeline?.state==='failed'){setMessage(state.pipeline.error||'Обновление завершилось с ошибкой.',true);}else{if(window.OilRadarCache)await window.OilRadarCache.clear();setMessage('Обновление завершено. Данные перезагрузятся при следующем открытии страниц.');}}catch(err){clearInterval(timer);button.disabled=false;setMessage(err.message,true);}},2000);}catch(err){button.disabled=false;setMessage(err.message,true);}});

const portalLoad=window.OilRadarCache?window.OilRadarCache.fetchJson('/api/portal'):jsonRequest('/api/portal');
Promise.all([portalLoad,jsonRequest('/static/yandex-iks.json?v=20261019').catch(()=>null),renderMap()]).then(([data,iks])=>{portalData=data;geoCities=data.geography?.cities||[];renderMetrics(data);renderSignals(data);renderCompanies(data);renderSources(data,iks);renderGeoLayer();if(window.OilRadarCache)window.OilRadarCache.prefetchAll();}).catch((err)=>{ $('metricGrid').innerHTML=`<p class="empty-message">Не удалось загрузить данные: ${esc(err.message)}</p>`; });
