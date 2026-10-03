"use strict";

// Yalnız kurulmuş, exact pinned registry paketinden yerel renderer dosyaları üretir.
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const root = path.resolve(__dirname, "..");
const version = "6.3.289";
const integrity =
  "sha512-ZHjSVpDa3D6izMq8/04lvkhkATUmL9px6ChPaXc1k6nU2Mrhlg1/7F0bdUqCwUjw3NsPTfPZsMDUU6ZIcRaeQw==";
const target = path.join(root, "ui", "lib", "pdfjs");
const digest = (bytes) =>
  crypto.createHash("sha256").update(bytes).digest("hex");
const referenceBytes = fs.readFileSync(
  path.join(__dirname, "pdfjs-6.3.289-source.json"),
);
if (
  digest(referenceBytes) !==
  "3e5f71a991c2f33aaf3031a4fe27b8cafef171aa5a60415e03c12e5edb553761"
)
  throw new Error("PDF.js resmî archive checksum referansı değişti.");
const reference = JSON.parse(referenceBytes);
if (reference.version !== version || reference.integrity !== integrity)
  throw new Error("PDF.js archive pin uyuşmazlığı.");
const upstream = new Map(reference.files.map((item) => [item.path, item]));
function verifyUpstream(name, bytes) {
  if (name === "README.md") return;
  const expected = upstream.get(name);
  if (
    !expected ||
    expected.bytes !== bytes.length ||
    expected.sha256 !== digest(bytes)
  )
    throw new Error(`PDF.js resmî kaynak uyuşmazlığı: ${name}`);
}
function files(directory, prefix = "") {
  return fs
    .readdirSync(directory, { withFileTypes: true })
    .flatMap((item) => {
      const name = prefix + item.name;
      if (item.isSymbolicLink())
        throw new Error(`Symlink izinli değil: ${name}`);
      return item.isDirectory()
        ? files(path.join(directory, item.name), name + "/")
        : [name];
    })
    .sort();
}
const manifestPath = path.join(target, "VENDOR-MANIFEST.json");
if (process.argv.includes("--check")) {
  const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
  if (manifest.version !== version || manifest.integrity !== integrity)
    throw new Error("PDF.js kaynak pin uyuşmazlığı.");
  const actual = files(target).filter(
    (name) => name !== "VENDOR-MANIFEST.json",
  );
  if (
    JSON.stringify(actual) !==
    JSON.stringify(manifest.files.map((item) => item.path).sort())
  )
    throw new Error("PDF.js dosya kapsamı değişti.");
  for (const item of manifest.files) {
    const bytes = fs.readFileSync(path.join(target, item.path));
    verifyUpstream(item.path, bytes);
    if (bytes.length !== item.bytes || digest(bytes) !== item.sha256)
      throw new Error(`PDF.js checksum uyuşmazlığı: ${item.path}`);
  }
  console.log(
    `PDF.js ${version}: ${actual.length} yerel dosya checksum ile doğrulandı.`,
  );
} else {
  const source = path.join(root, "node_modules", "pdfjs-dist");
  const pkg = JSON.parse(
    fs.readFileSync(path.join(source, "package.json"), "utf8"),
  );
  if (pkg.version !== version)
    throw new Error(
      "Önce pnpm install --frozen-lockfile çalıştırın; PDF.js sürümü uyuşmuyor.",
    );
  if (
    !fs
      .readFileSync(path.join(root, "pnpm-lock.yaml"), "utf8")
      .includes(integrity)
  )
    throw new Error("Registry integrity lockfile'da bulunamadı.");
  const selected = [
    "LICENSE",
    "build/pdf.mjs",
    "build/pdf.worker.mjs",
    ...["cmaps", "standard_fonts", "wasm", "iccs"].flatMap((dir) =>
      files(path.join(source, dir), dir + "/"),
    ),
  ].filter((name) => !name.startsWith("wasm/quickjs-eval."));
  fs.mkdirSync(target, { recursive: true });
  for (const name of selected) {
    verifyUpstream(name, fs.readFileSync(path.join(source, name)));
    const dest = path.join(target, name);
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    fs.copyFileSync(path.join(source, name), dest);
  }
  fs.writeFileSync(
    path.join(target, "README.md"),
    `# Yerel PDF.js\n\nMozilla PDF.js / pdfjs-dist ${version}, Apache-2.0.\n\nKaynak: https://github.com/mozilla/pdf.js\nRegistry: https://registry.npmjs.org/pdfjs-dist/-/pdfjs-dist-${version}.tgz\n\nPin: ${integrity}\n\nYeniden üretim: GUI kökünde pnpm install --frozen-lockfile ve pnpm vendor:pdf. Doğrulama: pnpm check:pdf. LICENSE ve font/codec lisansları bu klasörle dağıtılır. Renderer CDN kullanmaz; PDF byte'ları mevcut dar IPC üzerinden alınır.\n`,
    "utf8",
  );
  const manifest = {
    package: "pdfjs-dist",
    version,
    integrity,
    source: `https://registry.npmjs.org/pdfjs-dist/-/pdfjs-dist-${version}.tgz`,
    files: files(target)
      .filter((name) => name !== "VENDOR-MANIFEST.json")
      .map((name) => {
        const bytes = fs.readFileSync(path.join(target, name));
        return { path: name, bytes: bytes.length, sha256: digest(bytes) };
      }),
  };
  fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2) + "\n");
  console.log(
    `PDF.js ${version}: ${manifest.files.length} yerel dosya kopyalandı.`,
  );
}
