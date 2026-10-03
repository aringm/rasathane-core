import assert from "node:assert/strict";
import test from "node:test";
import { createSourceChat } from "../src/source-chat.js";
import { createSourceManager } from "../src/source-manager.js";

// A small event/element fixture exercises the real controllers, including
// deferred API responses. Native pointer/layout coverage lives in packaged QA.
function dom() {
  const ids = new Map();
  function el(tag, attrs = {}, ...children) {
    const listeners = new Map();
    const node = {
      tag, ...attrs, children: children.flat().filter(value => value != null),
      value: attrs.value ?? "", textContent: "", dataset: {},
      classList: { toggle() {} },
      addEventListener(type, callback) { listeners.set(type, callback); },
      async fire(type) { await listeners.get(type)?.({ preventDefault() {}, currentTarget: node }); },
      replaceChildren(...values) { node.children = values; },
      append(...values) { node.children.push(...values); },
      prepend(...values) { node.children.unshift(...values); },
      querySelector(selector) {
        for (const child of node.children) {
          if (typeof child !== "object") continue;
          if (child.tag === selector) return child;
          const found = child.querySelector(selector);
          if (found) return found;
        }
        return null;
      },
      close() { node.open = false; },
      showModal() { node.open = true; },
      focus() {}, reset() {},
    };
    if (attrs["data-source-id"]) node.dataset.sourceId = attrs["data-source-id"];
    if (tag === "select") node.value = node.children[0]?.value || "";
    if (attrs.id) ids.set(attrs.id, node);
    if (attrs.onclick) listeners.set("click", attrs.onclick);
    return node;
  }
  return { el, ids, $: id => ids.get(id) };
}
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
const tick = () => new Promise(resolve => setImmediate(resolve));
const text = node => typeof node === "string" ? node : `${node.textContent} ${node.children.map(text).join(" ")}`;
const receipt = (id = "receipt") => ({ id, message: "AI kaynakları öner", reply: "Üç kaynak önerildi.", status: "suggestions", created_at: "2026-10-03T12:00:00Z" });

test("typing a new source request while POST runs preserves the new draft", async () => {
  const d = dom(), post = deferred();
  const ui = createSourceChat({ ...d, api: path => path.endsWith("/history") ? Promise.resolve({ items: [] }) : post.promise, onChanged: async () => {}, sourceLink: () => null });
  ui.unlock(); await tick();
  const input = d.$("kaynak-sohbet-mesaj");
  input.value = "AI kaynakları öner";
  const sending = d.$("kaynak-sohbet-form").fire("submit");
  input.value = "Lexpera kaynağını duraklat";
  post.resolve(receipt()); await sending;
  assert.equal(input.value, "Lexpera kaynağını duraklat");
  assert.match(text(d.$("kaynak-sohbet-gecmis")), /Üç kaynak önerildi/);
});

test("late history response keeps newly received action receipts", async () => {
  const d = dom(), history = deferred();
  const ui = createSourceChat({ ...d, api: path => path.endsWith("/history") ? history.promise : Promise.resolve(receipt()), onChanged: async () => {}, sourceLink: () => null });
  ui.unlock();
  d.$("kaynak-sohbet-mesaj").value = "AI kaynakları öner";
  await d.$("kaynak-sohbet-form").fire("submit");
  history.resolve({ items: [{ ...receipt("old"), message: "Önceki mesaj", created_at: "2026-10-02T12:00:00Z" }] });
  await tick();
  const rendered = text(d.$("kaynak-sohbet-gecmis"));
  assert.match(rendered, /Önceki mesaj/);
  assert.match(rendered, /AI kaynakları öner/);
  assert.equal(d.$("kaynak-sohbet-gecmis").children.length, 2);
  assert.equal(d.$("kaynak-sohbet-mesaj").value, "");
});

test("late responses cannot restore source chat after logout", async () => {
  const d = dom(), history = deferred(), post = deferred();
  let changed = 0;
  const ui = createSourceChat({ ...d, api: path => path.endsWith("/history") ? history.promise : post.promise, onChanged: async () => { changed++; }, sourceLink: () => null });
  ui.unlock();
  d.$("kaynak-sohbet-mesaj").value = "https://example.org/feed";
  const sending = d.$("kaynak-sohbet-form").fire("submit");
  ui.reset();
  post.resolve({ ...receipt(), status: "applied" });
  history.resolve({ items: [receipt()] });
  await sending; await tick();
  assert.equal(d.$("kaynak-sohbet-gecmis").children.length, 0);
  assert.equal(d.$("kaynak-sohbet-mesaj").value, "");
  assert.equal(changed, 0);
});

test("lost response retries reuse request id and successful duplicate renders once", async () => {
  const d = dom(), sent = [];
  const ui = createSourceChat({ ...d, api: async (path, options) => {
    if (path.endsWith("/history")) return { items: [] };
    sent.push(options.body);
    if (sent.length === 1) throw new Error("Bağlantı kesildi.");
    return receipt(options.body.request_id);
  }, onChanged: async () => {}, sourceLink: () => null });
  ui.unlock(); await tick();
  d.$("kaynak-sohbet-mesaj").value = "AI kaynakları öner";
  await d.$("kaynak-sohbet-form").fire("submit");
  assert.equal(d.$("kaynak-sohbet-mesaj").value, "AI kaynakları öner");
  await d.$("kaynak-sohbet-form").fire("submit");
  assert.equal(sent[0].request_id, sent[1].request_id);
  assert.equal(d.$("kaynak-sohbet-gecmis").children.length, 1);
});

test("moving the last source from the selected category leaves a usable list; logout clears filters", async t => {
  const d = dom();
  const previous = Object.getOwnPropertyDescriptor(globalThis, "document");
  Object.defineProperty(globalThis, "document", { configurable: true, value: { body: d.el("body") } });
  t.after(() => { if (previous) Object.defineProperty(globalThis, "document", previous); else delete globalThis.document; });
  for (const id of ["kaynak-yonetimi", "kaynak-liste", "kaynak-ekle-ac"]) d.el("div", { id });
  const manager = createSourceManager({ ...d, api: async () => ({}), sourceLink: () => null, date: () => "", onChange: async () => {}, onRefresh: () => {}, onFilter: () => {} });
  const source = { id: "feed", name: "Publisher", url: "https://example.org/feed", category: "turk_hukuku", kind: "rss", enabled: true };
  manager.update([source]);
  await d.$("kaynak-kategori-filter").children[1].fire("click");
  manager.update([{ ...source, category: "dunya_ai" }]);
  assert.match(text(d.$("kaynak-liste")), /Publisher/);
  assert.equal(d.$("kaynak-kategori-filter").children[0]["aria-pressed"], "true");
  d.$("kaynak-ara").value = "Bulunmayan";
  d.$("kaynak-durum-filter").value = "paused";
  manager.reset();
  manager.update([source]);
  assert.equal(d.$("kaynak-ara").value, "");
  assert.equal(d.$("kaynak-durum-filter").value, "all");
  assert.match(text(d.$("kaynak-liste")), /Publisher/);
});
