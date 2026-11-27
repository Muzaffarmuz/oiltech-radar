/* ---------- POLICY & MARKET: external conditions ---------- */
(function(){
'use strict';
const $=(s,r=document)=>r.querySelector(s), $$=(s,r=document)=>[...r.querySelectorAll(s)];
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

const TYPES={
  sanc:{l:'Санкции',ico:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="m5.6 5.6 12.8 12.8"/></svg>'},
  reg:{l:'Регулирование',ico:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v18M5 7h14M7 7l-3 7a3 3 0 0 0 6 0L7 7Zm10 0-3 7a3 3 0 0 0 6 0l-3-7Z"/></svg>'},
  inc:{l:'Инциденты',ico:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3 2 20h20L12 3Z"/><path d="M12 10v4M12 17h.01"/></svg>'},
  mkt:{l:'Рынок',ico:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/></svg>'}
};
const GRP=['ИТ и автоматизация','Геологоразведка','Бурение и скважины','Добыча и нефтесервис','Транспорт и СПГ','Переработка и нефтехимия','Безопасность и экология','Энергопереход'];

/* Real public events (sources linked). Impact mapping and "what it means" are the radar's analytic layer (mock). */
const EVENTS=[
 {d:'2026-09-21',dt:'21 сен',t:'inc',sev:3,title:'Московский НПЗ остановил переработку нефти после атаки БПЛА',s:'Крупнейший НПЗ столичного региона выведен из работы; нагрузка на поставки бензина и дизеля в ЦФО.',g:['Переработка и нефтехимия','Безопасность и экология'],src:'The Moscow Times',url:'https://ru.themoscowtimes.com/2026/09/21/moskovskii-npz-ostanovil-pererabotku-nefti-posle-ataki-bpla-a206606',why:'Спрос на быстрый ремонт установок, резервирование узлов, отечественные катализаторы и системы физической защиты объектов.'},
 {d:'2026-09-16',dt:'16 сен',t:'inc',sev:3,title:'Ещё два НПЗ «Роснефти» остановили переработку после налётов БПЛА',s:'По оценкам отраслевых аналитиков, повреждения получили 27 из 32 крупнейших НПЗ страны; первичная переработка снижена примерно на 30 %.',g:['Переработка и нефтехимия','Безопасность и экология'],src:'The Moscow Times',url:'https://ru.themoscowtimes.com/2026/09/16/esche-dva-npz-rosnefti-ostanovilis-iz-za-naletov-bpla-a206264',why:'Приоритет смещается к ремонтопригодности, модульным установкам и локальным запасам оборудования.'},
 {d:'2026-09-15',dt:'15 сен',t:'reg',sev:2,title:'Запрет экспорта дизтоплива для производителей продлевается до конца октября',s:'Причины — перенос плановых ремонтов НПЗ на осень и пополнение запасов. Запрет экспорта бензина действует до 31 января 2027 г.',g:['Переработка и нефтехимия','Транспорт и СПГ'],src:'Ведомости',url:'https://www.vedomosti.ru/business/articles/2026/09/15/1229127-pravitelstvo-prodlit-zapret',why:'Экспортная премия недоступна: экономика модернизации НПЗ смещается к внутреннему рынку и глубине переработки.'},
 {d:'2026-09-06',dt:'6 сен',t:'mkt',sev:1,title:'Семь стран ОПЕК+ сохранили квоты добычи на октябрь',s:'После двух повышений по 188 тыс. барр./сут (июнь и сентябрь) квоты зафиксированы; следующая встреча — 4 октября.',g:['Добыча и нефтесервис'],src:'Ведомости',url:'https://www.vedomosti.ru/business/news/2026/09/06/1226692-semerka-opek-sohranila',why:'Потолок добычи ограничивает спрос на новое бурение; ценность смещается к эффективности на действующем фонде.'},
 {d:'2026-08-31',dt:'31 авг',t:'mkt',sev:2,title:'Экспортная выручка за август снизилась на 8 %, импорт нефтепродуктов — рекорд',s:'Урал торговался по 69,9 $/барр. при потолке 44,1 $; теневой флот перевёз 52 % морской нефти. Россия ввезла рекордные 172 тыс. т нефтепродуктов.',g:['Переработка и нефтехимия','Транспорт и СПГ'],src:'CREA',url:'https://energyandcleanair.org/august-2026-monthly-analysis-of-russian-fossil-fuel-exports-and-sanctions/',why:'Растёт роль собственного танкерного флота, страхования и логистики, а также отечественных мощностей по производству топлива.'},
 {d:'2026-08-26',dt:'26 авг',t:'inc',sev:2,title:'НПЗ НОРСИ остановил переработку после атаки БПЛА',s:'Кстовский НПЗ «Лукойла» — один из ключевых поставщиков топлива в Поволжье и ЦФО.',g:['Переработка и нефтехимия','Безопасность и экология'],src:'The Moscow Times',url:'https://ru.themoscowtimes.com/2026/08/26/npz-norsi-ostanovil-pererabotku-nefti-26-avg-posle-ataki-bpla-istochniki-a204422',why:'Подтверждает тренд: системы защиты периметра и ускоренный ремонт — новый обязательный класс технологий для НПЗ.'},
 {d:'2026-07-30',dt:'30 июл',t:'reg',sev:2,title:'Запрет экспорта бензина продлён до конца января 2027 года',s:'Правительство удерживает топливо на внутреннем рынке на фоне ремонтов и простоев НПЗ.',g:['Переработка и нефтехимия'],src:'Ведомости',url:'https://www.vedomosti.ru/business/articles/2026/07/30/1217778-pravitelstvo-prodlilo-zapret',why:'Длинный горизонт запрета снижает стимулы к экспортно-ориентированным проектам НПЗ.'},
 {d:'2026-07-24',dt:'24 июл',t:'reg',sev:2,title:'Принят закон о демпфере для импортного дизтоплива',s:'Бюджет компенсирует разницу между ценой импорта и внутренней оптовой ценой; механизм работает только при запрете экспорта. Для поставок из Белоруссии — повышенный коэффициент.',g:['Переработка и нефтехимия','Транспорт и СПГ'],src:'ПРАЙМ',url:'https://1prime.ru/20260721/diztoplivo-871646738.html',why:'Импорт топлива становится штатной частью баланса — растёт значение логистики и инфраструктуры приёма нефтепродуктов.'},
 {d:'2026-07-24',dt:'июль',t:'sanc',sev:2,title:'OFAC продлил лицензию GL 131H по продаже Lukoil International до 22 августа',s:'Восьмое продление подряд. Сделка с Carlyle (подписана в январе) требует отдельного разрешения OFAC и не закрыта.',g:['Добыча и нефтесервис','Переработка и нефтехимия'],src:'Fesenko Law',url:'https://fesenkolaw.com/blog/ofac-gl-131h-eighth-extension-in-a-row-gives-lukoil-international-gmbh-deal-until-august-22/',why:'Потеря зарубежных активов сокращает доступ к международным технологиям и компетенциям ВИНК.'},
 {d:'2026-05-18',dt:'18 мая',t:'reg',sev:2,title:'Новые сроки перевода значимых объектов КИИ на российское ПО: 2028, 2031, 2036',s:'Вместо единого срока — три этапа в зависимости от статуса проектов. К ноябрю 2025 г. переход завершили 40–45 % субъектов КИИ.',g:['ИТ и автоматизация','Безопасность и экология'],src:'Ведомости',url:'https://www.vedomosti.ru/technologies/importsubstitution/articles/2026/05/18/1197873-perehod-znachimih-obektov-kii-na-otechestvennii-soft-otlozhili-na-vosem-let',why:'Сохраняется устойчивый спрос на отечественные АСУ ТП, SCADA, промышленное ПО и кибербезопасность до 2028 г.'},
 {d:'2026-04-23',dt:'23 апр',t:'sanc',sev:3,title:'ЕС принял 20-й пакет санкций: удар по флоту, портам и СПГ',s:'+46 судов в списке (всего 632), запрет операций в портах Мурманск и Туапсе, запрет обслуживания СПГ-танкеров и ледоколов, запрет услуг СПГ-терминалов с января 2027 г.',g:['Транспорт и СПГ','Добыча и нефтесервис','ИТ и автоматизация'],src:'Совет ЕС',url:'https://www.consilium.europa.eu/en/press/press-releases/2026/04/23/russia-s-war-of-aggression-against-ukraine-20th-round-of-stern-eu-sanctions-hits-energy-military-industrial-complex-trade-and-financial-services-including-crypto/',why:'Критичным становится отечественное оборудование для СПГ, ледокольный и танкерный флот, сервис без западных подрядчиков.'},
 {d:'2026-04-16',dt:'16 апр',t:'inc',sev:3,title:'Туапсе: остановка НПЗ и терминала, разлив нефтепродуктов',s:'Серия ударов по НПЗ «Роснефти» мощностью 12 млн т. Вывезено более 13 тыс. м³ мазута и загрязнённого грунта; пляжи и акватория загрязнены.',g:['Безопасность и экология','Переработка и нефтехимия','Транспорт и СПГ'],src:'Wikipedia (сводка источников)',url:'https://en.wikipedia.org/wiki/2026_Tuapse_environmental_disaster',why:'Растёт спрос на технологии ликвидации разливов, экомониторинг и перенаправление экспорта через другие порты.'},
 {d:'2026-02-01',dt:'1 фев',t:'sanc',sev:2,title:'Потолок цены ЕС на российскую нефть снижен до 44,10 $/барр.',s:'Динамический механизм: потолок на 15 % ниже средней цены Urals за 22 недели, пересмотр раз в полгода.',g:['Добыча и нефтесервис','Транспорт и СПГ'],src:'Европейская комиссия',url:'https://finance.ec.europa.eu/news/new-dynamic-mechanism-lower-price-cap-russian-crude-oil-4410-barrel-2026-01-15_en',why:'Давление на выручку: усиливается фокус на снижении удельных затрат на добычу и логистику.'},
 {d:'2026-01-29',dt:'29 янв',t:'sanc',sev:2,title:'«Лукойл» договорился о продаже большей части зарубежных активов Carlyle',s:'Вынужденная продажа после санкций США против компании; закрытие сделки зависит от OFAC.',g:['Добыча и нефтесервис'],src:'Лукойл',url:'https://www.lukoil.com/PressCenter/Pressreleases/Pressrelease/lukoil-agrees-with-carlyle-on-sale-of',why:'Ресурсы и технологические команды перераспределяются на внутренние проекты.'}
];
const EXPORT=[['Сырая нефть',350,-9],['Трубопроводный газ',68,25],['Нефтепродукты',78,-32],['Уголь',62,-6],['СПГ',45,18]];
const SUPPLY=[
 ['Крупнотоннажное оборудование СПГ','теплообменники, компрессоры, криогеника',88],
 ['Газовые турбины и ГПА','энергоблоки, компрессорные станции',81],
 ['Катализаторы переработки','гидрокрекинг, риформинг, изомеризация',64],
 ['Телеметрия и РУС для бурения','LWD / MWD, роторные управляемые системы',61],
 ['Промышленное ПО и САПР','АСУ ТП, геомоделирование, симуляторы',52],
 ['Ледокольный и танкерный флот','суда ледового класса, сервис',74]
];
const IMPACT={ /* type -> 8 groups: [level, reason] */
 sanc:[[2,'Санкции на ПО и оборудование держат спрос на отечественные АСУ ТП и промышленное ПО'],[1,'Ограничения на сейсмическое оборудование и ПО интерпретации'],[2,'Экспортный контроль на РУС, телеметрию, буровые насосы'],[2,'Потолок цены и продажа зарубежных активов давят на экономику добычи'],[3,'20-й пакет: флот, порты, СПГ-танкеры и терминалы'],[2,'Ограничения на поставки катализаторов и запчастей'],[0,''],[1,'Сокращение доступа к технологиям CCUS и водорода']],
 reg:[[3,'Сроки перевода значимых объектов КИИ на российское ПО: 2028 / 2031 / 2036'],[0,''],[0,''],[1,'Налоговые стимулы для ТрИЗ'],[1,'Демпфер на импорт дизтоплива меняет логистику'],[3,'Запреты экспорта бензина и дизеля, демпфер, биржевые нормативы'],[2,'Требования к ликвидации разливов и отчётности'],[1,'Регулирование углеродной отчётности']],
 inc:[[1,'Спрос на системы видеоаналитики и защиты периметра'],[0,''],[0,''],[1,'Инциденты на промыслах и узлах подготовки'],[2,'Остановка отгрузок в Туапсе, переключение на другие порты'],[3,'Остановки НПЗ: Москва, НОРСИ, Туапсе и другие'],[3,'Разливы и загрязнение: Туапсе, Пермь'],[0,'']],
 mkt:[[1,'Давление на бюджеты цифровизации'],[1,'Сокращение разведочного бурения при квотах ОПЕК+'],[2,'Квоты ОПЕК+ и падение добычи смещают фокус на эффективность фонда'],[3,'Добыча на минимуме с 2009 г., доля ТрИЗ 63 %'],[2,'Теневой флот перевозит 52 % морской нефти'],[2,'Рекордный импорт нефтепродуктов'],[0,''],[1,'Интерес к распределённой энергетике на промыслах']]
};
const TAKE=[
 {k:'ПЕРЕРАБОТКА',h:'Надёжность НПЗ стала технологическим приоритетом номер один',p:'Серия остановок крупных НПЗ и запреты экспорта топлива переводят фокус с экспортной маржи на ремонтопригодность, резервирование узлов и защиту объектов.',do:'Проверить готовность ремонтных служб и запасы критичных узлов; оценить отечественные катализаторы и модульные установки.'},
 {k:'СПГ И ЛОГИСТИКА',h:'Санкции смещают узкое место с добычи на транспорт',p:'20-й пакет ЕС бьёт по флоту, портам и обслуживанию СПГ-танкеров, а с января 2027 г. — по услугам СПГ-терминалов. Риск по оборудованию СПГ — 88 из 100.',do:'Сформировать план локализации оборудования СПГ и сервисных компетенций без западных подрядчиков.'},
 {k:'ИТ И АВТОМАТИЗАЦИЯ',h:'Импортозамещение ПО на КИИ — гарантированный спрос до 2028 года',p:'Новые сроки дают три горизонта перехода, но первый — уже 1 января 2028 г. Около половины субъектов КИИ переход ещё не завершили.',do:'Сверить дорожную карту перехода АСУ ТП и промышленного ПО со сроками 2028 / 2031.'}
];

let TYPE='',ALL=false;
function sev(n){return `<span class="sev s${n}" title="Тяжесть ${n} из 3"><i></i><i></i><i></i></span>`;}
function renderPolicy(){
  const k=[
   {l:'Urals к потолку цены',v:'69,9 <small>$/барр.</small>',d:'потолок ЕС 44,1 $ · август 2026'},
   {l:'Первичная переработка',v:'−30 <small>%</small>',d:'27 из 32 крупнейших НПЗ получили повреждения'},
   {l:'Добыча нефти, прогноз 2026',v:'494 <small>млн т</small>',d:'минимум с 2009 г. · доля ТрИЗ 63 %'},
   {l:'Экспорт топлива',v:'запрет',d:'дизель — до конца окт., бензин — до 31 янв. 2027'},
   {l:'Судов в санкционном списке ЕС',v:'632',d:'+46 в 20-м пакете'}
  ];
  $('#polKpis').innerHTML=k.map(x=>`<div class="kpi"><div class="label">${x.l}</div><div class="v">${x.v}</div><div class="d">${x.d}</div></div>`).join('');
  renderTimeline();
  const mx=Math.max(...EXPORT.map(e=>e[1]));
  $('#polExport').innerHTML=EXPORT.map(e=>`<div class="xbar"><span>${e[0]}</span><div class="b"><i style="width:${e[1]/mx*100}%"></i></div><span class="v">${e[1]}<small class="${e[2]>0?'chg-up':'chg-dn'}">${e[2]>0?'+':'−'}${Math.abs(e[2])} %</small></span></div>`).join('')+'<div class="small muted" style="margin-top:6px">Итого 604 млн € в сутки, −8 % к июлю. Источник: CREA.</div>';
  $('#polSupply').innerHTML=[...SUPPLY].sort((a,b)=>b[2]-a[2]).map(s=>`<div class="risk"><div><div class="n">${s[0]}</div><div class="k">${s[1]}</div></div><div class="b"><i style="width:${s[2]}%"></i></div><span class="v">${s[2]}</span></div>`).join('');
  const names={sanc:'Санкции',reg:'Регулирование',inc:'Инциденты',mkt:'Рынок'};
  const lab=['—','низкое','среднее','сильное'];
  $('#polImpact').innerHTML=`<thead><tr><th>Тип события</th>${GRP.map(g=>`<th>${g}</th>`).join('')}</tr></thead><tbody>${Object.keys(IMPACT).map(t=>`<tr><td class="name">${names[t]}</td>${IMPACT[t].map((c,i)=>`<td class="i${c[0]}" ${c[1]?`data-why="${esc(c[1])}" data-h="${esc(names[t]+' → '+GRP[i])}"`:''}>${lab[c[0]]}</td>`).join('')}</tr>`).join('')}</tbody>`;
  let tip=$('.imx-tip');if(!tip){tip=document.createElement('div');tip.className='imx-tip';document.body.appendChild(tip);}
  $$('#polImpact td[data-why]').forEach(td=>{td.onmousemove=e=>{tip.style.display='block';tip.innerHTML=`<b>${td.dataset.h}</b>${td.dataset.why}`;tip.style.left=Math.min(e.clientX+14,innerWidth-310)+'px';tip.style.top=(e.clientY+14)+'px';};td.onmouseleave=()=>tip.style.display='none';});
  $('#polTake').innerHTML=TAKE.map(t=>`<div class="take"><div class="k">${t.k}</div><h3>${t.h}</h3><p>${t.p}</p><div class="do"><b>Рекомендуемое действие</b>${t.do}</div></div>`).join('');
  const c=$('#cntPol');if(c)c.textContent=EVENTS.length;
}
function renderTimeline(){
  const full=EVENTS.filter(e=>!TYPE||e.t===TYPE);const list=ALL?full:full.slice(0,7);
  $('#polTimeline').innerHTML=list.map((e,i)=>`<div class="ev" data-ev="${EVENTS.indexOf(e)}"><div class="dt">${e.dt}<br>2026</div><div><div class="t">${esc(e.title)}</div><div class="s">${esc(e.s)}</div><div class="m"><span class="ttype">${TYPES[e.t].ico}${TYPES[e.t].l}</span>${sev(e.sev)}${e.g.slice(0,3).map(g=>`<span class="tag">${g}</span>`).join('')}<a class="src-link" href="${e.url}" target="_blank" rel="noopener">${esc(e.src)} ↗</a></div></div></div>`).join('')+(full.length>7?`<div class="more"><button class="btn" id="polMore">${ALL?'Свернуть':'Показать все '+full.length+' событий'}</button></div>`:'');
  const pm=$('#polMore');if(pm)pm.onclick=()=>{ALL=!ALL;renderTimeline();};
  $$('#polTimeline .ev').forEach(el=>el.addEventListener('click',ev=>{if(ev.target.closest('a'))return;openEvent(EVENTS[+el.dataset.ev]);}));
}
function openEvent(e){
  $('#dLabel').innerHTML=`<span class="tag pol" style="margin-right:6px">Политика и рынок</span><span class="tag">${TYPES[e.t].l}</span> <span class="tag">${e.dt} 2026</span>`;
  $('#dTitle').textContent=e.title;
  $('#dBody').innerHTML=`<p style="color:var(--ink-2)">${esc(e.s)}</p>
   <div class="kv"><div><div class="label">Тяжесть</div><div class="v">${e.sev} <small class="muted" style="font-size:12px">из 3</small></div></div><div><div class="label">Направлений</div><div class="v">${e.g.length}</div></div><div><div class="label">Тип</div><div class="v" style="font-size:14px;margin-top:6px">${TYPES[e.t].l}</div></div></div>
   <div class="sect"><h3>Влияние на технологии</h3><div class="action"><b>Оценка радара</b>${esc(e.why)}</div></div>
   <div class="sect"><h3>Затронутые направления</h3><div class="co-list">${e.g.map(g=>`<span class="co">${g}</span>`).join('')}</div></div>
   <div class="sect"><h3>Источник</h3><div class="fact-row"><div class="t">${esc(e.src)}</div><div class="m"><a href="${e.url}" target="_blank" rel="noopener">Открыть публикацию ↗</a></div></div></div>
   <div class="small muted">События и цифры взяты из открытых источников. Связь с направлениями и оценка влияния — аналитический слой радара (в макете проставлены вручную).</div>`;
  $('#detail').classList.add('open');$('#detail').setAttribute('aria-hidden','false');$('#overlay').classList.add('open');
}
$('#polType').addEventListener('click',e=>{const b=e.target.closest('[data-t]');if(!b)return;TYPE=b.dataset.t;$$('#polType button').forEach(x=>x.setAttribute('aria-pressed',x===b));renderTimeline();});
renderPolicy();
window.POLICY_EVENTS=EVENTS;
})();
