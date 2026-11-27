const $=(selector,root=document)=>root.querySelector(selector);
const $$=(selector,root=document)=>[...root.querySelectorAll(selector)];
const esc=(value)=>String(value??'').replace(/[&<>"']/g,(char)=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const fmt=(value)=>new Intl.NumberFormat('ru-RU').format(Number(value)||0);

const groups=[
  {name:'ИТ и автоматизация',sci:214,pat:38,inv:4.2},
  {name:'Геологоразведка',sci:302,pat:44,inv:1.2},
  {name:'Бурение и скважины',sci:268,pat:91,inv:4.9},
  {name:'Добыча и нефтесервис',sci:176,pat:73,inv:3.1},
  {name:'Транспорт и СПГ',sci:88,pat:29,inv:1.0},
  {name:'Переработка и нефтехимия',sci:194,pat:66,inv:2.7},
  {name:'Безопасность и экология',sci:142,pat:21,inv:.6},
  {name:'Энергопереход',sci:236,pat:52,inv:6.4}
];

const scienceCenters=[
  ['РГУ нефти и газа им. Губкина','Москва',214,3.8,'Бурение, разработка, нефтехимия',97],
  ['Санкт-Петербургский горный университет','Санкт-Петербург',186,3.4,'Геология, ТрИЗ, экология',91],
  ['Казанский федеральный университет','Казань',142,4.1,'EOR, катализ, битумы',88],
  ['Тюменский индустриальный университет','Тюмень',128,2.6,'Бурение, мехдобыча',79],
  ['УГНТУ','Уфа',121,2.9,'Переработка, трубопроводы',77],
  ['ИНГГ СО РАН','Новосибирск',96,4.6,'Геофизика, бассейновое моделирование',83],
  ['Томский политехнический университет','Томск',102,3.1,'Цифровые двойники, геохимия',76],
  ['ВНИИГАЗ','Москва',88,2.4,'Транспорт газа, СПГ, водород',72]
];
const scienceWorks=[
  ['авг 2026','Полимер-ПАВ композиции для увеличения нефтеотдачи карбонатных коллекторов','КФУ · Нефтяное хозяйство','статья','Бурение и скважины'],
  ['авг 2026','Способ улавливания CO₂ на установке аминовой очистки газа','Патент RU · ВНИИГАЗ','патент','Энергопереход'],
  ['июл 2026','Прогноз проницаемости баженовской свиты методами машинного обучения','ТПУ · Георесурсы','статья','Геологоразведка'],
  ['июл 2026','Роторная управляемая система с гидравлическим отклонителем','Патент RU · Бурсервис','патент','Бурение и скважины'],
  ['июн 2026','Катализатор гидрокрекинга на основе отечественных цеолитов','Институт катализа СО РАН','статья','Переработка'],
  ['июн 2026','Спутниковый мониторинг метановых шлейфов на объектах добычи','ИКИ РАН','статья','Экология']
];
const scienceGap=[['Водород и CCUS',2.8],['Новые материалы',2.1],['EOR: химические методы',1.9],['Электроразведка',1.6],['Цифровой керн',1.5],['Мониторинг метана',1.3]];

const deals=[
  ['Раунд A: беспилотный мониторинг трубопроводов','Демо-кейс · ИТ и автоматизация','420','млн ₽'],
  ['СП по производству роторных управляемых систем','Демо-кейс · Бурение','2,1','млрд ₽'],
  ['Грант на катализаторы гидроочистки','Демо-кейс · Переработка','180','млн ₽'],
  ['Покупка доли в разработчике ПО для геомоделирования','Демо-кейс · M&A','—','сумма не раскрыта'],
  ['Проектное финансирование водородного кластера','Демо-кейс · Энергопереход','3,8','млрд ₽']
];
const startups=[
  ['Geosplit','Маркерная диагностика скважин без остановки добычи','Добыча и нефтесервис','зарождающаяся'],
  ['Цифровой керн','Томография и ИИ-петрофизика','Геологоразведка','зарождающаяся'],
  ['Нефтегазовые беспилотники','Дроны для мониторинга трубопроводов','ИТ и автоматизация','прорывная'],
  ['H2-Сибирь','Электролизёры для промысловой генерации водорода','Энергопереход','зарождающаяся'],
  ['Катализ-Тех','Катализаторы гидропроцессов','Переработка','прорывная'],
  ['Метан-Сенс','Сенсоры утечек метана на базе лазерной спектроскопии','Экология','зарождающаяся']
];

const policyEvents=[
  {date:'17 сен 2026',type:'market',typeLabel:'Рынок',title:'Экспортная выручка от ископаемого топлива снизилась на 8% за август',text:'CREA оценивает выручку в €604 млн в сутки; экспортные объёмы снизились на 7%.',groups:['Транспорт и СПГ','Переработка'],source:'CREA',url:'https://energyandcleanair.org/august-2026-monthly-analysis-of-russian-fossil-fuel-exports-and-sanctions/'},
  {date:'17 сен 2026',type:'market',typeLabel:'Рынок',title:'Импорт нефтепродуктов достиг 172 тыс. тонн',text:'По оценке CREA, показатель более чем в семь раз превысил прежний месячный максимум.',groups:['Переработка','Логистика'],source:'CREA',url:'https://energyandcleanair.org/august-2026-monthly-analysis-of-russian-fossil-fuel-exports-and-sanctions/'},
  {date:'23 апр 2026',type:'sanctions',typeLabel:'Санкции',title:'ЕС принял двадцатый пакет ограничительных мер',text:'В перечень добавлены 46 судов; введены ограничения на обслуживание российских СПГ-танкеров и ледоколов, а также операции с отдельными портами.',groups:['Транспорт и СПГ','Добыча'],source:'Совет ЕС',url:'https://www.consilium.europa.eu/en/press/press-releases/2026/04/23/russia-s-war-of-aggression-against-ukraine-20th-round-of-stern-eu-sanctions-hits-energy-revenues-military-industrial-complex-trade-and-financial-services-including-crypto/'},
  {date:'1 фев 2026',type:'sanctions',typeLabel:'Санкции',title:'Ценовой потолок на российскую нефть снижен до $44,10 за баррель',text:'Динамический механизм устанавливает потолок на 15% ниже средней цены Urals за предыдущие 22 недели.',groups:['Добыча','Транспорт'],source:'Европейская комиссия',url:'https://finance.ec.europa.eu/news/new-dynamic-mechanism-lower-price-cap-russian-crude-oil-4410-barrel-2026-01-15_en'},
  {date:'29 янв 2026',type:'market',typeLabel:'Сделка',title:'ЛУКОЙЛ сообщил о соглашении с Carlyle по международным активам',text:'Сделка требует регуляторных разрешений, включая согласование OFAC; активы в Казахстане в неё не входят.',groups:['Добыча','Переработка'],source:'ЛУКОЙЛ',url:'https://www.lukoil.com/PressCenter/Pressreleases/Pressrelease/lukoil-agrees-with-carlyle-on-sale-of'}
];

const flowConfig={
  science:{number:'ПОТОК 02 · НАУКА И РАЗРАБОТКИ',title:'Наука и патенты',description:'Патенты и новости вузов: темы разработок, организации и динамика.',symbol:'◈',metrics:[['Патентов','—','в реестре'],['Кластеров','—','темы'],['Подкластеров','—','внутри крупных тем'],['Noise','—','вне устойчивых кластеров']]},
  investments:{number:'ПОТОК 03 · ИНВЕСТИЦИИ И СТАРТАПЫ',title:'Инвестиции и стартапы',description:'Капитал, гранты, сделки и новые команды как индикатор того, какие технологии получают ресурс для масштабирования.',symbol:'◇',metrics:[['Статей','—','загрузка'],['Тем','—','загрузка'],['Растут','—','загрузка'],['Стартапов','—','загрузка']]},
  policy:{number:'ПОТОК 04 · ВНЕШНИЕ УСЛОВИЯ',title:'Политика и рынок',description:'Санкции, регулирование, рыночные сдвиги и инциденты — с прямой связью с технологиями, цепочками поставок и управленческими решениями.',symbol:'⚖',metrics:[['Статей','—','загрузка'],['Тем','—','загрузка'],['Растут','—','загрузка'],['Главный источник','—','загрузка']]}
};

function bars(items,color,split=false){const max=Math.max(...items.map((item)=>split?item.sci+item.pat:item[1]),1);return `<div class="horizontal-bars">${items.map((item)=>{const label=split?item.name:item[0];const value=split?item.sci+item.pat:item[1];const fill=split?`<i style="width:${item.sci/max*100}%;background:#8177b8"></i><i style="width:${item.pat/max*100}%;background:#d49a61"></i>`:`<i style="width:${value/max*100}%;background:${color}"></i>`;return `<div class="horizontal-bar"><span>${esc(label)}</span><div class="bar-track${split?' split':''}" style="display:flex;gap:2px;background:${split?'transparent':''}">${fill}</div><b>${split?fmt(value):String(value).replace('.',',')}</b></div>`;}).join('')}</div>`;}
const TAG_LABELS={news:'новости',digital:'ИТ',policy:'политика',investments:'инвестиции'};

function sourceBars(rows,color='#8177b8'){
  const max=Math.max(...rows.map((row)=>row.count),1);
  return `<div class="horizontal-bars">${rows.map((row)=>`<div class="horizontal-bar"><span>${esc(row.source)}</span><div class="bar-track"><i style="width:${row.count/max*100}%;background:${color}"></i></div><b>${fmt(row.count)}</b></div>`).join('')}</div>`;
}

function barRow(label,count,max,folded,color='#8177b8'){
  return `<div class="horizontal-bar${folded?' fold-extra is-folded':''}"><span>${esc(label)}</span><div class="bar-track"><i style="width:${count/max*100}%;background:${color}"></i></div><b>${fmt(count)}</b></div>`;
}

function flowBrowseBarRow({label,count,max,folded,color,browseKind,browseValue}){
  return `<div class="horizontal-bar is-science-browse${folded?' fold-extra is-folded':''}" role="button" tabindex="0" data-flow-browse="${esc(browseKind)}" data-browse-value="${esc(browseValue)}" data-browse-label="${esc(label)}"><span>${esc(label)}</span><div class="bar-track"><i style="width:${count/max*100}%;background:${color}"></i></div><b>${fmt(count)}</b></div>`;
}

function flowSourceBars(rows,color='#8177b8'){
  if(!rows||!rows.length) return '<p class="source-citation">Нет источников в выборке.</p>';
  const max=Math.max(...rows.map((row)=>row.count),1);
  return `<div class="horizontal-bars">${rows.map((row)=>flowBrowseBarRow({
    label:row.source,
    count:row.count,
    max,
    folded:false,
    color,
    browseKind:'source',
    browseValue:row.source,
  })).join('')}</div>`;
}

function flowSeverityHtml(sev){
  const n=Math.max(1,Math.min(3,Number(sev)||1));
  const words={1:'слабое',2:'заметное',3:'сильное'};
  return `<span class="flow-sev" title="Сила влияния: ${words[n]} (${n} из 3, оценка модели)" aria-label="Сила ${n} из 3">${'●'.repeat(n)}${'○'.repeat(3-n)}</span>`;
}

function flowAmountText(amount){
  if(!amount) return '';
  if(amount.text) return amount.text;
  const mln=Number(amount.amount_mln)||0;
  if(!mln) return '';
  const cur=FLOW_CURRENCY[amount.currency]||'';
  return mln>=1000?`${String((mln/1000).toFixed(1)).replace('.',',')} млрд ${cur}`:`${fmt(Math.round(mln))} млн ${cur}`;
}

function flowItemChips(item,{max=3}={}){
  const chips=[];
  const kind=flowKindMeta(item);
  if(kind) chips.push(`<span class="flow-tag flow-kind-tag" style="--kind:${kind.color}">${esc(kind.label)}</span>`);
  const e=item.enrich;
  if(e?.event_type) chips.push(flowSeverityHtml(e.severity));
  if(e?.amount) chips.push(`<span class="flow-tag flow-amount-tag">${esc(flowAmountText(e.amount))}</span>`);
  if(e?.is_startup) chips.push('<span class="flow-tag">стартап</span>');
  if(e?.is_digest) chips.push('<span class="flow-tag flow-digest-tag" title="Сводка нескольких новостей за день: тип определён по первой">дайджест</span>');
  (item.tags||[]).slice(0,max).forEach((tag)=>chips.push(`<span class="flow-tag">${esc(TAG_LABELS[tag]||tag)}</span>`));
  return chips.join(' ');
}

function flowWhyText(item){
  return item.enrich?.impact||item.reason||'';
}

function taggedWorks(items,foldId){
  return items.map((item,index)=>{
    const date=item.date||'без даты';
    const folded=index>=5;
    const why=flowWhyText(item);
    return `<div class="flow-item is-flow-article${folded?' fold-extra is-folded':''}" role="button" tabindex="0" data-flow-link="${esc(item.link)}"><time>${esc(date)}</time><div><strong>${esc(item.title)}</strong><p>${esc(item.source)}${why?` · ${esc(why)}`:''}</p></div><div class="flow-item-chips">${flowItemChips(item,{max:1})}</div></div>`;
  });
}

function currentYearMonth(){
  const d=new Date();
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}`;
}

function monthRowsFrom(data,color){
  const cap=currentYearMonth();
  const months=[...data.by_month]
    .filter((row)=>String(row.month||'')<=cap)
    .sort((a,b)=>b.month.localeCompare(a.month));
  const monthMax=Math.max(...months.map((row)=>row.count),1);
  return months.map((row,index)=>barRow(row.month,row.count,monthMax,index>=5,color));
}

function flowMonthRowsFrom(data,color){
  const cap=currentYearMonth();
  const months=[...data.by_month]
    .filter((row)=>String(row.month||'')<=cap)
    .sort((a,b)=>b.month.localeCompare(a.month));
  const monthMax=Math.max(...months.map((row)=>row.count),1);
  return months.map((row,index)=>flowBrowseBarRow({
    label:row.month,
    count:row.count,
    max:monthMax,
    folded:index>=5,
    color,
    browseKind:'month',
    browseValue:row.month,
  }));
}

let FLOW_DATA=null;
let FLOW_TAG=null;
let FLOW_BROWSE_CTX=null;
const FLOW_BROWSE_LIMIT=120;
const FLOW_MIN_YEAR=2022;
/** Списки — массивы ([] = «все»); macro: show|hide (policy); cross: all|only|exclude (investments). */
const FLOW_FILTERS={cluster:[],source:[],period:[],etype:[],deal:[],direction:[],macro:'show',cross:'all'};
let FLOW_KEEP_SELECT_ID='';

function resetFlowFilters(){
  Object.assign(FLOW_FILTERS,{cluster:[],source:[],period:[],etype:[],deal:[],direction:[],macro:'show',cross:'all'});
}

const FLOW_ETYPES={
  sanctions:{label:'Санкции',color:'#c4554d'},
  regulation:{label:'Регулирование',color:'#4f7fb8'},
  incident:{label:'Инциденты',color:'#d9822b'},
  market:{label:'Рынок',color:'#3c9a7a'},
  geopolitics:{label:'Геополитика',color:'#8b62b0'},
  macro:{label:'Макро и ЦБ',color:'#8a8fa3'},
  other:{label:'Прочее',color:'#b2ab94'},
};
const FLOW_DEALS={
  ma:{label:'M&A и доли',color:'#c4554d'},
  round:{label:'Венчурные раунды',color:'#8b62b0'},
  grant:{label:'Гранты и господдержка',color:'#3c9a7a'},
  agreement:{label:'Соглашения и СП',color:'#4f7fb8'},
  ipo:{label:'IPO и размещения',color:'#d9822b'},
  capex:{label:'Капвложения в проекты',color:'#2f6f8f'},
  finance_market:{label:'Рынок капитала',color:'#8a8fa3'},
  other:{label:'Прочее',color:'#b2ab94'},
};
const FLOW_ROLES={investor:'инвестор',target:'объект',partner:'партнёр',state:'государство',other:'участник'};
const FLOW_CURRENCY={RUB:'₽',USD:'$',EUR:'€',CNY:'¥',AED:'AED',KZT:'₸',other:''};

function flowKindMeta(item){
  const e=item?.enrich;
  if(!e) return null;
  if(e.event_type) return {...(FLOW_ETYPES[e.event_type]||FLOW_ETYPES.other),key:e.event_type};
  if(e.deal_type) return {...(FLOW_DEALS[e.deal_type]||FLOW_DEALS.other),key:e.deal_type};
  return null;
}

function flowIsMacro(item){
  const e=item?.enrich;
  return e?e.event_type==='macro':item?.source==='cbr.ru';
}

function flowEnrichedCount(items){
  return (items||[]).reduce((n,item)=>n+(item.enrich?1:0),0);
}

function flowArticleYear(item){
  const raw=String(item?.date||'').replace(/\./g,'-').slice(0,4);
  const year=Number(raw);
  return Number.isFinite(year)&&year>=1000?year:null;
}

function flowItemsFrom2022(items){
  return (items||[]).filter((item)=>{
    const year=flowArticleYear(item);
    return year!=null&&year>=FLOW_MIN_YEAR;
  });
}

function filterFlowItems(items,{ignorePeriod=false}={}){
  const base=flowItemsFrom2022(items);
  const clusters=asFilterValues(FLOW_FILTERS.cluster);
  const sources=asFilterValues(FLOW_FILTERS.source);
  const etypes=asFilterValues(FLOW_FILTERS.etype);
  const deals=asFilterValues(FLOW_FILTERS.deal);
  const directions=asFilterValues(FLOW_FILTERS.direction);
  const cutoff=ignorePeriod?'':periodCutoffMulti(FLOW_FILTERS.period);
  return base.filter((item)=>{
    if(clusters.length && !clusters.includes(String(item.cluster_id||''))) return false;
    const src=item.source||'(без источника)';
    if(sources.length && !sources.includes(src)) return false;
    const e=item.enrich;
    if(etypes.length && !(e&&etypes.includes(e.event_type))) return false;
    if(deals.length && !(e&&deals.includes(e.deal_type))) return false;
    if(directions.length && !(e&&(e.directions||[]).some((d)=>directions.includes(d)))) return false;
    if(FLOW_TAG==='policy' && FLOW_FILTERS.macro==='hide' && flowIsMacro(item)) return false;
    if(FLOW_TAG==='investments' && FLOW_FILTERS.cross!=='all'){
      const cross=(item.tags||[]).includes('policy');
      if(FLOW_FILTERS.cross==='only'?!cross:cross) return false;
    }
    if(cutoff){
      const day=patentNormDate(item.date||item.date_norm);
      if(!day || day<cutoff) return false;
    }
    return true;
  });
}

function flowFiltersActive(){
  return ['cluster','source','period','etype','deal','direction'].some((k)=>asFilterValues(FLOW_FILTERS[k]).length)
    ||FLOW_FILTERS.macro!=='show'||FLOW_FILTERS.cross!=='all';
}

function flowFilterSummary(){
  const bits=[];
  const clusters=asFilterValues(FLOW_FILTERS.cluster);
  const sources=asFilterValues(FLOW_FILTERS.source);
  const periods=asFilterValues(FLOW_FILTERS.period);
  const etypes=asFilterValues(FLOW_FILTERS.etype);
  const deals=asFilterValues(FLOW_FILTERS.deal);
  const directions=asFilterValues(FLOW_FILTERS.direction);
  if(clusters.length) bits.push(clusters.length===1?'1 кластер':`${clusters.length} кластера`);
  if(sources.length) bits.push(sources.length===1?'1 источник':`${sources.length} источн.`);
  if(periods.length) bits.push(periods.map(flowPeriodLabel).join('+'));
  if(etypes.length) bits.push(etypes.map((t)=>FLOW_ETYPES[t]?.label||t).join('+'));
  if(deals.length) bits.push(deals.map((t)=>FLOW_DEALS[t]?.label||t).join('+'));
  if(directions.length) bits.push(directions.length===1?directions[0]:`${directions.length} направл.`);
  if(FLOW_TAG==='policy'&&FLOW_FILTERS.macro==='hide') bits.push('без макро');
  if(FLOW_TAG==='investments'&&FLOW_FILTERS.cross==='only') bits.push('только с Политикой');
  if(FLOW_TAG==='investments'&&FLOW_FILTERS.cross==='exclude') bits.push('без Политики');
  return bits.length?bits.join(' · '):'';
}

function flowPeriodLabel(value){
  const map={all:'всё время','12':'12 мес.','6':'6 мес.','3':'3 мес.','1':'1 мес.'};
  return map[String(value)]||String(value);
}

function flowPeriodOptions(){
  return [
    {value:'all',label:'Всё время'},{value:'12',label:'12 месяцев'},{value:'6',label:'6 месяцев'},
    {value:'3',label:'3 месяца'},{value:'1',label:'1 месяц'},
  ];
}

function flowAggregateBySource(items){
  const map=new Map();
  for(const item of items||[]){
    const source=item.source||'(без источника)';
    map.set(source,(map.get(source)||0)+1);
  }
  return [...map.entries()]
    .map(([source,count])=>({source,count}))
    .sort((a,b)=>b.count-a.count||String(a.source).localeCompare(String(b.source),'ru'));
}

function flowMonthRowsFromItems(items,color){
  const cap=currentYearMonth();
  const map=new Map();
  for(const item of items||[]){
    const month=String(item.date||'').replace(/\./g,'-').slice(0,7);
    if(!month||month.length<7||month>cap) continue;
    map.set(month,(map.get(month)||0)+1);
  }
  const months=[...map.entries()]
    .map(([month,count])=>({month,count}))
    .sort((a,b)=>b.month.localeCompare(a.month));
  if(!months.length) return ['<p class="source-citation">Нет дат в выборке.</p>'];
  const monthMax=Math.max(...months.map((row)=>row.count),1);
  return months.map((row,index)=>flowBrowseBarRow({
    label:row.month,
    count:row.count,
    max:monthMax,
    folded:index>=5,
    color,
    browseKind:'month',
    browseValue:row.month,
  }));
}

function setFlowYearFilterVisible(visible){
  const panel=$('#flowYearFilter');
  if(!panel) return;
  // Год заменён тулбаром Кластер/Источник/Период — панель всегда скрыта.
  panel.hidden=true;
  if(visible) panel.setAttribute('aria-hidden','true');
}

/** Эвристические темы для потоков investments / policy (по заголовку и reason). */
const FLOW_CLUSTER_DEFS={
  investments:[
    {id:'deals',title:'Сделки и M&A',patterns:['сделк','поглощен','слияни','m&a','покупк','продаж дол','пакет акций','актив']},
    {id:'funding',title:'Раунды и привлечение капитала',patterns:['раунд','венчур','стартап','привлек','инвестор','ipo','размещени','фонд прям','private equity']},
    {id:'capex',title:'Капвложения и проекты',patterns:['инвестиц','капвложен','капиталовложен','проектн','строительств','ввод мощност','завод','миллиард','млрд']},
    {id:'grants',title:'Гранты и господдержка',patterns:['грант','субсиди','льгот','господдерж','госпрограм','финансирован']},
    {id:'startups',title:'Новые игроки и СП',patterns:['совместн предприяти','создан','новый игрок','спин-офф','дочерн','совместн']},
    {id:'other',title:'Прочие инвестиционные сигналы',patterns:[]},
  ],
  policy:[
    {id:'sanctions',title:'Санкции и ограничения',patterns:['санкц','эмбарго','ограничен','запрет','blacklist','черн список','пакет мер']},
    {id:'regulation',title:'Регулирование и законы',patterns:['закон','указ','постановлен','распоряжен','регулир','лицензи','госдум','правительств']},
    {id:'rates',title:'Ставка ЦБ, инфляция, валюта',patterns:['ключевая ставка','ставк','инфляц','цб','банк россии','валют','курс рубл','бюджет']},
    {id:'market',title:'Рынок нефти и газа',patterns:['рынок нефти','рынок газа','urals','опек','opec','цена нефти','ценов','потолок цен','баррел']},
    {id:'trade',title:'Экспорт, импорт, пошлины',patterns:['экспорт','импорт','пошлин','квот','тариф','таможен']},
    {id:'incidents',title:'Аварии и ЧС',patterns:['авария','разлив','чс','пожар','инцидент','катастроф']},
    {id:'other',title:'Прочие внешние условия',patterns:[]},
  ],
};

function enrichFlowItemsWithClusters(items,tag){
  const defs=FLOW_CLUSTER_DEFS[tag]||[];
  const fallback=defs.find((d)=>d.id==='other')||defs[defs.length-1]||{id:'other',title:'Прочее',patterns:[]};
  return (items||[]).map((item)=>{
    const blob=`${item.title||''}\n${item.reason||''}`.toLowerCase().replace(/ё/g,'е');
    let best=fallback;
    let bestScore=0;
    for(const def of defs){
      if(def.id==='other') continue;
      let score=0;
      for(const p of def.patterns){
        if(p&&blob.includes(p)) score+=1;
      }
      if(score>bestScore){
        bestScore=score;
        best=def;
      }
    }
    return {
      ...item,
      cluster_id:best.id,
      cluster_title:best.title,
    };
  });
}

function flowClusterRows(items){
  const counts=new Map();
  const titles=new Map();
  for(const item of items||[]){
    const id=item.cluster_id||'other';
    counts.set(id,(counts.get(id)||0)+1);
    if(!titles.has(id)) titles.set(id,item.cluster_title||id);
  }
  const labClusters=FLOW_DATA?.clusters;
  if(Array.isArray(labClusters)&&labClusters.length&&FLOW_DATA?.clustered){
    return labClusters
      .map((c)=>{
        const id=c.id;
        const count=counts.get(id)||0;
        return {
          id,
          title:c.title||titles.get(id)||id,
          count,
          description:c.description||'',
          subclusters:c.subclusters||[],
        };
      })
      .filter((c)=>c.count>0)
      .sort((a,b)=>b.count-a.count||String(a.title).localeCompare(String(b.title),'ru'));
  }
  return [...counts.entries()]
    .map(([id,count])=>({id,title:titles.get(id)||id,count,description:'',subclusters:[]}))
    .sort((a,b)=>b.count-a.count||String(a.title).localeCompare(String(b.title),'ru'));
}

function flowClusterBarsFromCounts(rows,color){
  if(!rows||!rows.length) return ['<p class="source-citation">Нет кластеров в выборке.</p>'];
  const max=Math.max(...rows.map((c)=>Number(c.count)||0),1);
  return rows.map((c,index)=>flowBrowseBarRow({
    label:c.title||c.id,
    count:Number(c.count)||0,
    max,
    folded:index>=10,
    color,
    browseKind:'cluster',
    browseValue:c.id,
  }));
}

function flowArticleItemHtml(item,folded=false){
  const tags=(item.tags||[]).slice(0,2).map((tag)=>`<span class="flow-tag">${esc(TAG_LABELS[tag]||tag)}</span>`).join('');
  const cluster=item.cluster_title?`<span class="flow-tag">${esc(String(item.cluster_title).slice(0,42))}</span>`:'';
  return `<div class="flow-item is-flow-article${folded?' fold-extra is-folded':''}" role="button" tabindex="0" data-flow-link="${esc(item.link)}"><time>${esc(item.date||'без даты')}</time><div><strong>${esc(item.title||'Без названия')}</strong><p>${esc(item.source||'')}</p></div><div>${cluster}${tags}</div></div>`;
}

function flowCompactClusters(clusterRows, itemsByCluster){
  return clusterRows.map((c,index)=>{
    const members=itemsByCluster.get(c.id)||[];
    const sample=members.slice(0,6).map((item)=>flowArticleItemHtml(item,false)).join('')
      ||'<p class="source-citation">Нет новостей в кластере.</p>';
    const sources=[...new Set(members.map((m)=>m.source).filter(Boolean))].slice(0,6);
    const sourceList=sources.map((s)=>`<li>${esc(s)} — ${fmt(members.filter((m)=>m.source===s).length)}</li>`).join('')
      ||'<li class="muted">Нет источников</li>';
    const subs=(c.subclusters||[]).map((s)=>`<li><span class="flow-tag">S${esc(s.local_id??'')}</span> ${esc(String(s.title||'').slice(0,70))} — ${fmt(s.member_count)}</li>`).join('')
      ||'<li class="muted">Подкластеры не выделены</li>';
    const subN=(c.subclusters||[]).length;
    const desc=c.description?` · ${esc(String(c.description).slice(0,110))}`:'';
    const folded=index>=10?' fold-extra is-folded':'';
    return `<article class="science-cluster-card${folded}" data-flow-cluster="${esc(c.id)}"><div class="flow-card-head science-cluster-card-head"><div><h3>${esc(c.title||c.id)}</h3><p>${fmt(members.length)} новостей${subN?` · ${fmt(subN)} подкл.`:''}${sources.length?` · ${esc(sources.slice(0,2).join(', '))}`:''}${desc}</p></div><button type="button" class="science-cluster-toggle" data-expand-flow-cluster="${esc(c.id)}" aria-expanded="false">Открыть</button></div><div class="science-cluster-body" data-flow-cluster-body="${esc(c.id)}" hidden><div class="flow-grid"><div class="flow-c5"><h4>Подкластеры</h4><ul class="list">${subs}</ul><h4 style="margin-top:12px">Источники</h4><ul class="list">${sourceList}</ul><p class="source-citation" style="margin-top:8px"><button type="button" class="fold-toggle" data-flow-browse="cluster" data-browse-value="${esc(c.id)}" data-browse-label="${esc(c.title||c.id)}" style="cursor:pointer">Все новости кластера →</button></p></div><div class="flow-c7"><h4>Новости</h4><div class="item-list">${sample}</div></div></div></div></article>`;
  }).join('');
}

function flowClusterListHtml(clusterRows,items,foldId){
  const byCluster=new Map();
  for(const item of items||[]){
    const id=item.cluster_id||'other';
    if(!byCluster.has(id)) byCluster.set(id,[]);
    byCluster.get(id).push(item);
  }
  const parts=flowCompactClusters(clusterRows,byCluster);
  const more=clusterRows.length>10;
  const toggle=more?`<button type="button" class="fold-toggle" data-fold="${foldId}" aria-expanded="false">Развернуть</button>`:'';
  return `<article class="panel flow-c12 science-clusters-panel"><div class="flow-card-head science-clusters-head"><div><h3>Темы кластеров</h3></div>${toggle}</div><div id="${foldId}" class="science-cluster-stack">${parts||'<p class="source-citation">Нет кластеров в выборке.</p>'}</div></article>`;
}

function foldToggleButton(id,parts){
  const more=parts.some((part)=>part.includes('fold-extra'));
  return more?`<button type="button" class="fold-toggle" data-fold="${id}" aria-expanded="false">Развернуть</button>`:'';
}

function foldList(id,parts,listClass){
  return `<div id="${id}" class="${listClass}">${parts.join('')}</div>`;
}

function foldPanel(colClass,titleHtml,subtitleHtml,id,parts,listClass,afterHtml=''){
  const sub=subtitleHtml?`<p>${subtitleHtml}</p>`:'';
  return `<article class="panel ${colClass}"><div class="flow-card-head fold-sticky-head"><div><h3>${titleHtml}</h3>${sub}</div>${foldToggleButton(id,parts)}</div>${foldList(id,parts,listClass)}${afterHtml||''}</article>`;
}

function setFoldState(id,expanded){
  const root=document.getElementById(id);
  const button=document.querySelector(`.fold-toggle[data-fold="${id}"]`);
  if(!root||!button) return;
  root.querySelectorAll('.fold-extra').forEach((node)=>node.classList.toggle('is-folded',!expanded));
  button.setAttribute('aria-expanded',String(expanded));
  button.textContent=expanded?'Свернуть':'Развернуть';
}

function bindFoldToggles(){
  const host=$('#flowContent');
  if(!host||host.dataset.foldBound==='1') return;
  host.dataset.foldBound='1';
  host.addEventListener('click',(event)=>{
    // на странице науки клики ведёт paintScienceView (иначе double-toggle «Развернуть»)
    if(host.dataset.scienceClicks==='1') return;
    const button=event.target.closest('.fold-toggle');
    if(!button||!host.contains(button)) return;
    event.preventDefault();
    const id=button.getAttribute('data-fold');
    const expanded=button.getAttribute('aria-expanded')!=='true';
    setFoldState(id,expanded);
  });
}

function uncalculated(title,text,body){
  return `<article class="panel flow-uncalculated flow-c12"><span class="uncalculated-mark">НЕ СЧИТАЕТСЯ ПО НАШИМ СТАТЬЯМ</span><div class="flow-card-head"><div><h3>${title}</h3><p>${text}</p></div></div>${body}</article>`;
}

function directionBarsSplit(rows){
  const list=(rows||[]).filter((row)=>(Number(row.articles)||0)+(Number(row.patents)||0)>0);
  if(!list.length) return '<p class="source-citation">Пока нет размеченных направлений.</p>';
  const max=Math.max(...list.map((row)=>(Number(row.articles)||0)+(Number(row.patents)||0)),1);
  return `<div class="horizontal-bars">${list.map((row)=>{
    const articles=Number(row.articles)||0;
    const patents=Number(row.patents)||0;
    const total=articles+patents;
    return `<div class="horizontal-bar"><span>${esc(row.name)}</span><div class="bar-track split" style="display:flex;gap:2px;background:transparent"><i style="width:${articles/max*100}%;background:#8177b8"></i><i style="width:${patents/max*100}%;background:#d49a61"></i></div><b title="статьи ${articles} · патенты ${patents}">${fmt(total)}</b></div>`;
  }).join('')}</div><div class="bar-legend"><span><i style="background:#8177b8"></i>Статьи</span><span><i style="background:#d49a61"></i>Патенты</span></div>`;
}

let SCIENCE_DATA=null;
let SCIENCE_MODE='patents'; // patents | news
const SCIENCE_DATA_BY_MODE={patents:null, news:null};
/** Кластер / орг / период — массивы; [] = «все». */
const SCIENCE_FILTERS={cluster:[],org:[],period:[]};
let SCIENCE_KEEP_SELECT_ID='';
const SCIENCE_VIZ={
  trend:new Set(),
  heatOrgs:new Set(),
  heatThemes:new Set(),
  scatter:new Set(),
  seededMode:'',
};

function resetScienceVizSeeds(){
  SCIENCE_VIZ.trend.clear();
  SCIENCE_VIZ.heatOrgs.clear();
  SCIENCE_VIZ.heatThemes.clear();
  SCIENCE_VIZ.scatter.clear();
  SCIENCE_VIZ.seededMode='';
}

function scienceThemeColor(id){
  const s=String(id??'');
  let h=2166136261;
  for(let i=0;i<s.length;i++){
    h^=s.charCodeAt(i);
    h=Math.imul(h,16777619);
  }
  const hue=(h*47)%360;
  const sat=62+(h%20);
  const light=40+((h>>>9)%16);
  const a=(sat/100)*Math.min(light/100,1-light/100);
  const f=(n)=>{
    const k=(n+hue/30)%12;
    const color=light/100-a*Math.max(Math.min(k-3,9-k,1),-1);
    return Math.round(255*color);
  };
  return `#${[f(0),f(8),f(4)].map((x)=>x.toString(16).padStart(2,'0')).join('')}`;
}

function scienceHexAlpha(hex,alpha){
  const m=/^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex||'');
  if(!m) return `rgba(120,140,150,${alpha})`;
  return `rgba(${parseInt(m[1],16)},${parseInt(m[2],16)},${parseInt(m[3],16)},${alpha})`;
}

function scienceWrapLabel(text,width=16){
  const words=String(text||'').split(/\s+/).filter(Boolean);
  if(!words.length) return '—';
  const lines=[];
  let cur='';
  for(const w of words){
    if(!cur){cur=w;continue;}
    if((cur.length+1+w.length)<=width) cur=`${cur} ${w}`;
    else{lines.push(cur);cur=w;}
  }
  if(cur) lines.push(cur);
  if(lines.length>3){
    const head=lines.slice(0,2);
    const rest=lines.slice(2).join(' ');
    head.push(rest.length>width?`${rest.slice(0,width-1)}…`:rest);
    return head.join('<br>');
  }
  return lines.join('<br>');
}

function scienceSelectNorm(text){
  return String(text||'').toLowerCase().replace(/ё/g,'е');
}

function asFilterValues(value){
  if(value instanceof Set) value=[...value];
  if(Array.isArray(value)) return value.map(String).filter((v)=>v!==''&&v!=='all');
  if(value==null||value===''||value==='all') return [];
  return [String(value)];
}

function isAllFilterValue(value, allValue='all'){
  const raw=Array.isArray(value)?value:[value];
  if(!raw.length) return true;
  return raw.every((v)=>v==null||v===''||v===allValue);
}

function scienceSelectTriggerLabel(options,selectedValues,{allLabel}={}){
  const vals=asFilterValues(selectedValues);
  if(!vals.length) return allLabel||options[0]?.label||'Все';
  const labels=vals.map((v)=>{
    const hit=options.find((o)=>String(o.value)===String(v));
    return hit?hit.label:v;
  });
  if(labels.length===1) return labels[0];
  if(labels.length===2) return labels.join(', ');
  return `Выбрано: ${labels.length}`;
}

function toggleMultiFilter(current,value,{allValue=''}={}){
  const clicked=String(value??'');
  if(clicked===''||clicked===allValue) return [];
  const set=new Set(asFilterValues(current));
  if(set.has(clicked)) set.delete(clicked);
  else set.add(clicked);
  return [...set];
}

function scienceSelectHtml(id,options,currentValue,{searchable=false,searchPlaceholder='Поиск…',multiple=false,allValue='',allLabel}={}){
  const selected=new Set(asFilterValues(currentValue));
  const allActive=!selected.size;
  const label=scienceSelectTriggerLabel(options,selected,{allLabel:allLabel||options[0]?.label||'Все'});
  const items=options.map((o)=>{
    const val=String(o.value??'');
    const isAllOpt=val===''||val===allValue;
    const active=isAllOpt?allActive:selected.has(val);
    const hay=scienceSelectNorm(`${o.label} ${o.value}`);
    return `<button type="button" class="science-select-option${active?' is-active':''}" role="option" data-value="${esc(val)}" data-search="${esc(hay)}" aria-selected="${active}">${esc(o.label)}</button>`;
  }).join('');
  const search=searchable
    ? `<div class="science-select-search"><input type="search" class="science-select-search-input" placeholder="${esc(searchPlaceholder)}" autocomplete="off" spellcheck="false" aria-label="${esc(searchPlaceholder)}"></div><p class="science-select-empty" hidden>Ничего не найдено</p>`
    : '';
  const multiAttr=multiple?' data-multiple="1"':'';
  const allAttr=allValue!==''?` data-all-value="${esc(allValue)}"`:' data-all-value=""';
  return `<div class="science-select${searchable?' is-searchable':''}${multiple?' is-multiple':''}" id="${esc(id)}"${multiAttr}${allAttr}><button type="button" class="science-select-trigger" aria-haspopup="listbox" aria-expanded="false"><span class="science-select-label">${esc(label)}</span><span class="science-select-chevron" aria-hidden="true"></span></button><div class="science-select-menu" role="listbox"${multiple?' aria-multiselectable="true"':''} hidden>${search}<div class="science-select-options">${items}</div></div></div>`;
}

function openScienceSelect(wrap,{focusSearch=true}={}){
  if(!wrap) return;
  wrap.classList.add('is-open');
  const trig=wrap.querySelector('.science-select-trigger');
  if(trig) trig.setAttribute('aria-expanded','true');
  const menu=wrap.querySelector('.science-select-menu');
  if(menu) menu.hidden=false;
  const input=wrap.querySelector('.science-select-search-input');
  if(input){
    filterScienceSelect(wrap,input.value||'');
    if(focusSearch) requestAnimationFrame(()=>input.focus());
  }
}

function applySelectChoice(wrap,value){
  const multiple=wrap?.dataset.multiple==='1';
  const allValue=wrap?.dataset.allValue??'';
  const id=wrap?.id||'';
  if(id==='scienceFilterCluster'){
    SCIENCE_FILTERS.cluster=multiple?toggleMultiFilter(SCIENCE_FILTERS.cluster,value,{allValue}):(value? [value]:[]);
    return {scope:'science',multiple};
  }
  if(id==='scienceFilterOrg'){
    SCIENCE_FILTERS.org=multiple?toggleMultiFilter(SCIENCE_FILTERS.org,value,{allValue}):(value?[value]:[]);
    return {scope:'science',multiple};
  }
  if(id==='scienceFilterPeriod'){
    SCIENCE_FILTERS.period=multiple?toggleMultiFilter(SCIENCE_FILTERS.period,value,{allValue:allValue||'all'}):(value&&value!=='all'?[value]:[]);
    return {scope:'science',multiple};
  }
  if(id==='flowFilterCluster'){
    FLOW_FILTERS.cluster=multiple?toggleMultiFilter(FLOW_FILTERS.cluster,value,{allValue}):(value?[value]:[]);
    return {scope:'flow',multiple};
  }
  if(id==='flowFilterSource'){
    FLOW_FILTERS.source=multiple?toggleMultiFilter(FLOW_FILTERS.source,value,{allValue}):(value?[value]:[]);
    return {scope:'flow',multiple};
  }
  if(id==='flowFilterPeriod'){
    FLOW_FILTERS.period=multiple?toggleMultiFilter(FLOW_FILTERS.period,value,{allValue:allValue||'all'}):(value&&value!=='all'?[value]:[]);
    return {scope:'flow',multiple};
  }
  const flowKey={flowFilterEtype:'etype',flowFilterDeal:'deal',flowFilterDirection:'direction'}[id];
  if(flowKey){
    FLOW_FILTERS[flowKey]=multiple?toggleMultiFilter(FLOW_FILTERS[flowKey],value,{allValue}):(value?[value]:[]);
    return {scope:'flow',multiple};
  }
  return null;
}

function filterScienceSelect(wrap,query){
  if(!wrap) return;
  const q=scienceSelectNorm(query).trim();
  let visible=0;
  $$('.science-select-option', wrap).forEach((opt)=>{
    const hay=opt.getAttribute('data-search')||scienceSelectNorm(opt.textContent);
    const show=!q || hay.includes(q);
    opt.hidden=!show;
    if(show) visible+=1;
  });
  const empty=wrap.querySelector('.science-select-empty');
  if(empty) empty.hidden=visible>0;
}

function closeScienceSelects(root){
  $$('.science-select.is-open', root).forEach((wrap)=>{
    wrap.classList.remove('is-open');
    const trig=wrap.querySelector('.science-select-trigger');
    if(trig) trig.setAttribute('aria-expanded','false');
    const menu=wrap.querySelector('.science-select-menu');
    if(menu) menu.hidden=true;
    const input=wrap.querySelector('.science-select-search-input');
    if(input){input.value=''; filterScienceSelect(wrap,'');}
  });
}

function patentNormDate(value){
  return String(value||'').replace(/\./g,'-').slice(0,10);
}

function periodCutoff(period){
  if(!period||period==='all') return '';
  const now=new Date();
  const d=new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
  if(period==='7d') d.setUTCDate(d.getUTCDate()-7);
  else d.setUTCMonth(d.getUTCMonth()-Number(period||0));
  return d.toISOString().slice(0,10);
}

function periodCutoffMulti(periods){
  const vals=asFilterValues(periods);
  if(!vals.length) return '';
  // несколько окон → самое широкое (OR)
  let maxMonths=0;
  for(const p of vals){
    if(p==='7d') maxMonths=Math.max(maxMonths,1);
    else maxMonths=Math.max(maxMonths,Number(p)||0);
  }
  if(!maxMonths) return '';
  return periodCutoff(String(maxMonths));
}

function filterScienceIndex(index){
  const clusters=asFilterValues(SCIENCE_FILTERS.cluster);
  const orgs=asFilterValues(SCIENCE_FILTERS.org);
  const cutoff=periodCutoffMulti(SCIENCE_FILTERS.period);
  return (index||[]).filter((item)=>{
    if(clusters.length && !clusters.includes(String(item.cluster_id||''))) return false;
    if(orgs.length){
      const names=item.org_names||[];
      if(!orgs.some((o)=>names.includes(o))) return false;
    }
    if(cutoff){
      const day=patentNormDate(item.date_norm||item.date);
      if(!day || day<cutoff) return false;
    }
    return true;
  });
}

function fillPatentDrawer(item){
  const isNews=SCIENCE_MODE==='news' || item.kind==='news';
  $('#patentDrawerStage').textContent=isNews
    ?(item.identity||item.source||'Новость')
    :(item.identity||item.patent_id||'Патент');
  $('#patentDrawerTitle').textContent=item.title||'Без названия';
  const who=item.patentee?String(item.patentee).slice(0,140):'';
  $('#patentDrawerMeta').textContent=[item.date||'', who].filter(Boolean).join(' · ');
  const tags=[];
  if(item.cluster_title) tags.push(`<span class="flow-tag">${esc(item.cluster_title)}</span>`);
  if(item.sub_cluster_title) tags.push(`<span class="flow-tag">S${esc(item.sub_local_id??'')}: ${esc(item.sub_cluster_title)}</span>`);
  (item.orgs||[]).slice(0,6).forEach((org)=>tags.push(`<span class="flow-tag">${esc(org.name||org)}</span>`));
  $('#patentDrawerTags').innerHTML=tags.join('')||'<span class="muted">Без меток</span>';
  const insightWrap=$('#patentDrawerInsightWrap');
  if(insightWrap) insightWrap.hidden=true;
  const emptyAbs=isNews
    ?'Текст новости недоступен.'
    :'Реферат в реестре отсутствует — первичный анализ по названию и МПК недоступен.';
  $('#patentDrawerAbstract').textContent=item.abstract||emptyAbs;
  const link=item.link||'';
  const openLabel=isNews?'Открыть новость на сайте источника':'Открыть источник / карточку патента';
  $('#patentDrawerSource').innerHTML=link
    ?`<a href="${esc(link)}" target="_blank" rel="noopener noreferrer">${openLabel}</a><p class="source-citation" style="margin-top:8px">${esc(item.ipc?`МПК: ${item.ipc}`:'')}</p>`
    :`<span class="muted">Ссылка на источник не указана.</span>${item.ipc?`<p class="source-citation">МПК: ${esc(item.ipc)}</p>`:''}`;
}

let SCIENCE_BROWSE_CTX=null;
const SCIENCE_BROWSE_LIMIT=120;

function setPatentDrawerMode(mode){
  const browse=$('#patentDrawerBrowse');
  const detail=$('#patentDrawerDetail');
  const back=$('#patentDrawerBack');
  if(!browse||!detail) return;
  const isBrowse=mode==='browse';
  browse.hidden=!isBrowse;
  detail.hidden=isBrowse;
  if(back) back.hidden=!(mode==='detail'&&(SCIENCE_BROWSE_CTX||FLOW_BROWSE_CTX));
}

function flowArticleKey(item){
  return String(item?.link||'');
}

function fillFlowArticleDrawer(item){
  const stage=FLOW_TAG==='investments'?'Инвестиции':FLOW_TAG==='policy'?'Политика':'Статья';
  $('#patentDrawerStage').textContent=item.source||stage;
  $('#patentDrawerTitle').textContent=item.title||'Без названия';
  $('#patentDrawerMeta').textContent=[item.date||'', item.source||''].filter(Boolean).join(' · ');
  const tags=[];
  if(FLOW_TAG) tags.push(`<span class="flow-tag">${esc(TAG_LABELS[FLOW_TAG]||FLOW_TAG)}</span>`);
  if(item.cluster_title) tags.push(`<span class="flow-tag">${esc(item.cluster_title)}</span>`);
  if(item.sub_cluster_title) tags.push(`<span class="flow-tag">${esc(item.sub_cluster_title)}</span>`);
  const chips=flowItemChips(item,{max:4});
  if(chips) tags.push(chips);
  $('#patentDrawerTags').innerHTML=tags.join('')||'<span class="muted">Без меток</span>';
  const insightWrap=$('#patentDrawerInsightWrap');
  const insight=$('#patentDrawerInsight');
  if(insightWrap&&insight){
    const html=flowInsightHtml(item);
    insight.innerHTML=html;
    insightWrap.hidden=!html;
  }
  $('#patentDrawerAbstract').textContent=item.abstract
    ||item.reason
    ||'Краткой выжимки в разметке нет — откройте новость на сайте источника.';
  const link=item.link||'';
  $('#patentDrawerSource').innerHTML=link
    ?`<a href="${esc(link)}" target="_blank" rel="noopener noreferrer">Открыть новость на сайте источника</a>`
    :'<span class="muted">Ссылка на источник не указана.</span>';
}

function flowInsightHtml(item){
  const e=item.enrich;
  const rows=[];
  if(e?.impact) rows.push(['На что влияет',esc(e.impact)]);
  if(item.reason) rows.push(['Почему в потоке',esc(item.reason)]);
  if(e){
    if(e.event_type) rows.push(['Тип и сила',`${esc(FLOW_ETYPES[e.event_type]?.label||e.event_type)} · ${flowSeverityHtml(e.severity)}`]);
    if(e.deal_type) rows.push(['Тип сделки',esc(FLOW_DEALS[e.deal_type]?.label||e.deal_type)+(e.is_startup?' · стартап':'')]);
    if(e.amount) rows.push(['Сумма',esc(flowAmountText(e.amount))]);
    if((e.directions||[]).length) rows.push(['Направления',e.directions.map((d)=>`<span class="flow-tag">${esc(d)}</span>`).join(' ')]);
    else if(e.event_type==='macro') rows.push(['Направления','<span class="muted">макрофон — влияет на отрасль целиком</span>']);
    if((e.companies||[]).length) rows.push(['Компании и ведомства',e.companies.map(esc).join(', ')]);
    if((e.participants||[]).length) rows.push(['Участники',e.participants.map((p)=>`${esc(p.name)} <span class="muted">(${esc(FLOW_ROLES[p.role]||p.role)})</span>`).join(', ')]);
    if((e.countries||[]).length) rows.push(['Страны',e.countries.map(esc).join(', ')]);
    if(e.is_digest) rows.push(['Формат','<span class="muted">дайджест за день: тип и направления определены по первой новости</span>']);
  }
  if(!rows.length) return '';
  return `<dl class="flow-insight-list">${rows.map(([k,v])=>`<dt>${esc(k)}</dt><dd>${v}</dd>`).join('')}</dl>`;
}

function flowBrowseItemCard(item){
  const chips=flowItemChips(item,{max:2});
  const why=flowWhyText(item);
  return `<button type="button" class="science-browse-item" data-flow-link="${esc(item.link)}">
    <span class="date">${esc(item.date||'без даты')}</span>
    <strong>${esc(item.title||'Без названия')}</strong>
    <p>${esc(item.source||'')}${why?` · ${esc(String(why).slice(0,140))}`:''}</p>
    ${chips?`<div class="patent-drawer-tags" style="margin-top:4px">${chips}</div>`:''}
  </button>`;
}

function groupFlowBrowseItems(items,groupBy){
  const map=new Map();
  for(const item of items){
    let key='—';
    if(groupBy==='month'){
      key=(item.date||'').slice(0,7)||'без даты';
    }else{
      key=item.source||'(без источника)';
    }
    if(!map.has(key)) map.set(key,{title:key,items:[]});
    map.get(key).items.push(item);
  }
  const groups=[...map.values()].map((g)=>({
    title:g.title,
    count:g.items.length,
    items:g.items,
  }));
  groups.sort((a,b)=>{
    if(groupBy==='month') return String(b.title).localeCompare(String(a.title));
    return b.count-a.count||String(a.title).localeCompare(String(b.title));
  });
  return groups;
}

function renderFlowBrowseHtml(ctx){
  const groupBy=['month','cluster','heat','timeline'].includes(ctx.kind)?'source':'month';
  const groups=groupFlowBrowseItems(ctx.items||[],groupBy);
  if(!groups.length){
    return '<p class="science-browse-note">В выборке нет новостей.</p>';
  }
  const kindLabel={source:'Источник',month:'Месяц',cluster:'Кластер',etype:'Тип события',deal:'Тип сделки',
    direction:'Направление',company:'Компания',participant:'Участник',country:'Страна',startup:'Стартапы',
    amount:'Раскрытые суммы',matrix:'Тип × направление',timeline:'Тип × месяц',heat:'Тема × период'}[ctx.kind]||'Выборка';
  const groupWord=groupBy==='source'?'источник':'месяц';
  return `<p class="science-browse-note"><span class="pill">${esc(kindLabel)}</span> ${esc(ctx.meta||'')}. Ниже — по ${groupWord}ам.</p>
    ${groups.map((g)=>`<section class="science-browse-cluster">
      <button type="button" class="science-browse-fold-head" data-browse-fold="cluster" aria-expanded="true">
        <span class="science-browse-fold-text"><strong>${esc(g.title)}</strong><small>${fmt(g.count)} новостей</small></span>
        <span class="science-browse-fold-chevron" aria-hidden="true"></span>
      </button>
      <div class="science-browse-cluster-body">
        <div class="science-browse-items">${g.items.map(flowBrowseItemCard).join('')}</div>
      </div>
    </section>`).join('')}`;
}

function showFlowBrowsePanel(){
  if(!FLOW_BROWSE_CTX) return;
  const drawer=$('#patentDrawer');
  const browse=$('#patentDrawerBrowse');
  if(!drawer||!browse) return;
  const stage=FLOW_TAG==='investments'?'Инвестиции':FLOW_TAG==='policy'?'Политика':'Статьи';
  $('#patentDrawerStage').textContent=stage;
  $('#patentDrawerTitle').textContent=FLOW_BROWSE_CTX.label||'Выборка';
  $('#patentDrawerMeta').textContent=FLOW_BROWSE_CTX.meta||'';
  browse.innerHTML=renderFlowBrowseHtml(FLOW_BROWSE_CTX);
  setPatentDrawerMode('browse');
}

function flowNewsWord(n){
  const m10=n%10;
  const m100=n%100;
  if(m10===1&&m100!==11) return 'новость';
  if(m10>=2&&m10<=4&&(m100<12||m100>14)) return 'новости';
  return 'новостей';
}

function openFlowBrowseDrawer({kind,value,label,items}){
  const drawer=$('#patentDrawer');
  const backdrop=$('#patentBackdrop');
  if(!drawer||!backdrop) return;
  SCIENCE_BROWSE_CTX=null;
  const sorted=[...items].sort((a,b)=>String(b.date||'').localeCompare(String(a.date||'')));
  const total=sorted.length;
  const limited=sorted.slice(0,FLOW_BROWSE_LIMIT);
  FLOW_BROWSE_CTX={
    kind,value,label,
    meta:total>FLOW_BROWSE_LIMIT
      ?`показаны ${fmt(FLOW_BROWSE_LIMIT)} из ${fmt(total)} новостей`
      :`${fmt(total)} ${flowNewsWord(total)}`,
    items:limited,
    total,
  };
  backdrop.hidden=false;
  backdrop.classList.add('open');
  drawer.classList.add('open');
  drawer.setAttribute('aria-hidden','false');
  showFlowBrowsePanel();
}

function collectFlowBrowseItems(kind,value){
  const items=FLOW_DATA?.items||[];
  const v=String(value??'');
  const [a,b]=v.split('||');
  const e=(item)=>item.enrich||{};
  if(kind==='source') return items.filter((item)=>String(item.source||'')===v);
  if(kind==='cluster') return items.filter((item)=>String(item.cluster_id||'')===v);
  if(kind==='month'){
    return items.filter((item)=>{
      const m=String(item.date||'').slice(0,7);
      if(v==='без даты') return !m;
      return m===v;
    });
  }
  if(kind==='etype') return items.filter((item)=>e(item).event_type===v);
  if(kind==='deal') return items.filter((item)=>e(item).deal_type===v);
  if(kind==='direction') return items.filter((item)=>(e(item).directions||[]).includes(v));
  if(kind==='company') return items.filter((item)=>(e(item).companies||[]).includes(v));
  if(kind==='participant') return items.filter((item)=>(e(item).participants||[]).some((p)=>p.name===v));
  if(kind==='country') return items.filter((item)=>(e(item).countries||[]).includes(v));
  if(kind==='startup') return items.filter((item)=>e(item).is_startup);
  if(kind==='amount') return items.filter((item)=>e(item).amount&&(!v||e(item).amount.currency===v));
  if(kind==='matrix') return items.filter((item)=>!e(item).is_digest&&e(item).event_type===a&&(e(item).directions||[]).includes(b));
  if(kind==='timeline') return items.filter((item)=>e(item).event_type===a&&String(item.date||'').slice(0,7)===b);
  if(kind==='heat') return items.filter((item)=>String(item.cluster_id||'')===a&&flowPeriodKey(item.date,FLOW_HEAT_UNIT)===b);
  return items;
}

function openFlowBrowseFromBar(el){
  const kind=el.getAttribute('data-flow-browse');
  const value=el.getAttribute('data-browse-value');
  const label=el.getAttribute('data-browse-label')||value||'';
  if(!kind||value==null) return;
  openFlowBrowseDrawer({kind,value,label,items:collectFlowBrowseItems(kind,value)});
}

async function openFlowArticleDrawer(item,{fromBrowse=false}={}){
  const drawer=$('#patentDrawer');
  const backdrop=$('#patentBackdrop');
  if(!drawer||!backdrop||!item) return;
  if(!fromBrowse) FLOW_BROWSE_CTX=null;
  SCIENCE_BROWSE_CTX=null;
  const draft={...item, abstract:item.abstract||''};
  if(!draft.abstract) draft.abstract='Загружаю текст…';
  fillFlowArticleDrawer(draft);
  setPatentDrawerMode('detail');
  backdrop.hidden=false;
  backdrop.classList.add('open');
  drawer.classList.add('open');
  drawer.setAttribute('aria-hidden','false');
  const aid=item.article_id;
  if(aid&&FLOW_TAG&&!item.abstract){
    try{
      const response=await fetch(`/api/flows/${FLOW_TAG}/news/${encodeURIComponent(aid)}`);
      if(response.ok){
        const detail=await response.json();
        fillFlowArticleDrawer({...item,...detail});
      }else{
        fillFlowArticleDrawer({...item, abstract:item.reason||'Текст недоступен в отчёте кластеров.'});
      }
    }catch(_err){
      fillFlowArticleDrawer({...item, abstract:item.reason||'Не удалось загрузить текст.'});
    }
  }
}

function scienceBrowseItemCard(item){
  const isNews=SCIENCE_MODE==='news'||item.kind==='news';
  const who=item.patentee||(item.org_names||[])[0]||item.source||'';
  const id=item.identity||item.patent_id||'';
  return `<button type="button" class="science-browse-item" data-patent-id="${esc(item.patent_id)}">
    <span class="date">${esc(item.date||'без даты')}${who?` · ${esc(String(who).slice(0,80))}`:''}</span>
    <strong>${esc(item.title||id)}</strong>
    <p>${esc(id)}${isNews&&item.source?` · ${esc(item.source)}`:''}</p>
  </button>`;
}

function groupScienceBrowseItems(items){
  const byCluster=new Map();
  for(const item of items){
    const cid=item.cluster_id||'__none__';
    if(!byCluster.has(cid)){
      byCluster.set(cid,{
        id:cid,
        title:item.cluster_title||(cid==='__none__'?'Вне кластеров':'Без названия'),
        subs:new Map(),
      });
    }
    const group=byCluster.get(cid);
    const sid=item.sub_cluster_id||(item.sub_cluster_title?`t:${item.sub_cluster_title}`:'__none__');
    if(!group.subs.has(sid)){
      group.subs.set(sid,{
        id:sid,
        title:item.sub_cluster_title||'Без подкластера',
        local:item.sub_local_id,
        items:[],
      });
    }
    group.subs.get(sid).items.push(item);
  }
  return [...byCluster.values()]
    .map((g)=>{
      const subs=[...g.subs.values()]
        .map((s)=>({...s,items:[...s.items].sort((a,b)=>String(b.date_norm||b.date||'').localeCompare(String(a.date_norm||a.date||'')))}))
        .sort((a,b)=>b.items.length-a.items.length||String(a.title).localeCompare(String(b.title),'ru'));
      const count=subs.reduce((n,s)=>n+s.items.length,0);
      return {...g,subs,count};
    })
    .sort((a,b)=>b.count-a.count||String(a.title).localeCompare(String(b.title),'ru'));
}

function renderScienceBrowseHtml(ctx){
  const unit=SCIENCE_MODE==='news'?'новостей':'патентов';
  const shown=ctx.items.length;
  const total=ctx.total||shown;
  const note=total>shown
    ?`Показаны ${fmt(shown)} из ${fmt(total)} ${unit} · свежие сверху`
    :`${fmt(shown)} ${unit} · свежие сверху`;
  const groups=groupScienceBrowseItems(ctx.items);
  if(!groups.length){
    return `<p class="science-browse-note">В выборке нет ${unit}.</p>`;
  }
  const kindLabel=ctx.kind==='cluster'?'Кластер':ctx.kind==='org'?'Организация':ctx.kind==='month'?'Месяц':'Выборка';
  return `<p class="science-browse-note"><span class="pill">${esc(kindLabel)}</span> ${esc(note)}</p>
    ${groups.map((g)=>`<section class="science-browse-cluster">
      <button type="button" class="science-browse-fold-head" data-browse-fold="cluster" aria-expanded="true">
        <span class="science-browse-fold-text"><strong>${esc(g.title)}</strong><small>${fmt(g.count)} ${unit}</small></span>
        <span class="science-browse-fold-chevron" aria-hidden="true"></span>
      </button>
      <div class="science-browse-cluster-body">
      ${g.subs.map((s)=>`<div class="science-browse-sub">
        <button type="button" class="science-browse-fold-head science-browse-fold-sub" data-browse-fold="sub" aria-expanded="true">
          <span class="science-browse-fold-text">${s.local!=null&&s.id!=='__none__'?`<span class="pill">S${esc(s.local)}</span>`:''}<span>${esc(s.title)}</span><span class="muted">· ${fmt(s.items.length)}</span></span>
          <span class="science-browse-fold-chevron" aria-hidden="true"></span>
        </button>
        <div class="science-browse-items">${s.items.map(scienceBrowseItemCard).join('')}</div>
      </div>`).join('')}
      </div>
    </section>`).join('')}`;
}

function showScienceBrowsePanel(){
  if(!SCIENCE_BROWSE_CTX) return;
  const drawer=$('#patentDrawer');
  const browse=$('#patentDrawerBrowse');
  if(!drawer||!browse) return;
  $('#patentDrawerStage').textContent=SCIENCE_MODE==='news'?'Новости':'Патенты';
  $('#patentDrawerTitle').textContent=SCIENCE_BROWSE_CTX.label||'Выборка';
  $('#patentDrawerMeta').textContent=SCIENCE_BROWSE_CTX.meta||'';
  browse.innerHTML=renderScienceBrowseHtml(SCIENCE_BROWSE_CTX);
  setPatentDrawerMode('browse');
}

function openScienceBrowseDrawer({kind,value,label,items}){
  const drawer=$('#patentDrawer');
  const backdrop=$('#patentBackdrop');
  if(!drawer||!backdrop) return;
  const sorted=[...items].sort((a,b)=>String(b.date_norm||b.date||'').localeCompare(String(a.date_norm||a.date||'')));
  const total=sorted.length;
  const limited=sorted.slice(0,SCIENCE_BROWSE_LIMIT);
  const unit=SCIENCE_MODE==='news'?'новостей':'патентов';
  SCIENCE_BROWSE_CTX={
    kind,value,label,
    meta:`${fmt(total)} ${unit} в текущих фильтрах`,
    items:limited,
    total,
  };
  backdrop.hidden=false;
  backdrop.classList.add('open');
  drawer.classList.add('open');
  drawer.setAttribute('aria-hidden','false');
  showScienceBrowsePanel();
}

function collectScienceBrowseItems(kind,value){
  if(!SCIENCE_DATA) return [];
  const filtered=filterScienceIndex(SCIENCE_DATA.index||[]);
  if(kind==='cluster') return filtered.filter((item)=>item.cluster_id===value);
  if(kind==='org') return filtered.filter((item)=>(item.org_names||[]).includes(value));
  if(kind==='month'){
    return filtered.filter((item)=>{
      const m=(item.date_norm||patentNormDate(item.date)||'').slice(0,7);
      return m===value;
    });
  }
  return filtered;
}

function openScienceBrowseFromBar(el){
  const kind=el.getAttribute('data-science-browse');
  const value=el.getAttribute('data-browse-value');
  const label=el.getAttribute('data-browse-label')||value||'';
  if(!kind||value==null) return;
  openScienceBrowseDrawer({kind,value,label,items:collectScienceBrowseItems(kind,value)});
}

async function openPatentDrawer(item,{fromBrowse=false}={}){
  const drawer=$('#patentDrawer');
  const backdrop=$('#patentBackdrop');
  if(!drawer||!backdrop||!item) return;
  if(!fromBrowse) SCIENCE_BROWSE_CTX=null;
  FLOW_BROWSE_CTX=null;
  const isNews=SCIENCE_MODE==='news'||item.kind==='news';
  fillPatentDrawer({...item, kind:isNews?'news':undefined, abstract:item.abstract||(isNews?'Загружаю текст…':'Загружаю реферат…')});
  setPatentDrawerMode('detail');
  backdrop.hidden=false;
  backdrop.classList.add('open');
  drawer.classList.add('open');
  drawer.setAttribute('aria-hidden','false');
  try{
    const endpoint=isNews
      ?`/api/flows/science/news/${encodeURIComponent(item.article_id||item.patent_id)}`
      :`/api/flows/science/patent/${encodeURIComponent(item.patent_id)}`;
    const response=await fetch(endpoint);
    if(!response.ok) throw new Error(String(response.status));
    fillPatentDrawer({...(await response.json()), kind:isNews?'news':undefined});
  }catch(error){
    if(!item.abstract){
      $('#patentDrawerAbstract').textContent=isNews
        ?'Не удалось загрузить текст новости.'
        :'Не удалось загрузить реферат.';
    }
  }
}

function closePatentDrawer(){
  const drawer=$('#patentDrawer');
  const backdrop=$('#patentBackdrop');
  if(!drawer||!backdrop) return;
  SCIENCE_BROWSE_CTX=null;
  FLOW_BROWSE_CTX=null;
  setPatentDrawerMode('detail');
  drawer.classList.remove('open');
  backdrop.classList.remove('open');
  drawer.setAttribute('aria-hidden','true');
  backdrop.hidden=true;
}

function bindPatentDrawerOnce(){
  if(document.body.dataset.patentDrawerBound==='1') return;
  document.body.dataset.patentDrawerBound='1';
  $('#patentDrawerClose')?.addEventListener('click',closePatentDrawer);
  $('#patentDrawerBack')?.addEventListener('click',()=>{
    if(FLOW_BROWSE_CTX) showFlowBrowsePanel();
    else showScienceBrowsePanel();
  });
  $('#patentBackdrop')?.addEventListener('click',closePatentDrawer);
  $('#patentDrawer')?.addEventListener('click',(event)=>{
    const foldBtn=event.target.closest('[data-browse-fold]');
    if(foldBtn&&$('#patentDrawer')?.contains(foldBtn)){
      event.preventDefault();
      const kind=foldBtn.getAttribute('data-browse-fold');
      const expanded=foldBtn.getAttribute('aria-expanded')!=='true';
      foldBtn.setAttribute('aria-expanded',String(expanded));
      if(kind==='cluster'){
        const body=foldBtn.parentElement?.querySelector('.science-browse-cluster-body');
        if(body) body.hidden=!expanded;
      }else{
        const items=foldBtn.parentElement?.querySelector('.science-browse-items');
        if(items) items.hidden=!expanded;
      }
      return;
    }
    const flowCard=event.target.closest('.science-browse-item[data-flow-link]');
    if(flowCard&&$('#patentDrawer')?.contains(flowCard)){
      event.preventDefault();
      const link=flowCard.getAttribute('data-flow-link');
      const item=(FLOW_BROWSE_CTX?.items||FLOW_DATA?.items||[]).find((row)=>flowArticleKey(row)===String(link));
      if(item) openFlowArticleDrawer(item,{fromBrowse:!!FLOW_BROWSE_CTX});
      return;
    }
    const card=event.target.closest('.science-browse-item[data-patent-id]');
    if(!card||!$('#patentDrawer')?.contains(card)) return;
    event.preventDefault();
    const id=card.getAttribute('data-patent-id');
    const item=(SCIENCE_BROWSE_CTX?.items||SCIENCE_DATA?.index||[]).find((p)=>String(p.patent_id)===String(id));
    if(item) openPatentDrawer(item,{fromBrowse:!!SCIENCE_BROWSE_CTX});
  });
  document.addEventListener('keydown',(event)=>{
    if(event.key!=='Escape') return;
    const detail=$('#patentDrawerDetail');
    if(FLOW_BROWSE_CTX && detail && !detail.hidden){
      showFlowBrowsePanel();
      return;
    }
    if(SCIENCE_BROWSE_CTX && detail && !detail.hidden){
      showScienceBrowsePanel();
      return;
    }
    closePatentDrawer();
  });
}

function bindFlowTagBrowse(host){
  if(!host) return;
  bindPatentDrawerOnce();
  host.dataset.scienceClicks='1';
  host.onclick=(event)=>{
    const selectOpt=event.target.closest('.science-select-option');
    if(selectOpt&&host.contains(selectOpt)){
      event.preventDefault();
      const wrap=selectOpt.closest('.science-select');
      const value=selectOpt.getAttribute('data-value')??'';
      const result=applySelectChoice(wrap,value);
      if(!result) return;
      FLOW_KEEP_SELECT_ID=result.multiple?(wrap?.id||''):'';
      paintFlowTagView();
      return;
    }
    if(event.target.closest('.science-select-search')) return;
    const selectTrig=event.target.closest('.science-select-trigger');
    if(selectTrig&&host.contains(selectTrig)){
      event.preventDefault();
      const wrap=selectTrig.closest('.science-select');
      const open=!wrap.classList.contains('is-open');
      closeScienceSelects(host);
      if(open) openScienceSelect(wrap);
      return;
    }
    if(!event.target.closest('.science-select')) closeScienceSelects(host);
    const segBtn=event.target.closest('[data-flow-toggle]');
    if(segBtn&&host.contains(segBtn)){
      event.preventDefault();
      const key=segBtn.getAttribute('data-flow-toggle');
      if(key in FLOW_FILTERS) FLOW_FILTERS[key]=segBtn.getAttribute('data-value');
      paintFlowTagView();
      return;
    }
    if(event.target.closest('[data-flow-reset]')){
      event.preventDefault();
      resetFlowFilters();
      paintFlowTagView();
      return;
    }
    const foldBtn=event.target.closest('.fold-toggle');
    if(foldBtn&&host.contains(foldBtn)&&!foldBtn.hasAttribute('data-flow-browse')){
      event.preventDefault();
      const id=foldBtn.getAttribute('data-fold');
      if(!id) return;
      const expanded=foldBtn.getAttribute('aria-expanded')!=='true';
      setFoldState(id,expanded);
      return;
    }
    const browseBar=event.target.closest('[data-flow-browse]');
    if(browseBar&&host.contains(browseBar)){
      event.preventDefault();
      openFlowBrowseFromBar(browseBar);
      return;
    }
    const toggle=event.target.closest('[data-expand-flow-cluster]');
    if(toggle&&host.contains(toggle)){
      event.preventDefault();
      const id=toggle.getAttribute('data-expand-flow-cluster');
      const body=host.querySelector(`[data-flow-cluster-body="${String(id||'').replace(/"/g,'')}"]`);
      if(!body) return;
      const open=body.hasAttribute('hidden');
      body.toggleAttribute('hidden',!open);
      toggle.setAttribute('aria-expanded',String(open));
      toggle.textContent=open?'Свернуть':'Открыть';
      return;
    }
    const row=event.target.closest('[data-flow-link]');
    if(row&&host.contains(row)){
      event.preventDefault();
      const link=row.getAttribute('data-flow-link');
      const item=(FLOW_DATA?.items||[]).find((rowItem)=>flowArticleKey(rowItem)===String(link));
      if(item) openFlowArticleDrawer(item);
    }
  };
  host.onkeydown=(event)=>{
    if(event.key!=='Enter'&&event.key!==' ') return;
    const browseBar=event.target.closest('[data-flow-browse]');
    if(browseBar&&host.contains(browseBar)){
      event.preventDefault();
      openFlowBrowseFromBar(browseBar);
      return;
    }
    const row=event.target.closest('[data-flow-link]');
    if(row&&host.contains(row)){
      event.preventDefault();
      const link=row.getAttribute('data-flow-link');
      const item=(FLOW_DATA?.items||[]).find((rowItem)=>flowArticleKey(rowItem)===String(link));
      if(item) openFlowArticleDrawer(item);
    }
  };
  host.oninput=(event)=>{
    const input=event.target.closest('.science-select-search-input');
    if(!input||!host.contains(input)) return;
    filterScienceSelect(input.closest('.science-select'), input.value);
  };
}

function patentItemHtml(item,folded=false){
  const sub=item.sub_cluster_title?`<span class="flow-tag">S${esc(item.sub_local_id??'')}</span>`:'';
  const cluster=item.cluster_title?`<span class="flow-tag">${esc(String(item.cluster_title).slice(0,42))}</span>`:'';
  const who=item.patentee?esc(String(item.patentee).slice(0,70)):'';
  const id=item.identity||item.patent_id||'';
  return `<div class="flow-item is-patent${folded?' fold-extra is-folded':''}" data-patent-id="${esc(item.patent_id)}" role="button" tabindex="0"><time>${esc(item.date||'без даты')}</time><div><strong>${esc(item.title||id)}</strong><p>${esc(id)}${who?` · ${who}`:''}</p></div><div>${cluster}${sub}</div></div>`;
}

function scienceBrowseBarRow({label,count,max,folded,color,browseKind,browseValue}){
  return `<div class="horizontal-bar is-science-browse${folded?' fold-extra is-folded':''}" role="button" tabindex="0" data-science-browse="${esc(browseKind)}" data-browse-value="${esc(browseValue)}" data-browse-label="${esc(label)}"><span>${esc(label)}</span><div class="bar-track"><i style="width:${count/max*100}%;background:${color}"></i></div><b>${fmt(count)}</b></div>`;
}

function scienceClusterBarsFromCounts(rows){
  const max=Math.max(...rows.map((c)=>Number(c.count)||0),1);
  return rows.map((c,index)=>scienceBrowseBarRow({
    label:c.title||c.id,
    count:Number(c.count)||0,
    max,
    folded:index>=10,
    color:'#d49a61',
    browseKind:'cluster',
    browseValue:c.id,
  }));
}

function scienceOrgBarsFromCounts(rows){
  const max=Math.max(...rows.map((o)=>Number(o.count)||0),1);
  return rows.map((o,index)=>scienceBrowseBarRow({
    label:o.name||'—',
    count:Number(o.count)||0,
    max,
    folded:index>=10,
    color:'#8177b8',
    browseKind:'org',
    browseValue:o.name||'',
  }));
}

function scienceMonthBarsFromCounts(rows){
  const max=Math.max(...rows.map((r)=>Number(r.count)||0),1);
  return rows.map((r,index)=>scienceBrowseBarRow({
    label:r.month,
    count:Number(r.count)||0,
    max,
    folded:index>=5,
    color:'#d49a61',
    browseKind:'month',
    browseValue:r.month,
  }));
}

function scienceCompactClusters(clusters, patentsByCluster){
  return clusters.map((c,index)=>{
    const patents=(patentsByCluster.get(c.id)||[]).slice(0,6);
    const subs=(c.subclusters||[]).map((s)=>`<li><span class="flow-tag">S${esc(s.local_id)}</span> ${esc(String(s.title||'').slice(0,70))} — ${fmt(s.member_count)}</li>`).join('')
      ||'<li class="muted">Подкластеры не выделены</li>';
    const patentHtml=patents.map((p)=>patentItemHtml(p,false)).join('')||'<p class="source-citation">Нет патентов в выборке.</p>';
    const folded=index>=10?' fold-extra is-folded':'';
    return `<article class="science-cluster-card${folded}" data-cluster="${esc(c.id)}"><div class="flow-card-head science-cluster-card-head"><div><h3>${esc(c.title||c.id)}</h3><p>${fmt((patentsByCluster.get(c.id)||[]).length)} в фильтре · ${(c.subclusters||[]).length} подкл.${c.description?` · ${esc(String(c.description).slice(0,110))}`:''}</p></div><button type="button" class="science-cluster-toggle" data-expand-cluster="${esc(c.id)}" aria-expanded="false">Открыть</button></div><div class="science-cluster-body" data-cluster-body="${esc(c.id)}" hidden><div class="flow-grid"><div class="flow-c5"><h4>Подкластеры</h4><ul class="list">${subs}</ul></div><div class="flow-c7"><h4>Патенты</h4><div class="item-list">${patentHtml}</div></div></div></div></article>`;
  }).join('');
}

function sciencePlotTheme(){
  const dark=document.documentElement.dataset.theme==='dark'||document.documentElement.dataset.theme==='dusk';
  return {
    dark,
    template:dark?'plotly_dark':'plotly_white',
    paper:'transparent',
    plot:'transparent',
    font:dark?'#edf7f6':'#203849',
    muted:dark?'#9bb0be':'#8190a0',
    grid:dark?'#294252':'#edf2f3',
  };
}

function scienceOrgRanking(filtered){
  return [...filtered.reduce((map,item)=>{
    for(const name of (item.org_names||[])){
      if(!name) continue;
      map.set(name,(map.get(name)||0)+1);
    }
    return map;
  },new Map())]
    .sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0],'ru'))
    .map(([name,count])=>({name,count}));
}

/** org → clusterId → count */
function scienceHeatPairCounts(filtered){
  const pairs=new Map();
  for(const item of filtered){
    const cid=item.cluster_id;
    if(!cid) continue;
    for(const name of (item.org_names||[])){
      if(!name) continue;
      let byTheme=pairs.get(name);
      if(!byTheme){byTheme=new Map();pairs.set(name,byTheme);}
      byTheme.set(cid,(byTheme.get(cid)||0)+1);
    }
  }
  return pairs;
}

/** Топ орг. и тем с максимальным пересечением (меньше пустых ячеек). */
function scienceHeatDenseDefaults(filtered, clusterRows, n=6){
  const pairs=scienceHeatPairCounts(filtered);
  const clusterIds=clusterRows.map((c)=>c.id);
  let themeIds=clusterIds.slice(0,Math.min(n*3,clusterIds.length));
  let orgNames=[];
  for(let iter=0;iter<3;iter++){
    const themeSet=new Set(themeIds);
    const orgScore=new Map();
    for(const [org,byTheme] of pairs){
      let s=0;
      for(const tid of themeSet) s+=byTheme.get(tid)||0;
      if(s>0) orgScore.set(org,s);
    }
    orgNames=[...orgScore.entries()]
      .sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0],'ru'))
      .slice(0,n)
      .map(([name])=>name);
    const orgSet=new Set(orgNames);
    const themeScore=new Map();
    for(const [org,byTheme] of pairs){
      if(!orgSet.has(org)) continue;
      for(const [tid,cnt] of byTheme){
        if(!clusterIds.includes(tid)) continue;
        themeScore.set(tid,(themeScore.get(tid)||0)+cnt);
      }
    }
    themeIds=[...themeScore.entries()]
      .sort((a,b)=>b[1]-a[1])
      .slice(0,n)
      .map(([id])=>id);
    if(!themeIds.length) themeIds=clusterIds.slice(0,n);
  }
  if(!orgNames.length){
    orgNames=scienceOrgRanking(filtered).slice(0,n).map((o)=>o.name);
  }
  if(!themeIds.length) themeIds=clusterIds.slice(0,n);
  return {orgNames,themeIds};
}

function scienceHeatOrgRankingForThemes(filtered, themeIds){
  const want=themeIds instanceof Set?themeIds:new Set(themeIds||[]);
  const map=new Map();
  for(const item of filtered){
    if(want.size && !want.has(item.cluster_id)) continue;
    for(const name of (item.org_names||[])){
      if(!name) continue;
      map.set(name,(map.get(name)||0)+1);
    }
  }
  return [...map.entries()]
    .sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0],'ru'))
    .map(([name,count])=>({name,count}));
}

function scienceMonthRange(startYm,endYm){
  if(!startYm||!endYm||startYm>endYm) return [];
  const out=[];
  let[y,m]=startYm.split('-').map(Number);
  const[ey,em]=endYm.split('-').map(Number);
  while(y<ey || (y===ey && m<=em)){
    out.push(`${y}-${String(m).padStart(2,'0')}`);
    m+=1;
    if(m>12){m=1;y+=1;}
    if(out.length>120) break;
  }
  return out;
}

function scienceMonthKeys(filtered){
  const cap=currentYearMonth();
  const cutoff=periodCutoffMulti(SCIENCE_FILTERS.period);
  if(cutoff){
    const start=cutoff.slice(0,7);
    return scienceMonthRange(start,cap);
  }
  const monthSet=new Set();
  for(const item of filtered){
    const m=(item.date_norm||patentNormDate(item.date)||'').slice(0,7);
    if(m.length===7 && m<=cap) monthSet.add(m);
  }
  return [...monthSet].sort().slice(-12);
}

function scienceClusterSeries(filtered, clusterId, months){
  const counts=Object.fromEntries(months.map((m)=>[m,0]));
  for(const item of filtered){
    if(item.cluster_id!==clusterId) continue;
    const m=(item.date_norm||patentNormDate(item.date)||'').slice(0,7);
    if(m in counts) counts[m]+=1;
  }
  let run=0;
  return months.map((m)=>{run+=counts[m];return run;});
}

function scienceScatterPoints(filtered, clusterRows, sciNames){
  return clusterRows.map((c)=>{
    let academic=0;
    let industry=0;
    for(const item of filtered){
      if(item.cluster_id!==c.id) continue;
      const names=item.org_names||[];
      const hasSci=names.some((n)=>sciNames.has(n));
      const hasOther=names.some((n)=>n && !sciNames.has(n));
      if(hasSci) academic+=1;
      if(hasOther || (!hasSci && names.length)) industry+=1;
      if(!names.length) industry+=1;
    }
    const denom=academic+industry || 1;
    return {
      id:c.id,
      title:c.title||c.id,
      size:c.count,
      academicShare:academic/denom,
      academic,
      industry,
    };
  });
}

function seedScienceVizSelections(filtered, clusterRows, orgRows){
  const seedKey=`${SCIENCE_MODE}:heat-dense-v1`;
  if(SCIENCE_VIZ.seededMode!==seedKey){
    SCIENCE_VIZ.trend.clear();
    SCIENCE_VIZ.heatOrgs.clear();
    SCIENCE_VIZ.heatThemes.clear();
    SCIENCE_VIZ.scatter.clear();
    SCIENCE_VIZ.seededMode=seedKey;
    clusterRows.slice(0,6).forEach((c)=>SCIENCE_VIZ.trend.add(c.id));
    const dense=scienceHeatDenseDefaults(filtered, clusterRows, 6);
    dense.orgNames.forEach((name)=>SCIENCE_VIZ.heatOrgs.add(name));
    dense.themeIds.forEach((id)=>SCIENCE_VIZ.heatThemes.add(id));
    clusterRows.slice(0,10).forEach((c)=>SCIENCE_VIZ.scatter.add(c.id));
    return;
  }
  const clusterIds=new Set(clusterRows.map((c)=>c.id));
  const orgNames=new Set(orgRows.map((o)=>o.name));
  for(const id of [...SCIENCE_VIZ.trend]) if(!clusterIds.has(id)) SCIENCE_VIZ.trend.delete(id);
  for(const id of [...SCIENCE_VIZ.heatThemes]) if(!clusterIds.has(id)) SCIENCE_VIZ.heatThemes.delete(id);
  for(const id of [...SCIENCE_VIZ.scatter]) if(!clusterIds.has(id)) SCIENCE_VIZ.scatter.delete(id);
  for(const name of [...SCIENCE_VIZ.heatOrgs]) if(!orgNames.has(name)) SCIENCE_VIZ.heatOrgs.delete(name);
}

function sciencePickHtml(items,{selectedSet,valueKey='id',labelKey='title',countKey='count',empty='Нет пунктов',kind=''}={}){
  if(!items.length) return `<p class="source-citation">${esc(empty)}</p>`;
  return `<ul class="science-viz-pick-list">${items.map((item)=>{
    const value=item[valueKey];
    const on=selectedSet.has(value);
    return `<li><button type="button" class="science-viz-pick-item${on?' is-selected':''}" data-pick-value="${esc(value)}" data-pick-kind="${esc(kind)}" aria-pressed="${on}"><span>${esc(item[labelKey]||value)}</span><span class="science-viz-pick-count">${fmt(item[countKey]||0)}</span></button></li>`;
  }).join('')}</ul>`;
}

function scienceVizPanelHtml({title,chartId,chartClass,pickId,pickTitle,hideActions=false}){
  const actions=hideActions?'':`<div class="science-viz-pick-actions">
          <button type="button" class="science-viz-pick-btn" data-viz-act="all" data-viz-target="${esc(pickId)}">Выбрать все</button>
          <button type="button" class="science-viz-pick-btn" data-viz-act="clear" data-viz-target="${esc(pickId)}">Сбросить</button>
        </div>`;
  return `<article class="panel flow-c12 science-viz-panel">
    <div class="science-viz-layout">
      <div class="science-viz-main">
        <div class="flow-card-head"><div><h3>${esc(title)}</h3></div></div>
        <div id="${esc(chartId)}" class="science-plotly ${esc(chartClass||'')}"></div>
      </div>
      <aside class="science-viz-pick" aria-label="${esc(pickTitle||'Фильтр')}">
        <div class="science-viz-pick-head"><h4>${esc(pickTitle||'Фильтр')}</h4></div>
        ${actions}
        <div id="${esc(pickId)}" class="science-viz-pick-body"></div>
      </aside>
    </div>
  </article>`;
}

function paintScienceTrendChart(filtered, clusterRows, unitLabel){
  const el=$('#scienceVizTrends');
  const pick=$('#scienceVizTrendPick');
  if(!el||typeof Plotly==='undefined') return;
  if(pick) pick.innerHTML=sciencePickHtml(clusterRows,{selectedSet:SCIENCE_VIZ.trend,empty:'Нет тем',kind:'trend'});
  const theme=sciencePlotTheme();
  const months=scienceMonthKeys(filtered);
  const selected=clusterRows.filter((c)=>SCIENCE_VIZ.trend.has(c.id));
  Plotly.purge(el);
  if(!selected.length || !months.length){
    Plotly.newPlot(el,[],{
      margin:{t:10,r:16,b:40,l:48},
      paper_bgcolor:theme.paper,plot_bgcolor:theme.plot,template:theme.template,
      xaxis:{visible:false},yaxis:{visible:false},
      annotations:[{text:selected.length?'Нет дат для динамики':'Выберите темы в фильтре',showarrow:false,xref:'paper',yref:'paper',x:0.5,y:0.5,font:{size:13,color:theme.muted}}],
    },{responsive:true,displayModeBar:false});
    return;
  }
  const traces=selected.map((c)=>{
    const color=scienceThemeColor(c.id);
    return {
      type:'scatter',mode:'lines+markers',
      name:String(c.title||c.id),
      x:months,
      y:scienceClusterSeries(filtered,c.id,months),
      customdata:months.map(()=>c.id),
      line:{color,width:2.6},
      marker:{size:6,color},
      showlegend:false,
      hovertemplate:`%{fullData.name}<br>%{x}: %{y}<extra></extra>`,
    };
  }).sort((a,b)=>(b.y[b.y.length-1]||0)-(a.y[a.y.length-1]||0));
  Plotly.newPlot(el,traces,{
    margin:{t:12,r:16,b:56,l:52},
    paper_bgcolor:theme.paper,plot_bgcolor:theme.plot,template:theme.template,
    font:{size:11,color:theme.font},
    hovermode:'closest',
    showlegend:false,
    xaxis:{title:{text:'Месяц',standoff:12},tickangle:-30,gridcolor:theme.grid,automargin:true},
    yaxis:{title:{text:`Накоплено (${unitLabel})`,standoff:8},rangemode:'tozero',gridcolor:theme.grid,automargin:true},
  },{responsive:true,displayModeBar:false});
}

function paintScienceHeatmap(filtered, clusterRows, orgRows){
  const el=$('#scienceVizHeatmap');
  const pick=$('#scienceVizHeatPick');
  if(!el||typeof Plotly==='undefined') return;
  const themeIdsSelected=SCIENCE_VIZ.heatThemes.size
    ?SCIENCE_VIZ.heatThemes
    :new Set(clusterRows.slice(0,6).map((c)=>c.id));
  const orgPickRows=(()=>{
    const ranked=scienceHeatOrgRankingForThemes(filtered, themeIdsSelected);
    if(!ranked.length) return orgRows;
    const seen=new Set(ranked.map((o)=>o.name));
    return ranked.concat(orgRows.filter((o)=>!seen.has(o.name)));
  })();
  if(pick){
    pick.innerHTML=`<div class="science-viz-pick-block"><div class="science-viz-pick-subrow"><span class="science-viz-pick-sub">Организации</span><span class="science-viz-pick-mini"><button type="button" class="science-viz-pick-btn" data-viz-act="orgs-all" data-viz-target="scienceVizHeatPick">Все</button><button type="button" class="science-viz-pick-btn" data-viz-act="orgs-clear" data-viz-target="scienceVizHeatPick">Сброс</button></span></div>${sciencePickHtml(orgPickRows,{selectedSet:SCIENCE_VIZ.heatOrgs,valueKey:'name',labelKey:'name',empty:'Нет организаций',kind:'heat-org'})}</div>
      <div class="science-viz-pick-block"><div class="science-viz-pick-subrow"><span class="science-viz-pick-sub">Темы</span><span class="science-viz-pick-mini"><button type="button" class="science-viz-pick-btn" data-viz-act="themes-all" data-viz-target="scienceVizHeatPick">Выбрать все</button><button type="button" class="science-viz-pick-btn" data-viz-act="themes-clear" data-viz-target="scienceVizHeatPick">Сбросить</button></span></div>${sciencePickHtml(clusterRows,{selectedSet:SCIENCE_VIZ.heatThemes,empty:'Нет тем',kind:'heat-theme'})}</div>`;
  }
  const theme=sciencePlotTheme();
  let orgs=orgRows.filter((o)=>SCIENCE_VIZ.heatOrgs.has(o.name));
  let themes=clusterRows.filter((c)=>SCIENCE_VIZ.heatThemes.has(c.id));
  Plotly.purge(el);
  if(!orgs.length || !themes.length){
    Plotly.newPlot(el,[],{
      margin:{t:10,r:16,b:40,l:48},
      paper_bgcolor:theme.paper,plot_bgcolor:theme.plot,template:theme.template,
      xaxis:{visible:false},yaxis:{visible:false},
      annotations:[{text:'Выберите организации и темы',showarrow:false,xref:'paper',yref:'paper',x:0.5,y:0.5,font:{size:13,color:theme.muted}}],
    },{responsive:true,displayModeBar:false});
    return;
  }
  const pairs=scienceHeatPairCounts(filtered);
  let z=orgs.map((org)=>{
    const byTheme=pairs.get(org.name);
    return themes.map((c)=>(byTheme?byTheme.get(c.id)||0:0));
  });
  // убираем полностью пустые строки и столбцы, чтобы матрица не выглядела «дырявой»
  const keepRows=z.map((row,i)=>row.some((v)=>v>0)?i:-1).filter((i)=>i>=0);
  const keepCols=themes.map((_,j)=>z.some((row)=>row[j]>0)?j:-1).filter((j)=>j>=0);
  if(keepRows.length && keepCols.length){
    orgs=keepRows.map((i)=>orgs[i]);
    themes=keepCols.map((j)=>themes[j]);
    z=keepRows.map((i)=>keepCols.map((j)=>z[i][j]));
  }
  // плотнее сверху: сортировка по сумме пересечений
  const rowSum=z.map((row)=>row.reduce((a,b)=>a+b,0));
  const colSum=themes.map((_,j)=>z.reduce((a,row)=>a+row[j],0));
  const rowOrder=rowSum.map((s,i)=>[s,i]).sort((a,b)=>b[0]-a[0]||a[1]-b[1]).map((x)=>x[1]);
  const colOrder=colSum.map((s,j)=>[s,j]).sort((a,b)=>b[0]-a[0]||a[1]-b[1]).map((x)=>x[1]);
  orgs=rowOrder.map((i)=>orgs[i]);
  themes=colOrder.map((j)=>themes[j]);
  z=rowOrder.map((i)=>colOrder.map((j)=>z[i][j]));

  const xLabels=themes.map((c)=>scienceWrapLabel(c.title||c.id,16));
  const yLabels=orgs.map((o)=>scienceWrapLabel(o.name,20));
  const leftPad=Math.min(240,48+Math.max(...orgs.map((o)=>String(o.name).length),8)*4.4);
  const bottomPad=Math.min(160,64+Math.max(...themes.map((c)=>String(c.title||c.id).length),8)*2);
  const zMax=Math.max(...z.flat(),1);
  Plotly.newPlot(el,[{
    type:'heatmap',
    z,
    x:xLabels,
    y:yLabels,
    customdata:orgs.map((org)=>themes.map((c)=>[org.name,c.id,c.title||c.id])),
    text:z.map((row)=>row.map((v)=>v?String(v):'')),
    texttemplate:'%{text}',
    textfont:{size:11,color:theme.font},
    colorscale:[
      [0,'#eef3f5'],
      [0.15,'#c5dbe6'],
      [0.4,'#7a9bb8'],
      [0.75,'#3d6a88'],
      [1,'#17334e'],
    ],
    zmin:0,
    zmax:zMax,
    hovertemplate:'%{customdata[0]}<br>%{customdata[2]}: %{z}<extra></extra>',
  }],{
    margin:{t:12,r:28,b:bottomPad,l:leftPad},
    paper_bgcolor:theme.paper,plot_bgcolor:theme.plot,template:theme.template,
    font:{size:10,color:theme.font},
    xaxis:{tickangle:0,automargin:true,gridcolor:theme.grid},
    yaxis:{autorange:'reversed',automargin:true,gridcolor:theme.grid},
  },{responsive:true,displayModeBar:false});
}

function paintScienceScatter(filtered, clusterRows, sciNames, unitLabel){
  const el=$('#scienceVizScatter');
  const pick=$('#scienceVizScatterPick');
  if(!el||typeof Plotly==='undefined') return;
  const points=scienceScatterPoints(filtered, clusterRows, sciNames);
  if(pick) pick.innerHTML=sciencePickHtml(clusterRows,{selectedSet:SCIENCE_VIZ.scatter,empty:'Нет тем',kind:'scatter'});
  const theme=sciencePlotTheme();
  const shareAxis=SCIENCE_MODE==='news'?'Доля академических организаций →':'Доля академических правообладателей →';
  const selectedCount=points.filter((p)=>SCIENCE_VIZ.scatter.has(p.id)).length;
  const hoverAll=selectedCount===0||selectedCount===points.length;
  const makeTrace=(pts,withHover,selected)=>{
    const base='#5b8fad';
    return {
      type:'scatter',
      mode:'markers',
      x:pts.map((p)=>p.academicShare),
      y:pts.map((p)=>p.size),
      text:pts.map((p)=>p.title),
      customdata:pts.map((p)=>[p.id,p.academic,p.industry]),
      marker:{
        size:pts.map((p)=>10+Math.min(22,Math.sqrt(p.size)*2.4)),
        color:pts.map(()=>scienceHexAlpha(base,selected?1:0.28)),
        line:{width:pts.map(()=>selected?2:0),color:'rgba(28,25,23,0.45)'},
      },
      hoverinfo:withHover?'text':'skip',
      hovertemplate:withHover
        ?'<b>%{text}</b><br>наука: %{customdata[1]} · прочие: %{customdata[2]}<br>доля науки: %{x:.0%}<br>объём: %{y}<extra></extra>'
        :undefined,
      showlegend:false,
    };
  };
  const selectedPts=points.filter((p)=>SCIENCE_VIZ.scatter.has(p.id));
  const otherPts=points.filter((p)=>!SCIENCE_VIZ.scatter.has(p.id));
  const traces=[];
  if(otherPts.length) traces.push(makeTrace(otherPts,hoverAll,false));
  if(selectedPts.length) traces.push(makeTrace(selectedPts,true,true));
  Plotly.purge(el);
  if(!points.length){
    Plotly.newPlot(el,[],{
      margin:{t:10,r:16,b:40,l:48},
      paper_bgcolor:theme.paper,plot_bgcolor:theme.plot,template:theme.template,
      xaxis:{visible:false},yaxis:{visible:false},
      annotations:[{text:'Нет тем для сравнения',showarrow:false,xref:'paper',yref:'paper',x:0.5,y:0.5,font:{size:13,color:theme.muted}}],
    },{responsive:true,displayModeBar:false});
    return;
  }
  const yMax=Math.max(...points.map((p)=>p.size),1)*1.12;
  Plotly.newPlot(el,traces,{
    margin:{t:20,r:14,b:48,l:52},
    paper_bgcolor:theme.paper,plot_bgcolor:theme.plot,template:theme.template,
    font:{size:11,color:theme.font},
    hovermode:'closest',
    xaxis:{title:shareAxis,range:[-0.02,1.02],tickformat:'.0%',gridcolor:theme.grid,zeroline:false},
    yaxis:{title:`Объём (${unitLabel}) →`,range:[0,yMax],gridcolor:theme.grid,zeroline:false,rangemode:'tozero'},
    shapes:[
      {type:'line',x0:0.5,x1:0.5,y0:0,y1:yMax,line:{dash:'dot',color:theme.muted,width:1}},
      {type:'line',x0:0,x1:1,y0:yMax/2,y1:yMax/2,line:{dash:'dot',color:theme.muted,width:1}},
    ],
  },{responsive:true,displayModeBar:false});
  el.on('plotly_click',(ev)=>{
    const id=ev?.points?.[0]?.customdata?.[0];
    if(!id) return;
    if(SCIENCE_VIZ.scatter.has(id)) SCIENCE_VIZ.scatter.delete(id);
    else SCIENCE_VIZ.scatter.add(id);
    paintScienceScatter(filtered, clusterRows, sciNames, unitLabel);
  });
}

function paintScienceAnalytics(filtered, clusterRows, sciNames, unitLabel){
  const orgRows=scienceOrgRanking(filtered);
  seedScienceVizSelections(filtered, clusterRows, orgRows);
  paintScienceTrendChart(filtered, clusterRows, unitLabel);
  paintScienceHeatmap(filtered, clusterRows, orgRows);
  if(SCIENCE_MODE!=='news') paintScienceScatter(filtered, clusterRows, sciNames, unitLabel);
}

function applyScienceVizAction(target,act,ctx){
  const {filtered,clusterRows,sciNames,unitLabel,orgRows}=ctx;
  if(target==='scienceVizTrendPick'){
    if(act==='all') clusterRows.forEach((c)=>SCIENCE_VIZ.trend.add(c.id));
    if(act==='clear') SCIENCE_VIZ.trend.clear();
    paintScienceTrendChart(filtered, clusterRows, unitLabel);
    return;
  }
  if(target==='scienceVizHeatPick'){
    if(act==='all'||act==='themes-all') clusterRows.forEach((c)=>SCIENCE_VIZ.heatThemes.add(c.id));
    if(act==='clear'||act==='themes-clear') SCIENCE_VIZ.heatThemes.clear();
    if(act==='orgs-all') orgRows.forEach((o)=>SCIENCE_VIZ.heatOrgs.add(o.name));
    if(act==='orgs-clear') SCIENCE_VIZ.heatOrgs.clear();
    paintScienceHeatmap(filtered, clusterRows, orgRows);
    return;
  }
  if(target==='scienceVizScatterPick'){
    if(act==='all') clusterRows.forEach((c)=>SCIENCE_VIZ.scatter.add(c.id));
    if(act==='clear') SCIENCE_VIZ.scatter.clear();
    paintScienceScatter(filtered, clusterRows, sciNames, unitLabel);
  }
}

function toggleScienceVizPick(target,value,kind,ctx){
  const {filtered,clusterRows,sciNames,unitLabel,orgRows}=ctx;
  if(target==='scienceVizTrendPick'||kind==='trend'){
    if(SCIENCE_VIZ.trend.has(value)) SCIENCE_VIZ.trend.delete(value);
    else SCIENCE_VIZ.trend.add(value);
    paintScienceTrendChart(filtered, clusterRows, unitLabel);
    return;
  }
  if(target==='scienceVizHeatPick'||kind==='heat-org'||kind==='heat-theme'){
    const set=kind==='heat-org'?SCIENCE_VIZ.heatOrgs:SCIENCE_VIZ.heatThemes;
    if(set.has(value)) set.delete(value);
    else set.add(value);
    paintScienceHeatmap(filtered, clusterRows, orgRows);
    return;
  }
  if(target==='scienceVizScatterPick'||kind==='scatter'){
    if(SCIENCE_VIZ.scatter.has(value)) SCIENCE_VIZ.scatter.delete(value);
    else SCIENCE_VIZ.scatter.add(value);
    paintScienceScatter(filtered, clusterRows, sciNames, unitLabel);
  }
}

function paintScienceView(){
  if(!SCIENCE_DATA) return;
  const data=SCIENCE_DATA;
  const clusterOpts=[{value:'',label:'Все кластеры'}]
    .concat((data.clusters||[]).map((c)=>({value:c.id,label:`${c.title} (${fmt(c.member_count)})`})));
  const orgOpts=[{value:'',label:'Все организации'}]
    .concat(((data.filter_orgs||[]).slice(0,400)).map((o)=>({value:o.name,label:`${o.name} (${fmt(o.patent_count)})`})));
  SCIENCE_FILTERS.cluster=asFilterValues(SCIENCE_FILTERS.cluster).filter((id)=>(data.clusters||[]).some((c)=>c.id===id));
  SCIENCE_FILTERS.org=asFilterValues(SCIENCE_FILTERS.org).filter((name)=>orgOpts.some((o)=>o.value===name));
  SCIENCE_FILTERS.period=asFilterValues(SCIENCE_FILTERS.period).map((p)=>p==='7d'?'1':p);
  const periodOpts=[
    {value:'all',label:'Всё время'},{value:'12',label:'12 месяцев'},{value:'6',label:'6 месяцев'},
    {value:'3',label:'3 месяца'},{value:'1',label:'1 месяц'}
  ];
  const filtered=filterScienceIndex(data.index||[]);
  const byCluster=new Map();
  const orgCounts=new Map();
  const monthCounts=new Map();
  for(const item of filtered){
    if(item.cluster_id){
      if(!byCluster.has(item.cluster_id)) byCluster.set(item.cluster_id,[]);
      byCluster.get(item.cluster_id).push(item);
    }
    for(const name of (item.org_names||[])) orgCounts.set(name,(orgCounts.get(name)||0)+1);
    const month=(item.date_norm||patentNormDate(item.date)||'').slice(0,7);
    if(month.length===7 && month<=currentYearMonth()) monthCounts.set(month,(monthCounts.get(month)||0)+1);
  }
  const clusterRows=(data.clusters||[])
    .map((c)=>({id:c.id,title:c.title,count:(byCluster.get(c.id)||[]).length,subclusters:c.subclusters,description:c.description}))
    .filter((c)=>c.count>0)
    .sort((a,b)=>b.count-a.count);
  const sciNames=new Set(((data.science_orgs||{}).items||[]).map((o)=>o.name));
  const orgRows=[...orgCounts.entries()]
    .filter(([name])=>sciNames.size?sciNames.has(name):true)
    .map(([name,count])=>({name,count}))
    .sort((a,b)=>b.count-a.count||a.name.localeCompare(b.name,'ru'));
  const monthRows=scienceMonthBarsFromCounts(
    [...monthCounts.entries()]
      .sort((a,b)=>b[0].localeCompare(a[0]))
      .map(([month,count])=>({month,count}))
  );
  const recent=filtered.slice(0,40);
  const recentParts=recent.map((item,index)=>patentItemHtml(item,index>=4));

  const isNews=SCIENCE_MODE==='news';
  const unit=isNews?'новостей':'патентов';
  const unitOne=isNews?'новости':'патента';
  $('#flowMetrics').innerHTML=[
    ['В выборке',fmt(filtered.length),`из ${fmt((data.index||[]).length)} ${unit}`],
    ['Кластеров',fmt(clusterRows.length),'после фильтра'],
    ['Орг. (наука)',fmt(orgRows.length),'вузы и НИИ в выборке'],
    ['Noise',fmt(filtered.filter((i)=>i.is_noise).length),'вне устойчивых тем']
  ].map((metric)=>`<article class="flow-metric"><span>${metric[0]}</span><strong>${metric[1]}</strong><small>${metric[2]}</small></article>`).join('');

  const modeToggle=`<div class="scale-toggle science-mode-toggle" role="group" aria-label="Режим потока Наука"><button type="button" data-science-mode="patents" aria-pressed="${SCIENCE_MODE==='patents'}">Патенты</button><button type="button" data-science-mode="news" aria-pressed="${SCIENCE_MODE==='news'}">Новости</button></div>`;
  const eyebrow=isNews?'НОВОСТНОЙ ЛАНДШАФТ':'ПАТЕНТНЫЙ ЛАНДШАФТ';
  const headline=isNews?'Кластеры новостей научных центров':'Кластеры и подкластеры Роспатента';
  const orgLabel=isNews?'Организация (источник)':'Организация (патентообладатель)';
  const orgSearch=isNews?'Поиск организации…':'Поиск патентообладателя…';
  const recentTitle=isNews?'Свежие новости':'Свежие патенты';
  const clusterListTitle=isNews?'Темы новостных кластеров':'Темы патентных кластеров';
  const clusterListParts=scienceCompactClusters(clusterRows, byCluster);
  // foldPanel ждёт массив кусков с fold-extra; для списка кластеров один HTML-блок
  const clusterListFoldHtml=(()=>{
    const more=clusterRows.length>10;
    const toggle=more?`<button type="button" class="fold-toggle" data-fold="scienceClusterList" aria-expanded="false">Развернуть</button>`:'';
    return `<article class="panel flow-c12 science-clusters-panel"><div class="flow-card-head science-clusters-head"><div><h3>${clusterListTitle}</h3></div>${toggle}</div><div id="scienceClusterList" class="science-cluster-stack">${clusterListParts||'<p class="source-citation">Нет кластеров в выборке.</p>'}</div></article>`;
  })();

  $('#flowContent').innerHTML=`<section class="flow-section"><div class="flow-section-head"><div><span class="eyebrow dark">${eyebrow}</span><h2>${headline}</h2></div></div>
  <div class="science-toolbar" id="scienceToolbar">
    <div class="science-filters">
      <label>Кластер${scienceSelectHtml('scienceFilterCluster',clusterOpts,SCIENCE_FILTERS.cluster,{searchable:true,searchPlaceholder:'Поиск кластера…',multiple:true,allValue:'',allLabel:'Все кластеры'})}</label>
      <label>${orgLabel}${scienceSelectHtml('scienceFilterOrg',orgOpts,SCIENCE_FILTERS.org,{searchable:true,searchPlaceholder:orgSearch,multiple:true,allValue:'',allLabel:'Все организации'})}</label>
      <label>Период${scienceSelectHtml('scienceFilterPeriod',periodOpts,SCIENCE_FILTERS.period,{multiple:true,allValue:'all',allLabel:'Всё время'})}</label>
    </div>
    ${modeToggle}
  </div>
  <div class="flow-grid">
    ${foldPanel('flow-c5','Размер кластеров','','scienceClusterBars',scienceClusterBarsFromCounts(clusterRows),'horizontal-bars')}
    ${foldPanel('flow-c7','Научные предприятия','','scienceOrgBars',scienceOrgBarsFromCounts(orgRows),'horizontal-bars')}
    ${foldPanel('flow-c5','По месяцам публикации','','scienceMonths',monthRows,'horizontal-bars')}
    ${foldPanel('flow-c7',recentTitle,'','scienceRecent',recentParts,'item-list')}
    ${scienceVizPanelHtml({title:'Динамика тем',chartId:'scienceVizTrends',pickId:'scienceVizTrendPick',pickTitle:'Темы'})}
    ${scienceVizPanelHtml({title:'Организации × темы',chartId:'scienceVizHeatmap',chartClass:'science-plotly-heatmap',pickId:'scienceVizHeatPick',pickTitle:'Фильтр',hideActions:true})}
    ${isNews?'':scienceVizPanelHtml({title:'Наука и индустрия',chartId:'scienceVizScatter',chartClass:'science-plotly-scatter',pickId:'scienceVizScatterPick',pickTitle:'Темы'})}
    ${clusterListFoldHtml}
  </div></section>`;

  const orgRowsAll=scienceOrgRanking(filtered);
  const vizCtx={filtered,clusterRows,sciNames,unitLabel:unit,orgRows:orgRowsAll};
  paintScienceAnalytics(filtered, clusterRows, sciNames, unit);
  bindPatentDrawerOnce();
  const host=$('#flowContent');
  host.dataset.scienceClicks='1';
  // один делегированный обработчик: fold / кластер / патент / селекты / режим
  host.onclick=(event)=>{
    const vizAct=event.target.closest('[data-viz-act]');
    if(vizAct&&host.contains(vizAct)){
      event.preventDefault();
      applyScienceVizAction(vizAct.getAttribute('data-viz-target'),vizAct.getAttribute('data-viz-act'),vizCtx);
      return;
    }
    const vizPick=event.target.closest('.science-viz-pick-item');
    if(vizPick&&host.contains(vizPick)){
      event.preventDefault();
      const pickBody=vizPick.closest('.science-viz-pick-body');
      toggleScienceVizPick(pickBody?.id,vizPick.getAttribute('data-pick-value'),vizPick.getAttribute('data-pick-kind')||'',vizCtx);
      return;
    }
    const modeBtn=event.target.closest('[data-science-mode]');
    if(modeBtn&&host.contains(modeBtn)){
      event.preventDefault();
      const next=modeBtn.getAttribute('data-science-mode');
      if(!next||next===SCIENCE_MODE) return;
      SCIENCE_MODE=next;
      SCIENCE_FILTERS.cluster=[];
      SCIENCE_FILTERS.org=[];
      resetScienceVizSeeds();
      renderScience();
      return;
    }
    const selectOpt=event.target.closest('.science-select-option');
    if(selectOpt&&host.contains(selectOpt)){
      event.preventDefault();
      const wrap=selectOpt.closest('.science-select');
      const value=selectOpt.getAttribute('data-value')??'';
      const result=applySelectChoice(wrap,value);
      if(!result) return;
      SCIENCE_KEEP_SELECT_ID=result.multiple?(wrap?.id||''):'';
      paintScienceView();
      return;
    }
    if(event.target.closest('.science-select-search')) return;
    const selectTrig=event.target.closest('.science-select-trigger');
    if(selectTrig&&host.contains(selectTrig)){
      event.preventDefault();
      const wrap=selectTrig.closest('.science-select');
      const open=!wrap.classList.contains('is-open');
      closeScienceSelects(host);
      if(open) openScienceSelect(wrap);
      return;
    }
    if(!event.target.closest('.science-select')) closeScienceSelects(host);
    const foldBtn=event.target.closest('.fold-toggle');
    if(foldBtn&&host.contains(foldBtn)){
      event.preventDefault();
      const id=foldBtn.getAttribute('data-fold');
      if(!id) return;
      const expanded=foldBtn.getAttribute('aria-expanded')!=='true';
      setFoldState(id,expanded);
      return;
    }
    const browseBar=event.target.closest('[data-science-browse]');
    if(browseBar&&host.contains(browseBar)){
      event.preventDefault();
      openScienceBrowseFromBar(browseBar);
      return;
    }
    const toggle=event.target.closest('[data-expand-cluster]');
    if(toggle&&host.contains(toggle)){
      const id=toggle.getAttribute('data-expand-cluster');
      const body=host.querySelector(`[data-cluster-body="${id.replace(/"/g,'')}"]`);
      if(!body) return;
      const open=body.hasAttribute('hidden');
      body.toggleAttribute('hidden',!open);
      toggle.setAttribute('aria-expanded',String(open));
      toggle.textContent=open?'Свернуть':'Открыть';
      return;
    }
    const row=event.target.closest('[data-patent-id]');
    if(row&&host.contains(row)){
      const id=row.getAttribute('data-patent-id');
      const item=(data.index||[]).find((p)=>p.patent_id===id);
      if(item) openPatentDrawer(item);
    }
  };
  host.onkeydown=(event)=>{
    if(event.key!=='Enter'&&event.key!==' ') return;
    const browseBar=event.target.closest('[data-science-browse]');
    if(!browseBar||!host.contains(browseBar)) return;
    event.preventDefault();
    openScienceBrowseFromBar(browseBar);
  };
  host.oninput=(event)=>{
    const input=event.target.closest('.science-select-search-input');
    if(!input||!host.contains(input)) return;
    filterScienceSelect(input.closest('.science-select'), input.value);
  };
  if(!document.documentElement.dataset.scienceSelectDoc){
    document.documentElement.dataset.scienceSelectDoc='1';
    document.addEventListener('click',(event)=>{
      if(event.target.closest('.science-select')) return;
      const flow=$('#flowContent');
      if(flow) closeScienceSelects(flow);
    });
    document.addEventListener('keydown',(event)=>{
      if(event.key!=='Escape') return;
      const flow=$('#flowContent');
      if(flow) closeScienceSelects(flow);
    });
  }
  if(SCIENCE_KEEP_SELECT_ID){
    const keepId=SCIENCE_KEEP_SELECT_ID;
    SCIENCE_KEEP_SELECT_ID='';
    const keepWrap=host.querySelector(`#${CSS.escape(keepId)}`);
    if(keepWrap) openScienceSelect(keepWrap,{focusSearch:false});
  }
}

async function renderScience(){
  setFlowYearFilterVisible(false);
  const loading=SCIENCE_MODE==='news'
    ?'Читаю кластеры новостей научных центров…'
    :'Читаю патентные кластеры…';
  $('#flowContent').innerHTML=`<p class="source-citation">${loading}</p>`;
  bindPatentDrawerOnce();
  const cacheKey=`/api/flows/science?mode=${encodeURIComponent(SCIENCE_MODE)}`;
  let data=SCIENCE_DATA_BY_MODE[SCIENCE_MODE];
  if(!data){
    try{
      if(window.OilRadarCache){
        data=await window.OilRadarCache.fetchJson(cacheKey);
      }else{
        const response=await fetch(cacheKey);
        if(!response.ok) throw new Error(String(response.status));
        data=await response.json();
      }
      SCIENCE_DATA_BY_MODE[SCIENCE_MODE]=data;
    }catch(error){
      const fail=SCIENCE_MODE==='news'
        ?'Не удалось прочитать кластеры новостей. Сначала: python scripts/cluster_science_news.py'
        :'Не удалось прочитать патентные кластеры.';
      $('#flowContent').innerHTML=`<p class="source-citation">${fail}</p>`;
      return;
    }
  }
  SCIENCE_DATA=data;
  paintScienceView();
}

let FLOW_HEAT_UNIT='month';

function flowPeriodKey(date,unit){
  const d=patentNormDate(date);
  if(d.length<7) return '';
  if(unit==='quarter') return `${d.slice(0,4)}-Q${Math.ceil(Number(d.slice(5,7))/3)}`;
  return d.slice(0,7);
}

function flowPeriodRange(items,unit,maxPeriods){
  const cap=currentYearMonth();
  const months=[...new Set((items||[]).map((i)=>flowPeriodKey(i.date,'month')).filter((m)=>m&&m<=cap))].sort();
  if(!months.length) return [];
  const range=scienceMonthRange(months[0],months[months.length-1]);
  const keys=unit==='quarter'?[...new Set(range.map((m)=>flowPeriodKey(`${m}-01`,'quarter')))]:range;
  return keys.slice(-maxPeriods);
}

function flowCountBy(items,keysOf){
  const map=new Map();
  for(const item of items||[]){
    for(const key of keysOf(item)||[]){
      if(key==null||key==='') continue;
      map.set(key,(map.get(key)||0)+1);
    }
  }
  return [...map.entries()].map(([key,count])=>({key,count})).sort((a,b)=>b.count-a.count||String(a.key).localeCompare(String(b.key),'ru'));
}

function flowKeyBars(rows,{kind,color,colorOf,labelOf,foldAfter=8,empty='Нет данных в выборке.'}){
  if(!rows.length) return [`<p class="source-citation">${esc(empty)}</p>`];
  const max=Math.max(...rows.map((r)=>r.count),1);
  return rows.map((r,index)=>flowBrowseBarRow({
    label:labelOf?labelOf(r.key):r.key,
    count:r.count,
    max,
    folded:index>=foldAfter,
    color:colorOf?colorOf(r.key):color,
    browseKind:kind,
    browseValue:r.key,
  }));
}

function flowDayShift(day,days){
  const d=new Date(`${day}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate()-days);
  return d.toISOString().slice(0,10);
}

/** Рост темы: последние 91 день против 91 дня до них, от последней даты в данных. */
function flowGrowthRows(items,clusterRows){
  const today=new Date().toISOString().slice(0,10);
  const days=(items||[]).map((i)=>patentNormDate(i.date)).filter((d)=>d.length===10&&d<=today).sort();
  if(!days.length) return {rows:[],end:''};
  const end=days[days.length-1];
  const recentFrom=flowDayShift(end,91);
  const prevFrom=flowDayShift(end,182);
  const months=flowPeriodRange(items,'month',12);
  const byCluster=new Map();
  for(const item of items){
    const id=String(item.cluster_id||'');
    if(!byCluster.has(id)) byCluster.set(id,[]);
    byCluster.get(id).push(item);
  }
  const rows=clusterRows.map((c)=>{
    const members=byCluster.get(String(c.id))||[];
    let recent=0;
    let prev=0;
    const perMonth=new Map();
    for(const m of members){
      const d=patentNormDate(m.date);
      if(d>recentFrom&&d<=end) recent+=1;
      else if(d>prevFrom&&d<=recentFrom) prev+=1;
      const mm=d.slice(0,7);
      perMonth.set(mm,(perMonth.get(mm)||0)+1);
    }
    const latest=members.reduce((best,m)=>(!best||String(m.date)>String(best.date)?m:best),null);
    return {...c,recent,prev,spark:months.map((mm)=>perMonth.get(mm)||0),latest,score:(recent-prev)/Math.max(prev,2)};
  });
  const growing=rows
    .filter((r)=>r.recent>=3&&r.recent-r.prev>=2&&r.recent>=r.prev*1.3)
    .sort((a,b)=>b.score-a.score||b.recent-a.recent);
  return {rows:growing,end};
}

function flowSparkSvg(values,color){
  const w=120;
  const h=30;
  const vals=values&&values.length?values:[0];
  const max=Math.max(...vals,1);
  const step=vals.length>1?w/(vals.length-1):w;
  const pts=vals.map((v,i)=>[(i*step).toFixed(1),(h-3-(v/max)*(h-7)).toFixed(1)]);
  const last=pts[pts.length-1];
  return `<svg class="flow-spark" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" aria-hidden="true" focusable="false"><polyline points="${pts.map((p)=>p.join(',')).join(' ')}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/><circle cx="${last[0]}" cy="${last[1]}" r="2.8" fill="${color}"/></svg>`;
}

function flowGrowthPanelHtml(growth){
  const top=growth.rows.slice(0,4);
  const head=`<div class="flow-card-head"><div><h3>Что растёт</h3></div></div>`;
  if(!top.length){
    return `<article class="panel flow-c12">${head}<p class="source-citation">Явного роста нет: ни одна тема не прибавила 30% и больше.</p></article>`;
  }
  const cards=top.map((r)=>{
    const pct=r.prev?`+${Math.round((r.recent-r.prev)/r.prev*100)}%`:'новая тема';
    return `<button type="button" class="flow-growth-card" data-flow-browse="cluster" data-browse-value="${esc(r.id)}" data-browse-label="${esc(r.title)}" aria-label="${esc(r.title)}: ${r.recent} новостей за 3 месяца, было ${r.prev}"><span class="flow-growth-pct">${esc(pct)}</span><strong>${esc(r.title)}</strong><small>${fmt(r.recent)} за 3 мес. · было ${fmt(r.prev)}</small>${flowSparkSvg(r.spark,scienceThemeColor(r.id))}${r.latest?`<em>${esc(String(r.latest.title||'').slice(0,96))}</em>`:''}</button>`;
  }).join('');
  return `<article class="panel flow-c12">${head}<div class="flow-growth-grid">${cards}</div></article>`;
}

function flowPlotScale(theme){
  return theme.dark
    ?[[0,'#15293a'],[0.15,'#1f4560'],[0.4,'#2f6f8f'],[0.75,'#5fa3c4'],[1,'#b9e1f0']]
    :[[0,'#eef3f5'],[0.15,'#c5dbe6'],[0.4,'#7a9bb8'],[0.75,'#3d6a88'],[1,'#17334e']];
}

function flowHeatPanelHtml(){
  const unitWord=FLOW_HEAT_UNIT==='quarter'?'кварталам':'месяцам';
  return `<article class="panel flow-c12"><div class="flow-card-head"><div><h3>Темы по ${unitWord}</h3></div></div><div id="flowHeatmap" class="science-plotly flow-heatmap" role="img" aria-label="Тепловая карта тем по ${unitWord}"></div></article>`;
}

function paintFlowHeatmap(items,clusterRows){
  const el=$('#flowHeatmap');
  if(!el) return;
  const periods=flowPeriodRange(items,FLOW_HEAT_UNIT,FLOW_HEAT_UNIT==='quarter'?12:18);
  const rows=clusterRows.slice(0,20);
  if(!periods.length||!rows.length){
    el.innerHTML='<p class="source-citation">Нет дат для карты.</p>';
    return;
  }
  const counts=new Map();
  for(const it of items){
    const k=`${it.cluster_id}||${flowPeriodKey(it.date,FLOW_HEAT_UNIT)}`;
    counts.set(k,(counts.get(k)||0)+1);
  }
  const z=rows.map((c)=>periods.map((p)=>counts.get(`${c.id}||${p}`)||0));
  el.setAttribute('aria-label',`Тепловая карта: ${rows.length} тем по периодам с ${periods[0]} по ${periods[periods.length-1]}. На узком экране — список с мини-графиками.`);
  if(window.matchMedia('(max-width: 760px)').matches||typeof Plotly==='undefined'){
    el.classList.add('is-list');
    el.innerHTML=`<div class="flow-heat-list">${rows.map((c,i)=>`<button type="button" class="flow-heat-row" data-flow-browse="cluster" data-browse-value="${esc(c.id)}" data-browse-label="${esc(c.title)}"><span>${esc(c.title)}</span>${flowSparkSvg(z[i],scienceThemeColor(c.id))}<b>${fmt(c.count)}</b></button>`).join('')}</div>`;
    return;
  }
  el.classList.remove('is-list');
  const theme=sciencePlotTheme();
  el.style.height=`${Math.max(320,rows.length*30+110)}px`;
  Plotly.purge(el);
  Plotly.newPlot(el,[{
    type:'heatmap',
    z,
    x:periods,
    y:rows.map((_,i)=>i),
    customdata:rows.map((c)=>periods.map((p)=>[c.id,p,c.title||c.id])),
    text:z.map((row)=>row.map((v)=>v?String(v):'')),
    texttemplate:'%{text}',
    textfont:{size:10},
    colorscale:flowPlotScale(theme),
    zmin:0,
    zmax:Math.max(...z.flat(),1),
    xgap:2,ygap:2,
    showscale:false,
    hovertemplate:'%{customdata[2]}<br>%{customdata[1]}: %{z} новостей<extra></extra>',
  }],{
    margin:{t:8,r:12,b:56,l:10},
    paper_bgcolor:theme.paper,plot_bgcolor:theme.plot,template:theme.template,
    font:{size:10,color:theme.font},
    xaxis:{type:'category',tickangle:-40,automargin:true},
    yaxis:{tickmode:'array',tickvals:rows.map((_,i)=>i),ticktext:rows.map((c)=>scienceWrapLabel(c.title||c.id,40)),autorange:'reversed',automargin:true},
  },{responsive:true,displayModeBar:false});
  el.on('plotly_click',(ev)=>{
    const [cid,period,title]=ev?.points?.[0]?.customdata||[];
    if(!cid) return;
    const value=`${cid}||${period}`;
    openFlowBrowseDrawer({kind:'heat',value,label:`${title} · ${period}`,items:collectFlowBrowseItems('heat',value)});
  });
}

function paintFlowTimeline(items){
  const el=$('#flowTimeline');
  if(!el||typeof Plotly==='undefined') return;
  const enriched=items.filter((i)=>i.enrich?.event_type);
  const months=flowPeriodRange(enriched,'month',18);
  if(!months.length){
    el.innerHTML='<p class="source-citation">Нет размеченных событий в выборке.</p>';
    return;
  }
  const counts=new Map();
  for(const it of enriched){
    const k=`${it.enrich.event_type}||${String(it.date||'').slice(0,7)}`;
    counts.set(k,(counts.get(k)||0)+1);
  }
  const theme=sciencePlotTheme();
  const traces=Object.entries(FLOW_ETYPES).map(([key,meta])=>({
    type:'bar',
    name:meta.label,
    x:months,
    y:months.map((m)=>counts.get(`${key}||${m}`)||0),
    customdata:months.map((m)=>[`${key}||${m}`,meta.label]),
    marker:{color:meta.color},
    hovertemplate:`${meta.label} · %{x}: %{y}<extra></extra>`,
  })).filter((t)=>t.y.some((v)=>v>0));
  Plotly.purge(el);
  Plotly.newPlot(el,traces,{
    barmode:'stack',
    margin:{t:8,r:12,b:56,l:40},
    paper_bgcolor:theme.paper,plot_bgcolor:theme.plot,template:theme.template,
    font:{size:10,color:theme.font},
    legend:{orientation:'h',y:1.12,x:0,font:{size:10}},
    xaxis:{type:'category',tickangle:-40,automargin:true},
    yaxis:{rangemode:'tozero',gridcolor:theme.grid,title:{text:'Событий',standoff:6}},
  },{responsive:true,displayModeBar:false});
  el.on('plotly_click',(ev)=>{
    const [value,label]=ev?.points?.[0]?.customdata||[];
    if(!value) return;
    const month=value.split('||')[1];
    openFlowBrowseDrawer({kind:'timeline',value,label:`${label} · ${month}`,items:collectFlowBrowseItems('timeline',value)});
  });
}

function flowMatrixHtml(items,directions){
  const enriched=items.filter((i)=>i.enrich?.event_type&&!i.enrich.is_digest);
  const cells=new Map();
  for(const it of enriched){
    for(const d of it.enrich.directions||[]){
      const k=`${it.enrich.event_type}||${d}`;
      const cell=cells.get(k)||{n:0,sev:0};
      cell.n+=1;
      cell.sev+=Number(it.enrich.severity)||1;
      cells.set(k,cell);
    }
  }
  const types=Object.keys(FLOW_ETYPES).filter((t)=>t!=='macro'&&directions.some((d)=>cells.has(`${t}||${d}`)));
  if(!types.length) return '<p class="source-citation">Нет событий с направлениями в выборке.</p>';
  const max=Math.max(...[...cells.values()].map((c)=>c.n),1);
  const head=directions.map((d)=>`<th scope="col">${esc(d)}</th>`).join('');
  const body=types.map((t)=>{
    const meta=FLOW_ETYPES[t];
    const tds=directions.map((d)=>{
      const cell=cells.get(`${t}||${d}`);
      if(!cell) return '<td><span class="flow-matrix-empty" aria-hidden="true">·</span></td>';
      const alpha=(0.12+0.78*cell.n/max).toFixed(2);
      const avg=(cell.sev/cell.n).toFixed(1).replace('.',',');
      const label=`${meta.label} × ${d}`;
      return `<td><button type="button" class="flow-matrix-cell" style="background:${scienceHexAlpha(meta.color,alpha)}" data-flow-browse="matrix" data-browse-value="${esc(`${t}||${d}`)}" data-browse-label="${esc(label)}" title="${esc(label)}: ${cell.n} событий, средняя сила ${avg} из 3" aria-label="${esc(label)}: ${cell.n} событий">${fmt(cell.n)}</button></td>`;
    }).join('');
    return `<tr><th scope="row"><span class="flow-kind-dot" style="background:${meta.color}"></span>${esc(meta.label)}</th>${tds}</tr>`;
  }).join('');
  return `<div class="flow-matrix-wrap"><table class="flow-matrix"><thead><tr><th scope="col"><span class="sr-only">Тип события</span></th>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function flowMlnText(mln,currency){
  const cur=FLOW_CURRENCY[currency]||currency||'';
  if(mln>=1000) return `${String((mln/1000).toFixed(1)).replace('.',',')} млрд ${cur}`;
  return `${fmt(Math.round(mln))} млн ${cur}`;
}

function flowMoneyByDirectionHtml(items,directions,color){
  const rows=directions.map((d)=>{
    const deals=items.filter((i)=>(i.enrich?.directions||[]).includes(d));
    const sums={};
    let disclosed=0;
    for(const it of deals){
      const a=it.enrich.amount;
      const mln=Number(a?.amount_mln)||0;
      if(!mln) continue;
      disclosed+=1;
      sums[a.currency]=(sums[a.currency]||0)+mln;
    }
    return {d,count:deals.length,disclosed,sums};
  }).filter((r)=>r.count>0).sort((a,b)=>b.count-a.count);
  if(!rows.length) return '<p class="source-citation">Нет сделок с направлениями в выборке.</p>';
  const max=Math.max(...rows.map((r)=>r.count),1);
  const order=['RUB','USD','EUR','CNY','AED','KZT','other'];
  return `<div class="horizontal-bars">${rows.map((r)=>{
    const money=Object.keys(r.sums).sort((a,b)=>order.indexOf(a)-order.indexOf(b)).map((c)=>flowMlnText(r.sums[c],c)).join(' + ');
    const sub=r.disclosed?`раскрыто в ${fmt(r.disclosed)}: ${money}`:'суммы не раскрыты';
    return `<div class="horizontal-bar is-science-browse flow-money-row" role="button" tabindex="0" data-flow-browse="direction" data-browse-value="${esc(r.d)}" data-browse-label="${esc(r.d)}"><span>${esc(r.d)}<small>${esc(sub)}</small></span><div class="bar-track"><i style="width:${r.count/max*100}%;background:${color}"></i></div><b>${fmt(r.count)}</b></div>`;
  }).join('')}</div>`;
}

function flowTopAmountsHtml(items){
  const order=['RUB','USD','EUR','CNY','AED','KZT','other'];
  const rows=items
    .filter((i)=>Number(i.enrich?.amount?.amount_mln)>0)
    .sort((a,b)=>order.indexOf(a.enrich.amount.currency)-order.indexOf(b.enrich.amount.currency)
      ||Number(b.enrich.amount.amount_mln)-Number(a.enrich.amount.amount_mln))
    .slice(0,8);
  if(!rows.length) return '<p class="source-citation">В выборке нет сделок с названной суммой.</p>';
  return `<div class="item-list">${rows.map((item)=>`<div class="flow-item is-flow-article" role="button" tabindex="0" data-flow-link="${esc(item.link)}"><time>${esc(item.date||'')}</time><div><strong>${esc(item.title)}</strong><p>${esc((item.enrich.participants||[]).map((p)=>p.name).slice(0,3).join(', ')||item.source)}</p></div><div><span class="flow-tag flow-amount-tag">${esc(flowAmountText(item.enrich.amount))}</span></div></div>`).join('')}</div>`;
}

function flowSegmentHtml(key,label,options){
  const cur=FLOW_FILTERS[key];
  return `<div class="flow-segment" role="group" aria-label="${esc(label)}"><span class="flow-segment-label">${esc(label)}</span>${options.map((o)=>`<button type="button" data-flow-toggle="${esc(key)}" data-value="${esc(o.value)}" aria-pressed="${cur===o.value}">${esc(o.label)}</button>`).join('')}</div>`;
}

function flowOptionsWithCounts(defs,counts,allLabel){
  return [{value:'',label:allLabel}].concat(
    Object.entries(defs).filter(([key])=>counts.get(key)).map(([key,meta])=>({value:key,label:`${meta.label||key} (${fmt(counts.get(key))})`}))
  );
}

function paintFlowTagView(){
  if(!FLOW_DATA||!FLOW_TAG) return;
  const host=$('#flowContent');
  if(host){host.onclick=null;host.onkeydown=null;host.oninput=null;}
  const isPolicy=FLOW_TAG==='policy';
  FLOW_HEAT_UNIT=isPolicy?'month':'quarter';
  const allItems=FLOW_DATA.allItems||FLOW_DATA.items||[];
  const corpus=flowItemsFrom2022(allItems);
  const clusterCatalog=FLOW_DATA.clusters||[];
  const knownClusterIds=new Set(clusterCatalog.map((c)=>String(c.id)));
  FLOW_FILTERS.cluster=asFilterValues(FLOW_FILTERS.cluster).filter((id)=>knownClusterIds.has(id)||!knownClusterIds.size);
  const sourceUniverse=[...new Set(corpus.map((item)=>item.source||'(без источника)'))];
  FLOW_FILTERS.source=asFilterValues(FLOW_FILTERS.source).filter((s)=>sourceUniverse.includes(s));
  FLOW_FILTERS.period=asFilterValues(FLOW_FILTERS.period).map((p)=>p==='7d'?'1':p);

  const items=filterFlowItems(allItems);
  FLOW_DATA={...FLOW_DATA,items};
  FLOW_BROWSE_CTX=null;
  const clusterRows=flowClusterRows(items);
  const bySource=flowAggregateBySource(items);
  const accent=FLOW_TAG==='investments'?'#d58a52':'#83b3de';
  const filterHint=flowFilterSummary();
  const subTotal=clusterRows.reduce((n,c)=>n+(c.subclusters||[]).length,0);
  const growthItems=filterFlowItems(allItems,{ignorePeriod:true});
  const growth=flowGrowthRows(growthItems,flowClusterRows(growthItems));
  const nEnrichedAll=flowEnrichedCount(corpus);
  const hasEnrich=nEnrichedAll>0;
  const directions=FLOW_DATA.directions||[];

  setFlowYearFilterVisible(false);
  const topSource=bySource[0];
  const startups=items.filter((i)=>i.enrich?.is_startup).length;
  const fourth=!isPolicy&&hasEnrich
    ?['Стартапов',fmt(startups),'по оценке модели']
    :['Главный источник',topSource?`${Math.round(topSource.count/Math.max(items.length,1)*100)}%`:'—',topSource?esc(topSource.source):'нет статей'];
  $('#flowMetrics').innerHTML=[
    ['Статей',fmt(items.length),esc(filterHint||`с ${FLOW_MIN_YEAR} года`)],
    ['Тем',fmt(clusterRows.length),`${fmt(subTotal)} подтем`],
    ['Растут',fmt(growth.rows.length),'тем: 3 мес. к предыдущим 3'],
    fourth,
  ].map((m)=>`<article class="flow-metric"><span>${m[0]}</span><strong>${m[1]}</strong><small>${m[2]}</small></article>`).join('');

  const eyebrow=isPolicy?'ВНЕШНИЕ УСЛОВИЯ':'КАПИТАЛ И НОВЫЕ ИГРОКИ';
  const title=isPolicy?'Что меняется вокруг отрасли':'Куда идут деньги';
  const feedTitle=isPolicy?'Лента событий':'Лента сделок';
  const clusterOpts=[{value:'',label:'Все кластеры'}].concat(
    (clusterCatalog.length?clusterCatalog:clusterRows).map((c)=>({
      value:c.id,
      label:`${c.title||c.id} (${fmt(c.member_count!=null?c.member_count:c.count||0)})`,
    }))
  );
  const sourceOpts=[{value:'',label:'Все источники'}].concat(
    flowAggregateBySource(corpus).slice(0,400).map((row)=>({value:row.source,label:`${row.source} (${fmt(row.count)})`}))
  );
  const selects=[
    `<label>Кластер${scienceSelectHtml('flowFilterCluster',clusterOpts,FLOW_FILTERS.cluster,{searchable:true,searchPlaceholder:'Поиск кластера…',multiple:true,allValue:'',allLabel:'Все кластеры'})}</label>`,
    `<label>Источник${scienceSelectHtml('flowFilterSource',sourceOpts,FLOW_FILTERS.source,{searchable:true,searchPlaceholder:'Поиск источника…',multiple:true,allValue:'',allLabel:'Все источники'})}</label>`,
    `<label>Период${scienceSelectHtml('flowFilterPeriod',flowPeriodOptions(),FLOW_FILTERS.period,{multiple:true,allValue:'all',allLabel:'Всё время'})}</label>`,
  ];
  if(hasEnrich){
    const typeKey=isPolicy?'event_type':'deal_type';
    const typeCounts=new Map(flowCountBy(corpus,(i)=>[i.enrich?.[typeKey]]).map((r)=>[r.key,r.count]));
    const dirCounts=new Map(flowCountBy(corpus,(i)=>i.enrich?.directions||[]).map((r)=>[r.key,r.count]));
    selects.push(isPolicy
      ?`<label>Тип события${scienceSelectHtml('flowFilterEtype',flowOptionsWithCounts(FLOW_ETYPES,typeCounts,'Все типы'),FLOW_FILTERS.etype,{multiple:true,allValue:'',allLabel:'Все типы'})}</label>`
      :`<label>Тип сделки${scienceSelectHtml('flowFilterDeal',flowOptionsWithCounts(FLOW_DEALS,typeCounts,'Все типы'),FLOW_FILTERS.deal,{multiple:true,allValue:'',allLabel:'Все типы'})}</label>`);
    const dirOpts=[{value:'',label:'Все направления'}].concat(directions.filter((d)=>dirCounts.get(d)).map((d)=>({value:d,label:`${d} (${fmt(dirCounts.get(d))})`})));
    selects.push(`<label>Направление${scienceSelectHtml('flowFilterDirection',dirOpts,FLOW_FILTERS.direction,{multiple:true,allValue:'',allLabel:'Все направления'})}</label>`);
  }
  const segment=isPolicy
    ?flowSegmentHtml('macro','Макро и ЦБ',[{value:'show',label:'Показывать'},{value:'hide',label:'Скрыть'}])
    :flowSegmentHtml('cross','Пересечение с «Политикой»',[{value:'all',label:'Все'},{value:'only',label:'Только общие'},{value:'exclude',label:'Без общих'}]);
  const resetBtn=flowFiltersActive()?'<button type="button" class="fold-toggle" data-flow-reset>Сбросить фильтры</button>':'';
  const toolbar=`<div class="science-toolbar flow-toolbar" id="flowToolbar"><div class="science-filters">${selects.join('')}</div><div class="flow-toolbar-row">${segment}${resetBtn}</div></div>`;

  let grid;
  if(!items.length){
    grid=`<article class="panel flow-c12 flow-empty"><h3>По этим фильтрам статей нет</h3><p>Ослабьте условия или сбросьте все фильтры сразу.</p><button type="button" class="fold-toggle" data-flow-reset>Сбросить фильтры</button></article>`;
  }else{
    const p=isPolicy?'policy':'invest';
    const parts=[flowGrowthPanelHtml(growth),flowHeatPanelHtml()];
    const enrichedItems=items.filter((i)=>i.enrich);
    if(hasEnrich&&isPolicy){
      const typeRows=flowCountBy(enrichedItems,(i)=>[i.enrich.event_type]);
      parts.push(foldPanel('flow-c5','Типы событий','',`${p}Types`,
        flowKeyBars(typeRows,{kind:'etype',colorOf:(k)=>(FLOW_ETYPES[k]||FLOW_ETYPES.other).color,labelOf:(k)=>(FLOW_ETYPES[k]||FLOW_ETYPES.other).label}),'horizontal-bars'));
      parts.push(`<article class="panel flow-c7"><div class="flow-card-head"><div><h3>События по месяцам</h3></div></div><div id="flowTimeline" class="science-plotly" role="img" aria-label="Столбчатая диаграмма: число событий каждого типа по месяцам"></div></article>`);
      parts.push(`<article class="panel flow-c12"><div class="flow-card-head"><div><h3>Какие направления затрагивают события</h3></div></div>${flowMatrixHtml(enrichedItems,directions)}</article>`);
      parts.push(foldPanel('flow-c7',feedTitle,'',`${p}Works`,taggedWorks(items),'item-list'));
      parts.push(foldPanel('flow-c5','Компании и ведомства','',`${p}Companies`,
        flowKeyBars(flowCountBy(enrichedItems,(i)=>i.enrich.companies||[]).slice(0,30),{kind:'company',color:accent,foldAfter:10,empty:'Компании не названы.'}),'horizontal-bars'));
    }else if(hasEnrich){
      const dealRows=flowCountBy(enrichedItems,(i)=>[i.enrich.deal_type]);
      parts.push(foldPanel('flow-c5','Типы сделок','',`${p}Deals`,
        flowKeyBars(dealRows,{kind:'deal',colorOf:(k)=>(FLOW_DEALS[k]||FLOW_DEALS.other).color,labelOf:(k)=>(FLOW_DEALS[k]||FLOW_DEALS.other).label}),'horizontal-bars'));
      parts.push(`<article class="panel flow-c7"><div class="flow-card-head"><div><h3>Направления и суммы</h3></div></div>${flowMoneyByDirectionHtml(enrichedItems,directions,accent)}</article>`);
      parts.push(foldPanel('flow-c7',feedTitle,'',`${p}Works`,taggedWorks(items),'item-list'));
      parts.push(foldPanel('flow-c5','Участники','',`${p}Participants`,
        flowKeyBars(flowCountBy(enrichedItems,(i)=>(i.enrich.participants||[]).map((x)=>x.name)).slice(0,30),{kind:'participant',color:accent,foldAfter:10,empty:'Участники не названы.'}),'horizontal-bars'));
      parts.push(`<article class="panel flow-c7"><div class="flow-card-head"><div><h3>Крупнейшие названные суммы</h3></div></div>${flowTopAmountsHtml(enrichedItems)}</article>`);
    }else{
      parts.push(foldPanel('flow-c7',feedTitle,'',`${p}Works`,taggedWorks(items),'item-list'));
    }
    parts.push(`<article class="panel flow-c5"><div class="flow-card-head"><div><h3>Откуда статьи</h3></div></div>${flowSourceBars(bySource,accent)}</article>`);
    parts.push(foldPanel(hasEnrich&&!isPolicy?'flow-c12':'flow-c7','Размер кластеров','',`${p}Clusters`,flowClusterBarsFromCounts(clusterRows,accent),'horizontal-bars'));
    if(!hasEnrich) parts.push(foldPanel('flow-c5','По месяцам','',`${p}Months`,flowMonthRowsFromItems(items,accent),'horizontal-bars'));
    parts.push(flowClusterListHtml(clusterRows,items,`${p}ClusterList`));
    grid=parts.join('');
  }

  $('#flowContent').innerHTML=`<section class="flow-section"><div class="flow-section-head"><div><span class="eyebrow dark">${eyebrow}</span><h2>${title}</h2></div><span class="demo-label">ПО НАШИМ СТАТЬЯМ</span></div>
  ${toolbar}
  <div class="flow-grid">${grid}</div></section>`;
  const content=$('#flowContent');
  bindFlowTagBrowse(content);
  if(items.length){
    paintFlowHeatmap(items,clusterRows);
    if(hasEnrich&&isPolicy) paintFlowTimeline(items);
  }
  if(FLOW_KEEP_SELECT_ID){
    const keepId=FLOW_KEEP_SELECT_ID;
    FLOW_KEEP_SELECT_ID='';
    const keepWrap=content.querySelector(`#${CSS.escape(keepId)}`);
    if(keepWrap) openScienceSelect(keepWrap,{focusSearch:false});
  }
}

async function loadFlowTagData(tag){
  const host=$('#flowContent');
  if(host){host.onclick=null;host.onkeydown=null;host.oninput=null;}
  if(FLOW_TAG && FLOW_TAG!==tag) resetFlowFilters();
  $('#flowContent').innerHTML='<p class="source-citation">Читаю размеченные статьи…</p>';
  setFlowYearFilterVisible(false);
  let data;
  try{
    const url=`/api/flows/${tag}`;
    if(window.OilRadarCache){
      data=await window.OilRadarCache.fetchJson(url);
    }else{
      const response=await fetch(url);
      if(!response.ok) throw new Error(String(response.status));
      data=await response.json();
    }
  }catch(error){
    $('#flowContent').innerHTML='<p class="source-citation">Не удалось прочитать размеченные статьи.</p>';
    return null;
  }
  const isLab=data.source==='flow_news_clusters'
    ||(Array.isArray(data.clusters)&&data.clusters.length&&(Array.isArray(data.index)||Array.isArray(data.items)));
  let enriched;
  if(isLab){
    const rows=Array.isArray(data.items)&&data.items.length?data.items:(data.index||[]);
    enriched=rows.map((item)=>({
      ...item,
      date:item.date||item.date_norm||'',
      tags:item.tags||[],
      reason:item.reason||'',
      cluster_id:item.cluster_id||(item.is_noise?'noise':'other'),
      cluster_title:item.cluster_title||(item.is_noise?'Без устойчивой темы':'Кластер'),
    }));
  }else{
    enriched=enrichFlowItemsWithClusters(data.items||[],tag);
  }
  FLOW_TAG=tag;
  FLOW_DATA={...data,allItems:enriched,items:enriched,clustered:!!isLab};
  FLOW_BROWSE_CTX=null;
  return FLOW_DATA;
}

async function renderInvestments(){
  const data=await loadFlowTagData('investments');
  if(!data) return;
  setFlowStatus(data);
  paintFlowTagView();
}

async function renderPolicy(){
  const data=await loadFlowTagData('policy');
  if(!data) return;
  setFlowStatus(data);
  paintFlowTagView();
}

function setFlowStatus(_data){
  /* мета-подписи в шапке/футере убраны */
}

function init(){
  const path=location.pathname;
  const requested=new URLSearchParams(location.search).get('flow');
  const flow=['science','investments','policy'].includes(requested)?requested:path.includes('investments')?'investments':path.includes('policy')?'policy':'science';
  const config=flowConfig[flow];
  document.body.dataset.flow=flow;
  document.title=`${config.title} — OilTech Radar`;
  $('#breadcrumbFlow').textContent=config.title;
  $('#flowKicker').textContent=config.number;
  $('#flowTitle').textContent=config.title;
  $('#flowDescription').textContent=config.description;
  $('#flowSymbol').textContent=config.symbol;
  $('#flowMetrics').innerHTML=config.metrics.map((metric)=>`<article class="flow-metric"><span>${metric[0]}</span><strong>${metric[1]}</strong><small>${metric[2]}</small></article>`).join('');
  $$('[data-flow-link]').forEach((link)=>link.classList.toggle('active',link.dataset.flowLink===flow));
  $$('[data-flow-tab]').forEach((link)=>link.classList.toggle('active',link.dataset.flowTab===flow));
  const paint=flow==='science'?renderScience():flow==='investments'?renderInvestments():renderPolicy();
  Promise.resolve(paint).finally(()=>{
    if(window.OilRadarCache) window.OilRadarCache.prefetchAll();
  });
}
init();
