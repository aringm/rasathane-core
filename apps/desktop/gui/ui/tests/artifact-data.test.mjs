import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import {
  parseMindmapHTML,
  validateMindmapTree,
  mapLayout,
  validatePDFBytes,
  ARTIFACT_LIMIT,
} from "../src/artifact-data.js";

const tree = {
  content: "Türkçe İıĞğŞşÇç &lt;img src=x onerror=alert(1)&gt;",
  children: [{ content: 'Tırnak " ve süslü { }', children: [] }],
};
const html = (value) =>
  `<script>throw new Error('Bu script çalışmamalı');</script>\n<script>\nconst veri = ${JSON.stringify(value)};\nalert('Çalışmamalı');</script>`;
test("HTML scriptleri yorumlanmadan yalnız JSON ağacı ve Türkçe metin alınır", () => {
  const data = parseMindmapHTML(html(tree));
  assert.equal(data.content, "Türkçe İıĞğŞşÇç <img src=x onerror=alert(1)>");
  assert.equal(data.children[0].content, tree.children[0].content);
  assert.equal(mapLayout(data).rows.length, 2);
  assert.equal(mapLayout(data, new Set(["0"])).rows.length, 1);
});
test("script ifadesi, birden çok ağaç ve kırık JSON veri olarak kabul edilmez", () => {
  assert.throws(() => parseMindmapHTML("\nconst veri = alert(1);"));
  assert.throws(() => parseMindmapHTML(html(tree) + html(tree)), /belirsiz/);
  assert.throws(() =>
    parseMindmapHTML('\nconst veri = {"content":"x","children":['),
  );
  assert.throws(() =>
    validateMindmapTree({
      content: "x",
      children: [],
      src: "https://example.com/script",
    }),
  );
  assert.throws(() =>
    validateMindmapTree(
      JSON.parse('{"content":"x","children":[],"__proto__":{}}'),
    ),
  );
});
test("boyut, derinlik ve düğüm limitleri pahalı artifact'i durdurur", () => {
  assert.throws(
    () => parseMindmapHTML(" ".repeat(ARTIFACT_LIMIT + 1)),
    /boyut/,
  );
  assert.throws(
    () => validateMindmapTree({ content: "x".repeat(4001), children: [] }),
    /metin/,
  );
  assert.throws(
    () =>
      validateMindmapTree({
        content: "x",
        children: Array.from({ length: 1000 }, () => ({
          content: "x",
          children: [],
        })),
      }),
    /düğüm sınırı/,
  );
  let deep = { content: "x", children: [] };
  for (let index = 0; index < 25; index++)
    deep = { content: "x", children: [deep] };
  assert.throws(() => validateMindmapTree(deep), /düğüm sınırı/);
});
test("PDF byte sözleşmesi HTML ve büyük yanıtları reddeder", () => {
  assert.throws(() =>
    validatePDFBytes(new TextEncoder().encode("<script>alert(1)</script>")),
  );
  assert.throws(() => validatePDFBytes(new Uint8Array(ARTIFACT_LIMIT + 1)));
  assert.equal(
    validatePDFBytes(new TextEncoder().encode("%PDF-1.7\nfixture")).length,
    16,
  );
});
test("renderer artifact HTML yürütmez; iframe/CSP izinleri genişlemez", () => {
  const ui = new URL("../", import.meta.url);
  const shell = fs.readFileSync(new URL("index.html", ui), "utf8");
  const renderer = fs.readFileSync(new URL("src/artifacts.js", ui), "utf8");
  assert.equal(/<iframe\b/.test(shell), false);
  assert.match(shell, /script-src 'self';/);
  assert.equal(
    /innerHTML|srcdoc|eval\(|new Function|document\.write/.test(renderer),
    false,
  );
  assert.match(renderer, /isEvalSupported: false/);
  assert.match(renderer, /useWasm: false/);
  assert.match(renderer, /AnnotationMode\.DISABLE/);
  assert.match(
    renderer,
    /new Worker\(\s*new URL\("\.\.\/lib\/pdfjs\/build\/pdf.worker.mjs"/,
  );
  assert.equal(
    fs.existsSync(new URL("lib/pdfjs/wasm/quickjs-eval.wasm", ui)),
    false,
  );
});
