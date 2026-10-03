"use strict";
const test = require("node:test"), assert = require("node:assert/strict");
const fs = require("node:fs"), os = require("node:os"), path = require("node:path");
const { resolveOutputDirectory } = require("./output-directory.cjs");

function setup(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "rasathane-output-test-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const locations = { documents: path.join(root, "Documents"), desktop: path.join(root, "Desktop"), userData: path.join(root, "AppData") };
  for (const folder of Object.values(locations)) fs.mkdirSync(folder);
  return locations;
}
function populated(folder) { fs.mkdirSync(folder, { recursive: true }); fs.writeFileSync(path.join(folder, "saved.txt"), "saved"); }
test("new output uses Documents/Rasathane and never the Desktop source checkout", t => {
  const locations = setup(t);
  populated(path.join(locations.desktop, "Rasathane"));
  fs.mkdirSync(path.join(locations.desktop, "Rasathane", ".git"));
  assert.equal(resolveOutputDirectory(locations), path.join(locations.documents, "Rasathane"));
});
test("existing Electron output is retained until an explicit migration", t => {
  const locations = setup(t), old = path.join(locations.userData, "workspace");
  populated(old);
  assert.equal(resolveOutputDirectory(locations), old);
});
test("migrated output takes priority while old artifact archives remain intact", t => {
  const locations = setup(t), target = path.join(locations.documents, "Rasathane");
  populated(target); populated(path.join(locations.userData, "workspace"));
  assert.equal(resolveOutputDirectory(locations), target);
});
test("legacy Gözlemevi output remains visible before migration", t => {
  const locations = setup(t), old = path.join(locations.desktop, "Rasathane  Gözlemevi");
  populated(old);
  assert.equal(resolveOutputDirectory(locations), old);
});
test("a repository in the default destination is rejected", t => {
  const locations = setup(t), target = path.join(locations.documents, "Rasathane");
  populated(target); fs.mkdirSync(path.join(target, ".git"));
  assert.throws(() => resolveOutputDirectory(locations), /kaynak repo/);
});
test("explicit user output selection is preserved", t => {
  const locations = setup(t), configured = path.join(locations.documents, "Selected output");
  assert.equal(resolveOutputDirectory({ ...locations, configured }), configured);
});
