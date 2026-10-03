# Held-out TR Eval Korpusu — Şablon ve Rehber

> Bu dizin **şablondur** (commit'lenir). Gerçek belgeler `eval/real_docs/`'a konur ve
> `.gitignore` ile dışlanır — held-out disiplini + KVKK (müvekkil/kişisel içerik repoya girmez).
> Master'a merge GATE'i: `eval/real_docs/`'taki gerçek belgelerde eval eşikleri geçince.

## Neden bu korpus var (moat #1)

Üç değişmezden biri: **"Master'a merge yalnız held-out Türkçe eval geçince."** Segmentasyon,
keyword, özet sadakati ve retrieval metrikleri **gerçeklendi ve ayırt-edici** (sentetik+golden ile
doğrulandı), ama **eşik değerleri** (örn. "Pk ≤ ?", "F1 ≥ ?", "faithfulness ≥ ?") gerçek-dünya
TR belgesiyle kalibre edilmeden KİLİTLENMEZ. Bu korpus o kalibrasyonu sağlar.

"Held-out" = dev/golden üretiminde **kullanılmamış**, sistemin daha önce görmediği gerçek içerik.
Golden referansları **insan** (sen) üretir — sistemin kendi çıktısı golden olamaz (totoloji).

## Bir "vaka" nasıl kurulur

Her gerçek video = bir alt-dizin: `eval/real_docs/<video_slug>/`. İçine bu şablondaki dosyaları
kopyalayıp doldur. Önerilen başlangıç: **3-5 vaka** (en az biri hukuk içerikli, biri konuşmalı/uzun).

```
eval/real_docs/
├── golden_retrieval.json          # korpus-düzeyi (tek dosya, tüm vakalar için) — opsiyonel
├── sozlesme-hukuku-temelleri/     # vaka 1
│   ├── kaynak.json
│   ├── golden_segment.json
│   ├── golden_keywords.json
│   ├── golden_ozet.md
│   └── golden_transcript.md       # opsiyonel (WER kalibrasyonu için)
└── ...
```

## Golden dosyaları — format ve hangi metriği besler

| Dosya | Besleyen metrik (fonksiyon) | İçerik |
|---|---|---|
| `kaynak.json` | (manifest) | video_url + konu + anadil + neden held-out |
| `golden_segment.json` | `segmentasyon_metrik(referans, tahmin)` → Pk/WindowDiff | cümle-başına segment-id (elle-işaretli "doğru" segmentasyon) |
| `golden_keywords.json` | `keyword_metrik(tahmin, golden)` → P/R/F1 | bu video için "doğru" anahtar kelime referans seti |
| `golden_ozet.md` | `faithfulness_metrik(ozet, kaynak, llm)` referansı + kalite A/B | insan yazımı referans özet |
| `golden_retrieval.json` | `retrieval_recall_hesapla(golden, ...)` → recall@k/nDCG | korpus-düzeyi: sorgu → dönmesi gereken video_id'ler |
| `golden_transcript.md` | `TRANSCRIPT_WER` (henüz `_ni` — kod bekliyor) | referans transkript (WER hedefi %12-25) |

### `golden_segment.json` doğru nasıl işaretlenir
Sistemin `cumlelere_bol()` çıktısı sırasıyla AYNI cümle listesini kullan; her cümleye ait olduğu
segmentin id'sini ver. id **monoton artan** (0,0,0,1,1,2…). Yeni konu = yeni id. Bu, `referans:
list[int]` parametresine birebir karşılık gelir.

## Kalibrasyon + master-merge GATE (golden hazır olunca)

1. Her vakayı **gerçek modda** analiz et (Ollama açık; fixture YOK): `analiz_et(url, konu)`.
2. Üretilen döküm/keyword/özet'i golden ile karşılaştır (yukarıdaki metrik fonksiyonları).
3. Gerçek-dünya bantlarına göre **eşikleri belirle** (senin kararın; örn. Pk ≤ 0.30, keyword_f1 ≥
   0.40, faithfulness ≥ 0.70, recall@5 ≥ 0.80, WER ≤ %25). Bu değerler bantlardan + bu korpustaki
   gözlemden gelir.
4. Eşikler geçerse master merge açılır.

## ⚠️ Henüz eksik olan kod (sıradaki adım — bu şablon onu beklemiyor)

`eval/yteval/runner.py::eval_kos` şu an YALNIZ sentetik örneklerle koşar; `eval/real_docs/`'tan
vaka OKUYAN bir loader (`gercek_korpus_kos`) + eşik-kontrol HENÜZ YAZILMADI. İlk gerçek vaka
gelince TDD ile yazılacak (golden formatı bu şablona göre sabit; loader düz olur). Şablonu
doldurduğunda bunu söyle — loader'ı o zaman gerçek vakaya karşı yazarım.
