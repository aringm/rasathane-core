import test from "node:test";
import assert from "node:assert/strict";
import { bulletinCandidates, bulletinSourceGroups, recentBulletins } from "../src/news-bulletin.js";

test("bülten tarih filtresi eski ve gelecekteki yayınları dışarıda bırakır, tarihi olmayanı güncel saymaz", () => {
  const now = Date.parse("2026-10-03T12:00:00Z");
  const items = [
    { id: "old", published_at: "2020-01-01", created_at: "2026-10-03" },
    { id: "new", published_at: "2026-10-03T10:00:00Z" },
    { id: "unknown" },
    { id: "future", published_at: "2030-01-01" },
    { id: "fetched", fetched_at: "2026-10-03T11:00:00Z" },
  ];
  assert.deepEqual(bulletinCandidates(items, 1, 10, now).map(x => x.id), ["new", "fetched"]);
  assert.deepEqual(bulletinCandidates(items, 0, 2, now).map(x => x.id), ["old", "new"]);
});

test("bülten kaynak eki tüm kayıtları adlarına göre kayıpsız gruplar", () => {
  const items = [
    { title: "Bir", source_name: "Resmî Gazete", url: "https://example.com/1" },
    { title: "İki", source_name: "Hukuk", url: "https://example.com/2" },
    { title: "Üç", source_name: "Resmî Gazete", url: "https://example.com/3" },
    { title: "Dört", url: "https://example.com/4" },
  ];
  assert.deepEqual(bulletinSourceGroups(items).map(({ name, entries }) => [name, entries.map((entry) => entry.title)]), [
    ["Resmî Gazete", ["Bir", "Üç"]], ["Hukuk", ["İki"]], ["Diğer kaynaklar", ["Dört"]],
  ]);
});

test("ilk açılış için en son bülten seçilir; API dizisi değiştirilmez", () => {
  const items = [
    { id: "eski", created_at: "2026-10-01T12:00:00Z" },
    { id: "tarihsiz" },
    { id: "yeni", created_at: "2026-10-03T12:00:00Z" },
  ];
  assert.deepEqual(recentBulletins(items).map((item) => item.id), ["yeni", "eski", "tarihsiz"]);
  assert.equal(items[0].id, "eski");
});

import { createNewsBulletin } from "../src/news-bulletin.js";
function bulletinDOM() {
  const ids = new Map();
  function el(tag, attrs = {}, ...children) {
    const events = new Map(), classes = new Set((attrs.class || "").split(" ")); let value = String(attrs.value ?? "");
    const node = { tag, ...attrs, children: children.flat(Infinity).filter(item => item != null), textContent: "", hidden: !!attrs.hidden,
      get value() { return value; }, set value(next) { value = String(next); },
      classList: { toggle(name, enabled) { enabled ? classes.add(name) : classes.delete(name); }, contains(name) { return classes.has(name); } },
      append(...items) { node.children.push(...items); }, replaceChildren(...items) { node.children = items.flat(Infinity).filter(item => item != null); },
      setAttribute(name, val) { node[name] = val; }, removeAttribute(name) { delete node[name]; },
      addEventListener(type, fn) { events.set(type, fn); }, async fire(type) { await events.get(type)?.({ preventDefault() {} }); },
      pause() {}, load() {}, async play() {},
      querySelectorAll(selector) {
        const all = node.children.filter(item => typeof item === "object").flatMap(item => [item, ...item.querySelectorAll("*")]);
        if (selector === "*") return all;
        if (selector === ".bulletin-items > li") return all.filter(item => item.classList.contains("bulletin-items")).flatMap(item => item.children.filter(child => child?.tag === "li"));
        return all.filter(item => selector.startsWith(".") ? item.classList.contains(selector.slice(1)) : item.tag === selector);
      },
    };
    if (attrs.id) ids.set(attrs.id, node);
    if (attrs.onclick) events.set("click", attrs.onclick);
    if (tag === "select") node.value = node.children[0]?.value ?? "";
    return node;
  }
  return { el, $: id => ids.get(id) };
}
test("personal digest starts as one readable story, keeps four direct actions and collapses evaluation details", async () => {
  const d = bulletinDOM(), controlled = [];
  const bulletin = createNewsBulletin({ ...d, api: async () => ({ items: [] }), request: async () => {},
    sourceLink: (url, label) => d.el("a", { href: url }, label),
    articleControls: item => { controlled.push(item.article_id); return d.el("div", { class: "news-actions" }, d.el("a", { href: item.url }, "Kaynağı aç"), ...["Özetle", "Seslendir", "Derinlemesine analiz et"].map(label => d.el("button", {}, label))); },
  });
  const items = [1, 2, 3].map(number => ({ article_id: `a${number}`, url: `https://example.com/${number}`, title: `Haber ${number}`, summary: "Okunabilir Türkçe haber özeti.", source_name: "Kaynak", relevance_reason: "Projenizle ilgili.", project_impact: "Araştırma planını etkiler.", suggested_action: "Kaynağı inceleyin." }));
  bulletin.showBulletin({ id: "personal", agenda: true, article_count: 3, title: "Kişisel gündem", notice: "Yerel model değerlendirmesi eksik.", created_at: "2026-10-04", items }, false);
  assert.deepEqual(controlled, ["a1", "a2", "a3"]);
  assert.equal(d.$("bulten-heading").textContent, "Gündem");
  const rows = d.$("bulten-sonuc").querySelectorAll(".bulletin-items > li");
  assert.equal(rows.filter(row => !row.hidden).length, 1);
  for (const row of rows) {
    assert.equal(row.querySelectorAll("a").length, 1);
    assert.equal(row.querySelectorAll("button").length, 3);
    assert.equal(row.querySelectorAll(".agenda-evaluation")[0].tag, "details");
    assert.notEqual(row.querySelectorAll(".agenda-evaluation")[0].open, true);
  }
  assert.equal(d.$("bulten-sonuc").querySelectorAll(".bulletin-notice")[0].tag, "details");
  await d.$("bulten-oku").fire("click");
  assert.equal(rows.filter(row => !row.hidden).length, 3);
  assert.equal(d.$("bulten-oku").textContent, "Okuma görünümünü daralt");
  await d.$("bulten-oku").fire("click"); assert.equal(rows.filter(row => !row.hidden).length, 1);
  bulletin.reset();
});

test("digest summary readback replaces the visible Turkish headline and body without rewriting the archived snapshot", () => {
  const d = bulletinDOM(), callbacks = new Map();
  const bulletin = createNewsBulletin({ ...d, api: async () => ({ items: [] }), request: async () => {},
    sourceLink: (url, label) => d.el("a", { href: url }, label),
    articleControls: (item, onSummary) => { callbacks.set(item.article_id, onSummary); return d.el("div", { class: "news-actions" }); },
  });
  const item = { article_id: "saved", title: "Eski başlık", summary: "Türkçe özet henüz hazırlanmadı.", url: "https://example.com/article" };
  const snapshot = { id: "history", article_count: 1, title: "Bülten", created_at: "2026-10-04", items: [item] };
  const archived = JSON.stringify(snapshot);
  bulletin.showBulletin(snapshot, false);
  const onSummary = callbacks.get("saved"), row = d.$("bulten-sonuc").querySelectorAll(".bulletin-items > li")[0];
  assert.equal(onSummary({ status: "ready", language: "en", title: "English", summary: "English body" }), false);
  assert.equal(onSummary({ status: "pending", language: "tr", summary: "" }), false);
  assert.equal(onSummary({ status: "ready", language: "tr", title: "Türkçe haber başlığı", summary: "Güncellenmiş Türkçe haber özeti.", notice: "Yerel modelden." }), true);
  assert.equal(row.children[1].textContent, "Türkçe haber başlığı");
  assert.equal(row.children[2].textContent, "Güncellenmiş Türkçe haber özeti.");
  assert.equal(row.classList.contains("bulletin-summary-expanded"), true);
  assert.equal(JSON.stringify(snapshot), archived);
  bulletin.reset();
  assert.equal(onSummary({ status: "ready", language: "tr", summary: "Çıkış sonrası gecikmiş yanıt." }), false);
});
