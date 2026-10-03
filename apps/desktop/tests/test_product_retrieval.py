"""Sentetik TR-FTS-v1: sürümlü kaynaklar, raw Unicode baseline ve bilinen sınır.

Bu küçük test corpus'u yalnız yazım/lexical retrieval regresyonunu ölçer. Sonuç
gerçek karar corpus'unun veya bir embedding modelinin kalite puanı değildir.
"""

from __future__ import annotations

import re

from rasathane.product.store import ProductStore

CORPUS_VERSION = "tr-fts-v1-2026-10-03"
CORPUS = [
    ("iscilik", "İşçilik alacağı", "Kıdem tazminatı ve işçilik alacağı araştırması."),
    ("kira", "Kiracı tahliyesi", "Kira sözleşmesi ve kiracı tahliyesi koşulları."),
    ("kisilik", "Kişilik hakkı", "Kişilik hakkı ve kişisel veri koruması."),
    ("sure", "Çalışma süresi", "Çalışma süresi ve fazla çalışma hesaplaması."),
    ("fesih", "Haklı fesih", "Onur kırıcı davranış haklı fesih nedeni olabilir."),
]
CASES = [
    ("exact", "İşçilik alacağı", "iscilik"),
    ("ascii", "iscilik alacagi", "iscilik"),
    ("capital-dotless", "KIDEM TAZMINATI", "iscilik"),
    ("distractor", "kiracı tahliyesi", "kira"),
    ("ascii-dotless", "kisilik hakki", "kisilik"),
    ("capital-tr", "ÇALIŞMA SÜRESİ", "sure"),
    ("semantic-limit", "işverenin aşağılayıcı tutumu", "fesih"),
    ("no-answer", "veraset ilamı uzay aracı", None),
]


def test_versioned_turkish_retrieval_vs_raw_unicode_baseline(tmp_path, record_property):
    store = ProductStore(tmp_path)
    workspace = store.create_workspace("Sentetik değerlendirme")
    ids = {}
    with store.connection() as conn:
        conn.execute("CREATE VIRTUAL TABLE baseline USING fts5(id UNINDEXED,title,body)")
        conn.executemany("INSERT INTO baseline VALUES(?,?,?)", CORPUS)
    for key, title, evidence in CORPUS:
        note = store.save_note(workspace["id"], title, evidence)
        ids[note["id"]] = key
    before, after = [], []
    for case_id, query, expected in CASES:
        tokens = re.findall(r"\w+", query)
        expression = " AND ".join('"' + token + '"*' for token in tokens)
        with store.connection() as conn:
            baseline = [
                row[0]
                for row in conn.execute(
                    "SELECT id FROM baseline WHERE baseline MATCH ? "
                    "ORDER BY bm25(baseline) LIMIT 5",
                    (expression,),
                )
            ]
        actual = [ids[row["id"]] for row in store.search(query, workspace["id"], 5)]
        if expected is None:
            assert baseline == actual == [], case_id
            continue
        before.append(1 / (baseline.index(expected) + 1) if expected in baseline else 0)
        after.append(1 / (actual.index(expected) + 1) if expected in actual else 0)
        if case_id == "semantic-limit":
            # FTS dilbilgisi/anlam eşleşmesi yapmaz; bulunmayan yanıt üretmez.
            assert actual == []
        else:
            assert actual == [expected], case_id
    assert sum(after) > sum(before)
    assert sum(value > 0 for value in before) == 2
    assert sum(value > 0 for value in after) == 6
    record_property("corpus_version", CORPUS_VERSION)
    record_property("index", "sqlite-fts5/unicode61+turkish-fold/schema2")
    record_property("embedding_model", "none")
    record_property("baseline_recall_at_5", sum(value > 0 for value in before) / len(before))
    record_property("recall_at_5", sum(value > 0 for value in after) / len(after))
    record_property("baseline_mrr", sum(before) / len(before))
    record_property("mrr", sum(after) / len(after))
