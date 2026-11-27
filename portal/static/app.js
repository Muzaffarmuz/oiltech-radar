let DATA = null;
const PORTAL_API =
  (document.body && document.body.dataset && document.body.dataset.portalApi) || "/api/portal";
const FLOW_READONLY = Boolean(
  document.body && document.body.dataset && document.body.dataset.flowReadonly === "1"
);
let pollTimer = null;
let topicsExpanded = false;
const TOPICS_PREVIEW_COUNT = 9; // 3 колонки × 3 ряда
/** @type {Set<string>} */
const selectedThemeIds = new Set();

function stageBaseColor(stage) {
  if (stage === "breakthrough") return "#b45309";
  if (stage === "emerging") return "#15803d";
  if (stage === "mature") return "#1d4ed8";
  return "#78716c";
}

function hexToRgba(hex, alpha) {
  const h = hex.replace("#", "");
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

async function fetchJSON(url, options) {
  const res = await fetch(url, options);
  if (!res.ok) {
    const text = await res.text();
    let detail = text || res.statusText;
    try {
      const parsed = JSON.parse(text);
      if (parsed?.detail) detail = typeof parsed.detail === "string" ? parsed.detail : JSON.stringify(parsed.detail);
    } catch (_) {
      /* keep raw */
    }
    throw new Error(detail);
  }
  return res.json();
}

function stageClass(stage) {
  return `stage ${stage || ""}`;
}

function getPeriodBounds() {
  const raw = document.getElementById("periodSelect").value || "12";
  if (raw === "all") {
    return {
      allTime: true,
      months: null,
      days: null,
      label: "всё время",
      preferEvents: false,
      cutoffStr: "0000-01",
      cutoffDay: "0000-01-01",
    };
  }
  const cutoff = new Date();
  if (raw === "7d") {
    cutoff.setDate(cutoff.getDate() - 7);
    return {
      allTime: false,
      months: null,
      days: 7,
      label: "1 неделя",
      preferEvents: true,
      cutoffStr: cutoff.toISOString().slice(0, 7),
      cutoffDay: cutoff.toISOString().slice(0, 10),
    };
  }
  const months = Number(raw) || 12;
  cutoff.setMonth(cutoff.getMonth() - months);
  return {
    allTime: false,
    months,
    days: null,
    label: months === 1 ? "1 месяц" : `${months} мес.`,
    // Для коротких окон месячный trend слишком грубый — считаем по датам событий
    preferEvents: months <= 1,
    cutoffStr: cutoff.toISOString().slice(0, 7),
    cutoffDay: cutoff.toISOString().slice(0, 10),
  };
}

/** @type {Set<string>} выбран значений компаний; спец. "__none__" = без компании */
const selectedCompanies = new Set();
/** @type {Set<string>} выбран доменов источников */
const selectedSources = new Set();
/** @type {string[]} активные поисковые теги (ИЛИ) */
const searchTags = [];

function getCompanyFilter() {
  if (!selectedCompanies.size) return { mode: "all", names: [], includeNone: false };
  const names = [...selectedCompanies].filter((v) => v !== "__none__");
  return {
    mode: "multi",
    names,
    includeNone: selectedCompanies.has("__none__"),
  };
}

function eventMatchesCompany(e) {
  const f = getCompanyFilter();
  if (f.mode === "all") return true;
  const company = String(e?.company || "").trim();
  if (!company) return f.includeNone;
  return f.names.includes(company);
}

function companyFilterActive() {
  return getCompanyFilter().mode !== "all";
}

/** Домен / читаемая метка источника (без www, %20, IP-мусора). */
function sourceDomain(value) {
  let raw = String(value || "").trim();
  if (!raw) return "";
  try {
    raw = decodeURIComponent(raw.replace(/\+/g, " "));
  } catch (_) {
    raw = raw.replace(/%20/gi, " ").replace(/\+/g, " ");
  }
  raw = raw.replace(/\s+/g, " ").trim();
  // явный URL → hostname
  if (/^https?:\/\//i.test(raw) || (/^[\w.-]+\.[a-z]{2,}/i.test(raw) && !/\s/.test(raw))) {
    try {
      const withProto = /^https?:\/\//i.test(raw) ? raw : `https://${raw}`;
      const host = new URL(withProto).hostname.toLowerCase().replace(/^www\./, "");
      if (host && !/^(?:\d{1,3}\.){3}\d{1,3}$/.test(host) && !host.includes("news.google")) {
        return host;
      }
    } catch (_) {
      /* fall through */
    }
  }
  // IP / google junk
  if (/^(?:\d{1,3}\.){3}\d{1,3}$/.test(raw) || /news\.google|consent\.google/i.test(raw)) {
    return "";
  }
  // человекочитаемое имя источника
  if (raw.length >= 2) return raw;
  return "";
}

function eventSourceDomain(e) {
  // сначала домен из ссылки издателя, затем очищенный source
  return sourceDomain(e?.link) || sourceDomain(e?.source);
}

function getSourceFilter() {
  if (!selectedSources.size) return { mode: "all", domains: [] };
  return { mode: "multi", domains: [...selectedSources] };
}

function eventMatchesSource(e) {
  const f = getSourceFilter();
  if (f.mode === "all") return true;
  const domain = eventSourceDomain(e);
  return Boolean(domain) && f.domains.includes(domain);
}

function sourceFilterActive() {
  return getSourceFilter().mode !== "all";
}

function eventFiltersActive() {
  return companyFilterActive() || sourceFilterActive();
}

function eventMatchesFilters(e) {
  return eventMatchesCompany(e) && eventMatchesSource(e);
}

function multiFilterButtonText(selected, emptyLabel) {
  const values = [...selected];
  if (!values.length) return emptyLabel;
  if (values.length === 1) {
    return values[0] === "__none__" ? "Без компании" : values[0];
  }
  if (emptyLabel === "Все компании") return `${values.length} комп.`;
  return `${values.length} ист.`;
}

function closeMultiFilters(exceptId) {
  for (const root of document.querySelectorAll(".multi-filter")) {
    if (exceptId && root.id === exceptId) continue;
    const btn = root.querySelector(".multi-filter-btn");
    const panel = root.querySelector(".multi-filter-panel");
    if (btn) btn.setAttribute("aria-expanded", "false");
    if (panel) panel.hidden = true;
  }
}

function updateMultiFilterButton(btnId, selected, emptyLabel) {
  const btn = document.getElementById(btnId);
  if (btn) btn.textContent = multiFilterButtonText(selected, emptyLabel);
}

function fillMultiFilterPanel({ panelId, btnId, selected, options, emptyLabel }) {
  const panel = document.getElementById(panelId);
  if (!panel) return;

  const rows = options
    .map(
      ([value, label]) => `
      <label>
        <input type="checkbox" value="${escapeAttr(value)}" ${selected.has(value) ? "checked" : ""} />
        <span>${escapeHtml(label)}</span>
      </label>`
    )
    .join("");

  panel.innerHTML = `
    ${rows || `<div class="muted" style="padding:8px;font-size:13px">Нет вариантов</div>`}
    <div class="multi-filter-actions">
      <button type="button" data-action="clear">Сбросить</button>
    </div>`;

  panel.querySelectorAll('input[type="checkbox"]').forEach((input) => {
    input.addEventListener("change", () => {
      if (input.checked) selected.add(input.value);
      else selected.delete(input.value);
      updateMultiFilterButton(btnId, selected, emptyLabel);
      refreshFilteredViews({ resetTopicsExpand: true });
    });
  });
  panel.querySelector('[data-action="clear"]')?.addEventListener("click", () => {
    selected.clear();
    panel.querySelectorAll('input[type="checkbox"]').forEach((input) => {
      input.checked = false;
    });
    updateMultiFilterButton(btnId, selected, emptyLabel);
    refreshFilteredViews({ resetTopicsExpand: true });
  });

  updateMultiFilterButton(btnId, selected, emptyLabel);
}

function populateCompanySelect() {
  const names = new Set();
  for (const c of DATA.clusters || []) {
    for (const co of c.companies || []) {
      if (co?.name) names.add(String(co.name).trim());
    }
    for (const e of c.events || []) {
      if (e?.company) names.add(String(e.company).trim());
    }
  }
  const sorted = [...names].filter(Boolean).sort((a, b) => a.localeCompare(b, "ru"));
  for (const v of [...selectedCompanies]) {
    if (v !== "__none__" && !names.has(v)) selectedCompanies.delete(v);
  }
  fillMultiFilterPanel({
    panelId: "companyFilterPanel",
    btnId: "companyFilterBtn",
    selected: selectedCompanies,
    options: [["__none__", "Без упоминания компании"], ...sorted.map((n) => [n, n])],
    emptyLabel: "Все компании",
  });
}

function populateSourceSelect() {
  // Только источники, у которых в радаре есть хотя бы одно событие/статья в кластерах.
  // DATA.sources — полный DISTINCT из БД и может содержать пустые для мониторинга домены.
  const domains = new Set();
  for (const c of DATA.clusters || []) {
    for (const e of c.events || []) {
      const d = eventSourceDomain(e);
      if (d) domains.add(d);
    }
  }
  const sorted = [...domains].filter(Boolean).sort((a, b) => a.localeCompare(b, "ru"));
  for (const v of [...selectedSources]) {
    if (!domains.has(v)) selectedSources.delete(v);
  }
  fillMultiFilterPanel({
    panelId: "sourceFilterPanel",
    btnId: "sourceFilterBtn",
    selected: selectedSources,
    options: sorted.map((n) => [n, n]),
    emptyLabel: "Все источники",
  });
}

function bindMultiFilterToggle(rootId, btnId, panelId) {
  const root = document.getElementById(rootId);
  const btn = document.getElementById(btnId);
  const panel = document.getElementById(panelId);
  if (!root || !btn || !panel) return;
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    const open = btn.getAttribute("aria-expanded") === "true";
    closeMultiFilters();
    if (!open) {
      btn.setAttribute("aria-expanded", "true");
      panel.hidden = false;
    }
  });
  panel.addEventListener("click", (e) => e.stopPropagation());
}

function eventInPeriod(e, cutoffDay, allTime = false) {
  const d = String(e?.date || "").trim();
  // Без даты: показываем только в режиме «всё время» (часто у новых custom sources)
  if (!d) return Boolean(allTime);
  return d >= cutoffDay;
}

function clusterHasActivity(c, cutoffStr, cutoffDay) {
  const { preferEvents, allTime } = getPeriodBounds();
  if (eventFiltersActive()) {
    return (c.events || []).some((e) => eventInPeriod(e, cutoffDay, allTime) && eventMatchesFilters(e));
  }
  const byEvents = (c.events || []).some((e) => eventInPeriod(e, cutoffDay, allTime));
  if (preferEvents) return byEvents;
  if ((c.trend || []).some((t) => t.month >= cutoffStr && (t.count || 0) > 0)) return true;
  return byEvents;
}

function periodTrend(c, cutoffStr) {
  return (c.trend || []).filter((t) => t.month >= cutoffStr);
}

function periodMentions(c, cutoffStr) {
  const { cutoffDay, preferEvents } = getPeriodBounds();
  if (preferEvents || eventFiltersActive()) {
    return periodEvents(c, cutoffDay).length;
  }
  const fromTrend = periodTrend(c, cutoffStr).reduce((sum, t) => sum + (t.count || 0), 0);
  if (fromTrend > 0) return fromTrend;
  return periodEvents(c, cutoffDay).length;
}

function periodEvents(c, cutoffDay) {
  const { allTime } = getPeriodBounds();
  return (c.events || []).filter((e) => eventInPeriod(e, cutoffDay, allTime) && eventMatchesFilters(e));
}

function computeSlope(trendPts) {
  const vals = (trendPts || []).map((p) => p.count || 0);
  if (vals.length < 2) return 0;
  const n = vals.length;
  const xs = vals.map((_, i) => i);
  const mx = xs.reduce((a, b) => a + b, 0) / n;
  const my = vals.reduce((a, b) => a + b, 0) / n;
  const denom = xs.reduce((s, x) => s + (x - mx) ** 2, 0) || 1;
  return xs.reduce((s, x, i) => s + (x - mx) * (vals[i] - my), 0) / denom;
}

/** Темы с активностью в выбранном периоде (без текстового поиска). */
function clustersInPeriod() {
  const { cutoffStr, cutoffDay } = getPeriodBounds();
  return (DATA.clusters || []).filter((c) => clusterHasActivity(c, cutoffStr, cutoffDay));
}

function clusterSearchBlob(c) {
  return [
    c.title,
    c.description,
    c.segment_focus,
    ...(c.companies || []).map((x) => x.name),
    ...(c.events || []).flatMap((e) => [e.topic, e.summary, e.company]),
  ]
    .join(" ")
    .toLowerCase();
}

function normalizeSearchTag(raw) {
  return String(raw || "").trim().replace(/\s+/g, " ");
}

function addSearchTag(raw) {
  const label = normalizeSearchTag(raw);
  if (!label) return false;
  const key = label.toLowerCase();
  if (searchTags.some((t) => t.toLowerCase() === key)) return false;
  searchTags.push(label);
  const input = document.getElementById("searchInput");
  if (input) input.value = "";
  renderSearchTags();
  refreshFilteredViews({ resetTopicsExpand: true });
  return true;
}

function removeSearchTag(index) {
  if (index < 0 || index >= searchTags.length) return;
  searchTags.splice(index, 1);
  renderSearchTags();
  refreshFilteredViews({ resetTopicsExpand: true });
}

function renderSearchTags() {
  const root = document.getElementById("searchTags");
  if (!root) return;
  if (!searchTags.length) {
    root.hidden = true;
    root.innerHTML = "";
    return;
  }
  root.hidden = false;
  root.innerHTML = searchTags
    .map(
      (tag, i) => `
      <span class="search-tag">
        <span class="search-tag-label">${escapeHtml(tag)}</span>
        <button type="button" class="search-tag-remove" data-tag-index="${i}" aria-label="Убрать тег ${escapeAttr(tag)}">×</button>
      </span>`
    )
    .join("");
  root.querySelectorAll(".search-tag-remove").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      removeSearchTag(Number(btn.getAttribute("data-tag-index")));
    });
  });
}

function filterClusters() {
  const list = clustersInPeriod();
  if (!searchTags.length) return list;
  const keys = searchTags.map((t) => t.toLowerCase());
  return list.filter((c) => {
    const blob = clusterSearchBlob(c);
    return keys.some((q) => blob.includes(q));
  });
}

function periodStats() {
  const { cutoffStr, cutoffDay, label, preferEvents } = getPeriodBounds();
  const clusters = clustersInPeriod();
  const sources = new Set();
  const articleLinks = new Set();
  let events = 0;
  const companyCounts = new Map();
  const scored = clusters.map((c) => {
    const evs = periodEvents(c, cutoffDay);
    const mentions = periodMentions(c, cutoffStr);
    let trend = periodTrend(c, cutoffStr);
    if (preferEvents || eventFiltersActive()) {
      const byDay = new Map();
      for (const e of evs) {
        const d = (e.date || "").slice(0, 10);
        if (!d) continue;
        byDay.set(d, (byDay.get(d) || 0) + 1);
      }
      trend = [...byDay.entries()]
        .sort((a, b) => a[0].localeCompare(b[0]))
        .map(([month, count]) => ({ month, count }));
    }
    const slope = computeSlope(trend);
    events += mentions;
    for (const e of evs) {
      if (e.source) sources.add(e.source);
      if (e.link) articleLinks.add(e.link);
      if (e.company) companyCounts.set(e.company, (companyCounts.get(e.company) || 0) + 1);
    }
    let delta = 0;
    if (trend.length >= 2) {
      const mid = Math.floor(trend.length / 2);
      const first = trend.slice(0, mid).reduce((s, t) => s + (t.count || 0), 0);
      const second = trend.slice(mid).reduce((s, t) => s + (t.count || 0), 0);
      delta = second - first;
    } else if (preferEvents || eventFiltersActive()) {
      delta = mentions;
    }
    return { id: c.id, title: c.title, mentions, slope, delta };
  });
  const growing = scored.filter((c) => c.slope > 0.05).sort((a, b) => b.slope - a.slope).slice(0, 5);
  const fading = scored.filter((c) => c.slope < -0.05).sort((a, b) => a.slope - b.slope).slice(0, 5);
  const companies = [...companyCounts.entries()]
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, "ru"))
    .slice(0, 12);
  return {
    label,
    clusters,
    scored,
    events,
    articles: articleLinks.size || events,
    sources: sources.size,
    growing: growing.length ? growing : scored.slice().sort((a, b) => b.mentions - a.mentions).slice(0, 5),
    fading,
    companies,
  };
}

function renderKpis() {
  const s = periodStats();
  const items = [
    ["Тем в мониторинге", s.clusters.length],
    ["Событий", s.events],
    ["Статей", s.articles],
    ["Источников", s.sources],
    ["Растущих тем", s.growing.length],
  ];
  document.getElementById("kpis").innerHTML = items
    .map(
      ([label, value]) => `
      <div class="kpi"><div class="label">${label}</div><div class="value">${value ?? "—"}</div></div>`
    )
    .join("");
}

function renderMeta(status) {
  const pills = [
    `Обновлено: ${DATA.generated_at ? new Date(DATA.generated_at).toLocaleString("ru-RU") : "—"}`,
  ];
  if (!FLOW_READONLY) {
    pills.push(`Режим: ${status?.update_mode || "—"}`);
  } else if (DATA.product) {
    pills.push(String(DATA.product));
  }
  const metaEl = document.getElementById("metaPills");
  if (metaEl) {
    metaEl.innerHTML = pills.map((p) => `<span class="pill">${p}</span>`).join("");
  }
  const modeEl = document.getElementById("updateMode");
  if (modeEl && status?.update_mode) {
    modeEl.value = status.update_mode;
  }
  // Плашку provenance не показываем — мигала из‑за периодического refreshStatus.
}

function renderDiff() {
  const s = periodStats();
  const intro = document.getElementById("diffIntro");
  if (intro) {
    intro.textContent = `Кратко за выбранный период (${s.label}) — какие темы набирают упоминания.`;
  }
  const lines = [];
  if (!s.scored.length) {
    lines.push("В выбранном периоде нет упоминаний.");
  } else {
    lines.push(`За период: ${s.events} упоминаний в ${s.clusters.length} темах.`);
    const byDelta = s.scored
      .filter((c) => c.delta > 0)
      .sort((a, b) => b.delta - a.delta || b.mentions - a.mentions)
      .slice(0, 5);
    for (const g of byDelta) {
      lines.push(`+${g.delta} к теме «${g.title}».`);
    }
    if (byDelta.length < 3) {
      const byMentions = s.scored
        .slice()
        .sort((a, b) => b.mentions - a.mentions)
        .slice(0, 5 - byDelta.length)
        .filter((c) => !byDelta.some((x) => x.id === c.id));
      for (const g of byMentions) {
        lines.push(`${g.mentions} уп. по теме «${g.title}».`);
      }
    }
    if (lines.length === 1) {
      lines.push("Существенных сдвигов внутри периода не видно.");
    }
  }
  document.getElementById("diffList").innerHTML = lines.map((l) => `<li>${escapeHtml(l)}</li>`).join("");
}

function renderTopics() {
  const { cutoffStr } = getPeriodBounds();
  const clusters = filterClusters();
  const root = document.getElementById("topics");
  const toggleBtn = document.getElementById("topicsToggle");
  if (!clusters.length) {
    root.innerHTML = `<div class="card"><p class="intro">Ничего не найдено по текущим тегам. Уберите тег или добавьте другой — например «бурение».</p></div>`;
    if (toggleBtn) toggleBtn.hidden = true;
    return;
  }
  const needsToggle = clusters.length > TOPICS_PREVIEW_COUNT;
  const visible = topicsExpanded || !needsToggle ? clusters : clusters.slice(0, TOPICS_PREVIEW_COUNT);
  root.innerHTML = visible
    .map(
      (c) => `
      <button class="topic" data-id="${c.id}" type="button">
        <span class="${stageClass(c.stage)}">${escapeHtml(c.stage_label || c.stage)}</span>
        <h3>${escapeHtml(c.title)}</h3>
        <p>${escapeHtml((c.description || "").slice(0, 140) || "Без описания")}</p>
        <div class="foot">${mentionsLabel(periodMentions(c, cutoffStr))} · ${escapeHtml(c.segment_focus || "")} · ${escapeHtml(c.forecast?.direction || "")}</div>
      </button>`
    )
    .join("");
  root.querySelectorAll(".topic").forEach((btn) => {
    btn.addEventListener("click", () => openCluster(btn.dataset.id));
  });
  if (toggleBtn) {
    if (needsToggle) {
      toggleBtn.hidden = false;
      const hidden = clusters.length - TOPICS_PREVIEW_COUNT;
      toggleBtn.textContent = topicsExpanded
        ? "Свернуть каталог"
        : `Развернуть все темы (${hidden} ещё)`;
    } else {
      toggleBtn.hidden = true;
    }
  }
}

function renderSideLists() {
  const growing = document.getElementById("growingList");
  const fading = document.getElementById("fadingList");
  const companies = document.getElementById("companiesList");
  if (!growing || !fading || !companies) return;
  const s = periodStats();
  growing.innerHTML = s.growing.length
    ? s.growing.map((c) => `<li><a href="#" data-id="${c.id}" class="open-link">${escapeHtml(c.title)}</a></li>`).join("")
    : "<li class='muted'>Нет</li>";
  fading.innerHTML = s.fading.length
    ? s.fading.map((c) => `<li><a href="#" data-id="${c.id}" class="open-link">${escapeHtml(c.title)}</a></li>`).join("")
    : "<li class='muted'>Нет</li>";
  companies.innerHTML = s.companies.length
    ? s.companies.map((c) => `<li>${escapeHtml(c.name)} — ${c.count}</li>`).join("")
    : "<li class='muted'>Нет</li>";
  document.querySelectorAll(".open-link").forEach((a) => {
    a.addEventListener("click", (e) => {
      e.preventDefault();
      openCluster(a.dataset.id);
    });
  });
}

function renderThemePickList() {
  const { cutoffStr } = getPeriodBounds();
  const clusters = filterClusters()
    .slice()
    .sort(
      (a, b) =>
        periodMentions(b, cutoffStr) - periodMentions(a, cutoffStr) ||
        String(a.title).localeCompare(String(b.title), "ru")
    );
  const root = document.getElementById("themePickList");
  if (!root) return;
  if (!clusters.length) {
    root.innerHTML = `<li class="muted">Нет тем в выбранном периоде</li>`;
    return;
  }
  const visibleIds = new Set(clusters.map((c) => c.id));
  for (const id of [...selectedThemeIds]) {
    if (!visibleIds.has(id)) selectedThemeIds.delete(id);
  }
  root.innerHTML = clusters
    .map((c) => {
      const on = selectedThemeIds.has(c.id);
      return `<li>
        <button type="button" class="theme-pick-item${on ? " is-selected" : ""}" data-id="${escapeAttr(c.id)}" aria-pressed="${on}">
          <span>${escapeHtml(c.title)}</span>
          <span class="mentions">${periodMentions(c, cutoffStr)}</span>
        </button>
      </li>`;
    })
    .join("");
  root.querySelectorAll(".theme-pick-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.id;
      if (selectedThemeIds.has(id)) selectedThemeIds.delete(id);
      else selectedThemeIds.add(id);
      renderThemePickList();
      renderQuadrant();
      renderCumulativeChart();
    });
  });
}

function themeLineHex(id) {
  const s = String(id ?? "");
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  const hue = (h * 47) % 360;
  const sat = 62 + (h % 20);
  const light = 40 + ((h >>> 9) % 16);
  const a = (sat / 100) * Math.min(light / 100, 1 - light / 100);
  const f = (n) => {
    const k = (n + hue / 30) % 12;
    const color = light / 100 - a * Math.max(Math.min(k - 3, 9 - k, 1), -1);
    return Math.round(255 * color);
  };
  return `#${[f(0), f(8), f(4)].map((x) => x.toString(16).padStart(2, "0")).join("")}`;
}

function buildThemeSeries(c, cutoffStr, cutoffDay, preferEvents) {
  const counts = new Map();
  const useEvents = preferEvents || eventFiltersActive();
  if (useEvents) {
    for (const e of periodEvents(c, cutoffDay)) {
      const key = (e.date || "").slice(0, 10);
      if (!key) continue;
      counts.set(key, (counts.get(key) || 0) + 1);
    }
  } else {
    for (const t of periodTrend(c, cutoffStr)) {
      counts.set(t.month, (counts.get(t.month) || 0) + (t.count || 0));
    }
  }
  const keys = [...counts.keys()].sort();
  let run = 0;
  const x = [];
  const y = [];
  for (const k of keys) {
    run += counts.get(k) || 0;
    x.push(k);
    y.push(run);
  }
  return { x, y, total: run };
}

function renderCumulativeChart() {
  const el = document.getElementById("cumulativeChart");
  const legendEl = document.getElementById("cumulativeLegend");
  if (!el || typeof Plotly === "undefined") return;

  const { cutoffStr, cutoffDay, preferEvents } = getPeriodBounds();
  const clusters = filterClusters();
  const selectedCount = clusters.filter((c) => selectedThemeIds.has(c.id)).length;
  // Как на карте стадий: нет выбора / все выбраны → все «равноценны»;
  // частичный выбор → выбранные яркие, остальные тусклые.
  const allDim = selectedCount === 0;
  const allBright = selectedCount > 0 && selectedCount === clusters.length;

  const toPlot = clusters
    .map((c) => {
      const series = buildThemeSeries(c, cutoffStr, cutoffDay, preferEvents);
      const selected = selectedThemeIds.has(c.id);
      const bright = allBright || (!allDim && selected);
      const color = themeLineHex(c.id);
      return { ...c, series, selected, bright, color };
    })
    .filter((c) => c.series.x.length > 0)
    .filter((c) => allDim || c.selected)
    .sort((a, b) => b.series.total - a.series.total || String(a.title).localeCompare(String(b.title), "ru"));

  if (legendEl) {
    legendEl.hidden = true;
    legendEl.innerHTML = "";
  }

  if (!toPlot.length) {
    Plotly.newPlot(
      el,
      [],
      {
        margin: { t: 10, r: 16, b: 48, l: 52 },
        annotations: [
          {
            text: "Нет данных за выбранный период",
            showarrow: false,
            xref: "paper",
            yref: "paper",
            x: 0.5,
            y: 0.5,
            font: { color: "#78716c", size: 14 },
          },
        ],
        paper_bgcolor: "rgba(0,0,0,0)",
        plot_bgcolor: "rgba(0,0,0,0)",
        template: document.documentElement.dataset.theme === "dark" ? "plotly_dark" : "plotly_white",
        xaxis: { visible: false },
        yaxis: { visible: false },
      },
      { responsive: true, displayModeBar: false }
    );
    return;
  }

  // С выбранными — только они; без выбора — все тусклые
  const ordered = toPlot;

  const traces = ordered.map((c) => {
    const lineColor = allDim ? hexToRgba(c.color, 0.35) : c.color;
    return {
      x: c.series.x,
      y: c.series.y,
      name: c.title,
      customdata: c.series.x.map(() => c.id),
      type: "scatter",
      mode: "lines+markers",
      showlegend: false,
      line: {
        color: lineColor,
        width: allDim ? 1.8 : 3,
      },
      marker: { size: allDim ? 5 : 7, color: lineColor },
      hoverinfo: "text",
      hovertemplate: "%{fullData.name}<br>%{x}: %{y} уп.<extra></extra>",
    };
  });

  Plotly.newPlot(
    el,
    traces,
    {
      margin: { t: 12, r: 16, b: 64, l: 52 },
      xaxis: {
        title: { text: preferEvents || eventFiltersActive() ? "Дата" : "Месяц", standoff: 18 },
        automargin: true,
      },
      yaxis: {
        title: { text: "Накоплено упоминаний", standoff: 8 },
        rangemode: "tozero",
        automargin: true,
      },
      showlegend: false,
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      template: document.documentElement.dataset.theme === "dark" ? "plotly_dark" : "plotly_white",
      hovermode: "closest",
    },
    { responsive: true, displayModeBar: false }
  );

  // Легенда только для выбранных справа; цвет = цвет линии
  if (legendEl && selectedCount > 0) {
    const legendItems = toPlot.filter((c) => c.selected);
    legendEl.hidden = legendItems.length === 0;
    legendEl.innerHTML = legendItems
      .map(
        (c) => `<button type="button" class="cumul-legend-item" data-id="${escapeAttr(c.id)}">
          <span class="cumul-legend-swatch" style="background:${c.color}"></span>
          <span class="cumul-legend-label" title="${escapeAttr(c.title)}">${escapeHtml(c.title)}</span>
        </button>`
      )
      .join("");
    legendEl.querySelectorAll(".cumul-legend-item").forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = btn.dataset.id;
        if (selectedThemeIds.has(id)) selectedThemeIds.delete(id);
        else selectedThemeIds.add(id);
        renderThemePickList();
        renderQuadrant();
        renderCumulativeChart();
      });
    });
  }

  el.on("plotly_click", (ev) => {
    const id = ev.points?.[0]?.customdata;
    if (id) openCluster(id);
  });
}

function renderQuadrant() {
  const { cutoffStr } = getPeriodBounds();
  const clusters = filterClusters();
  const points = clusters.map((c) => ({
    x: c.execution_score,
    y: c.innovation_score,
    text: c.title,
    id: c.id,
    stage: c.stage,
    mentions: periodMentions(c, cutoffStr),
    selected: selectedThemeIds.has(c.id),
  }));
  const selectedCount = points.filter((p) => p.selected).length;
  // Названия при hover: для всех, если ничего не выбрано или выбраны все;
  // при частичном выборе — только у выбранных.
  const hoverAll = selectedCount === 0 || selectedCount === points.length;

  const makeTrace = (pts, withHover) => ({
    x: pts.map((p) => p.x),
    y: pts.map((p) => p.y),
    text: pts.map((p) => p.text),
    customdata: pts.map((p) => p.id),
    mode: "markers",
    marker: {
      size: pts.map((p) => 10 + Math.min(20, p.mentions || 0)),
      color: pts.map((p) => hexToRgba(stageBaseColor(p.stage), p.selected ? 1 : 0.28)),
      line: {
        width: pts.map((p) => (p.selected ? 2 : 0)),
        color: "rgba(28,25,23,0.55)",
      },
    },
    hoverinfo: withHover ? "text" : "skip",
    hovertemplate: withHover
      ? "<b>%{text}</b><br>Внедрённость=%{x:.0f}<br>Новизна=%{y:.0f}<extra></extra>"
      : undefined,
    showlegend: false,
  });

  const selectedPts = points.filter((p) => p.selected);
  const otherPts = points.filter((p) => !p.selected);
  const traces = [];
  if (otherPts.length) traces.push(makeTrace(otherPts, hoverAll));
  if (selectedPts.length) traces.push(makeTrace(selectedPts, true));

  Plotly.newPlot(
    "quadrant",
    traces,
    {
      margin: { t: 20, r: 10, b: 40, l: 50 },
      xaxis: {
        title: "Внедрённость →",
        range: [0, 100],
        tickmode: "array",
        tickvals: [0, 20, 40, 60, 80, 100],
        // один «0» в углу — только у оси Y
        ticktext: ["", "20", "40", "60", "80", "100"],
      },
      yaxis: {
        title: "Новизна →",
        range: [0, 100],
        tickmode: "array",
        tickvals: [0, 20, 40, 60, 80, 100],
      },
      shapes: [
        { type: "line", x0: 50, x1: 50, y0: 0, y1: 100, line: { dash: "dot", color: "#a8a29e" } },
        { type: "line", x0: 0, x1: 100, y0: 50, y1: 50, line: { dash: "dot", color: "#a8a29e" } },
      ],
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      template: document.documentElement.dataset.theme === "dark" ? "plotly_dark" : "plotly_white",
    },
    { responsive: true, displayModeBar: false }
  );
  document.getElementById("quadrant").on("plotly_click", (ev) => {
    const id = ev.points?.[0]?.customdata;
    if (id) openCluster(id);
  });
}

function mentionsLabel(n) {
  const abs = Math.abs(Number(n) || 0);
  const mod10 = abs % 10;
  const mod100 = abs % 100;
  let word = "упоминаний";
  if (mod10 === 1 && mod100 !== 11) word = "упоминание";
  else if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) word = "упоминания";
  return `${abs} ${word}`;
}

function openCluster(id) {
  const c = (DATA.clusters || []).find((x) => x.id === id);
  if (!c) return;
  const { cutoffStr, cutoffDay, preferEvents } = getPeriodBounds();
  const filteredMentions = periodMentions(c, cutoffStr);
  const filteredEvents = periodEvents(c, cutoffDay);

  document.getElementById("drawerStage").textContent = c.stage_label || c.stage;
  document.getElementById("drawerTitle").textContent = c.title;
  document.getElementById("drawerDesc").textContent = c.description || "";
  document.getElementById("drawerMeta").innerHTML = [
    mentionsLabel(filteredMentions),
    c.segment_focus || "—",
    `прогноз: ${c.forecast?.direction || "—"}`,
  ]
    .map((x) => `<span class="pill">${escapeHtml(x)}</span>`)
    .join("");
  document.getElementById("forecastNarrative").textContent = c.forecast?.narrative || "Нет прогноза";
  document.getElementById("forecastAction").textContent = c.forecast?.action || "—";
  const subs = c.subclusters || [];
  document.getElementById("drawerSubclusters").innerHTML = subs.length
    ? subs
        .map(
          (s) =>
            `<li><span class="pill">S${escapeHtml(s.local_id)}</span> ${escapeHtml(s.title)} — ${s.mentions}</li>`
        )
        .join("")
    : "<li class='muted'>Подкластеры не выделены (мало точек или однородная тема)</li>";

  const companyCounts = new Map();
  for (const e of filteredEvents) {
    if (!e.company) continue;
    companyCounts.set(e.company, (companyCounts.get(e.company) || 0) + 1);
  }
  const companiesFromEvents = [...companyCounts.entries()]
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count);
  document.getElementById("drawerCompanies").innerHTML = companiesFromEvents.length
    ? companiesFromEvents.map((co) => `<li>${escapeHtml(co.name)} — ${co.count}</li>`).join("")
    : "<li class='muted'>В выбранных фильтрах компании не найдены</li>";

  document.getElementById("drawerEvents").innerHTML = filteredEvents.length
    ? filteredEvents
        .map((e) => {
          const topic = String(e.topic || "").trim();
          const summary = String(e.summary || "").trim();
          const showSummary = summary && !isNearDuplicateText(topic, summary);
          return `
      <article class="event">
        <div class="date">${escapeHtml(e.date || "")} · ${escapeHtml(e.company || "без компании")} · ${escapeHtml(eventSourceDomain(e) || e.source || "")}${
            e.sub_local_id != null ? ` · S${escapeHtml(e.sub_local_id)}` : ""
          }</div>
        <strong>${escapeHtml(topic)}</strong>
        ${e.sub_cluster_title ? `<div class="muted" style="font-size:12px;margin:4px 0">${escapeHtml(e.sub_cluster_title)}</div>` : ""}
        ${showSummary ? `<p>${escapeHtml(summary)}</p>` : ""}
        ${e.link ? `<a href="${escapeAttr(e.link)}" target="_blank" rel="noopener">Открыть источник</a>` : "<span class='muted'>Нет ссылки</span>"}
      </article>`;
        })
        .join("")
    : "<p class='muted'>Нет событий в выбранном периоде / по фильтрам</p>";

  let trend;
  if (preferEvents || eventFiltersActive()) {
    const byDay = new Map();
    for (const e of filteredEvents) {
      const d = (e.date || "").slice(0, 10);
      if (!d) continue;
      byDay.set(d, (byDay.get(d) || 0) + 1);
    }
    trend = [...byDay.entries()]
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([month, count]) => ({ month, count }));
  } else {
    trend = (c.trend || []).filter((t) => t.month >= cutoffStr);
  }
  Plotly.newPlot(
    "trendChart",
    [
      {
        x: trend.map((t) => t.month),
        y: trend.map((t) => t.count),
        type: "scatter",
        mode: "lines+markers",
        line: { color: "#0f766e", width: 3 },
      },
    ],
    {
      margin: { t: 10, r: 10, b: 40, l: 40 },
      yaxis: { title: "Упоминания", allowdecimals: false, rangemode: "tozero" },
      xaxis: { type: "date" },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      template: document.documentElement.dataset.theme === "dark" ? "plotly_dark" : "plotly_white",
    },
    { responsive: true, displayModeBar: false }
  );

  document.getElementById("backdrop").classList.add("open");
  document.getElementById("drawer").classList.add("open");
}

function closeDrawer() {
  document.getElementById("backdrop").classList.remove("open");
  document.getElementById("drawer").classList.remove("open");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

/** title≈summary: RSS/перевод часто дублируют заголовок ± хвост СМИ */
function normForDup(text) {
  let s = String(text || "")
    .toLowerCase()
    .replaceAll("ё", "е");
  s = s.replace(
    /[\s\u2010-\u2015\-–—|:]*\(?\s*(?:rigzone|yahoo\s*finance|aerotime|world\s*oil|offshore\s*energy|hart\s*energy|reuters|bloomberg|oilfield\s*technology|ships\s*monthly|brazil\s*energy\s*insight|the\s*business\s*journals|abb|exxonmobil|shell|bp|chevron|aramco|equinor|eni|petrobras|conocophillips|totalenergies|adnoc|occidental|oxy)\s*\)?\s*$/i,
    ""
  );
  s = s.replace(/[\s\u2010-\u2015\-–—|:]+[a-z0-9 .%&]{2,40}$/i, "");
  s = s.replace(/[^\p{L}\p{N}]+/gu, " ").replace(/\s+/g, " ").trim();
  return s;
}

function tokenJaccard(a, b) {
  const ta = new Set(a.split(" ").filter((t) => t.length > 1));
  const tb = new Set(b.split(" ").filter((t) => t.length > 1));
  if (!ta.size || !tb.size) return 0;
  let inter = 0;
  for (const t of ta) if (tb.has(t)) inter += 1;
  return inter / (ta.size + tb.size - inter);
}

function stemJaccard(a, b) {
  const stem = (s) =>
    new Set(
      s
        .split(" ")
        .filter((t) => t.length > 1)
        .map((t) => (t.length <= 4 ? t : t.slice(0, 5)))
    );
  const ta = stem(a);
  const tb = stem(b);
  if (!ta.size || !tb.size) return 0;
  let inter = 0;
  for (const t of ta) if (tb.has(t)) inter += 1;
  return inter / (ta.size + tb.size - inter);
}

function seqRatio(a, b) {
  if (!a || !b) return 0;
  if (a === b) return 1;
  const m = a.length;
  const n = b.length;
  const dp = new Array(n + 1);
  for (let j = 0; j <= n; j++) dp[j] = j;
  for (let i = 1; i <= m; i++) {
    let prev = dp[0];
    dp[0] = i;
    for (let j = 1; j <= n; j++) {
      const tmp = dp[j];
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      dp[j] = Math.min(dp[j] + 1, dp[j - 1] + 1, prev + cost);
      prev = tmp;
    }
  }
  return 1 - dp[n] / Math.max(m, n);
}

function isNearDuplicateText(a, b, threshold = 0.78) {
  const na = normForDup(a);
  const nb = normForDup(b);
  if (!na || !nb) return false;
  if (na === nb) return true;
  if (na.includes(nb) || nb.includes(na)) return true;
  if (tokenJaccard(na, nb) >= threshold) return true;
  if (stemJaccard(na, nb) >= threshold) return true;
  return seqRatio(na, nb) >= 0.88;
}
function escapeAttr(value) {
  return escapeHtml(value).replaceAll("'", "&#39;");
}

function setBanner(text, kind) {
  const el = document.getElementById("statusBanner");
  if (!el) return;
  if (!text) {
    el.style.display = "none";
    return;
  }
  el.style.display = "block";
  el.className = `banner ${kind || ""}`;
  el.textContent = text;
}

async function refreshStatus() {
  const status = await fetchJSON("/api/status");
  renderMeta(status);
  const st = status.pipeline?.state;
  const stage = status.pipeline?.stage;
  const refreshBtn = document.getElementById("refreshBtn");
  if (st === "running") {
    setBanner(`Идёт обновление: ${stage || "…"}`, "");
    if (refreshBtn) refreshBtn.disabled = true;
  } else if (st === "error") {
    setBanner(`Ошибка пайплайна: ${status.pipeline?.error || "unknown"}`, "err");
    if (refreshBtn) refreshBtn.disabled = false;
  } else if (refreshBtn) {
    refreshBtn.disabled = false;
  }
  return status;
}

function refreshFilteredViews({ resetTopicsExpand = false } = {}) {
  if (resetTopicsExpand) topicsExpanded = false;
  renderKpis();
  renderDiff();
  renderTopics();
  renderThemePickList();
  renderSideLists();
  renderQuadrant();
  renderCumulativeChart();
}

async function loadAll() {
  if (window.OilRadarCache) {
    DATA = await window.OilRadarCache.fetchJson(PORTAL_API);
  } else {
    DATA = await fetchJSON(PORTAL_API);
  }
  const status = FLOW_READONLY ? {} : await refreshStatus();
  if (!FLOW_READONLY) {
    renderMeta(status);
  } else {
    renderMeta({});
  }
  populateCompanySelect();
  populateSourceSelect();
  refreshFilteredViews();
  if (!FLOW_READONLY) {
    await loadCustomSources().catch(() => {});
  }
  if (!FLOW_READONLY && status.pipeline?.state !== "running") {
    setBanner("", "");
  }
  if (window.OilRadarCache) window.OilRadarCache.prefetchAll();
}

function setCustomSourceBanner(text, kind) {
  const el = document.getElementById("customSourceBanner");
  if (!el) return;
  if (!text) {
    el.style.display = "none";
    return;
  }
  el.style.display = "block";
  el.className = `banner ${kind || ""}`;
  el.textContent = text;
}

async function loadCustomSources() {
  const root = document.getElementById("customSourcesList");
  if (!root) return;
  const data = await fetchJSON("/api/custom-sources");
  const items = data.items || [];
  const countEl = document.getElementById("flowSourcesCount");
  if (countEl) {
    if (items.length) {
      countEl.hidden = false;
      countEl.textContent = String(items.length);
    } else {
      countEl.hidden = true;
      countEl.textContent = "";
    }
  }
  if (!items.length) {
    root.innerHTML = `<li class="muted">Пока нет дополнительных источников — добавьте URL выше.</li>`;
    return;
  }
  root.innerHTML = items
    .map((s) => {
      const statusClass = !s.enabled ? "off" : s.status === "error" ? "err" : "";
      const statusText = !s.enabled ? "выключен" : s.status === "error" ? "ошибка" : "готов";
      const url = s.list_url || s.start_url || "";
      return `<li data-id="${escapeAttr(s.source_id)}">
        <div class="src-meta">
          <strong title="${escapeAttr(url)}">${escapeHtml(s.domain)}</strong>
          <span class="status-pill ${statusClass}">${statusText}</span>
          ${s.last_error ? `<span>${escapeHtml(s.last_error)}</span>` : ""}
        </div>
        <div class="src-actions">
          <button type="button" class="theme-pick-btn" data-act="toggle">${s.enabled ? "Выключить" : "Включить"}</button>
          <button type="button" class="theme-pick-btn" data-act="delete">Удалить</button>
        </div>
      </li>`;
    })
    .join("");
  root.querySelectorAll("li[data-id]").forEach((li) => {
    const id = li.dataset.id;
    li.querySelector('[data-act="delete"]')?.addEventListener("click", async () => {
      await fetchJSON(`/api/custom-sources/${encodeURIComponent(id)}`, { method: "DELETE" });
      await loadCustomSources();
    });
    li.querySelector('[data-act="toggle"]')?.addEventListener("click", async () => {
      const item = items.find((x) => x.source_id === id);
      await fetchJSON(`/api/custom-sources/${encodeURIComponent(id)}/enabled`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: !item?.enabled }),
      });
      await loadCustomSources();
    });
  });
}

function openFlowModal() {
  const backdrop = document.getElementById("flowModalBackdrop");
  if (!backdrop) return;
  backdrop.hidden = false;
  loadCustomSources().catch(() => {});
  document.getElementById("customSourceUrl")?.focus();
}

function closeFlowModal() {
  const backdrop = document.getElementById("flowModalBackdrop");
  if (backdrop) backdrop.hidden = true;
}

async function onAddCustomSource() {
  const input = document.getElementById("customSourceUrl");
  const btn = document.getElementById("addCustomSourceBtn");
  const url = (input?.value || "").trim();
  if (!url) {
    setCustomSourceBanner("Вставьте URL сайта", "err");
    return;
  }
  setCustomSourceBanner("Обходим домен, ищем ленты и проверяем тематику…", "");
  if (btn) btn.disabled = true;
  try {
    const res = await fetchJSON("/api/custom-sources", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    if (input) input.value = "";
    const probe = res.item?.probe || {};
    setCustomSourceBanner(
      `Добавлено: ${res.item?.domain || url}. Проверка: ${probe.articles || 0} статей. Нажмите «Обновить данные».`,
      "ok"
    );
    await loadCustomSources();
  } catch (e) {
    setCustomSourceBanner(String(e.message || e), "err");
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function onRefresh() {
  setBanner("Запускаем обновление…", "");
  document.getElementById("refreshBtn").disabled = true;
  if (window.OilRadarCache) await window.OilRadarCache.clear();
  await fetchJSON("/api/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scrape: true, include_seed: false, full_recluster: false }),
  });
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    const status = await refreshStatus();
    if (status.pipeline?.state === "idle" || status.pipeline?.state === "error") {
      clearInterval(pollTimer);
      pollTimer = null;
      if (status.pipeline?.state === "idle") {
        setBanner("Обновление завершено", "ok");
        if (window.OilRadarCache) await window.OilRadarCache.clear();
        await loadAll();
      }
    }
  }, 1500);
}

document.getElementById("refreshBtn")?.addEventListener("click", () => onRefresh().catch((e) => setBanner(String(e), "err")));
document.getElementById("closeDrawer")?.addEventListener("click", closeDrawer);
document.getElementById("backdrop")?.addEventListener("click", closeDrawer);
document.getElementById("topicsToggle")?.addEventListener("click", () => {
  topicsExpanded = !topicsExpanded;
  renderTopics();
});
document.getElementById("searchTagAddBtn")?.addEventListener("click", () => {
  addSearchTag(document.getElementById("searchInput")?.value || "");
});
document.getElementById("searchInput")?.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    addSearchTag(e.target.value || "");
  }
});
renderSearchTags();
document.getElementById("periodSelect")?.addEventListener("change", () => {
  refreshFilteredViews({ resetTopicsExpand: true });
});
bindMultiFilterToggle("companyFilter", "companyFilterBtn", "companyFilterPanel");
bindMultiFilterToggle("sourceFilter", "sourceFilterBtn", "sourceFilterPanel");
document.addEventListener("click", () => closeMultiFilters());
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeMultiFilters();
});
document.getElementById("themeSelectAll")?.addEventListener("click", () => {
  filterClusters().forEach((c) => selectedThemeIds.add(c.id));
  renderThemePickList();
  renderQuadrant();
  renderCumulativeChart();
});
document.getElementById("themeClearAll")?.addEventListener("click", () => {
  selectedThemeIds.clear();
  renderThemePickList();
  renderQuadrant();
  renderCumulativeChart();
});
document.getElementById("updateMode")?.addEventListener("change", async (e) => {
  await fetchJSON("/api/update-mode", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode: e.target.value }),
  });
  setBanner(`Частота обновления: ${e.target.value}`, "ok");
  await refreshStatus();
});
document.getElementById("flowSettingsBtn")?.addEventListener("click", () => openFlowModal());
document.getElementById("closeFlowModal")?.addEventListener("click", () => closeFlowModal());
document.getElementById("flowModalBackdrop")?.addEventListener("click", (e) => {
  if (e.target === e.currentTarget) closeFlowModal();
});
document.getElementById("flowModal")?.addEventListener("click", (e) => e.stopPropagation());
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeFlowModal();
});
document.getElementById("addCustomSourceBtn")?.addEventListener("click", () => {
  onAddCustomSource().catch((e) => setCustomSourceBanner(String(e), "err"));
});
document.getElementById("customSourceUrl")?.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    onAddCustomSource().catch((err) => setCustomSourceBanner(String(err), "err"));
  }
});

loadAll().catch((e) => setBanner(String(e), "err"));
