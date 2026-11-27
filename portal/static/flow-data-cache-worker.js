/**
 * SharedWorker: общий кэш JSON потоков Oil Radar.
 * Живёт, пока открыта хотя бы одна вкладка проекта; при закрытии всех — память очищается сама.
 */
const store = new Map();

function reply(port, id, payload) {
  port.postMessage({ id, ...payload });
}

function onMessage(port, data) {
  const id = data && data.id;
  const type = data && data.type;
  try {
    if (type === "get") {
      const key = String(data.key || "");
      reply(port, id, { ok: true, value: store.has(key) ? store.get(key) : null, hit: store.has(key) });
      return;
    }
    if (type === "set") {
      const key = String(data.key || "");
      if (key) store.set(key, data.value);
      reply(port, id, { ok: true });
      return;
    }
    if (type === "delete") {
      store.delete(String(data.key || ""));
      reply(port, id, { ok: true });
      return;
    }
    if (type === "clear") {
      store.clear();
      reply(port, id, { ok: true });
      return;
    }
    if (type === "keys") {
      reply(port, id, { ok: true, keys: [...store.keys()] });
      return;
    }
    reply(port, id, { ok: false, error: "unknown type" });
  } catch (err) {
    reply(port, id, { ok: false, error: String(err && err.message ? err.message : err) });
  }
}

self.onconnect = (event) => {
  const port = event.ports[0];
  port.onmessage = (ev) => onMessage(port, ev.data || {});
  port.start();
};
