import assert from "node:assert/strict";
import test from "node:test";
import { createPersonalAgenda } from "../src/personal-agenda.js";

// Real controller with deferred API responses; this fixture supplies only the
// element/events needed to verify draft preservation and asynchronous results.
function dom() {
  const ids = new Map();
  function el(tag, attrs = {}, ...children) {
    const listeners = new Map();
    let value = String(attrs.value ?? "");
    const node = {
      tag, ...attrs, children: children.flat().filter(child => child != null),
      textContent: "", checked: false,
      get value() { return value; }, set value(next) { value = String(next); },
      get options() { return node.children.filter(child => child?.tag === "option"); },
      append(...values) { node.children.push(...values); },
      replaceChildren(...values) { node.children = values; },
      addEventListener(type, callback) { listeners.set(type, callback); },
      async fire(type) { await listeners.get(type)?.({ preventDefault() {}, target: node }); },
      querySelectorAll(selector) {
        const result = [];
        for (const child of node.children) {
          if (typeof child !== "object") continue;
          if (child.tag === "input" && (selector === "input" || selector === "input:checked" && child.checked)) result.push(child);
          result.push(...child.querySelectorAll(selector));
        }
        return result;
      },
      reset() {
        for (const child of node.children) if (typeof child === "object") child.reset();
        node.value = attrs.value ?? (tag === "select" ? node.options[0]?.value ?? "" : "");
        node.checked = false;
      },
      focus() { node.focused = true; },
    };
    if (attrs.onclick) listeners.set("click", attrs.onclick);
    if (tag === "select") node.value = node.options[0]?.value ?? "";
    if (attrs.id) ids.set(attrs.id, node);
    return node;
  }
  return { el, $: id => ids.get(id) };
}
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
const profile = { enabled: true, interests: "hukuk", project_context: "Yasal araştırma", refresh_minutes: 30, window_hours: 72, max_items: 8, use_local_model: true };
const state = (latest = { id: "personal-1" }, job = { id: "job", status: "completed" }) => ({ profile: { ...profile }, latest, status: { job } });
function fixture(t, options = {}) {
  const d = dom(), shown = [];
  const ui = createPersonalAgenda({ ...d, api: async () => state(), bulletin: { showBulletin(data) { shown.push(data.id); return true; } }, ...options });
  t.after(() => ui.reset());
  ui.unlock();
  return { ...d, ui, shown };
}

test("personal agenda retries its first bulletin when another bulletin operation is busy", t => {
  let busy = true;
  const attempts = [], f = fixture(t, { bulletin: { showBulletin(data) { attempts.push({ id: data.id, accepted: !busy }); return !busy; } } });
  f.ui.update(state(), []);
  busy = false;
  f.ui.update(state(), []);
  f.ui.update(state(), []);
  assert.deepEqual(attempts, [{ id: "personal-1", accepted: false }, { id: "personal-1", accepted: true }]);
});

test("background agenda changes preserve the current reading until the user opens the new result", async t => {
  const f = fixture(t);
  f.ui.update(state(), []);
  f.ui.update(state({ id: "personal-2" }), []);
  assert.deepEqual(f.shown, ["personal-1"]);
  assert.match(f.$("gundem-son-ac").textContent, /Yeni kişisel gündem/);
  await f.$("gundem-son-ac").fire("click");
  assert.deepEqual(f.shown, ["personal-1", "personal-2"]);
  assert.equal(f.$("gundem-son-ac").textContent, "Son kişisel gündemi aç");
});

test("manual generation opens its completed bulletin", async t => {
  const calls = [];
  const f = fixture(t, { api: async (path, options) => { calls.push([path, options?.method]); return state({ id: "personal-1" }, { id: "job", status: "running" }); } });
  f.ui.update(state(), []);
  await f.ui.run();
  f.ui.update(state({ id: "personal-2" }), []);
  assert.deepEqual(calls, [["/agenda", "POST"], ["/agenda", undefined]]);
  assert.deepEqual(f.shown, ["personal-1", "personal-2"]);
});

for (const outcome of ["failed", "cancelled", "interrupted"]) {
  test(`a ${outcome} manual job does not reopen its previous bulletin`, async t => {
    const f = fixture(t, { api: async () => state({ id: "personal-1" }, { id: "job", status: "running" }) });
    f.ui.update(state(), []);
    await f.ui.run();
    f.ui.update(state({ id: "personal-1" }, { id: "job", status: outcome, error: "Kaynak alınamadı." }), []);
    assert.deepEqual(f.shown, ["personal-1"]);
    assert.equal(f.$("gundem-yenile").disabled, false);
    assert.equal(f.$("gundem-iptal").hidden, true);
  });
}

test("logout discards pending generation responses and never runs its refresh callback", async t => {
  const post = deferred();
  let changed = 0;
  const f = fixture(t, { api: () => post.promise, onChanged: () => { changed++; } });
  f.ui.update(state(), []);
  const running = f.ui.run();
  f.ui.reset();
  post.resolve({ job: { id: "job" } });
  await running;
  assert.equal(changed, 0);
  assert.equal(f.$("gundem-durum").textContent, "");
  assert.equal(f.$("gundem-son-ac").hidden, true);
  assert.equal(f.$("gundem-ilgiler").value, "");
  f.ui.update(state({ id: "private-late" }), []);
  assert.deepEqual(f.shown, ["personal-1"]);
});

test("a new profile draft typed during save survives the saved profile readback", async t => {
  const post = deferred(), submitted = [];
  const f = fixture(t, { api: async (path, options) => { if (options?.method === "POST") { submitted.push(options.body); return post.promise; } return state(); } });
  f.ui.update(state(), []);
  f.$("gundem-ilgiler").value = "Kaydedilecek ilgi";
  await f.$("gundem-profil-form").fire("input");
  const saving = f.$("gundem-profil-form").fire("submit");
  f.$("gundem-ilgiler").value = "Sonraki taslak";
  await f.$("gundem-profil-form").fire("input");
  post.resolve(submitted[0]);
  await saving;
  assert.equal(submitted[0].interests, "Kaydedilecek ilgi");
  assert.equal(f.$("gundem-ilgiler").value, "Sonraki taslak");
  assert.match(f.$("gundem-profil-durum").textContent, /sonraki değişiklikleriniz henüz kaydedilmedi/);
});

test("late profile save cannot restore form content after logout", async t => {
  const post = deferred();
  let requests = 0;
  const f = fixture(t, { api: () => { requests++; return post.promise; } });
  f.ui.update(state(), []);
  const saving = f.$("gundem-profil-form").fire("submit");
  f.ui.reset();
  post.resolve({ ...profile, interests: "Eski oturumun profili" });
  await saving;
  assert.equal(requests, 1);
  assert.equal(f.$("gundem-ilgiler").value, "");
  assert.equal(f.$("gundem-profil-durum").textContent, "");
});

test("generation requires unsaved profile edits to be saved first", async t => {
  let calls = 0;
  const f = fixture(t, { api: async () => { calls++; return {}; } });
  f.ui.update(state(), []);
  f.$("gundem-ilgiler").value = "Yeni ilgi";
  await f.$("gundem-profil-form").fire("input");
  await f.ui.run();
  assert.equal(calls, 0);
  assert.equal(f.$("gundem-profil").open, true);
  assert.equal(f.$("gundem-profil-kaydet").focused, true);
  assert.match(f.$("gundem-profil-durum").textContent, /Önce profil/);
});


test("legacy agenda context fields are not submitted after workspace and topic retirement", async t => {
  const requests = [];
  const f = fixture(t, { api: async (path, options) => {
    if (path === "/agenda-profile") { requests.push(options.body); return { profile: options.body }; }
    return state();
  } });
  f.ui.update({ ...state(), profile: { ...profile, workspace_ids: ["old"], include_topics: true } }, [{ id: "old", name: "Eski alan" }]);
  f.$("gundem-ilgiler").value = "Mevzuat ve yerel modeller";
  await f.$("gundem-ilgiler").fire("input");
  await f.$("gundem-profil-form").fire("submit");
  assert.equal(requests.length, 1);
  assert.equal(requests[0].interests, "Mevzuat ve yerel modeller");
  assert.equal(Object.hasOwn(requests[0], "workspace_ids"), false);
  assert.equal(Object.hasOwn(requests[0], "include_topics"), false);
  assert.equal(f.$("gundem-konular"), undefined);
});
