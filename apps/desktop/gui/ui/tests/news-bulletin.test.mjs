import test from "node:test";
import assert from "node:assert/strict";
import { bulletinCandidates } from "../src/news-bulletin.js";

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
