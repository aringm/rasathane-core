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
