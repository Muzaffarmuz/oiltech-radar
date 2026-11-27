const $ = (id) => document.getElementById(id);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fmt = (v) => new Intl.NumberFormat('ru-RU').format(Number(v) || 0);
let DATA = null;
let currentId = null;
let currentEvents = [];
let allEventsVisible = false;
function sourceRows(events) { const counts = new Map(); events.forEach((e) => {if(e.source)counts.set(e.source,(counts.get(e.source)||0)+1);}); return [...counts].sort((a,b)=>b[1]-a[1]); }
function eventsForCluster(cluster) {
  const members = (DATA.audit?.members || []).filter((m) => m.cluster_id === cluster.id && !m.is_noise);
  if (!members.length) return cluster.events || [];
  const seen = new Set();
  return members.filter((m) => { if (seen.has(m.event_id)) return false; seen.add(m.event_id); return true; })
    .map((m) => ({id:m.event_id, topic:m.topic_label, summary:m.ai_summary, date:(m.datatime||'').slice(0,10), source:m.source, company:m.company, link:m.link}))
    .sort((a,b) => String(b.date).localeCompare(String(a.date)));
}
function renderEvidenceEvents() {
  const events = allEventsVisible ? currentEvents : currentEvents.slice(0,5);
  const list = $('evidenceEvents');
  list.classList.toggle('expanded', allEventsVisible);
  list.innerHTML = events.length ? events.map((e)=>`<a class="evidence-event" href="${esc(/^https?:\/\//.test(e.link||'')?e.link:'#')}" target="_blank" rel="noopener noreferrer"><strong>${esc(e.topic||e.summary||'Событие')}</strong><small>${esc(e.date||'')} · ${esc(e.source||'')}${e.company?' · '+esc(e.company):''}</small></a>`).join('') : '<p class="empty-message">Публикации не найдены.</p>';
  const button = $('showAllEvents');
  button.hidden = currentEvents.length <= 5;
  button.textContent = allEventsVisible ? 'Свернуть список ↑' : `Показать все ${fmt(currentEvents.length)} событий →`;
  button.setAttribute('aria-expanded', String(allEventsVisible));
}
function renderList() {
  const query = $('topicSearch').value.trim().toLocaleLowerCase('ru');
  const topics = (DATA.clusters || []).filter((c) => `${c.title} ${c.description}`.toLocaleLowerCase('ru').includes(query));
  $('ontologyListSummary').textContent = `${topics.length} из ${DATA.clusters.length} тем`;
  $('ontologyList').innerHTML = topics.length ? topics.map((c) => `<button type="button" class="topic-option${c.id===currentId?' selected':''}" data-id="${esc(c.id)}"><span>${esc(c.title)}</span><small>${fmt(c.mentions)} событий · ${(c.subclusters||[]).length} подкл.</small></button>`).join('') : '<p class="empty-message">Тема не найдена.</p>';
  $('ontologyList').querySelectorAll('button[data-id]').forEach((b) => b.addEventListener('click',()=>selectCluster(b.dataset.id)));
}
function selectCluster(id) {
  const cluster = (DATA.clusters || []).find((c) => c.id===id);
  if(!cluster)return;
  currentId=id;
  renderList();
  $('selectedTitle').textContent=cluster.title;
  $('selectedMentions').textContent=`${fmt(cluster.mentions)} событий`;
  $('clusterNode').innerHTML=`<strong>${esc(cluster.title)}</strong><span>${esc(cluster.stage_label||'')} · ${fmt(cluster.mentions)} событий</span>`;
  const subclusters=cluster.subclusters||[];
  $('subclusterNodes').innerHTML=subclusters.length ? subclusters.map((s)=>`<div class="graph-node sub-node"><strong>${esc(s.title)}</strong><span>${fmt(s.mentions)} событий</span></div>`).join('') : '<div class="graph-node sub-node muted-node"><strong>Без разделения</strong><span>Внутри темы пока нет устойчивых подгрупп</span></div>';
  $('graphExplainer').textContent=cluster.description||'Тема объединяет близкие по смыслу события из текущего корпуса.';
  const companies=cluster.companies||[];
  $('evidenceCompanies').innerHTML=companies.length?companies.slice(0,6).map((c)=>`<div class="evidence-row"><strong>${esc(c.name)}</strong><span>${fmt(c.count)}</span></div>`).join(''):'<p class="empty-message">Компании не размечены.</p>';
  currentEvents=eventsForCluster(cluster);
  allEventsVisible=false;
  const sources=sourceRows(currentEvents);
  $('evidenceSources').innerHTML=sources.length?sources.slice(0,6).map(([s,n])=>`<div class="evidence-row"><strong>${esc(s)}</strong><span>${fmt(n)}</span></div>`).join(''):'<p class="empty-message">Источники не размечены.</p>';
  renderEvidenceEvents();
}
const CLUSTER_COLORS=['#168b87','#4f7fc1','#8a68b5','#d08045','#498f5d','#c55f72','#3f8fa8','#a17b36','#6c75c7','#2f9b76','#b45c9a','#7d8f3c','#d0614e','#4581a5','#8d6a4a','#4e9a99','#a65e68','#647fbb'];
function colorWithAlpha(hex,alpha){const value=hex.replace('#','');const number=Number.parseInt(value,16);return `rgba(${number>>16},${(number>>8)&255},${number&255},${alpha})`;}
function convexHull(points){
  const sorted=[...points].sort((a,b)=>a[0]-b[0]||a[1]-b[1]);
  if(sorted.length<3)return sorted;
  const cross=(o,a,b)=>(a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0]);
  const lower=[];for(const point of sorted){while(lower.length>=2&&cross(lower.at(-2),lower.at(-1),point)<=0)lower.pop();lower.push(point);}
  const upper=[];for(const point of [...sorted].reverse()){while(upper.length>=2&&cross(upper.at(-2),upper.at(-1),point)<=0)upper.pop();upper.push(point);}
  return lower.slice(0,-1).concat(upper.slice(0,-1));
}
function renderClusterScatter(members){
  if(typeof Plotly==='undefined')return;
  const clusterById=new Map((DATA.clusters||[]).map((cluster)=>[cluster.id,cluster]));
  const grouped=new Map();
  members.forEach((member)=>{const id=member.is_noise||!member.cluster_id?'__noise__':member.cluster_id;if(!grouped.has(id))grouped.set(id,[]);grouped.get(id).push(member);});
  const ids=[...grouped.keys()].filter((id)=>id!=='__noise__').sort((a,b)=>(grouped.get(b)?.length||0)-(grouped.get(a)?.length||0));
  const hulls=[];const points=[];
  ids.forEach((id,index)=>{
    const cluster=clusterById.get(id)||{};const rows=grouped.get(id)||[];const color=CLUSTER_COLORS[index%CLUSTER_COLORS.length];
    const coordinates=rows.filter((row)=>row.umap_x!=null&&row.umap_y!=null&&row.umap_x!==''&&row.umap_y!=='').map((row)=>[Number(row.umap_x),Number(row.umap_y)]).filter(([x,y])=>Number.isFinite(x)&&Number.isFinite(y));
    const hull=convexHull(coordinates);
    if(hull.length>=3)hulls.push({x:[...hull.map((point)=>point[0]),hull[0][0]],y:[...hull.map((point)=>point[1]),hull[0][1]],mode:'lines',line:{color:colorWithAlpha(color,.62),width:1},fill:'toself',fillcolor:colorWithAlpha(color,.09),hoverinfo:'skip',showlegend:false});
    const subCount=(cluster.subclusters||[]).length;const stage=cluster.stage_label||'стадия не указана';
    points.push({x:rows.map((row)=>row.umap_x),y:rows.map((row)=>row.umap_y),mode:'markers',name:cluster.title||id,customdata:rows.map((row)=>[cluster.title||id,rows.length,subCount,stage,row.topic_label||'Событие',row.company?` · ${row.company}`:'']),marker:{color,size:8,opacity:.88,line:{color:'rgba(255,255,255,.8)',width:.8}},hovertemplate:'<b>%{customdata[0]}</b><br>%{customdata[1]} точек · %{customdata[2]} подкластеров<br>%{customdata[3]}<br><span style="color:#91a4ae">%{customdata[4]}%{customdata[5]}</span><extra></extra>',showlegend:false});
  });
  const noise=grouped.get('__noise__')||[];
  if(noise.length)points.push({x:noise.map((row)=>row.umap_x),y:noise.map((row)=>row.umap_y),mode:'markers',name:'Вне кластеров',customdata:noise.map((row)=>[row.topic_label||'Событие']),marker:{color:'#aab5bd',size:6,opacity:.55,symbol:'circle-open'},hovertemplate:'<b>Вне устойчивого кластера</b><br>%{customdata[0]}<extra></extra>',showlegend:false});
  const dark=document.documentElement.dataset.theme==='dark';
  Plotly.newPlot('scatter',[...hulls,...points],{margin:{t:15,r:15,b:38,l:42},xaxis:{title:'UMAP X',zeroline:false,gridcolor:dark?'#294252':'#edf2f3'},yaxis:{title:'UMAP Y',zeroline:false,gridcolor:dark?'#294252':'#edf2f3'},paper_bgcolor:'transparent',plot_bgcolor:'transparent',template:dark?'plotly_dark':'plotly_white',hoverlabel:{align:'left',bgcolor:dark?'#152c3b':'#ffffff',bordercolor:dark?'#406276':'#d9e5e8',font:{size:11,color:dark?'#edf7f6':'#203849'}},hovermode:'closest',dragmode:'pan',uirevision:'cluster-map-v1'},{responsive:true,displayModeBar:false});
}
function renderTechnical() {
  const members=DATA.audit?.members||[];
  renderClusterScatter(members);
  $('table').querySelector('tbody').innerHTML=members.slice(0,500).map((m)=>`<tr><td>${esc((m.datatime||'').slice(0,10))}</td><td>${esc(m.cluster_id||'—')}</td><td>${esc(m.sub_cluster_title||'—')}</td><td>${esc(m.topic_label||'')}</td><td>${esc(m.company||'')}</td><td>${m.is_noise?'Да':'—'}</td><td>${m.probability!=null?Number(m.probability).toFixed(2):'—'}</td><td>${/^https?:\/\//.test(m.link||'')?`<a href="${esc(m.link)}" target="_blank" rel="noopener noreferrer">Источник ↗</a>`:'—'}</td></tr>`).join('');
}
async function load(force) {
  if(window.OilRadarCache){
    DATA=await window.OilRadarCache.fetchJson('/api/portal',{force:!!force});
  }else{
    const response=await fetch('/api/portal'); if(!response.ok)throw new Error(`Не удалось загрузить данные: ${response.status}`);
    DATA=await response.json();
  }
  $('dataTopicCount').textContent=`${fmt(DATA.clusters?.length)} тем`;
  $('dataSubCount').textContent=`${fmt((DATA.clusters||[]).reduce((n,c)=>n+(c.subclusters||[]).length,0))} подкластеров`;
  $('dataEventCount').textContent=`${fmt(DATA.kpis?.events)} событий`;
  renderList(); if(DATA.clusters?.length)selectCluster(DATA.clusters[0].id);
  renderTechnical();
  if(window.OilRadarCache) window.OilRadarCache.prefetchAll();
}
$('topicSearch').addEventListener('input',renderList);
$('showAllEvents').addEventListener('click', () => { allEventsVisible=!allEventsVisible; renderEvidenceEvents(); });
document.querySelector('.technical-details').addEventListener('toggle',(event)=>{if(event.currentTarget.open&&typeof Plotly!=='undefined')requestAnimationFrame(()=>Plotly.Plots.resize($('scatter')));});
$('reclusterBtn').addEventListener('click',async()=>{
  const banner=$('banner');banner.hidden=false;banner.textContent='Запускаю пересчёт…';
  $('reclusterBtn').disabled=true;
  try{
    if(window.OilRadarCache) await window.OilRadarCache.clear();
    const response=await fetch('/api/refresh',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scrape:false,full_recluster:true})});
    if(!response.ok)throw new Error((await response.json()).detail||'Ошибка запуска');
    const timer=setInterval(async()=>{try{const status=await fetch('/api/status').then((r)=>r.json());if(status.pipeline?.state==='running'){banner.textContent=`Пересчёт: ${status.pipeline.stage||'обработка'}…`;return;}clearInterval(timer);$('reclusterBtn').disabled=false;if(status.pipeline?.state==='failed'){banner.textContent=status.pipeline.error||'Пересчёт завершился с ошибкой';}else{banner.textContent='Готово';if(window.OilRadarCache)await window.OilRadarCache.clear();await load(true);}}catch(e){clearInterval(timer);$('reclusterBtn').disabled=false;banner.textContent=String(e);}},1800);
  }catch(e){$('reclusterBtn').disabled=false;banner.textContent=String(e);}
});
load().catch((e)=>{$('ontologyList').innerHTML=`<p class="empty-message">${esc(e.message)}</p>`;});
