import assert from "node:assert/strict";
import test from "node:test";
import { createResearchChat } from "../src/research-chat.js";

// Run the real conversation controller with only the supported screen controls.
// Unknown IDs fail so an accidentally retained workspace selector fails the flow.
function fixture(t) {
  const previousDocument = globalThis.document;
  globalThis.document = { addEventListener() {}, activeElement: null };
  t.after(() => { globalThis.document = previousDocument; });
  function el(tag, attrs = {}, ...children) {
    const events = new Map();
    const node = {
      tag, ...attrs, value: "", textContent: "", style: {}, hidden: true,
      checked: false, children: children.flat().filter(item => item != null),
      scrollTop: 0, scrollHeight: 60,
      addEventListener(type, handler) { events.set(type, handler); },
      async fire(type) { await events.get(type)?.({ preventDefault() {}, target: node }); },
      setAttribute(key, value) { node[key] = value; },
      append(...values) { node.children.push(...values); },
      replaceChildren(...values) { node.children = values; },
      querySelectorAll(selector) {
        return node.children.filter(child => typeof child === "object").flatMap(child => [
          ...(child.tag === selector ? [child] : []), ...child.querySelectorAll(selector),
        ]);
      },
      contains(target) { return node === target || node.children.some(child => typeof child === "object" && child.contains(target)); },
      focus() { globalThis.document.activeElement = node; },
    };
    if (attrs.onclick) events.set("click", attrs.onclick);
    return node;
  }
  const ids = ["arastir-sonuc", "arastir-durum", "arastir-sorgu", "arastir-form", "arastir-gecmis", "arastir-gecmis-panel", "arastir-gecmis-ac", "arastir-gecmis-ara", "arastir-baslik", "arastir-btn", "arastir-yeni", "arastir-web"];
  const nodes = new Map(ids.map(id => [id, el("div", { id })]));
  const $ = id => { assert.ok(nodes.has(id), `Retired or unknown control requested: ${id}`); return nodes.get(id); };
  const requests = [];
  const api = async (path, options = {}) => {
    requests.push({ path, ...options });
    if (path === "/research") return { id: "job", request: { conversation_id: "conversation" } };
    if (path === "/conversations/conversation") return {
      id: "conversation", title: "Hukuk", workspace_id: "legacy-workspace", messages: [
        { role: "assistant", content: "Kaynağa dayalı yanıt", result: { citations: [{ title: "Haber", url: "https://example.com", quote: "Kaynak metni" }] } },
      ],
    };
    if (path === "/conversations") return { items: [{ id: "conversation", title: "Hukuk" }] };
    throw new Error(`Unexpected path: ${path}`);
  };
  const chat = createResearchChat({ $, el, api, waitJob: async () => ({ conversation_id: "conversation" }), sourceLink: (url, label) => el("a", { href: url }, label) });
  return { $, chat, requests };
}

test("research opens an existing scoped conversation and continues without retired workspace controls or payload", async t => {
  const f = fixture(t);
  await f.chat.open("conversation");
  f.$("arastir-sorgu").value = "Yeni mevzuat nedir?";
  f.$("arastir-web").checked = true;
  await f.$("arastir-form").fire("submit");
  const submitted = f.requests.find(item => item.path === "/research").body;
  assert.deepEqual(submitted, { query: "Yeni mevzuat nedir?", web: true, conversation_id: "conversation" });
  assert.equal(f.$("arastir-btn").disabled, false);
  assert.equal(f.$("arastir-sonuc").children[0].class, "chat-message chat-assistant");
});

test("new research conversation searches records without requiring a workspace and resets safely", async t => {
  const f = fixture(t);
  f.$("arastir-sorgu").value = "Yerel model haberleri";
  await f.$("arastir-form").fire("submit");
  assert.deepEqual(f.requests.find(item => item.path === "/research").body, { query: "Yerel model haberleri", web: false });
  await f.$("arastir-yeni").fire("click");
  assert.equal(f.$("arastir-baslik").textContent, "Yeni konuşma");
  assert.equal(f.$("arastir-sorgu").value, "");
  assert.equal(f.$("arastir-durum").textContent, "Yeni konuşma. Sorunuzu yazın.");
  f.chat.reset();
});
