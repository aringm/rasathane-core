// Sidecar gerektirmeyen çok-kaynaklı demo paketi. Yalnız `?demo=<kaynak>`
// modunda dinamik yüklenir; üretim veri yoluna girmez.

const ORTAK = {
  pii_tespit: false,
  cloud_cagrisi_sayisi: 0,
  ollama_ping_ms: 186,
  ceviri_durumu: "atlandi",
  dokum_segment_sayisi: 6,
  ozet_faithfulness: 0.88,
  ozet_faithfulness_durum: "gecti",
  degerleme_puani: 81,
  degerleme_durum: "uretildi",
  kisisel_durum: "uretildi",
  factcheck_durum: "uretildi",
  factcheck_iddia_sayisi: 1,
  index_eklendi: true,
  bellek_eklendi: true,
  harita_durum: "uretildi",
  harita_dugum_sayisi: 11,
  ses_durum: "uretildi",
  ses_kaynak: "piper",
  sunum_durum: "uretildi",
  hedef: "local",
  karmasiklik: "medium",
  cloud_girdi_token: 0,
  cloud_cikti_token: 0,
  stub: false,
  commit_yapildi: true,
};

const faktorler = (novelty, rarity, nis, recency, length) => ({
  novelty, rarity, nis, recency, length,
});

export const DEMO_VERILERI = {
  youtube: {
    ...ORTAK,
    klasor: "__demo__/youtube",
    index: {
      baslik: "Yapay Zekâ ve KVKK: Hukuki Çerçeve ile Pratik Uygulamalar",
      kanal: "Hukuk ve Teknoloji",
      yayin_tarihi: "2026-05-01",
      sure_sn: 1287,
      konu: "hukuk",
      anadil: "tr",
      video_id: "demo123abc",
      kaynak_turu: "youtube",
      kaynak_url: "https://www.youtube.com/watch?v=demo123abc",
      kaynak_id: "demo123abc",
      kaynak_sahibi: "Hukuk ve Teknoloji",
      kaynak_tarihi: "2026-05-01",
      kaynak_metrikleri: { goruntulenme: 18420, begeni: 934, yorum: 87 },
      keywords: ["yapay zekâ", "KVKK", "açık rıza", "otomatik karar", "profilleme"],
      degerleme_faktorleri: faktorler(0.72, 0.65, 0.8, 0.9, 0.55),
    },
    transkript_durumu: "altyazi",
    transkript_kaynak_dil: "tr",
    transkript_karakter: 18432,
    asr_tier: null,
    ozet_kisa: "Video, yapay zekâ sistemlerinin KVKK kapsamında değerlendirilmesini ve veri sorumlularının yükümlülüklerini ele alıyor.",
    ozet_detay: "Konuşmacı, model eğitim verilerinin kişisel veri içerebileceğini ve otomatik karar süreçlerinin şeffaf belgelenmesi gerektiğini açıklıyor.\n\nSon bölüm; veri minimizasyonu, aydınlatma ve düzenli denetim için uygulanabilir bir kontrol listesi sunuyor.",
    kisisel_analiz: "Hukuki boyut: Otomatik karar verme süreçleri KVKK m.11 kapsamındaki itiraz hakkı gözetilerek tasarlanmalıdır.\n\nMesleki ilgi: Yapay zekâ entegrasyonundan önce veri envanteri ve etki değerlendirmesi hazırlanması yerinde olur.",
    factcheck_iddialar: [{
      iddia: "KVKK m.11, otomatik karar sonucuna itiraz hakkı tanır.",
      karar: "DESTEKLİYOR",
      guven: 0.82,
      gerekce: "Kanun metni bu değerlendirmeyi destekliyor.",
      kaynaklar: ["https://www.mevzuat.gov.tr/"],
    }],
    kaynak_sinyalleri: [
      { etiket: "Altyazı", deger: "Yayıncı altyazısı", aciklama: "Zaman kodları korunarak alındı." },
      { etiket: "Konuşma yoğunluğu", deger: "14,3 dk / 21,5 dk", aciklama: "Müzik ve sessizlik aralıkları dışarıda bırakıldı." },
      { etiket: "Bölüm yapısı", deger: "6 bölüm", aciklama: "Konu geçişleri dökümde işaretlendi." },
    ],
  },

  github: {
    ...ORTAK,
    klasor: "__demo__/github",
    index: {
      baslik: "rasathane-labs / source-adapters",
      konu: "genel",
      anadil: "en",
      kaynak_turu: "github",
      kaynak_url: "https://github.com/rasathane-labs/source-adapters",
      kaynak_id: "rasathane-labs/source-adapters",
      kaynak_sahibi: "rasathane-labs",
      kaynak_tarihi: "2026-07-08",
      kaynak_metrikleri: { yildiz: 1284, fork: 146, acik_issue: 23, katilimci: 18 },
      keywords: ["Python", "adaptör", "içerik çıkarımı", "yerel LLM", "lisans"],
      degerleme_faktorleri: faktorler(0.84, 0.61, 0.82, 0.96, 0.68),
    },
    kaynak_durumu: "kaynak",
    transkript_durumu: "kaynak",
    transkript_kaynak_dil: "en",
    transkript_karakter: 26741,
    ozet_kisa: "Repository, farklı web kaynaklarını ortak bir belge şemasına dönüştüren modüler Python adaptörleri sunuyor.",
    ozet_detay: "Kod tabanı adaptör sözleşmesini, normalize edilmiş metadata alanlarını ve hata sınırlarını ayrı paketlerde tanımlıyor.\n\nTestler GitHub, arXiv ve Reddit örnekleri için çevrimdışı fixture kullanıyor; ağ erişimi entegrasyon katmanında izole edilmiş.",
    kisisel_analiz: "Teknik değerlendirme: Adaptör arayüzü genişlemeye uygun; rate-limit ve lisans bilgisinin sonuç şemasında zorunlu tutulması izlenebilirliği güçlendirir.",
    factcheck_iddialar: [{
      iddia: "Repository MIT lisansıyla yayımlanıyor.", karar: "DESTEKLİYOR", guven: 0.97,
      gerekce: "Kök dizindeki LICENSE kaydı MIT metnini içeriyor.", kaynaklar: ["https://github.com/"],
    }],
    kaynak_sinyalleri: [
      { etiket: "Varsayılan dal", deger: "main", aciklama: "Son commit 2 gün önce." },
      { etiket: "Dil dağılımı", deger: "%86 Python", aciklama: "TypeScript %9, diğer %5." },
      { etiket: "Bakım sinyali", deger: "Etkin", aciklama: "Son 30 günde 41 commit ve 12 birleşen PR." },
      { etiket: "Lisans", deger: "MIT", aciklama: "Ticari kullanıma açık." },
    ],
  },

  arxiv: {
    ...ORTAK,
    klasor: "__demo__/arxiv",
    index: {
      baslik: "Evidence-Grounded Agents for Long-Form Research Synthesis",
      konu: "genel",
      anadil: "en",
      kaynak_turu: "arxiv",
      kaynak_url: "https://arxiv.org/abs/2606.12345",
      kaynak_id: "2606.12345",
      kaynak_sahibi: "A. Demir ve 4 yazar",
      kaynak_tarihi: "2026-06-18",
      kaynak_metrikleri: { sayfa: 24, referans: 63, surum: 2, kategori: "cs.CL" },
      keywords: ["agent", "RAG", "atıf", "kanıt", "uzun bağlam"],
      degerleme_faktorleri: faktorler(0.89, 0.76, 0.91, 0.94, 0.74),
    },
    kaynak_durumu: "kaynak",
    transkript_durumu: "kaynak",
    transkript_kaynak_dil: "en",
    transkript_karakter: 54892,
    ozet_kisa: "Makale, uzun araştırma sentezlerinde her iddiayı doğrulanabilir kanıt parçalarıyla eşleyen bir agent mimarisi öneriyor.",
    ozet_detay: "Yöntem, retrieval ve sentez adımlarını ayrı denetim döngülerine bölüyor. Atıf kapsaması ve iddia-kanal uyumu birlikte ölçülüyor.\n\nAblation sonuçları, kanıt yeniden sıralamasının doğruluk artışındaki temel bileşen olduğunu gösteriyor.",
    kisisel_analiz: "Araştırma değeri: Kanıt izi yaklaşımı hukuki araştırma araçlarına uyarlanabilir; ancak benchmark'ın İngilizce ve açık veri kümeleriyle sınırlı olduğu not edilmeli.",
    factcheck_iddialar: [{
      iddia: "Kanıt yeniden sıralaması doğruluk artışındaki en etkili bileşendir.", karar: "DESTEKLİYOR", guven: 0.9,
      gerekce: "Ablation tablosundaki en büyük düşüş bu bileşen çıkarıldığında görülüyor.", kaynaklar: ["https://arxiv.org/"],
    }],
    kaynak_sinyalleri: [
      { etiket: "Makale türü", deger: "Araştırma", aciklama: "24 sayfa · 7 tablo · 4 şekil." },
      { etiket: "Sürüm", deger: "v2", aciklama: "İlk sürümden sonra yöntem bölümü genişletilmiş." },
      { etiket: "Kaynakça", deger: "63 referans", aciklama: "18'i son iki yıldan." },
    ],
  },

  reddit: {
    ...ORTAK,
    klasor: "__demo__/reddit",
    index: {
      baslik: "Yerel LLM ile uzun belgeleri işlerken hangi RAG yaklaşımı daha güvenilir?",
      konu: "genel",
      anadil: "tr",
      kaynak_turu: "reddit",
      kaynak_url: "https://www.reddit.com/r/LocalLLaMA/comments/demo123/",
      kaynak_id: "demo123",
      kaynak_sahibi: "r/LocalLLaMA · u/veri_gozcusu",
      kaynak_tarihi: "2026-07-06",
      kaynak_metrikleri: { oy: 842, yorum: 164, oy_orani: "%96", odul: 3 },
      keywords: ["RAG", "chunking", "embedding", "yerel model", "deneyim"],
      degerleme_faktorleri: faktorler(0.7, 0.54, 0.77, 0.98, 0.62),
    },
    kaynak_durumu: "kaynak",
    transkript_durumu: "kaynak",
    transkript_kaynak_dil: "tr",
    transkript_karakter: 31228,
    ozet_kisa: "Başlık ve yorumlar, uzun belge RAG akışlarında sabit chunk yerine başlık-duyarlı bölmenin daha tutarlı bulunduğunu gösteriyor.",
    ozet_detay: "En çok oy alan yorumlar hybrid retrieval, küçük overlap ve reranker kullanımında birleşiyor.\n\nKarşı görüşler, değerlendirme veri kümesi olmadan tek bir chunk stratejisinin genellenemeyeceğini vurguluyor.",
    kisisel_analiz: "Topluluk sinyali: Öneriler pratik deneyime dayanıyor; ürün kararı verilmeden kontrollü bir veri kümesinde ölçülmeli.",
    factcheck_iddialar: [{
      iddia: "Hybrid retrieval her veri kümesinde dense retrieval'dan üstündür.", karar: "BELİRSİZ", guven: 0.46,
      gerekce: "Yorumlar deneyim aktarıyor; ortak ve kontrollü ölçüm sunulmuyor.", kaynaklar: [],
    }],
    kaynak_sinyalleri: [
      { etiket: "Tartışma", deger: "164 yorum", aciklama: "11 ana görüş kümesi belirlendi." },
      { etiket: "Uzlaşma", deger: "%68", aciklama: "Hybrid retrieval yönündeki yorum payı." },
      { etiket: "Karşı görüş", deger: "27 yorum", aciklama: "Veri kümesine özgü ölçüm gereğini savunuyor." },
    ],
  },

  huggingface: {
    ...ORTAK,
    klasor: "__demo__/huggingface",
    index: {
      baslik: "rasathane-ai / turkish-legal-embedding",
      konu: "hukuk",
      anadil: "tr",
      kaynak_turu: "huggingface",
      kaynak_url: "https://huggingface.co/rasathane-ai/turkish-legal-embedding",
      kaynak_id: "rasathane-ai/turkish-legal-embedding",
      kaynak_sahibi: "rasathane-ai",
      kaynak_tarihi: "2026-06-29",
      kaynak_metrikleri: { indirme_aylik: 28400, begeni: 517, parametre: "0.6B", lisans: "apache-2.0" },
      keywords: ["embedding", "Türkçe hukuk", "sentence-transformers", "benchmark"],
      degerleme_faktorleri: faktorler(0.82, 0.78, 0.95, 0.93, 0.58),
    },
    kaynak_durumu: "kaynak",
    transkript_durumu: "kaynak",
    transkript_kaynak_dil: "tr",
    transkript_karakter: 19364,
    ozet_kisa: "Model kartı, Türkçe hukuk metinleri için ince ayarlanmış 0.6B parametreli bir embedding modelini ve benchmark sonuçlarını belgeliyor.",
    ozet_detay: "Eğitim verisi mevzuat, anonimleştirilmiş karar ve sentetik soru-cevap çiftlerinden oluşuyor.\n\nModel kartı kullanım sınırlarını, lisansı ve retrieval benchmark sonuçlarını ayrı bölümlerde sunuyor.",
    kisisel_analiz: "Risk notu: Model kartındaki anonimleştirme beyanı olumlu; üretim öncesinde eğitim verisi yönetişimi ve benchmark tekrar üretilebilirliği doğrulanmalı.",
    factcheck_iddialar: [{
      iddia: "Model Apache 2.0 lisansı altında sunuluyor.", karar: "DESTEKLİYOR", guven: 0.99,
      gerekce: "Model kartı ve repository metadata alanı aynı lisansı gösteriyor.", kaynaklar: ["https://huggingface.co/"],
    }],
    kaynak_sinyalleri: [
      { etiket: "Görev", deger: "Feature extraction", aciklama: "Sentence Transformers uyumlu." },
      { etiket: "Aylık indirme", deger: "28,4 bin", aciklama: "Son 30 günlük Hub metriği." },
      { etiket: "Model boyutu", deger: "1,3 GB", aciklama: "Safetensors formatı." },
      { etiket: "Lisans", deger: "Apache 2.0", aciklama: "Model kartında açıkça belirtilmiş." },
    ],
  },

  web: {
    ...ORTAK,
    klasor: "__demo__/web",
    index: {
      baslik: "Yerel yapay zekâ sistemlerinde denetlenebilirlik için uygulama rehberi",
      konu: "hukuk",
      anadil: "tr",
      kaynak_turu: "web",
      kaynak_url: "https://ornek.test/yerel-yapay-zeka-denetlenebilirlik",
      kaynak_id: "yerel-yapay-zeka-denetlenebilirlik",
      kaynak_sahibi: "Rasathane Araştırma Notları",
      kaynak_tarihi: "2026-07-03",
      kaynak_metrikleri: { okuma_suresi: "9 dk", baslik: 7, dis_baglanti: 14, guncelleme: "2026-07-07" },
      keywords: ["denetlenebilirlik", "yerel AI", "kanıt izi", "veri minimizasyonu"],
      degerleme_faktorleri: faktorler(0.76, 0.58, 0.86, 0.97, 0.64),
    },
    kaynak_durumu: "kaynak",
    transkript_durumu: "kaynak",
    transkript_kaynak_dil: "tr",
    transkript_karakter: 15743,
    ozet_kisa: "Rehber, yerel yapay zekâ akışlarında kaynak izi, model kaydı ve kişisel veri denetimini uygulanabilir kontrollere dönüştürüyor.",
    ozet_detay: "İçerik; girdi kaydı, model sürümü, retrieval kanıtı ve çıktı onayını tek bir denetim zincirinde topluyor.\n\nGenel web sayfası güvenlik nedeniyle arayüzde iframe içine alınmıyor; yalnız çıkarılmış metin ve metadata yerel olarak işleniyor.",
    kisisel_analiz: "Hukuki değerlendirme: Denetim izi, hesap verebilirlik bakımından güçlü bir başlangıçtır; saklama süresi ve erişim rolleri politika düzeyinde ayrıca tanımlanmalıdır.",
    factcheck_iddialar: [{
      iddia: "Her model çağrısı için kullanılan model sürümü kaydedilmelidir.", karar: "DESTEKLİYOR", guven: 0.84,
      gerekce: "Rehber bu kontrolü denetim zincirinin zorunlu alanı olarak tanımlıyor.", kaynaklar: ["https://ornek.test/"],
    }],
    kaynak_sinyalleri: [
      { etiket: "İçerik türü", deger: "Uygulama rehberi", aciklama: "7 başlık ve 2 kontrol listesi." },
      { etiket: "Dış kaynak", deger: "14 bağlantı", aciklama: "9 farklı alan adına dağılıyor." },
      { etiket: "Güncellik", deger: "4 gün önce", aciklama: "İlk yayından sonra bir kez güncellenmiş." },
    ],
  },
};

// Eski `?demo` sözleşmesi ve mevcut importlar için YouTube fixture alias'ı.
export const ORNEK = DEMO_VERILERI.youtube;

export const DEMO_URLLER = Object.fromEntries(
  Object.entries(DEMO_VERILERI).map(([tur, sonuc]) => [tur, sonuc.index.kaynak_url]),
);

export const DEMO_KUTUPHANE = Object.values(DEMO_VERILERI).map((sonuc, sira) => ({
  klasor: sonuc.klasor,
  baslik: sonuc.index.baslik,
  kanal: sonuc.index.kanal,
  kaynak_sahibi: sonuc.index.kaynak_sahibi || sonuc.index.kanal,
  kaynak_turu: sonuc.index.kaynak_turu || "youtube",
  konu: sonuc.index.konu,
  tarih: sonuc.index.kaynak_tarihi || sonuc.index.yayin_tarihi,
  puan: sonuc.degerleme_puani - sira,
}));

export const DEMO_AYARLAR = {
  ollama_host: "http://127.0.0.1:11434",
  ollama_host_kaynak: "varsayilan",
  output_base: "C:\\Rasathane\\analizler (demo)",
  motor_kok: "C:\\Rasathane\\motor (demo)",
};

export const DEMO_MODELLER = ["qwen3.6:35b", "qwen3.6:27b", "gemma4:12b"];

export function demoVerisi(tur) {
  return DEMO_VERILERI[tur] || DEMO_VERILERI.youtube;
}

// Küçük, kendine yeten zihin haritası. Bu yalnız uygulamanın ürettiği srcdoc'tur;
// genel web içeriği veya kaynak URL'si hiçbir zaman iframe'e yüklenmez.
export const DEMO_HARITA = `<!doctype html><html><head><meta charset="utf-8">
<style>
  body{margin:0;background:#0d0f12;color:#e6e9ef;font:14px 'Segoe UI',sans-serif;
    display:flex;align-items:center;justify-content:center;height:100vh;}
  .kok{display:flex;align-items:center;gap:18px;}
  .dal{display:flex;flex-direction:column;gap:10px;}
  .nd{padding:7px 12px;border-radius:8px;border:1px solid #2b313b;background:#14171c;white-space:nowrap;}
  .nd.ana{border-color:#22456f;color:#8fbcff;background:#16263d;}
  .nd.merkez{border-color:#1c4733;color:#74d9a8;background:#102619;font-weight:600;}
</style></head><body>
  <div class="kok">
    <div class="nd merkez">Kaynak analizi</div>
    <div class="dal">
      <div class="nd ana">Ana iddialar</div><div class="nd ana">Kaynak sinyalleri</div>
      <div class="nd ana">Kanıt izi</div><div class="nd ana">Uygulama notları</div>
    </div>
    <div class="dal">
      <div class="nd">Metadata</div><div class="nd">Doğrulama</div>
      <div class="nd">Riskler</div><div class="nd">Sonraki adımlar</div>
    </div>
  </div>
</body></html>`;
