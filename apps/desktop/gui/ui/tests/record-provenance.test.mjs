import assert from "node:assert/strict";
import test from "node:test";
import { recordDate } from "../src/record-provenance.js";

test("karar tarihi null published_at ve yeni edinim zamanından bağımsızdır", () => {
  const shown = recordDate(
    {
      published_at: null,
      source_id: "public-yargitay",
      created_at: "2026-10-03T18:00:00Z",
      provenance: { decision_date: "2026-09-01", date_kind: "decision" },
    },
    "yargitay_public",
  );
  assert.deepEqual(shown, {
    label: "Karar tarihi: ",
    value: "2026-09-01",
    dayOnly: true,
  });
});

test("yayım kaydı olmayan karar için yeni edinim karartarihi sayılmaz", () => {
  const shown = recordDate(
    {
      published_at: null,
      source_id: "managed",
      created_at: "2026-10-03T18:00:00Z",
      provenance: {
        date_kind: "unknown",
        source_fetched_at: "2026-10-02T12:00:00Z",
      },
    },
    "yargitay",
  );
  assert.equal(shown.label, "Edinim zamanı: ");
  assert.equal(shown.value, "2026-10-02T12:00:00Z");
  assert.equal(shown.dayOnly, false);
});

test("legacy upstream tarihi yayım tarihi diye sunulmaz", () => {
  const shown = recordDate(
    {
      published_at: "2026-09-01",
      provenance: {
        date_kind: "unknown",
        date_semantics: "upstream_date_unverified",
      },
    },
    "yargitay",
  );
  assert.equal(shown.label, "Kaynak tarih kaydı: ");
});

test("Resmî Gazete düzenlemesinin yayım tarihi kayıt zamanıyla değişmez", () => {
  const shown = recordDate(
    { published_at: "2026-10-01", created_at: "2026-10-03" },
    "resmi_gazete",
  );
  assert.equal(shown.label, "Yayım tarihi: ");
  assert.equal(shown.value, "2026-10-01");
});

test("çalışma alanı notunun kayıt zamanı edinim diye etiketlenmez", () => {
  assert.deepEqual(recordDate({ created_at: "2026-10-03T12:00:00Z" }), {
    label: "Kayıt tarihi: ",
    value: "2026-10-03T12:00:00Z",
    dayOnly: false,
  });
});
