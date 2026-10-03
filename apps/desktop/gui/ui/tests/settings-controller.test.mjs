import assert from "node:assert/strict";
import test from "node:test";
import { createSettingsDraft } from "../src/settings-controller.js";

const defaults = { theme: "system", analysis_profile: "ram8", search_provider: "auto", web_enabled: true };
function fixture() {
  let value = { ...defaults };
  let state;
  const draft = createSettingsDraft({ read: () => value, write: (next) => { value = { ...next }; }, onState: (next) => { state = next; } });
  draft.receive(defaults);
  return { draft, edit: (change) => { Object.assign(value, change); draft.changed(); }, value: () => value, state: () => state };
}
test("background refresh preserves unsaved settings and reset uses latest persisted state", () => {
  const f = fixture();
  f.edit({ theme: "dark" });
  f.draft.receive({ ...defaults, search_provider: "duckduckgo" });
  assert.equal(f.value().theme, "dark");
  assert.equal(f.state().dirty, true);
  f.draft.reset();
  assert.equal(f.value().theme, "system");
  assert.equal(f.value().search_provider, "duckduckgo");
  assert.equal(f.state().dirty, false);
});
test("save verifies returned settings and preserves draft on mismatched response", () => {
  const f = fixture();
  f.edit({ web_enabled: false });
  assert.throws(() => f.draft.saved(defaults, f.draft.read()), /doğrulanamadı/);
  assert.equal(f.value().web_enabled, false);
  assert.equal(f.draft.hasChanges(), true);
  const submitted = f.draft.read();
  f.draft.saved(submitted, submitted);
  assert.equal(f.draft.hasChanges(), false);
});
test("edits made during save remain unsaved after response and subsequent reload", () => {
  const f = fixture();
  f.edit({ theme: "dark" });
  const submitted = f.draft.read();
  f.edit({ theme: "light" });
  f.draft.saved(submitted, submitted);
  f.draft.receive(submitted);
  assert.equal(f.value().theme, "light");
  assert.equal(f.draft.hasChanges(), true);
});
test("clean forms accept background updates without becoming dirty", () => {
  const f = fixture();
  f.draft.receive({ ...defaults, theme: "light" });
  assert.equal(f.value().theme, "light");
  assert.equal(f.state().dirty, false);
});
