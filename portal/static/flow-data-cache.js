/**
 * Кэш JSON потоков Oil Radar.
 * IndexedDB переживает переход между страницами в той же вкладке.
 * Очистка: только когда закрыты все вкладки проекта (новая вкладка без «тёплой» sessionStorage
 * и без чужих heartbeat) или явный OilRadarCache.clear() после «Обновить данные».
 */
(function (global) {
  const DB_NAME = "oilradar-flow-cache";
  const DB_STORE = "payloads";
  const DB_VERSION = 4; // bump: majors → компании wording
  const TABS_KEY = "oilradar:open-tabs";
  const TAB_ID_KEY = "oilradar:tab-id";
  const WARM_KEY = "oilradar:session-warm";
  const HEARTBEAT_MS = 5000;
  const STALE_TAB_MS = 20000;
  const PREFETCH_URLS = [
    "/api/portal",
    "/api/portal/foreign-it",
    "/api/flows/policy",
    "/api/flows/investments",
    "/api/flows/science?mode=news",
    "/api/flows/science?mode=patents",
  ];

  function stableTabId() {
    try {
      let id = sessionStorage.getItem(TAB_ID_KEY);
      if (!id) {
        id =
          global.crypto && crypto.randomUUID
            ? crypto.randomUUID()
            : `t-${Date.now()}-${Math.random().toString(16).slice(2)}`;
        sessionStorage.setItem(TAB_ID_KEY, id);
      }
      return id;
    } catch (_) {
      return `t-${Date.now()}`;
    }
  }

  const tabId = stableTabId();
  const memory = new Map();
  const inflight = new Map();
  let dbPromise = null;
  let workerPort = null;
  let workerReady = null;
  let reqSeq = 0;
  const pending = new Map();
  let prefetchStarted = false;
  let bootDone = null;

  function openDb() {
    if (dbPromise) return dbPromise;
    dbPromise = new Promise((resolve) => {
      if (!global.indexedDB) {
        resolve(null);
        return;
      }
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains(DB_STORE)) {
          db.createObjectStore(DB_STORE);
        }
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => resolve(null);
      req.onblocked = () => resolve(null);
    });
    return dbPromise;
  }

  function idbReq(fn) {
    return openDb().then(
      (db) =>
        new Promise((resolve) => {
          if (!db) {
            resolve(null);
            return;
          }
          try {
            fn(db, resolve);
          } catch (_) {
            resolve(null);
          }
        })
    );
  }

  function idbGet(key) {
    return idbReq((db, resolve) => {
      const tx = db.transaction(DB_STORE, "readonly");
      const req = tx.objectStore(DB_STORE).get(key);
      req.onsuccess = () => resolve(req.result === undefined ? null : req.result);
      req.onerror = () => resolve(null);
    });
  }

  function idbSet(key, value) {
    return idbReq((db, resolve) => {
      const tx = db.transaction(DB_STORE, "readwrite");
      tx.objectStore(DB_STORE).put(value, key);
      tx.oncomplete = () => resolve(true);
      tx.onerror = () => resolve(false);
      tx.onabort = () => resolve(false);
    });
  }

  function idbClear() {
    return idbReq((db, resolve) => {
      const tx = db.transaction(DB_STORE, "readwrite");
      tx.objectStore(DB_STORE).clear();
      tx.oncomplete = () => resolve(true);
      tx.onerror = () => resolve(false);
    });
  }

  function connectWorker() {
    if (workerReady) return workerReady;
    workerReady = new Promise((resolve) => {
      if (typeof SharedWorker === "undefined") {
        resolve(false);
        return;
      }
      try {
        const worker = new SharedWorker("/static/flow-data-cache-worker.js?v=3", {
          name: "oilradar-flow-cache",
        });
        workerPort = worker.port;
        workerPort.onmessage = (ev) => {
          const msg = ev.data || {};
          const wait = pending.get(msg.id);
          if (!wait) return;
          pending.delete(msg.id);
          if (msg.ok) wait.resolve(msg);
          else wait.reject(new Error(msg.error || "cache worker error"));
        };
        workerPort.start();
        const id = ++reqSeq;
        pending.set(id, {
          resolve: () => resolve(true),
          reject: () => resolve(false),
        });
        workerPort.postMessage({ id, type: "keys" });
        setTimeout(() => {
          if (pending.has(id)) {
            pending.delete(id);
            resolve(false);
          }
        }, 1200);
      } catch (_) {
        resolve(false);
      }
    });
    return workerReady;
  }

  function workerCall(type, payload) {
    return connectWorker().then((ok) => {
      if (!ok || !workerPort) return null;
      const id = ++reqSeq;
      return new Promise((resolve, reject) => {
        pending.set(id, { resolve, reject });
        workerPort.postMessage({ id, type, ...payload });
        setTimeout(() => {
          if (pending.has(id)) {
            pending.delete(id);
            reject(new Error("cache worker timeout"));
          }
        }, 8000);
      }).catch(() => null);
    });
  }

  async function get(key) {
    await bootDone;
    if (memory.has(key)) return memory.get(key);
    const msg = await workerCall("get", { key });
    if (msg && msg.hit) {
      memory.set(key, msg.value);
      return msg.value;
    }
    const fromDb = await idbGet(key);
    if (fromDb != null) {
      memory.set(key, fromDb);
      workerCall("set", { key, value: fromDb });
      return fromDb;
    }
    return null;
  }

  async function set(key, value) {
    await bootDone;
    memory.set(key, value);
    await Promise.all([workerCall("set", { key, value }), idbSet(key, value)]);
  }

  async function clear() {
    memory.clear();
    inflight.clear();
    await Promise.all([workerCall("clear", {}), idbClear()]);
  }

  async function fetchJson(url, options) {
    await bootDone;
    const opts = options || {};
    const key = String(url);
    if (!opts.force) {
      const hit = await get(key);
      if (hit != null) return hit;
      if (inflight.has(key)) return inflight.get(key);
    }
    const task = (async () => {
      const response = await fetch(url, opts.fetchOptions || {});
      if (!response.ok) {
        const err = new Error(`HTTP ${response.status}`);
        err.status = response.status;
        throw err;
      }
      const data = await response.json();
      await set(key, data);
      return data;
    })();
    if (!opts.force) inflight.set(key, task);
    try {
      return await task;
    } finally {
      if (inflight.get(key) === task) inflight.delete(key);
    }
  }

  function prefetchAll(extraUrls) {
    if (prefetchStarted) return;
    prefetchStarted = true;
    const urls = [...PREFETCH_URLS, ...(extraUrls || [])];
    const run = () => {
      urls.forEach((url) => {
        fetchJson(url).catch(() => {});
      });
    };
    if (typeof requestIdleCallback === "function") {
      requestIdleCallback(run, { timeout: 1500 });
    } else {
      setTimeout(run, 200);
    }
  }

  function readTabs() {
    try {
      return JSON.parse(localStorage.getItem(TABS_KEY) || "{}") || {};
    } catch (_) {
      return {};
    }
  }

  function writeTabs(tabs) {
    try {
      localStorage.setItem(TABS_KEY, JSON.stringify(tabs));
    } catch (_) {}
  }

  function pruneTabs(tabs, now) {
    const next = {};
    Object.keys(tabs || {}).forEach((id) => {
      const ts = Number(tabs[id]) || 0;
      if (now - ts <= STALE_TAB_MS) next[id] = ts;
    });
    return next;
  }

  function heartbeat() {
    const now = Date.now();
    const tabs = pruneTabs(readTabs(), now);
    tabs[tabId] = now;
    writeTabs(tabs);
  }

  /**
   * Переход Science→Policy тоже шлёт pagehide. Кэш IndexedDB трогать нельзя.
   * Только снимаем heartbeat этой вкладки; очистка — при следующем «холодном» старте.
   */
  function onPageHide() {
    clearInterval(beatTimer);
    const now = Date.now();
    const tabs = pruneTabs(readTabs(), now);
    delete tabs[tabId];
    writeTabs(tabs);
  }

  /**
   * Холодный старт вкладки (sessionStorage пуст) и нет других живых вкладок
   * → предыдущая сессия полностью закрыта → чистим кэш.
   * Навигация внутри вкладки: WARM уже есть → кэш оставляем.
   */
  async function bootSession() {
    let warm = false;
    try {
      warm = sessionStorage.getItem(WARM_KEY) === "1";
      sessionStorage.setItem(WARM_KEY, "1");
    } catch (_) {}

    const now = Date.now();
    const others = pruneTabs(readTabs(), now);
    delete others[tabId];
    const alone = Object.keys(others).length === 0;

    if (!warm && alone) {
      memory.clear();
      await idbClear();
      await workerCall("clear", {});
    }

    heartbeat();
  }

  const beatTimer = setInterval(heartbeat, HEARTBEAT_MS);
  global.addEventListener("pagehide", onPageHide);
  // beforeunload не чистит IDB — иначе ломается переход между потоками.

  connectWorker();
  bootDone = openDb()
    .then(() => bootSession())
    .catch(() => {})
    .finally(() => {
      if (document.readyState === "complete") {
        setTimeout(() => prefetchAll(), 50);
      } else {
        global.addEventListener("load", () => setTimeout(() => prefetchAll(), 50), { once: true });
      }
    });

  global.OilRadarCache = {
    get,
    set,
    clear,
    fetchJson,
    prefetchAll,
    PREFETCH_URLS,
  };
})(window);
