import assert from "node:assert/strict";
import test from "node:test";
import { createNewsSummary } from "../src/news-summary.js";
import { articlePreview } from "../src/radar-feed.js";

function dom() {
  function el(tag, attrs = {}, ...children) {
    const events = new Map();
    const node = { tag, ...attrs, children: children.flat().filter(item => item != null), textContent: "", disabled: !!attrs.disabled,
      append(...items) { node.children.push(...items); }, replaceChildren(...items) { node.children = items.filter(item => item != null); },
      addEventListener(type, handler) { events.set(type, handler); }, async fire(type) { await events.get(type)?.({ preventDefault() {} }); },
      removeAttribute(name) { delete node[name]; }, pause() { node.paused = true; }, load() {}, async play() { node.played = true; },
      queryAll(tag) { return node.children.filter(item => typeof item === "object").flatMap(item => [...(item.tag === tag ? [item] : []), ...item.queryAll(tag)]); },
    };
    return node;
  }
  return { el };
}
function fixture(t, options = {}) {
  const d = dom(); const calls = [];
  const originalCreate = URL.createObjectURL, originalRevoke = URL.revokeObjectURL;
  URL.createObjectURL = () => "blob:voice-fixture"; URL.revokeObjectURL = () => {};
  t.after(() => { URL.createObjectURL = originalCreate; URL.revokeObjectURL = originalRevoke; });
  const controller = createNewsSummary({ ...d, pause: async () => {},
    api: async path => { calls.push(path); return { status: "ready", language: "tr", summary: "Türkçe haber özeti" }; },
    request: async path => { calls.push(path); return new Response(new Blob(["wav"]), { status: 200 }); }, ...options });
  let analyses = 0;
  const node = controller.control({ id: "news", url: "https://example.com/article" }, { source: d.el("a", { href: "https://example.com/article" }, "Kaynağı aç"), onAnalyze: async () => { analyses++; } });
  t.after(() => controller.stopAll());
  const actionRow = node.children[0], output = node.children[1];
  return { controller, node, actionRow, output, calls, analyses: () => analyses };
}

test("feed card shows four direct actions and one speech click prepares, speaks and plays without another button", async t => {
  const f = fixture(t);
  assert.deepEqual(f.actionRow.children.map(node => node.children[0]), ["Kaynağı aç", "Özetle", "Seslendir", "Derinlemesine analiz et"]);
  await f.actionRow.children[2].fire("click");
  assert.deepEqual(f.calls, ["/articles/news/summary", "/api/rasathane/articles/news/speech"]);
  assert.equal(f.output.queryAll("audio")[0].played, true);
  assert.equal(f.output.queryAll("button").length, 0);
  assert.equal(f.actionRow.children.length, 4);
  await f.actionRow.children[3].fire("click"); assert.equal(f.analyses(), 1);
});
test("a queued summary is read back before voice generation and never speaks an empty pending result", async t => {
  const calls = []; let summaries = 0;
  const f = fixture(t, { api: async path => {
    calls.push(path);
    if (path.startsWith("/jobs/")) return { status: "completed" };
    return ++summaries === 1 ? { status: "pending", job_id: "queued-summary", summary: "" } : { status: "ready", language: "tr", summary: "Hazır Türkçe özet" };
  } });
  await f.actionRow.children[2].fire("click");
  assert.deepEqual(calls, ["/articles/news/summary", "/jobs/queued-summary", "/articles/news/summary"]);
  assert.deepEqual(f.calls, ["/api/rasathane/articles/news/speech"]);
});
test("non-Turkish ready summary cannot be presented or spoken as Turkish", async t => {
  const f = fixture(t, { api: async () => ({ status: "ready", language: "en", summary: "English text" }) });
  await f.actionRow.children[2].fire("click");
  assert.equal(f.calls.length, 0);
  assert.match(f.output.children[2].textContent, /Türkçe özet doğrulanamadı/);
});
test("metadata without text leaves four fixed actions and displays the unavailable notice without adding speech controls", async t => {
  const f = fixture(t, { api: async () => ({ status: "unavailable", language: "tr", summary: null, notice: "Karar künyesi; tam metin yok." }) });
  await f.actionRow.children[1].fire("click");
  assert.equal(f.actionRow.children[2].disabled, true);
  assert.equal(f.actionRow.children.length, 4);
  assert.equal(f.output.queryAll("button").length, 0);
});
test("raw HN boilerplate and untranslated feed body never leak into the readable news preview", () => {
  const item = { summary: "Article URL: https://example.com/article Comments URL: https://news.ycombinator.com/item?id=1 Points: 100 # Comments: 50" };
  assert.equal(articlePreview(item).includes("Article URL"), false);
  assert.equal(articlePreview({ summary: "An untranslated English paragraph" }).includes("English"), false);
  assert.equal(articlePreview({ ...item, summary_display: { status: "ready", language: "tr", summary: "Yeni model yerel cihazlarda çalışıyor." } }), "Yeni model yerel cihazlarda çalışıyor.");
  assert.match(articlePreview({ ...item, summary_display: { status: "pending", job_id: "running" } }), /hazırlanıyor/);
});

test("logout during queued summary prevents a late private response and speech call from returning", async t => {
  let release; let signal;
  const pending = new Promise(resolve => { release = resolve; });
  const started = new Promise(resolve => { signal = resolve; });
  const f = fixture(t, { api: async () => { signal(); return pending; } });
  const speaking = f.actionRow.children[2].fire("click");
  await started; f.controller.stopAll();
  release({ status: "ready", language: "tr", summary: "Eski oturumun özel haberi" });
  await speaking;
  assert.equal(f.calls.length, 0);
  assert.equal(f.output.children[0].children.length, 0);
});

test("a digest that applies the returned summary inline avoids a duplicate text panel", async t => {
  const d = dom();
  const controller = createNewsSummary({ ...d, api: async () => ({ status: "ready", language: "tr", summary: "Türkçe içerik" }), request: async () => {} });
  t.after(() => controller.stopAll());
  let applied = null;
  const node = controller.control({ id: "digest" }, { onSummary: summary => { applied = summary.summary; return true; } });
  await node.children[0].children[1].fire("click");
  assert.equal(applied, "Türkçe içerik");
  assert.equal(node.children[1].children[0].hidden, true);
  assert.equal(node.children[1].hidden, true);
  assert.equal(node.children[0].children.length, 4);
});
