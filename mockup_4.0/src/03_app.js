(function(){
'use strict';
const $=(s,r=document)=>r.querySelector(s), $$=(s,r=document)=>[...r.querySelectorAll(s)];
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=n=>Number(n||0).toLocaleString('ru-RU');
const TODAY=new Date('2026-09-18T12:00:00');
const STAGE={breakthrough:{l:'Прорывные',c:'var(--st-break)'},emerging:{l:'Зарождающиеся',c:'var(--st-emerg)'},mature:{l:'Зрелые',c:'var(--st-mature)'},fading:{l:'Угасающие',c:'var(--st-fade)'}};
const DIR={growing:{l:'растёт',cls:'up'},stable:{l:'стабильно',cls:''},declining:{l:'снижается',cls:'down'}};
const SERIES=['#2a78d6','#eb6834','#1baf7a','#eda100','#e87ba4','#4a3aa7','#008300','#e34948'];

/* ---------- reference data: directions ---------- */
const GROUPS=[
 {id:'it',name:'ИТ и автоматизация',live:true,topics:['роботизация','автоматизация','промышленный IoT','искусственный интеллект','машинное обучение','компьютерное зрение','цифровые двойники','автономные системы','беспилотные технологии','predictive maintenance','кибербезопасность'],news:0,sci:214,pat:38,inv:31,tr:[3,4,4,6,5,7,8,9,8,11,12,10]},
 {id:'geo',name:'Геологоразведка',topics:['геология','геофизика','разведка'],news:186,sci:302,pat:44,inv:6,tr:[6,5,7,6,8,7,9,8,8,10,9,11]},
 {id:'drill',name:'Бурение и скважины',topics:['бурение','строительство скважин','ГРП','EOR'],news:241,sci:268,pat:91,inv:9,tr:[8,9,7,10,9,11,10,12,13,12,14,15]},
 {id:'prod',name:'Добыча и нефтесервис',topics:['добыча нефти','добыча газа','нефтесервис','промысловое оборудование'],news:318,sci:176,pat:73,inv:12,tr:[10,11,12,10,13,12,11,14,13,15,14,16]},
 {id:'mid',name:'Транспорт и СПГ',topics:['транспортировка','трубопроводы','СПГ'],news:154,sci:88,pat:29,inv:7,tr:[5,6,5,7,6,8,7,7,9,8,10,9]},
 {id:'down',name:'Переработка и нефтехимия',topics:['переработка нефти','переработка газа','нефтехимия'],news:172,sci:194,pat:66,inv:8,tr:[7,6,8,7,9,8,10,9,11,10,12,11]},
 {id:'hse',name:'Безопасность и экология',topics:['промышленная безопасность','экология'],news:129,sci:142,pat:21,inv:4,tr:[4,5,5,6,5,7,6,8,7,9,8,10]},
 {id:'new',name:'Энергопереход и новые направления',topics:['энергетика','CCUS','водород','новые материалы'],news:97,sci:236,pat:52,inv:9,tr:[3,4,5,6,8,9,11,13,14,17,19,22]}
];
/* geography of sources (demo counts per layer) */
const GEO=[
 {c:'Москва',news:412,sci:286,inv:64,org:'РГУ нефти и газа им. Губкина, ВНИИГАЗ, штаб-квартиры ВИНК, neftegaz.ru, comnews.ru'},
 {c:'Санкт-Петербург',news:96,sci:174,inv:22,org:'Горный университет, Газпром нефть (НТЦ), Политех'},
 {c:'Тюмень',news:118,sci:142,inv:14,org:'ТИУ, ТННЦ (Роснефть), Западно-Сибирский НОЦ'},
 {c:'Казань',news:64,sci:118,inv:9,org:'КФУ (ИГиНГТ), ТатНИПИнефть, Татнефть'},
 {c:'Уфа',news:58,sci:126,inv:7,org:'УГНТУ, БашНИПИнефть, Башнефть'},
 {c:'Томск',news:31,sci:108,inv:5,org:'ТПУ, ТГУ, Газпром трансгаз Томск'},
 {c:'Пермь',news:34,sci:74,inv:4,org:'ПНИПУ, ПермНИПИнефть, Лукойл-Пермь'},
 {c:'Самара',news:38,sci:62,inv:6,org:'СамГТУ, СамараНИПИнефть'},
 {c:'Новосибирск',news:29,sci:96,inv:8,org:'ИНГГ СО РАН, НГУ, Академпарк'},
 {c:'Екатеринбург',news:41,sci:48,inv:5,org:'УрФУ, Уралмаш НГО Холдинг'},
 {c:'Сургут',news:52,sci:18,inv:3,org:'Сургутнефтегаз, СурГУ'},
 {c:'Нижневартовск',news:27,sci:9,inv:1,org:'Самотлорнефтегаз, nprom.online (региональные материалы)'},
 {c:'Новый Уренгой',news:33,sci:12,inv:2,org:'Газпром добыча Уренгой, Ямбург'},
 {c:'Красноярск',news:22,sci:38,inv:3,org:'СФУ, Ванкорнефть'},
 {c:'Иркутск',news:18,sci:41,inv:2,org:'ИРНИТУ, ИНК'},
 {c:'Якутск',news:12,sci:26,inv:1,org:'СВФУ, Якутская топливно-энергетическая компания'},
 {c:'Хабаровск',news:14,sci:19,inv:1,org:'ТОГУ, Хабаровский НПЗ'},
 {c:'Владивосток',news:19,sci:33,inv:4,org:'ДВФУ, Приморский НОЦ'},
 {c:'Южно-Сахалинск',news:24,sci:11,inv:3,org:'Сахалинская Энергия, СахГУ'},
 {c:'Архангельск',news:9,sci:22,inv:1,org:'САФУ, Арктические проекты'},
 {c:'Мурманск',news:15,sci:14,inv:2,org:'Новатэк-Мурманск, ММБИ'},
 {c:'Астрахань',news:17,sci:21,inv:1,org:'АГТУ, Газпром добыча Астрахань'},
 {c:'Краснодар',news:21,sci:27,inv:2,org:'КубГТУ, Роснефть-НТЦ'},
 {c:'Оренбург',news:13,sci:19,inv:1,org:'ОГУ, Газпром добыча Оренбург'},
 {c:'Альметьевск',news:26,sci:17,inv:2,org:'Татнефть, Высшая школа нефти'},
 {c:'Ухта',news:11,sci:24,inv:1,org:'УГТУ, Лукойл-Коми'},
 {c:'Салехард',news:9,sci:6,inv:0,org:'Научный центр изучения Арктики'},
 {c:'Омск',news:16,sci:23,inv:2,org:'ОмГТУ, Омский НПЗ'}
];
/* sources & authority (demo score) */
const SOURCES=[
 {n:'neftegaz.ru',k:'отраслевой портал',t:'news',sqi:2900,cit:78,pop:82,live:true},
 {n:'nprom.online',k:'отраслевое издание',t:'news',sqi:820,cit:61,pop:54,live:true},
 {n:'sectormedia.ru',k:'отраслевое издание',t:'news',sqi:640,cit:44,pop:41,live:true},
 {n:'angi.ru',k:'новостное агентство',t:'news',sqi:1350,cit:57,pop:63,live:true},
 {n:'oilcapital.ru',k:'новостной портал',t:'news',sqi:1100,cit:52,pop:58,live:true},
 {n:'comnews.ru',k:'ИТ-издание',t:'news',sqi:2300,cit:66,pop:71,live:true},
 {n:'elibrary.ru / РИНЦ',k:'научные публикации',t:'sci',sqi:9100,cit:96,pop:88},
 {n:'ФИПС (патенты)',k:'патентная база',t:'sci',sqi:6200,cit:90,pop:52},
 {n:'Сколково / ФРИИ',k:'реестры инвестиций',t:'inv',sqi:4100,cit:71,pop:66}
];
SOURCES.forEach(s=>{const a=Math.min(100,Math.log10(s.sqi+1)/4*100);s.score=Math.round(.5*a+.3*s.cit+.2*s.pop);});

/* ---------- state ---------- */
const P=window.PROTO;
const S={period:365,view:'overview',mapLayer:'all',sel:new Set(),newsGroup:'it',company:'',source:'',stage:'',q:'',sort:'mentions',sources:SOURCES.filter(s=>s.live).map(s=>({...s,on:true}))};
try{const v=localStorage.getItem('otr.view');if(v)S.view=v;}catch(e){}

/* ---------- helpers ---------- */
const cutoff=()=>S.period?new Date(TODAY.getTime()-S.period*864e5):null;
const cutStr=()=>{const c=cutoff();return c?c.toISOString().slice(0,7):'';};
function ptrend(c){const cs=cutStr();return cs?c.trend.filter(p=>p.month>=cs):c.trend;}
function pmentions(c){const t=ptrend(c);return t.reduce((a,p)=>a+p.count,0)||(S.period?0:c.mentions);}
function slope(t){const v=t.map(p=>p.count);const n=v.length;if(n<2)return 0;const mx=(n-1)/2,my=v.reduce((a,b)=>a+b,0)/n;let num=0,den=0;v.forEach((y,i)=>{num+=(i-mx)*(y-my);den+=(i-mx)**2;});return den?num/den:0;}
function pevents(c){const cu=cutoff();return cu?c.events.filter(e=>e.date&&new Date(e.date)>=cu):c.events;}
function monthsRange(){const cs=cutStr()||'2025-03';const out=[];let d=new Date(cs+'-01T00:00:00');while(d<=TODAY){out.push(d.toISOString().slice(0,7));d.setMonth(d.getMonth()+1);}return out;}
function spark(vals,color,w=72,h=24,area=true){if(!vals.length)return '';const mx=Math.max(...vals,1),n=vals.length;const pts=vals.map((v,i)=>[(i/(n-1||1))*(w-2)+1,h-2-(v/mx)*(h-6)]);const d='M'+pts.map(p=>p[0].toFixed(1)+','+p[1].toFixed(1)).join('L');const last=pts[n-1];return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">${area?`<path d="${d}L${last[0].toFixed(1)},${h}L1,${h}Z" fill="${color}" opacity=".12"/>`:''}<path d="${d}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linejoin="round"/><circle cx="${last[0].toFixed(1)}" cy="${last[1].toFixed(1)}" r="2" fill="${color}"/></svg>`;}
function toast(msg){const t=$('#toast');t.textContent=msg;t.classList.add('show');clearTimeout(t._t);t._t=setTimeout(()=>t.classList.remove('show'),2600);}
function mon(m){const M=['янв','фев','мар','апр','май','июн','июл','авг','сен','окт','ноя','дек'];const [y,mm]=m.split('-');return M[+mm-1]+' '+y.slice(2);}
function dateRu(d){if(!d)return '';const x=new Date(d);if(isNaN(x))return d;return x.toLocaleDateString('ru-RU',{day:'numeric',month:'short',year:'numeric'});}

/* ---------- navigation ---------- */
function setView(v){S.view=v;$$('.nav button').forEach(b=>b.setAttribute('aria-current',b.dataset.view===v?'page':'false'));$$('.view').forEach(s=>s.hidden=s.id!=='view-'+v);try{localStorage.setItem('otr.view',v);}catch(e){}window.scrollTo({top:0});}
$$('.nav button').forEach(b=>b.addEventListener('click',()=>setView(b.dataset.view)));
$$('.topbar .seg [data-period]').forEach(b=>b.addEventListener('click',()=>{S.period=+b.dataset.period;$$('.topbar .seg [data-period]').forEach(x=>x.setAttribute('aria-pressed',x===b));renderAll();}));

/* ---------- overview: KPIs ---------- */
const ITTOTAL=P.kpis.events;
function renderKpis(){
  const total=GROUPS.reduce((a,g)=>a+(g.live?ITTOTAL:g.news)+g.sci+g.pat+g.inv,0);
  const withCo=P.clusters.reduce((a,c)=>a+c.events.filter(e=>e.company).length,0);
  const sigs=computeSignals();
  const mo=monthlyAll();
  const k=[
   {l:'Событий в контуре',v:fmt(total),d:'новости, наука, патенты, инвестиции',sp:mo},
   {l:'Сигналов за неделю',v:sigs.length,d:`<span class="tag up">${sigs.filter(s=>s.hot).length} сильных</span> требуют внимания`},
   {l:'Направлений растёт',v:GROUPS.filter(g=>g.tr[11]>g.tr[8]).length+' <small>из 8</small>',d:'по темпу упоминаний за квартал'},
   {l:'Событий с компанией',v:fmt(withCo+118),d:'основа конкурентного анализа'},
   {l:'Источников',v:S.sources.filter(s=>s.on).length+3,d:'взвешены по авторитетности'}
  ];
  $('#kpis').innerHTML=k.map(x=>`<div class="kpi"><div class="label">${x.l}</div><div class="v">${x.v}</div><div class="d">${x.d}</div>${x.sp?`<svg class="spark" viewBox="0 0 200 28" preserveAspectRatio="none">${sparkPath(x.sp,200,28)}</svg>`:''}</div>`).join('');
  $('#fSources').textContent=S.sources.filter(s=>s.on).length+3;
  $('#fSignals').textContent=sigs.length;
}
function sparkPath(vals,w,h){const mx=Math.max(...vals,1),n=vals.length;const pts=vals.map((v,i)=>[(i/(n-1))*(w-2)+1,h-2-(v/mx)*(h-6)]);const d='M'+pts.map(p=>p.join(',')).join('L');return `<path d="${d}L${w-1},${h}L1,${h}Z" fill="var(--accent)" opacity=".12"/><path d="${d}" fill="none" stroke="var(--accent)" stroke-width="1.5"/>`;}
function monthlyAll(){const m={};P.clusters.forEach(c=>c.trend.forEach(p=>{m[p.month]=(m[p.month]||0)+p.count;}));return Object.keys(m).sort().slice(-12).map(k=>m[k]*3+40);}

/* ---------- signals ---------- */
function computeSignals(){
  const out=[];
  P.clusters.forEach(c=>{const t=c.trend;if(t.length<3)return;const last=t.slice(-2).reduce((a,p)=>a+p.count,0);const prev=t.slice(0,-2).reduce((a,p)=>a+p.count,0)/Math.max(1,t.length-2)*2;if(last>=3&&last>prev*1.4)out.push({t:c.title,g:'ИТ и автоматизация',stream:'news',pct:Math.round((last/Math.max(prev,1)-1)*100),hot:last>prev*2,tr:t.map(p=>p.count),id:c.id,live:true});});
  out.sort((a,b)=>b.pct-a.pct);
  const demo=[
   {t:'Водородные технологии на промыслах: пилоты электролизёров',g:'Энергопереход',stream:'sci',pct:190,hot:true,tr:[1,1,2,2,3,4,5,7,9]},
   {t:'Остановки НПЗ: спрос на ремонт, резервирование и защиту объектов',g:'Политика и рынок → Переработка',stream:'pol',pct:160,hot:true,tr:[1,1,2,2,3,4,6,8,9]},
   {t:'Роторные управляемые системы российской сборки',g:'Бурение и скважины',stream:'news',pct:120,hot:true,tr:[2,3,2,4,4,5,6,8,9]},
   {t:'Улавливание CO₂ на газоперерабатывающих заводах',g:'Энергопереход',stream:'inv',pct:85,hot:false,tr:[1,2,2,2,3,3,4,5,6]},
   {t:'Полимерные ПАВ для EOR на месторождениях Татарстана',g:'Бурение и скважины',stream:'sci',pct:64,hot:false,tr:[3,3,4,4,4,5,5,6,7]},
   {t:'Отечественные катализаторы гидрокрекинга',g:'Переработка и нефтехимия',stream:'news',pct:48,hot:false,tr:[4,4,5,5,6,6,6,7,8]}
  ];
  return [...out.slice(0,4),...demo].slice(0,8);
}
function renderSignals(){
  const s=computeSignals();
  $('#signals').innerHTML=s.map(x=>`<div class="sig" ${x.id?`data-open="${x.id}"`:''}>
    <div class="ico ${x.hot?'hot':''}">+${x.pct}%</div>
    <div><div class="t">${esc(x.t)}</div><div class="m"><span class="tag ${x.stream}">${x.stream==='news'?'медиа':x.stream==='sci'?'наука':x.stream==='pol'?'внешние условия':'инвестиции'}</span>${esc(x.g)}${x.live?' · <span class="muted">реальные данные</span>':''}</div></div>
    ${spark(x.tr,x.hot?'var(--amber)':'var(--accent)',64,26)}</div>`).join('');
  $('#fSignalsD').innerHTML=`${s.filter(x=>x.hot).length} сильных · ${s.length-s.filter(x=>x.hot).length} умеренных`;
}

/* ---------- landscape matrix ---------- */
function lvl(v,max){if(!v)return 0;const r=v/max;return r>.8?5:r>.6?4:r>.4?3:r>.2?2:1;}
function renderMatrix(){
  const cols=[['news','Медиа'],['sci','Наука'],['pat','Патенты'],['inv','Инвестиции']];
  const val=(g,k)=>k==='news'&&g.live?ITTOTAL:g[k];
  const max={};cols.forEach(([k])=>max[k]=Math.max(...GROUPS.map(g=>val(g,k))));
  $('#matrix').innerHTML=`<thead><tr><th>Направление</th>${cols.map(c=>`<th class="c">${c[1]}</th>`).join('')}<th class="c">Итого</th><th>12 мес.</th></tr></thead><tbody>${GROUPS.map(g=>{const tot=cols.reduce((a,[k])=>a+val(g,k),0);return `<tr class="clickable" data-group="${g.id}"><td class="name">${esc(g.name)}${g.live?'<span class="live-mark" title="реальные данные"></span>':''}<small>${g.topics.slice(0,4).join(', ')}${g.topics.length>4?' …':''}</small></td>${cols.map(([k])=>`<td class="c"><span class="cell l${lvl(val(g,k),max[k])}">${fmt(val(g,k))}</span></td>`).join('')}<td class="c num">${fmt(tot)}</td><td>${spark(g.tr,g.tr[11]>g.tr[8]?'var(--good)':'var(--muted)',70,22,false).replace('<svg','<svg class="trend"')}</td></tr>`;}).join('')}</tbody>`;
  $$('#matrix tr[data-group]').forEach(tr=>tr.addEventListener('click',()=>{S.newsGroup=tr.dataset.group;setView('news');renderNews();}));
}

/* ---------- map ---------- */
const MAP={vb:[0,0,1000,538],base:[0,0,1000,538]};
function renderMap(){
  const svg=$('#map');
  const layer=S.mapLayer;
  const val=g=>layer==='all'?g.news+g.sci+g.inv:g[layer];
  const mx=Math.max(...GEO.map(val));
  const clsOf=g=>{if(layer!=='all')return layer==='sci'?'sci':layer==='inv'?'inv':'';return g.sci>g.news?'sci':'';};
  const sorted=[...GEO].sort((a,b)=>val(b)-val(a));
  svg.innerHTML=`<path class="map-land" d="${window.RU_PATH}"/>`+sorted.map(g=>{const [x,y]=window.CITIES[g.c];const r=6+Math.sqrt(val(g)/mx)*46;return `<g class="city" data-city="${esc(g.c)}"><circle class="zone ${clsOf(g)}" cx="${x}" cy="${y}" r="${r.toFixed(1)}"/><circle class="zone-core ${clsOf(g)}" cx="${x}" cy="${y}" r="2.6"/>${val(g)>=mx*.12?`<text class="map-label" x="${x+5}" y="${y-5}">${esc(g.c)}</text>`:''}</g>`;}).join('');
  applyVB();
  const tip=$('#mapTip'),wrap=$('#mapWrap');
  $$('#map .city').forEach(el=>{
    el.addEventListener('mousemove',e=>{const g=GEO.find(x=>x.c===el.dataset.city);const r=wrap.getBoundingClientRect();tip.style.display='block';tip.innerHTML=`<b>${esc(g.c)}</b>${fmt(g.news+g.sci+g.inv)} материалов · медиа ${g.news}, наука ${g.sci}, компании ${g.inv}<div style="opacity:.75;margin-top:3px">${esc(g.org)}</div>`;tip.style.left=Math.min(e.clientX-r.left+14,r.width-270)+'px';tip.style.top=(e.clientY-r.top+14)+'px';});
    el.addEventListener('mouseleave',()=>tip.style.display='none');
    el.addEventListener('click',()=>{$$('#map .zone').forEach(z=>z.classList.remove('active'));el.querySelector('.zone').classList.add('active');highlightGeo(el.dataset.city);});
  });
  $('#geoList').innerHTML=sorted.slice(0,8).map(g=>`<div class="geo-row" data-city="${esc(g.c)}"><div><div style="display:flex;justify-content:space-between;gap:8px"><span>${esc(g.c)}</span><span class="n">${fmt(val(g))}</span></div><div class="bar"><i style="width:${(val(g)/mx*100).toFixed(0)}%"></i></div></div></div>`).join('');
}
function highlightGeo(c){$$('#geoList .geo-row').forEach(r=>r.style.background=r.dataset.city===c?'var(--surface-2)':'');}
function applyVB(){$('#map').setAttribute('viewBox',MAP.vb.join(' '));}
function zoom(f,cx,cy){const [x,y,w,h]=MAP.vb;const nw=Math.max(120,Math.min(1000,w/f)),nh=nw*538/1000;cx=cx??x+w/2;cy=cy??y+h/2;const nx=cx-(cx-x)*nw/w,ny=cy-(cy-y)*nh/h;MAP.vb=[nx,ny,nw,nh];applyVB();}
$('#zoomIn').onclick=()=>zoom(1.5);$('#zoomOut').onclick=()=>zoom(1/1.5);$('#zoomReset').onclick=()=>{MAP.vb=[...MAP.base];applyVB();};
$('#mapLayer').addEventListener('click',e=>{const b=e.target.closest('[data-layer]');if(!b)return;S.mapLayer=b.dataset.layer;$$('#mapLayer button').forEach(x=>x.setAttribute('aria-pressed',x===b));renderMap();});
(function panZoom(){const svg=$('#map');let drag=null;
  const toSvg=(ex,ey)=>{const r=svg.getBoundingClientRect();const [x,y,w,h]=MAP.vb;return [x+(ex-r.left)/r.width*w,y+(ey-r.top)/r.height*h];};
  svg.addEventListener('wheel',e=>{e.preventDefault();const [cx,cy]=toSvg(e.clientX,e.clientY);zoom(e.deltaY<0?1.2:1/1.2,cx,cy);},{passive:false});
  svg.addEventListener('pointerdown',e=>{drag={x:e.clientX,y:e.clientY,vb:[...MAP.vb]};svg.setPointerCapture(e.pointerId);svg.classList.add('dragging');});
  svg.addEventListener('pointermove',e=>{if(!drag)return;const r=svg.getBoundingClientRect();const dx=(e.clientX-drag.x)/r.width*drag.vb[2],dy=(e.clientY-drag.y)/r.height*drag.vb[3];MAP.vb=[drag.vb[0]-dx,drag.vb[1]-dy,drag.vb[2],drag.vb[3]];applyVB();});
  const up=()=>{drag=null;svg.classList.remove('dragging');};svg.addEventListener('pointerup',up);svg.addEventListener('pointercancel',up);
})();

/* ---------- NEWS: groups ---------- */
function renderNews(){
  $('#newsGroups').innerHTML=GROUPS.map(g=>`<button class="chip" data-g="${g.id}" aria-pressed="${S.newsGroup===g.id}">${g.live?'<span class="dot"></span>':''}${esc(g.name)}<span class="cnt">${fmt(g.live?ITTOTAL:g.news)}</span></button>`).join('');
  $$('#newsGroups .chip').forEach(b=>b.addEventListener('click',()=>{S.newsGroup=b.dataset.g;renderNews();}));
  const g=GROUPS.find(x=>x.id===S.newsGroup);
  $('#newsLive').hidden=!g.live;$('#newsDemo').hidden=g.live;
  if(g.live)renderProto();else renderNewsDemo(g);
}
function renderNewsDemo(g){
  const themes=DEMO_THEMES[g.id]||[];
  $('#newsDemo').innerHTML=`<div class="filters"><span class="tag demo">макет целевого охвата</span><span class="small muted">${esc(g.name)}: ${g.topics.join(', ')}. Структура раздела повторяет «ИТ и автоматизацию»; поток подключается в версии 4.0.</span></div>
  <div class="grid"><div class="card c12"><div class="card-h"><div><h2>Что изменилось</h2><div class="sub">За выбранный период</div></div></div><div class="two"><div>${themes.slice(0,3).map(t=>`<div class="mini"><span class="t">${esc(t.t)}</span><span class="n" style="color:var(--good)">+${t.d}</span></div>`).join('')}</div><div>${themes.slice(3,6).map(t=>`<div class="mini"><span class="t">${esc(t.t)}</span><span class="n muted">${t.d>0?'+':''}${t.d}</span></div>`).join('')}</div></div></div>
  <div class="c12"><div class="card-h" style="margin-bottom:10px"><div><h2>Темы направления</h2><div class="sub">${themes.length} тем</div></div></div><div class="topics">${themes.map(t=>`<div class="topic"><div class="stripe" style="background:${STAGE[t.s].c}"></div><h3>${esc(t.t)}</h3><div class="desc">${esc(t.desc)}</div><div class="foot"><div class="tags"><span class="tag"><span class="dot" style="background:${STAGE[t.s].c}"></span>${STAGE[t.s].l}</span><span class="tag">${t.m} упом.</span></div>${spark(t.tr,STAGE[t.s].c)}</div></div>`).join('')}</div></div></div>`;
}
const DEMO_THEMES={
 geo:[{t:'Сейсморазведка высокой плотности 3D/4D',s:'breakthrough',m:41,d:9,tr:[2,3,4,4,5,6,7,8],desc:'Широкоазимутальная съёмка и повторные 4D-наблюдения для контроля разработки.'},{t:'Электроразведка и грави-магнитные методы для трудноизвлекаемых запасов',s:'emerging',m:23,d:5,tr:[1,2,2,3,3,4,4,5],desc:'Комплексирование потенциальных полей для картирования ТрИЗ и доманиковых отложений.'},{t:'Отечественное ПО интерпретации сейсмики',s:'emerging',m:34,d:7,tr:[2,2,3,4,5,5,6,7],desc:'Импортозамещение пакетов обработки и интерпретации, включая инверсию.'},{t:'Бассейновое моделирование и оценка ресурсов Арктики',s:'mature',m:18,d:1,tr:[3,3,3,2,3,3,3,3],desc:'Оценка нефтегазоносности шельфа и Восточной Сибири.'},{t:'Керновые исследования: цифровой керн',s:'emerging',m:15,d:3,tr:[1,1,2,2,2,3,3,4],desc:'Томография керна и цифровая петрофизика для прогнозирования свойств пласта.'},{t:'Геохимические методы поиска',s:'fading',m:9,d:-2,tr:[3,3,2,2,2,2,1,1],desc:'Поверхностная геохимия как дополнение к сейсмике.'}],
 drill:[{t:'Роторные управляемые системы российской сборки',s:'breakthrough',m:58,d:14,tr:[2,3,2,4,4,5,6,9],desc:'Серийные РУС для наклонно-направленного и горизонтального бурения.'},{t:'Многостадийный ГРП на горизонтальных скважинах',s:'mature',m:64,d:4,tr:[6,6,7,7,7,8,8,8],desc:'Технологии заканчивания с 20+ стадиями, отечественные пропанты и жидкости.'},{t:'Полимерные и ПАВ-методы EOR',s:'emerging',m:27,d:6,tr:[1,2,2,3,3,4,5,6],desc:'Химические методы увеличения нефтеотдачи на зрелых месторождениях.'},{t:'Буровые растворы и долота для сложных пластов',s:'mature',m:39,d:2,tr:[4,4,5,5,5,5,6,6],desc:'PDC-долота, растворы для баженовской свиты.'},{t:'Бурение на шельфе и в Арктике',s:'emerging',m:21,d:3,tr:[2,2,2,3,3,3,4,4],desc:'Технологии для ледовых условий и глубоководья.'},{t:'Термические методы EOR',s:'fading',m:11,d:-3,tr:[3,3,3,2,2,2,1,1],desc:'Паротепловое воздействие на высоковязкую нефть.'}],
 prod:[{t:'Мехдобыча: отечественные УЭЦН и станции управления',s:'mature',m:71,d:5,tr:[7,7,8,8,8,9,9,10],desc:'Импортозамещение погружного оборудования.'},{t:'Разработка трудноизвлекаемых запасов',s:'breakthrough',m:53,d:11,tr:[3,4,4,5,6,7,8,9],desc:'Бажен, ачимовка, доманик: технологии добычи.'},{t:'Промысловая подготовка нефти и газа',s:'mature',m:32,d:1,tr:[4,4,4,4,4,5,4,5],desc:'Сепарация, обезвоживание, компримирование.'},{t:'Нефтесервис: интегрированные проекты',s:'emerging',m:29,d:6,tr:[2,2,3,3,4,4,5,6],desc:'Переход к контрактам полного цикла.'},{t:'Добыча газа на многопластовых залежах',s:'emerging',m:18,d:2,tr:[2,2,2,3,3,3,3,4],desc:'Ачимовские и туронские залежи Ямала.'},{t:'Ремонт скважин: колтюбинг',s:'mature',m:24,d:0,tr:[3,3,3,3,3,3,3,3],desc:'Гибкие НКТ для ремонта и стимуляции.'}],
 mid:[{t:'Крупнотоннажное СПГ на российских технологиях',s:'breakthrough',m:47,d:12,tr:[2,3,3,4,5,6,7,9],desc:'Линии сжижения «Арктический каскад» и последующие.'},{t:'Диагностика трубопроводов внутритрубными снарядами',s:'mature',m:36,d:2,tr:[4,4,4,5,5,5,5,5],desc:'Магнитные и ультразвуковые дефектоскопы.'},{t:'Малотоннажное СПГ и автономная газификация',s:'emerging',m:22,d:5,tr:[1,2,2,2,3,3,4,5],desc:'Мини-заводы и криогенное оборудование.'},{t:'Танкерный флот ледового класса',s:'emerging',m:19,d:4,tr:[1,1,2,2,3,3,3,4],desc:'Суда для Северного морского пути.'},{t:'Компрессорные станции и ГПА',s:'mature',m:28,d:1,tr:[3,3,4,4,4,4,4,4],desc:'Газоперекачивающие агрегаты нового поколения.'},{t:'Антикоррозионные покрытия труб',s:'fading',m:10,d:-1,tr:[2,2,2,2,1,1,1,1],desc:'Полимерные и эпоксидные покрытия.'}],
 down:[{t:'Отечественные катализаторы гидропроцессов',s:'breakthrough',m:44,d:10,tr:[3,3,4,4,5,6,7,8],desc:'Гидрокрекинг, гидроочистка, риформинг.'},{t:'Глубокая переработка: гидроконверсия гудрона',s:'emerging',m:26,d:6,tr:[1,2,2,3,3,4,4,5],desc:'Повышение выхода светлых нефтепродуктов.'},{t:'Полиолефины и крупнотоннажная нефтехимия',s:'mature',m:39,d:3,tr:[4,4,5,5,5,5,6,6],desc:'Пиролиз, полиэтилен, полипропилен.'},{t:'Переработка газа: гелий и этан',s:'emerging',m:21,d:5,tr:[1,1,2,2,3,3,4,4],desc:'Амурский ГПЗ и новые проекты.'},{t:'Малотоннажная химия и спецпродукты',s:'emerging',m:17,d:3,tr:[1,1,2,2,2,3,3,3],desc:'Присадки, растворители, катализаторы.'},{t:'Модернизация НПЗ под Евро-6',s:'fading',m:12,d:-2,tr:[3,3,2,2,2,2,1,1],desc:'Завершение программ модернизации.'}],
 hse:[{t:'Мониторинг выбросов метана',s:'breakthrough',m:33,d:9,tr:[1,2,2,3,4,5,6,7],desc:'Спутниковые и дроновые системы обнаружения утечек.'},{t:'Промбезопасность: системы контроля состояния персонала',s:'emerging',m:24,d:5,tr:[2,2,2,3,3,4,4,5],desc:'Носимые устройства и видеоаналитика.'},{t:'Утилизация ПНГ',s:'mature',m:28,d:1,tr:[3,3,4,4,4,4,4,4],desc:'Достижение 95 % полезного использования.'},{t:'Рекультивация и ликвидация накопленного вреда',s:'emerging',m:16,d:3,tr:[1,1,2,2,2,3,3,3],desc:'Технологии очистки грунтов и водоёмов.'},{t:'Обращение с буровыми отходами',s:'mature',m:14,d:0,tr:[2,2,2,2,2,2,2,2],desc:'Переработка шламов.'},{t:'Противофонтанная безопасность',s:'fading',m:8,d:-1,tr:[2,2,1,1,1,1,1,1],desc:'Регламенты и оборудование.'}],
 new:[{t:'Водород: производство и транспорт',s:'breakthrough',m:39,d:15,tr:[1,1,2,2,3,4,6,8],desc:'Паровая конверсия с улавливанием, электролиз, водородные хабы.'},{t:'CCUS: улавливание и закачка CO₂',s:'emerging',m:31,d:11,tr:[1,1,2,3,3,4,5,7],desc:'Хранение в истощённых пластах, CO₂-EOR.'},{t:'Новые материалы: композиты и сплавы для агрессивных сред',s:'emerging',m:22,d:6,tr:[1,2,2,2,3,3,4,5],desc:'Стеклопластиковые трубы, коррозионно-стойкие стали.'},{t:'Распределённая энергетика на промыслах',s:'emerging',m:18,d:4,tr:[1,1,2,2,2,3,3,4],desc:'Газопоршневые и солнечные установки, накопители.'},{t:'Геотермальная энергия на скважинном фонде',s:'emerging',m:9,d:3,tr:[0,0,1,1,1,2,2,3],desc:'Использование выработанных скважин.'},{t:'Биотопливо и SAF',s:'emerging',m:11,d:2,tr:[1,1,1,2,2,2,2,3],desc:'Ко-процессинг растительного сырья на НПЗ.'}]
};

/* ---------- PROTOTYPE (real data) ---------- */
function filtered(){
  return P.clusters.filter(c=>{
    if(S.stage&&c.stage!==S.stage)return false;
    if(S.q&&!(c.title+' '+c.description+' '+c.subclusters.map(s=>s.title).join(' ')+' '+c.events.map(e=>e.topic).join(' ')).toLowerCase().includes(S.q))return false;
    if(S.company&&!c.events.some(e=>e.company===S.company))return false;
    if(S.source&&!c.events.some(e=>e.source===S.source))return false;
    if(S.period&&pmentions(c)===0&&pevents(c).length===0)return false;
    return true;
  });
}
function renderProto(){
  if(!$('#fCompany').dataset.done){
    $('#fCompany').innerHTML='<option value="">Все компании</option>'+P.companies.map(c=>`<option>${esc(c.name)}</option>`).join('');
    $('#fSource').innerHTML='<option value="">Все источники</option>'+P.sources.map(s=>`<option>${esc(s)}</option>`).join('');
    $('#fCompany').dataset.done=1;
    $('#fCompany').onchange=e=>{S.company=e.target.value;renderProto();};
    $('#fSource').onchange=e=>{S.source=e.target.value;renderProto();};
    $('#fStage').onchange=e=>{S.stage=e.target.value;renderProto();};
    $('#q').oninput=e=>{S.q=e.target.value.trim().toLowerCase();renderProto();};
    $('#sortTopics').onchange=e=>{S.sort=e.target.value;renderTopics();};
  }
  renderDiff();renderQuad();renderLines();renderSide();renderTopics();
}
function renderDiff(){
  const d30=new Date(TODAY.getTime()-30*864e5),d60=new Date(TODAY.getTime()-60*864e5);
  const rows=P.clusters.map(c=>{const a=c.events.filter(e=>e.date&&new Date(e.date)>=d30).length;const b=c.events.filter(e=>e.date&&new Date(e.date)>=d60&&new Date(e.date)<d30).length;return {c,a,b,d:a-b};});
  const up=rows.filter(r=>r.d>0).sort((a,b)=>b.d-a.d).slice(0,4),dn=rows.filter(r=>r.d<0).sort((a,b)=>a.d-b.d).slice(0,4);
  const newEv=rows.reduce((s,r)=>s+r.a,0);
  $('#diffSub').textContent=`За последние 30 дней: ${newEv} новых событий · ${up.length} тем ускорились · ${dn.length} замедлились`;
  $('#diffBody').innerHTML=`<div><div class="label" style="margin-bottom:6px">Набирают упоминания</div>${up.map(r=>`<div class="mini" data-open="${r.c.id}"><span class="t">${esc(r.c.title)}</span><span class="n" style="color:var(--good)">+${r.d} · ${r.a} за мес.</span></div>`).join('')||'<div class="empty">Нет ускорившихся тем</div>'}</div><div><div class="label" style="margin-bottom:6px">Теряют внимание</div>${dn.map(r=>`<div class="mini" data-open="${r.c.id}"><span class="t">${esc(r.c.title)}</span><span class="n" style="color:var(--bad)">${r.d} · ${r.a} за мес.</span></div>`).join('')||'<div class="empty">Нет замедлившихся тем</div>'}</div>`;
}
function renderQuad(){
  const cs=filtered();const W=640,H=440,pl=44,pr=16,pt=16,pb=40;const X=v=>pl+(v/100)*(W-pl-pr),Y=v=>pt+(1-v/100)*(H-pt-pb);
  const mx=Math.max(...cs.map(c=>c.mentions),1);
  let s=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Карта стадий тем">`;
  [0,25,50,75,100].forEach(v=>{s+=`<line class="gl" x1="${X(v)}" y1="${pt}" x2="${X(v)}" y2="${H-pb}"/><line class="gl" x1="${pl}" y1="${Y(v)}" x2="${W-pr}" y2="${Y(v)}"/><text class="axis" x="${X(v)}" y="${H-pb+16}" text-anchor="middle">${v}</text><text class="axis" x="${pl-8}" y="${Y(v)+4}" text-anchor="end">${v}</text>`;});
  s+=`<line class="mid" x1="${X(55)}" y1="${pt}" x2="${X(55)}" y2="${H-pb}"/><line class="mid" x1="${pl}" y1="${Y(55)}" x2="${W-pr}" y2="${Y(55)}"/>`;
  s+=`<text class="qlabel" x="${X(57)}" y="${pt+14}">Прорывные</text><text class="qlabel" x="${pl+6}" y="${pt+14}">Зарождающиеся</text><text class="qlabel" x="${X(57)}" y="${H-pb-8}">Зрелые</text><text class="qlabel" x="${pl+6}" y="${H-pb-8}">Угасающие</text>`;
  s+=`<text class="axis" x="${(pl+W-pr)/2}" y="${H-6}" text-anchor="middle">Внедрённость →</text><text class="axis" transform="translate(12 ${(pt+H-pb)/2}) rotate(-90)" text-anchor="middle">Новизна →</text>`;
  [...cs].sort((a,b)=>b.mentions-a.mentions).forEach(c=>{const r=5+Math.sqrt(c.mentions/mx)*20;s+=`<circle data-id="${c.id}" cx="${X(c.exe).toFixed(1)}" cy="${Y(c.inn).toFixed(1)}" r="${r.toFixed(1)}" fill="${STAGE[c.stage].c}" fill-opacity=".78"/>`;});
  s+='</svg><div class="tip" id="qTip"></div>';
  const q=$('#quad');q.innerHTML=s;
  const tip=$('#qTip');
  $$('circle',q).forEach(el=>{const c=P.clusters.find(x=>x.id===el.dataset.id);
    el.addEventListener('mousemove',e=>{const r=q.getBoundingClientRect();tip.style.display='block';tip.innerHTML=`<b>${esc(c.title)}</b>${STAGE[c.stage].l} · ${c.mentions} упом.<br>новизна ${c.inn} · внедрённость ${c.exe}<br><span style="opacity:.75">${c.companies.slice(0,3).map(x=>x.name).join(', ')||'компании не названы'}</span>`;tip.style.left=Math.min(e.clientX-r.left+12,r.width-290)+'px';tip.style.top=(e.clientY-r.top+12)+'px';});
    el.addEventListener('mouseleave',()=>tip.style.display='none');
    el.addEventListener('click',()=>openCluster(c.id));
  });
}
let TOP=[];
function renderLines(){
  const cs=filtered().sort((a,b)=>pmentions(b)-pmentions(a));
  TOP=cs.slice(0,10);
  if(!S.sel.size||![...S.sel].some(id=>TOP.find(c=>c.id===id)))S.sel=new Set(TOP.slice(0,4).map(c=>c.id));
  const months=monthsRange();const W=520,H=240,pl=34,pr=110,pt=10,pb=26;
  const series=TOP.map((c,i)=>{const m={};c.trend.forEach(p=>m[p.month]=p.count);let acc=0;return {c,col:SERIES[i%8],v:months.map(mo=>acc+=(m[mo]||0))};});
  const mx=Math.max(...series.filter(s=>S.sel.has(s.c.id)).map(s=>s.v[s.v.length-1]),1);
  const X=i=>pl+i/(months.length-1||1)*(W-pl-pr),Y=v=>pt+(1-v/mx)*(H-pt-pb);
  let s=`<svg viewBox="0 0 ${W} ${H}">`;
  [0,.5,1].forEach(f=>{s+=`<line class="gl" x1="${pl}" x2="${W-pr}" y1="${Y(mx*f)}" y2="${Y(mx*f)}"/><text class="axis" x="${pl-6}" y="${Y(mx*f)+4}" text-anchor="end">${Math.round(mx*f)}</text>`;});
  months.forEach((mo,i)=>{if(i%Math.ceil(months.length/6)===0||i===months.length-1)s+=`<text class="axis" x="${X(i)}" y="${H-8}" text-anchor="middle">${mon(mo)}</text>`;});
  const sel=series.filter(x=>S.sel.has(x.c.id));
  const ends=[];
  sel.forEach(x=>{const d='M'+x.v.map((v,i)=>X(i).toFixed(1)+','+Y(v).toFixed(1)).join('L');s+=`<path class="s" d="${d}" stroke="${x.col}"/>`;ends.push({y:Y(x.v[x.v.length-1]),col:x.col,t:x.c.title});});
  ends.sort((a,b)=>a.y-b.y);let last=-99;ends.forEach(e=>{let y=Math.max(e.y,last+12);last=y;s+=`<circle cx="${W-pr}" cy="${e.y}" r="3" fill="${e.col}"/><text class="end" x="${W-pr+7}" y="${y+4}">${esc(e.t.length>18?e.t.slice(0,17)+'…':e.t)}</text>`;});
  s+='</svg>';$('#lines').innerHTML=s;
  $('#pick').innerHTML=series.map(x=>`<button aria-pressed="${S.sel.has(x.c.id)}" data-id="${x.c.id}"><i style="${S.sel.has(x.c.id)?'background:'+x.col:''}"></i><span>${esc(x.c.title)}</span><span class="n">${pmentions(x.c)}</span></button>`).join('');
  $$('#pick button').forEach(b=>b.addEventListener('click',()=>{const id=b.dataset.id;if(S.sel.has(id)){if(S.sel.size>1)S.sel.delete(id);}else S.sel.add(id);renderLines();}));
}
function renderSide(){
  const cs=filtered().map(c=>({c,s:slope(ptrend(c)),m:pmentions(c)}));
  const g=cs.filter(x=>x.s>.05).sort((a,b)=>b.s-a.s).slice(0,6),f=cs.filter(x=>x.s<-.05).sort((a,b)=>a.s-b.s).slice(0,6);
  const row=(x,cls)=>`<div class="mini" data-open="${x.c.id}"><span class="t">${esc(x.c.title)}</span><span class="n" style="color:var(--${cls})">${x.s>0?'+':''}${x.s.toFixed(2)}/мес</span></div>`;
  $('#growing').innerHTML=g.map(x=>row(x,'good')).join('')||'<div class="empty">Нет растущих тем в периоде</div>';
  $('#fading').innerHTML=f.map(x=>row(x,'bad')).join('')||'<div class="empty">Нет снижающихся тем в периоде</div>';
  const co={};filtered().forEach(c=>pevents(c).forEach(e=>{if(e.company)co[e.company]=(co[e.company]||0)+1;}));
  const list=Object.entries(co).sort((a,b)=>b[1]-a[1]).slice(0,12);
  $('#coList').innerHTML=list.map(([n,k])=>`<button class="co" data-co="${esc(n)}">${esc(n)}<span class="n">${k}</span></button>`).join('')||'<div class="empty">Компании не названы</div>';
  $$('#coList .co').forEach(b=>b.addEventListener('click',()=>{S.company=b.dataset.co;$('#fCompany').value=S.company;renderProto();}));
}
function renderTopics(){
  const old=$('#moreBtn');if(old)old.remove();let cs=filtered().map(c=>({...c,pm:pmentions(c),sl:slope(ptrend(c))}));
  const k=S.sort;cs.sort((a,b)=>k==='mentions'?b.pm-a.pm:k==='slope'?b.sl-a.sl:b[k]-a[k]);
  $('#catSub').textContent=`${cs.length} тем · ${cs.reduce((a,c)=>a+c.pm,0)} упоминаний за период`;
  const LIM=S.showAll?cs.length:16;$('#topics').innerHTML=cs.slice(0,LIM).map(c=>`<div class="topic" data-open="${c.id}"><div class="stripe" style="background:${STAGE[c.stage].c}"></div><h3>${esc(c.title)}</h3><div class="desc">${esc(c.description)}</div><div class="foot"><div class="tags"><span class="tag"><span class="dot" style="background:${STAGE[c.stage].c}"></span>${STAGE[c.stage].l}</span><span class="tag">${c.pm} упом.</span>${c.forecast.direction!=='stable'?`<span class="tag ${DIR[c.forecast.direction].cls}">${DIR[c.forecast.direction].l}</span>`:''}</div>${spark(ptrend(c).map(p=>p.count),STAGE[c.stage].c)}</div></div>`).join('')||'<div class="empty c12">Ничего не найдено. Измените фильтры или период.</div>';
  if(cs.length>16)$('#topics').insertAdjacentHTML('afterend',`<div class="more" id="moreBtn"><button class="btn">${S.showAll?'Свернуть':'Показать все '+cs.length+' тем'}</button></div>`);
  const ob=$('#moreBtn');if(ob){ob.querySelector('button').onclick=()=>{S.showAll=!S.showAll;renderTopics();};}
}
document.addEventListener('click',e=>{const el=e.target.closest('[data-open]');if(el&&!e.target.closest('a'))openCluster(el.dataset.open);});

/* ---------- detail drawer ---------- */
function openCluster(id){
  const c=P.clusters.find(x=>x.id===id);if(!c)return;
  $('#dLabel').innerHTML=`<span class="tag" style="margin-right:6px"><span class="dot" style="background:${STAGE[c.stage].c}"></span>${STAGE[c.stage].l}</span><span class="tag news">Новости · ИТ и автоматизация</span> <span class="tag">${c.segment}</span>`;
  $('#dTitle').textContent=c.title;
  const ev=[...c.events].filter(e=>!S.company||e.company===S.company);
  const coMax=Math.max(...c.companies.map(x=>x.count),1);
  const months=monthsRange();const m={};c.trend.forEach(p=>m[p.month]=p.count);
  const f=c.forecast;
  $('#dBody').innerHTML=`
   <p style="color:var(--ink-2)">${esc(c.description)}</p>
   <div class="kv"><div><div class="label">Упоминаний</div><div class="v num">${c.mentions}</div></div><div><div class="label">Новизна</div><div class="v num">${c.inn}</div></div><div><div class="label">Внедрённость</div><div class="v num">${c.exe}</div></div></div>
   <div class="sect"><h3>Динамика упоминаний <span class="tag ${DIR[f.direction].cls}">${DIR[f.direction].l}</span></h3><div style="height:64px">${spark(months.map(x=>m[x]||0),STAGE[c.stage].c,400,64).replace('<svg','<svg style="width:100%;height:64px"')}</div><div class="small muted" style="display:flex;justify-content:space-between"><span>${mon(months[0])}</span><span>${mon(months[months.length-1])}</span></div></div>
   <div class="sect"><h3>Сценарий на 6 месяцев <span class="help left" tabindex="0">?<span class="tip"><b>Как строится прогноз</b>Помесячный ряд упоминаний темы передаётся в языковую модель вместе с примерами событий; модель возвращает направление, качественный нарратив и рекомендуемое действие. Уверенность ${Math.round((f.confidence||0)*100)} % отражает длину и плотность ряда. Не является инвестиционной рекомендацией.</span></span></h3><p style="font-size:13px;color:var(--ink-2)">${esc(f.narrative)}</p><div class="action" style="margin-top:10px"><b>Рекомендуемое действие</b>${esc(f.action)}</div></div>
   ${c.subclusters.length?`<div class="sect"><h3>Подтемы</h3><div class="subs">${c.subclusters.map(s=>`<div><span>${esc(s.title)}</span><span class="num muted">${s.mentions}</span></div>`).join('')}</div></div>`:''}
   ${c.companies.length?`<div class="sect"><h3>Компании в теме</h3><div class="bars">${c.companies.map(x=>`<div class="row"><span>${esc(x.name)}</span><div class="b"><i style="width:${x.count/coMax*100}%"></i></div><span class="n">${x.count}</span></div>`).join('')}</div></div>`:''}
   <div class="sect"><h3>Факты и источники <span class="tag">${ev.length} из ${c.n_events}</span></h3>${ev.map(e=>`<div class="fact-row"><div class="t">${esc(e.topic)}</div><div class="s">${esc(e.summary)}</div><div class="m">${e.company?`<span class="tag">${esc(e.company)}</span>`:''}<span>${dateRu(e.date)}</span><span>${esc(e.source)}</span><a href="${esc(e.link)}" target="_blank" rel="noopener">Открыть публикацию ↗</a></div></div>`).join('')}</div>`;
  openDrawer('detail');
}
function openDrawer(id){$('#'+id).classList.add('open');$('#'+id).setAttribute('aria-hidden','false');$('#overlay').classList.add('open');}
function closeDrawers(){$$('.drawer').forEach(d=>{d.classList.remove('open');d.setAttribute('aria-hidden','true');});$('#overlay').classList.remove('open');}
$('#overlay').onclick=closeDrawers;$('#dClose').onclick=closeDrawers;$('#sClose').onclick=closeDrawers;
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeDrawers();});
$('#btnSettings').onclick=()=>openDrawer('settings');

/* ---------- SCIENCE (demo) ---------- */
function renderScience(){
  $('#sciGroups').innerHTML=`<span class="tag sci">Публикации</span><span class="tag pat">Патенты</span><span class="small muted" style="align-self:center">Источники: eLibrary / РИНЦ, ФИПС, сайты 42 университетов и НИИ · макет целевого охвата</span>`;
  const mx=Math.max(...GROUPS.map(g=>g.sci+g.pat));
  $('#sciBars').innerHTML=GROUPS.map(g=>`<div class="hbar"><span>${esc(g.name)}</span><div class="b" style="display:flex;gap:2px;background:none"><i style="width:${g.sci/mx*100}%;background:var(--sci)"></i><i style="width:${g.pat/mx*100}%;background:var(--pat)"></i></div><span class="n">${g.sci+g.pat}</span></div>`).join('')+`<div class="legend"><span><i style="background:var(--sci)"></i>Статьи</span><span><i style="background:var(--pat)"></i>Патенты</span></div>`;
  const centers=[['РГУ нефти и газа им. Губкина','Москва',214,3.8,'Бурение, разработка, нефтехимия',97],['Санкт-Петербургский горный университет','Санкт-Петербург',186,3.4,'Геология, ТрИЗ, экология',91],['Казанский федеральный университет','Казань',142,4.1,'EOR, катализ, битумы',88],['Тюменский индустриальный университет','Тюмень',128,2.6,'Бурение, мехдобыча',79],['УГНТУ','Уфа',121,2.9,'Переработка, трубопроводы',77],['ИНГГ СО РАН','Новосибирск',96,4.6,'Геофизика, бассейновое моделирование',83],['Томский политехнический университет','Томск',102,3.1,'Цифровые двойники, геохимия',76],['ВНИИГАЗ (Газпром)','Москва',88,2.4,'Транспорт газа, СПГ, водород',72]];
  $('#sciCenters').innerHTML=`<thead><tr><th>Центр</th><th>Город</th><th class="num">Публикаций</th><th class="num">Цитируемость</th><th>Фокус</th><th class="num">Индекс</th></tr></thead><tbody>${centers.map(c=>`<tr><td><b>${c[0]}</b></td><td>${c[1]}</td><td class="num">${c[2]}</td><td class="num">${c[3]}</td><td class="muted">${c[4]}</td><td class="num"><span class="cell l${lvl(c[5],100)}">${c[5]}</span></td></tr>`).join('')}</tbody>`;
  const pubs=[['авг 2026','Полимер-ПАВ композиции для увеличения нефтеотдачи карбонатных коллекторов','КФУ · Нефтяное хозяйство','pub','Бурение и скважины'],['авг 2026','Способ улавливания CO₂ на установке аминовой очистки газа','патент RU · ВНИИГАЗ','pat','Энергопереход'],['июл 2026','Прогноз проницаемости баженовской свиты методами машинного обучения по данным керна','ТПУ · Георесурсы','pub','Геологоразведка'],['июл 2026','Роторная управляемая система с гидравлическим отклонителем','патент RU · Бурсервис','pat','Бурение и скважины'],['июн 2026','Катализатор гидрокрекинга на основе отечественных цеолитов','Институт катализа СО РАН · Катализ в промышленности','pub','Переработка'],['июн 2026','Спутниковый мониторинг метановых шлейфов на объектах добычи','ИКИ РАН · Исследование Земли из космоса','pub','Безопасность и экология']];
  $('#pubs').innerHTML=pubs.map(p=>`<div class="pub"><div class="y">${p[0]}</div><div><div class="t">${p[1]}</div><div class="s">${p[2]}</div><div class="m"><span class="tag ${p[3]==='pat'?'pat':'sci'}">${p[3]==='pat'?'патент':'статья'}</span><span class="tag">${p[4]}</span></div></div></div>`).join('');
  const gap=[['Водород и CCUS',2.8],['Новые материалы',2.1],['EOR (химические методы)',1.9],['Геофизика (электроразведка)',1.6],['Цифровой керн',1.5],['Мониторинг метана',1.3]];
  $('#gap').innerHTML=gap.map(g=>`<div class="hbar"><span>${g[0]}</span><div class="b"><i style="width:${g[1]/3*100}%;background:${g[1]>=1.5?'var(--sci)':'var(--line)'}"></i></div><span class="n">${g[1].toFixed(1)}×</span></div>`).join('')+'<div class="small muted" style="margin-top:8px">Значение выше 1,5× — ранний сигнал: наука опережает рынок.</div>';
}

/* ---------- INVEST (demo) ---------- */
function renderInvest(){
  const inv=[['Энергопереход и новые направления',6.4],['Бурение и скважины',4.9],['ИТ и автоматизация',4.2],['Добыча и нефтесервис',3.1],['Переработка и нефтехимия',2.7],['Геологоразведка',1.2],['Транспорт и СПГ',1.0],['Безопасность и экология',0.6]];
  $('#invBars').innerHTML=inv.map(x=>`<div class="hbar"><span>${x[0]}</span><div class="b"><i style="width:${x[1]/6.4*100}%;background:var(--inv)"></i></div><span class="n">${x[1].toFixed(1)}</span></div>`).join('')+'<div class="small muted" style="margin-top:8px">млрд ₽, раскрытые суммы сделок</div>';
  const deals=[['Раунд A: «Геоскан Нефть» — беспилотный мониторинг трубопроводов','Фонд НТИ · ИТ и автоматизация','420','млн ₽ · сен 2026'],['СП «Роснефть» и «Технопром» по производству РУС','Совместное предприятие · Бурение','2,1','млрд ₽ · авг 2026'],['Грант Сколково: катализаторы гидроочистки без импортных компонентов','Грант · Переработка','180','млн ₽ · авг 2026'],['Покупка «Газпром нефтью» доли в разработчике ПО для геомоделирования','M&A · ИТ и автоматизация','—','сумма не раскрыта · июл 2026'],['Проектное финансирование водородного кластера на Сахалине','ВЭБ.РФ · Энергопереход','3,8','млрд ₽ · июл 2026']];
  $('#deals').innerHTML=deals.map(d=>`<div class="deal"><div><div class="t">${d[0]}</div><div class="s">${d[1]}</div></div><div class="amt">${d[2]}<small>${d[3]}</small></div></div>`).join('');
  const st=[['Geosplit','Маркерная диагностика скважин без остановки добычи','Добыча и нефтесервис','emerging',[1,2,2,3,4,4,5,6]],['Цифровой керн','Томография и ИИ-петрофизика','Геологоразведка','emerging',[1,1,2,2,3,3,4,5]],['Нефтегазовые беспилотники','Дроны для мониторинга трубопроводов','ИТ и автоматизация','breakthrough',[2,3,3,4,5,6,7,9]],['H2-Сибирь','Электролизёры для промысловой генерации водорода','Энергопереход','emerging',[0,1,1,2,2,3,4,5]],['Катализ-Тех','Катализаторы гидропроцессов','Переработка и нефтехимия','breakthrough',[1,2,3,3,4,5,6,7]],['Метан-Сенс','Сенсоры утечек метана на базе лазерной спектроскопии','Безопасность и экология','emerging',[1,1,1,2,2,3,3,4]]];
  $('#startups').innerHTML=st.map(s=>`<div class="topic"><div class="stripe" style="background:var(--inv)"></div><h3>${s[0]}</h3><div class="desc">${s[1]}</div><div class="foot"><div class="tags"><span class="tag">${s[2]}</span><span class="tag"><span class="dot" style="background:${STAGE[s[3]].c}"></span>${STAGE[s[3]].l}</span></div>${spark(s[4],'var(--inv)')}</div></div>`).join('');
}

/* ---------- COMPANIES ---------- */
const COS=['Газпром нефть','Роснефть','Лукойл','Татнефть','СИБУР','НОВАТЭК','Сургутнефтегаз','Газпром'];
const CODEMO={'Газпром нефть':[14,22,31,9,12,8,11],'Роснефть':[19,27,38,7,15,6,9],'Лукойл':[8,14,21,5,17,7,4],'Татнефть':[6,18,16,2,9,4,3],'СИБУР':[1,0,2,8,29,9,5],'НОВАТЭК':[5,3,9,26,4,3,12],'Сургутнефтегаз':[4,11,14,1,2,2,1],'Газпром':[9,6,12,21,7,5,10]};
function renderCompanies(){
  const it={};P.clusters.forEach(c=>c.events.forEach(e=>{if(e.company)it[e.company]=(it[e.company]||0)+1;}));
  const cols=GROUPS.map(g=>g.name);
  const rows=COS.map(n=>[it[n]||0,...CODEMO[n]]);
  const mx=Math.max(...rows.flat());
  $('#cmx').innerHTML=`<table><thead><tr><th></th>${cols.map((c,i)=>`<th class="rot">${c}${i===0?' <span class="live-mark" style="display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--good)"></span>':''}</th>`).join('')}</tr></thead><tbody>${COS.map((n,i)=>`<tr><td class="name">${n}</td>${rows[i].map(v=>`<td class="cell l${lvl(v,mx)}">${v||'·'}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
  const sel=$('#coPick');if(!sel.options.length){sel.innerHTML=P.companies.map(c=>`<option>${esc(c.name)}</option>`).join('');sel.onchange=renderCoEvents;}
  renderCoEvents();
}
function renderCoEvents(){
  const n=$('#coPick').value;const ev=[];const th={};
  P.clusters.forEach(c=>c.events.forEach(e=>{if(e.company===n){ev.push({...e,cl:c});th[c.title]=(th[c.title]||0)+1;}}));
  ev.sort((a,b)=>(b.date||'').localeCompare(a.date||''));
  $('#coEvSub').textContent=`${n}: ${ev.length} событий в потоке «ИТ и автоматизация»`;
  $('#coEvents').innerHTML=ev.slice(0,8).map(e=>`<div class="fact-row" data-open="${e.cl.id}" style="cursor:pointer"><div class="t">${esc(e.topic)}</div><div class="s">${esc(e.summary)}</div><div class="m"><span class="tag"><span class="dot" style="background:${STAGE[e.cl.stage].c}"></span>${esc(e.cl.title.length>40?e.cl.title.slice(0,39)+'…':e.cl.title)}</span><span>${dateRu(e.date)}</span><span>${esc(e.source)}</span><a href="${esc(e.link)}" target="_blank" rel="noopener">Источник ↗</a></div></div>`).join('')||'<div class="empty">Нет событий</div>';
  const list=Object.entries(th).sort((a,b)=>b[1]-a[1]).slice(0,8);const mx=Math.max(...list.map(x=>x[1]),1);
  $('#coProfile').innerHTML=`<div class="bars">${list.map(([t,k])=>`<div class="row" style="grid-template-columns:1fr 80px 28px"><span style="font-size:12px">${esc(t)}</span><div class="b"><i style="width:${k/mx*100}%"></i></div><span class="n">${k}</span></div>`).join('')}</div>`;
}

/* ---------- DATA ---------- */
function renderData(){
  const pipe=[['Сбор','9 источников','ок'],['Статьи','410 в базе','+41'],['События','481','LLM'],['Кластеры','56 тем','UMAP+HDBSCAN'],['Подтемы','22',''],['Прогнозы','56','LLM']];
  $('#pipe').innerHTML=pipe.map(p=>`<div><div class="label">${p[0]}</div><b>${p[1]}</b><div class="muted small">${p[2]}</div></div>`).join('');
  const mth=[['1. Сбор','Скраперы и правила для каждого источника; новые сайты подключаются по URL'],['2. Извлечение','LLM выделяет события: технология + задача, сегмент, компания-оператор'],['3. Взвешивание','Упоминание умножается на вес источника (авторитетность, цитируемость, популярность)'],['4. Кластеризация','Эмбеддинги событий группируются в темы и подтемы; имена даёт LLM'],['5. Оценка','Новизна, внедрённость, стадия, наклон динамики, сигналы'],['6. Сценарий','Прогноз на 6 месяцев и рекомендуемое действие для каждой темы']];
  $('#method').innerHTML=mth.map(m=>`<div><b style="font-size:13px">${m[0]}</b><div class="muted small" style="margin-top:4px">${m[1]}</div></div>`).join('');
  $('#srcList').innerHTML=SOURCES.sort((a,b)=>b.score-a.score).map(s=>`<div class="src-row"><div><div class="n">${esc(s.n)} ${s.live?'<span class="live-mark" style="display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--good);margin-left:4px"></span>':''}</div><div class="k">${s.k}</div></div><div class="score"><div class="bar"><i style="width:${s.score}%;background:var(--${s.t==='news'?'accent':s.t})"></i></div></div><div class="score"><span class="v">${s.score}</span></div></div>`).join('');
  renderOnto();
}
function renderOnto(){
  const cl=[...P.clusters].sort((a,b)=>b.mentions-a.mentions).slice(0,14);
  const W=1200,H=960,cx=W/2,cy=H/2,R1=265,R2=345;
  const n=cl.length;let s='';const nodes=[];
  cl.forEach((c,i)=>{const a=-Math.PI/2+i/n*Math.PI*2;nodes.push({c,a,x:cx+Math.cos(a)*R1,y:cy+Math.sin(a)*R1});});
  const cut=(t,k)=>t.length>k?t.slice(0,k-1)+'…':t;
  nodes.forEach(nd=>{s+=`<path class="lk" data-c="${nd.c.id}" d="M${cx},${cy} L${nd.x.toFixed(1)},${nd.y.toFixed(1)}"/>`;
    const subs=nd.c.subclusters.slice(0,3);subs.forEach((sc,j)=>{const off=(j-(subs.length-1)/2)*.13;const a=nd.a+off;const x=cx+Math.cos(a)*R2,y=cy+Math.sin(a)*R2;const right=Math.cos(a)>=0;s+=`<path class="lk" data-c="${nd.c.id}" d="M${nd.x.toFixed(1)},${nd.y.toFixed(1)} L${x.toFixed(1)},${y.toFixed(1)}"/><g class="nd sub" data-c="${nd.c.id}"><circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${(3+Math.sqrt(sc.mentions)).toFixed(1)}" fill="${STAGE[nd.c.stage].c}" fill-opacity=".6"/><text transform="translate(${x.toFixed(1)} ${y.toFixed(1)}) rotate(${(a*180/Math.PI+(right?0:180)).toFixed(1)})" x="${right?10:-10}" y="4" text-anchor="${right?'start':'end'}">${esc(cut(sc.title,26))}</text></g>`;});
  });
  nodes.forEach(nd=>{const r=6+Math.sqrt(nd.c.mentions)*1.5;const right=Math.cos(nd.a)>=0;const deg=nd.a*180/Math.PI+(right?0:180);s+=`<g class="nd grp" data-c="${nd.c.id}" data-open="${nd.c.id}"><circle cx="${nd.x.toFixed(1)}" cy="${nd.y.toFixed(1)}" r="${r.toFixed(1)}" fill="${STAGE[nd.c.stage].c}"/><text transform="translate(${nd.x.toFixed(1)} ${nd.y.toFixed(1)}) rotate(${deg.toFixed(1)})" x="${right?-(r+6):(r+6)}" y="4" text-anchor="${right?'end':'start'}">${esc(cut(nd.c.title,21))}</text></g>`;});
  s+=`<g class="nd root"><circle cx="${cx}" cy="${cy}" r="46" fill="var(--accent)"/><text x="${cx}" y="${cy-2}" text-anchor="middle" style="fill:#fff;stroke:none">ИТ и</text><text x="${cx}" y="${cy+13}" text-anchor="middle" style="fill:#fff;stroke:none">автоматизация</text></g>`;
  $('#onto').innerHTML=`<svg viewBox="0 0 ${W} ${H}">${s}</svg><div class="legend" style="position:absolute;left:12px;bottom:8px"><span><i style="background:var(--st-break)"></i>Прорывные</span><span><i style="background:var(--st-emerg)"></i>Зарождающиеся</span><span><i style="background:var(--st-fade)"></i>Угасающие</span><span class="muted">14 крупнейших тем из 56 · размер — упоминания</span></div>`;
  const svg=$('#onto svg');
  $$('.nd[data-c]',svg).forEach(g=>{g.addEventListener('mouseenter',()=>{const id=g.dataset.c;$$('.nd[data-c]',svg).forEach(x=>x.classList.toggle('dim',x.dataset.c!==id));$$('.lk',svg).forEach(x=>x.classList.toggle('hi',x.dataset.c===id));});g.addEventListener('mouseleave',()=>{$$('.nd',svg).forEach(x=>x.classList.remove('dim'));$$('.lk',svg).forEach(x=>x.classList.remove('hi'));});});
}

/* ---------- SETTINGS ---------- */
function renderSources(){
  $('#srcMgr').innerHTML=S.sources.map((s,i)=>`<div class="src-item"><span class="d" style="background:var(--${s.t==='news'?'accent':s.t});opacity:${s.on?1:.3}"></span><div><div class="u">${esc(s.n)}</div><div class="k">${s.k} · вес ${s.score}</div></div><label class="switch"><input type="checkbox" data-i="${i}" ${s.on?'checked':''}><i></i></label><button class="rm" data-rm="${i}" aria-label="Удалить">×</button></div>`).join('');
  $('#srcCount').textContent=S.sources.filter(s=>s.on).length+' активных';
  $$('#srcMgr input').forEach(c=>c.onchange=()=>{S.sources[+c.dataset.i].on=c.checked;renderSources();renderKpis();toast(c.checked?'Источник включён':'Источник выключен');});
  $$('#srcMgr .rm').forEach(b=>b.onclick=()=>{const s=S.sources.splice(+b.dataset.rm,1)[0];renderSources();renderKpis();toast(`Источник ${s.n} удалён`);});
}
$('#srcAdd').onclick=()=>{const u=$('#srcUrl').value.trim();if(!/^https?:\/\/\S+\.\S+/.test(u)){toast('Введите адрес сайта, например https://itek.ru');return;}const d=u.replace(/^https?:\/\//,'').split('/')[0];$('#srcUrl').value='';toast(`Проверяем ${d}: ищем ленту новостей…`);setTimeout(()=>{S.sources.push({n:d,k:'добавлен вручную',t:'news',score:Math.round(40+Math.random()*30),on:true});renderSources();renderKpis();toast(`${d} подключён: найдено 5 пробных статей`);},1800);};
$('#btnRunNow').onclick=$('#btnRefresh').onclick=()=>{const p=$('#prog i');if(p._run)return;p._run=1;const stages=['Сбор источников','Извлечение событий','Взвешивание','Кластеризация','Прогнозы','Сборка витрины'];let i=0;$('#pulse').style.background='var(--amber)';const tick=()=>{if(i<stages.length){p.style.width=((i+1)/stages.length*100)+'%';$('#refreshLabel').textContent=stages[i]+'…';i++;setTimeout(tick,650);}else{p.style.width='0';p._run=0;$('#pulse').style.background='var(--good)';$('#refreshLabel').textContent='Обновлено только что';toast('Потоки обновлены: 41 новая публикация, существенных изменений нет');}};tick();};
$$('#settings [data-mode]').forEach(b=>b.onclick=()=>{$$('#settings [data-mode]').forEach(x=>x.setAttribute('aria-pressed',x===b));toast('Режим обновления: '+b.textContent);});
$('#topicChecks').innerHTML=GROUPS.flatMap(g=>g.topics).map(t=>`<label><input type="checkbox" checked>${t}</label>`).join('');

/* ---------- boot ---------- */
function renderAll(){renderKpis();renderSignals();renderMatrix();renderMap();renderNews();renderScience();renderInvest();renderCompanies();renderData();renderSources();}
renderAll();setView(S.view);
})();
