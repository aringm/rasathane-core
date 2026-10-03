import assert from "node:assert/strict";
import test from "node:test";
import { createRadarFeed } from "../src/radar-feed.js";

function fixture() {
  const ids = new Map(), requests = [], callbacks = new Map();
  let stopped = 0, rendered = 0, disposed = 0, moves = 0;
  function el(tag, attrs = {}, ...children) {
    const events = new Map(), classes = new Set((attrs.class || "").split(" "));
    const node = { tag, ...attrs, children: children.flat().filter(x => x != null), textContent: children.filter(x => typeof x === "string").join(""), value: attrs.value || "",
      classList: { add: name => classes.add(name), remove: name => classes.delete(name), contains: name => classes.has(name) },
      append(...items) { this.children.push(...items); }, replaceChildren(...items) { this.children = items; },
      insertBefore(child, before) { if (child.parentElement) child.remove(); const index = before ? this.children.indexOf(before) : this.children.length; this.children.splice(index, 0, child); child.parentElement = this; },
      moveBefore(child, before) { moves++; this.insertBefore(child, before); },
      remove() { const parent = this.parentElement; if (parent) parent.children.splice(parent.children.indexOf(this), 1); this.parentElement = null; },
      after() {}, closest() { return node; }, setAttribute(name, value) { this[name] = value; }, removeAttribute(name) { delete this[name]; },
      addEventListener(type, fn) { events.set(type, fn); }, fire(type) { events.get(type)?.(); },
      querySelectorAll(selector) { return this.children.filter(x => x && typeof x === "object").flatMap(x => [...((selector.startsWith(".") ? x.classList.contains(selector.slice(1)) : x.tag === selector) ? [x] : []), ...x.querySelectorAll(selector)]); },
      querySelector(selector) { return this.querySelectorAll(selector)[0]; },
    };
    if (tag === "select") node.value = children[0]?.value || "";
    if (attrs.id) ids.set(attrs.id, node);
    return node;
  }
  for (const id of ["akis-liste", "akis-icerik-baslik", "akis-kaynak-ozet"]) el("div", { id });
  const feed = createRadarFeed({ el, $: id => ids.get(id),
    api: path => new Promise((resolve, reject) => requests.push({ path, resolve, reject })),
    news: { stopAll() { stopped++; } }, bulletin: { updateItems() {} }, onSources() {},
    renderRecord(item, callback) { rendered++; callbacks.set(item.id, callback); const control = el("div", { class: "running-controls" }); control.dispose = () => { disposed++; }; return control; },
  });
  const article = (id, title = id) => ({ id, title, category: "genel", summary_display: { status: "not_prepared" } });
  function complete(from, items) { for (const request of requests.slice(from, from + 2)) request.resolve({ items, total: items.length }); }
  return { feed, requests, ids, callbacks, article, complete, rendered: () => rendered, stopped: () => stopped, disposed: () => disposed, moves: () => moves };
}
const settle = () => new Promise(resolve => setImmediate(resolve));

test("overlapping state refreshes share one flight and preserve visible summary/audio controls", async () => {
  const f = fixture();
  const pending = f.feed.update({ sources: [] });
  for (let i = 0; i < 6; i++) assert.equal(f.feed.update({ sources: [] }), pending);
  assert.equal(f.requests.length, 2);
  f.complete(0, [f.article("one")]); await pending;
  const original = f.ids.get("akis-liste").children[0];
  const refreshed = f.feed.update({ sources: [] });
  f.callbacks.get("one")({ status: "ready", language: "tr", summary: "Manuel hazırlanmış özet", title: "Türkçe başlık" });
  f.complete(2, [f.article("one"), f.article("two")]); await refreshed;
  assert.equal(f.ids.get("akis-liste").children[0], original);
  assert.equal(original.querySelector(".radar-entry-excerpt").textContent, "Manuel hazırlanmış özet");
  assert.equal(f.rendered(), 2);
  assert.equal(f.stopped(), 0);
  f.feed.reset();
});

test("search changes coalesce behind a slow flight and never render its stale response", async t => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const f = fixture(), pending = f.feed.update({ sources: [] });
  const search = f.ids.get("akis-ara");
  search.value = "first search"; search.fire("input"); t.mock.timers.tick(251);
  search.value = "latest search"; search.fire("input"); t.mock.timers.tick(251);
  for (let i = 0; i < 4; i++) f.feed.update({ sources: [] });
  assert.equal(f.requests.length, 2);
  f.complete(0, [f.article("stale")]); await settle();
  assert.equal(f.ids.get("akis-liste").children.length, 0);
  assert.equal(f.requests.length, 4);
  assert.equal(new URL(f.requests[2].path, "http://localhost").searchParams.get("query"), "latest search");
  assert.equal(new URL(f.requests[3].path, "http://localhost").searchParams.get("query"), "latest search");
  f.complete(2, [f.article("current")]); await pending;
  assert.equal(f.ids.get("akis-liste").children[0]["data-article-id"], "current");
  assert.equal(f.rendered(), 1);
  f.feed.reset();
});

test("logout discards a queued search and late private response", async t => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const f = fixture(), pending = f.feed.update({ sources: [] });
  const search = f.ids.get("akis-ara"); search.value = "private"; search.fire("input"); t.mock.timers.tick(251);
  f.feed.reset(); f.complete(0, [f.article("private")]); await pending;
  assert.equal(f.requests.length, 2);
  assert.equal(f.ids.get("akis-liste").children.length, 0);
});

test("changed source input or ready source hash invalidates the old summary/audio control", async () => {
  const f = fixture();
  let pending = f.feed.update({ sources: [] });
  f.complete(0, [f.article("one", "Original title")]); await pending;
  const initial = f.ids.get("akis-liste").children[0];
  f.callbacks.get("one")({ status: "ready", language: "tr", summary: "Eski kaynak özeti", source_hash: "old-hash" });
  pending = f.feed.update({ sources: [] });
  f.complete(2, [f.article("one", "Updated title")]); await pending;
  const changed = f.ids.get("akis-liste").children[0];
  assert.notEqual(changed, initial);
  assert.notEqual(changed.querySelector(".radar-entry-excerpt").textContent, "Eski kaynak özeti");
  assert.equal(f.disposed(), 1);
  assert.equal(f.stopped(), 0);
  f.callbacks.get("one")({ status: "ready", language: "tr", summary: "Birinci metin", source_hash: "first-hash" });
  pending = f.feed.update({ sources: [] });
  f.complete(4, [{ ...f.article("one", "Updated title"), summary_display: { status: "ready", language: "tr", summary: "Yeni kaynak metni", source_hash: "second-hash" } }]); await pending;
  assert.notEqual(f.ids.get("akis-liste").children[0], changed);
  assert.equal(f.ids.get("akis-liste").children[0].querySelector(".radar-entry-excerpt").textContent, "Yeni kaynak metni");
  assert.equal(f.disposed(), 2);
  assert.equal(f.stopped(), 0);
  f.feed.reset();
});

test("a failed page waits for its companion request before draining the latest search", async t => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const f = fixture(), pending = f.feed.update({ sources: [] });
  const search = f.ids.get("akis-ara"); search.value = "latest"; search.fire("input"); t.mock.timers.tick(251);
  f.requests[0].reject(new Error("Temporary failure")); await settle();
  assert.equal(f.requests.length, 2);
  f.requests[1].resolve({ items: [], total: 0 }); await settle();
  assert.equal(f.requests.length, 4);
  f.complete(2, [f.article("latest")]); await pending;
  assert.equal(f.ids.get("akis-liste").children[0]["data-article-id"], "latest");
  f.feed.reset();
});

test("a refreshed page disposes only removed cards while preserving remaining controls", async () => {
  const f = fixture();
  let pending = f.feed.update({ sources: [] }); f.complete(0, [f.article("removed"), f.article("retained")]); await pending;
  const retained = f.ids.get("akis-liste").children[1];
  pending = f.feed.update({ sources: [] }); f.complete(2, [f.article("retained"), f.article("new")]); await pending;
  assert.equal(f.disposed(), 1);
  assert.equal(f.stopped(), 0);
  assert.equal(f.ids.get("akis-liste").children[0], retained);
  f.feed.reset();
});

test("sorting retained cards uses a state-preserving DOM move instead of rebuilding media", async () => {
  const f = fixture();
  let pending = f.feed.update({ sources: [] }); f.complete(0, [f.article("first"), f.article("second")]); await pending;
  const first = f.ids.get("akis-liste").children[0], second = f.ids.get("akis-liste").children[1];
  pending = f.feed.update({ sources: [] }); f.complete(2, [f.article("second"), f.article("first")]); await pending;
  assert.deepEqual(f.ids.get("akis-liste").children, [second, first]);
  assert.equal(f.moves(), 1);
  assert.equal(f.disposed(), 0);
  assert.equal(f.stopped(), 0);
  assert.equal(f.rendered(), 2);
  f.feed.reset();
});

test("a failed refresh retains same-filter controls but a failed new filter disposes them", async t => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const f = fixture();
  let pending = f.feed.update({ sources: [] }); f.complete(0, [f.article("one")]); await pending;
  const original = f.ids.get("akis-liste").children[0];
  pending = f.feed.update({ sources: [] });
  f.requests[2].reject(new Error("Offline")); f.requests[3].resolve({ items: [] }); await pending;
  assert.equal(f.ids.get("akis-liste").children[0], original);
  assert.equal(f.disposed(), 0);
  const search = f.ids.get("akis-ara"); search.value = "other"; search.fire("input"); t.mock.timers.tick(251);
  f.requests[4].reject(new Error("Offline")); f.requests[5].resolve({ items: [] }); await settle();
  assert.notEqual(f.ids.get("akis-liste").children[0], original);
  assert.equal(f.disposed(), 1);
  f.feed.reset();
});

test("pending-summary polling invalidates changed source input through the shared load path", async t => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const f = fixture();
  const queued = { ...f.article("queued"), summary_display: { status: "pending", job_id: "job" } };
  const pending = f.feed.update({ sources: [] }); f.complete(0, [f.article("one"), queued]); await pending;
  const original = f.ids.get("akis-liste").children[0];
  f.callbacks.get("one")({ status: "ready", language: "tr", summary: "Eski kaynak özeti" });
  t.mock.timers.tick(2501);
  assert.equal(f.requests.length, 3);
  f.requests[2].resolve({ items: [f.article("one", "Updated source"), queued], total: 2 }); await settle();
  assert.equal(f.requests.length, 5);
  f.complete(3, [f.article("one", "Updated source"), f.article("queued")]); await settle();
  assert.notEqual(f.ids.get("akis-liste").children[0], original);
  assert.equal(f.disposed(), 1);
  assert.equal(f.ids.get("akis-liste").children[0].querySelector("h3").textContent, "Updated source");
  f.feed.reset();
});
