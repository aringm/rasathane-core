import assert from "node:assert/strict";
import test from "node:test";
import {
  ensureExamples,
  workspaceExamples,
} from "../src/workspace-examples.js";

function database() {
  const rows = { workspaces: [], notes: [], topics: [] };
  let failure = false;
  let next = 0;
  const calls = [];
  const api = async (path, options = {}) => {
    calls.push({ path, method: options.method || "GET" });
    const url = new URL(path, "http://localhost");
    const table = url.pathname.slice(1);
    assert.ok(Object.hasOwn(rows, table), "Only local collection APIs allowed");
    if (options.method !== "POST") {
      return {
        items: rows[table].filter(
          (item) =>
            table !== "notes" ||
            item.workspace_id === url.searchParams.get("workspace_id"),
        ),
      };
    }
    const item = { id: String(++next), ...options.body };
    rows[table].push(item);
    if (failure && table === "notes") {
      failure = false;
      throw new Error("Response lost after commit");
    }
    return item;
  };
  return { rows, calls, api, failOnce: () => (failure = true) };
}

test("example setup is additive and repeated/concurrent calls do not duplicate", async () => {
  const db = database();
  db.rows.workspaces.push({ id: "user", name: "Kullanıcının alanı" });
  const [one, concurrent] = await Promise.all([
    ensureExamples(db.api),
    ensureExamples(db.api),
  ]);
  assert.equal(one, concurrent);
  assert.deepEqual(one.created, { workspaces: 2, notes: 2, topics: 2 });
  const second = await ensureExamples(db.api);
  assert.deepEqual(second.created, { workspaces: 0, notes: 0, topics: 0 });
  assert.deepEqual(second.reused, { workspaces: 2, notes: 2, topics: 2 });
  assert.equal(db.rows.workspaces.length, 3);
  assert.equal(db.rows.workspaces[0].name, "Kullanıcının alanı");
  assert.ok(db.calls.every(({ path }) => !path.includes("refresh")));
});

test("retry discovers a partial commit even if its response was lost", async () => {
  const db = database();
  db.failOnce();
  await assert.rejects(ensureExamples(db.api), /yeniden deneyin/);
  assert.equal(db.rows.notes.length, 1);
  await ensureExamples(db.api);
  assert.equal(db.rows.workspaces.length, 2);
  assert.equal(db.rows.notes.length, 2);
  assert.equal(db.rows.topics.length, 2);
});

test("matching names do not overwrite customized notes or different topic queries", async () => {
  const db = database();
  const example = workspaceExamples[0];
  db.rows.workspaces.push({ id: "existing", name: example.name });
  db.rows.notes.push({
    id: "custom-note",
    workspace_id: "existing",
    title: example.note.title,
    body: "Kullanıcının düzenlediği içerik",
  });
  db.rows.topics.push({
    id: "custom-topic",
    name: example.topic.name,
    query: "Farklı takip sorgusu",
  });
  const result = await ensureExamples(db.api);
  assert.equal(result.reused.workspaces, 1);
  assert.equal(result.reused.notes, 1);
  assert.equal(db.rows.notes[0].body, "Kullanıcının düzenlediği içerik");
  assert.equal(db.rows.topics[0].query, "Farklı takip sorgusu");
  assert.equal(db.rows.topics.length, 3);
});
