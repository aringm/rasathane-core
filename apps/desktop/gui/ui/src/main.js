import { createLoginGate } from "./login-gate.js";
let loginGate;
import { createProductUI } from "./product.js";
import { createProfileSettings } from "./profile-settings.js";
import {
  renderArtifact,
  clearArtifact,
  clearAllArtifacts,
} from "./artifacts.js";
import { ARTIFACT_LIMIT } from "./artifact-data.js";
// GUI -> sidecar veri yolu. 127.0.0.1 (localhost DEĞİL) — IPv6 mismatch önlemi.
// Port artık sabit değil: kabuk (Electron) açılışta boş bir port seçip sidecar'ı orada
// başlatır ve `?sidecarPort=` ile bildirir. Paketli origin'de yalnız ADAY_PORTLAR
// kabul edilir (CSP connect-src listesiyle birebir aynı); statik browser önizlemesinde
// (127.0.0.1/localhost) serbest port test seam'i olarak açık kalır.
const ADAY_PORTLAR = [8765, 8766, 8767, 8768];
const SIDECAR_PORT = (() => {
  const varsayilan = ADAY_PORTLAR[0];
  const aday =
    new URLSearchParams(window.location.search).get("sidecarPort") || "";
  if (!/^\d{4,5}$/.test(aday)) return varsayilan;
  const port = Number(aday);
  if (ADAY_PORTLAR.includes(port)) return port;
  const yerel = ["127.0.0.1", "localhost"].includes(window.location.hostname);
  return yerel && port >= 1024 && port <= 65535 ? port : varsayilan;
})();
const SIDECAR = `http://127.0.0.1:${SIDECAR_PORT}`;
const $ = (id) => document.getElementById(id);

// Kaynaklar yalnız kullanıcının tıklamasıyla, main'in URL denetiminden sonra açılır.
document.addEventListener("click", async (event) => {
  const anchor = event.target.closest?.("a[href]");
  if (!anchor || !window.rasathane?.openSource) return;
  const url = new URL(anchor.href, window.location.href);
  if (!["http:", "https:"].includes(url.protocol)) return;
  event.preventDefault();
  try {
    await window.rasathane.openSource(url.href);
  } catch (error) {
    const status = anchor.closest("#ilk-kurulum")
      ? $("model-kurulum-durum")
      : anchor.closest("#hesap-dialog")
        ? $("hesap-durum")
        : $("urun-durum");
    status.textContent = error.message || "Kaynak bağlantısı açılamadı.";
    status.classList.add("status-error");
  }
});

// Electron'da renderer yalnız dar preload sözleşmesini kullanır. Doğrudan fetch,
// yalnız loopback browser preview'da kullanılabilir; paketli UI fail-closed kalır.
async function sidecarFetch(url, options = {}) {
  if (!loginGate?.allowed()) throw new Error("Devam etmek için giriş yapın.");
  const sessionGeneration = loginGate.generation();
  const target = new URL(url, SIDECAR);
  if (target.origin !== SIDECAR)
    throw new Error("İzinli yerel servis dışında istek reddedildi.");
  if (window.rasathane?.request) {
    const body =
      typeof options.body === "string"
        ? JSON.parse(options.body)
        : options.body;
    const response = await window.rasathane.request(
      target.pathname + target.search,
      {
        method: options.method || "GET",
        ...(body === undefined ? {} : { body }),
      },
    );
    if (!loginGate.allowed() || sessionGeneration !== loginGate.generation())
      throw new Error("Oturum kapandı; yanıt gösterilmedi.");
    const bytes = response.base64
      ? Uint8Array.from(atob(response.base64), (c) => c.charCodeAt(0))
      : JSON.stringify(response.data ?? null);
    return new Response(bytes, {
      status: response.status || (response.ok ? 200 : 500),
      headers: { "Content-Type": response.contentType || "application/json" },
    });
  }
  if (!["127.0.0.1", "localhost"].includes(window.location.hostname)) {
    throw new Error(
      "Uygulama veri bağlantısı hazır değil. Rasathane'yi yeniden açın.",
    );
  }
  return fetch(target.href, options);
}
async function frameDosyaYukle(frame, klasor, ad) {
  const requestId = (frame.dataset.requestId =
    String(Date.now()) + Math.random());
  clearArtifact(frame);
  frame.replaceChildren(
    el("p", { class: "artifact-status", role: "status" }, "Çıktı yükleniyor…"),
  );
  try {
    const response = await sidecarFetch(
      `${SIDECAR}/gui/dosya?klasor=${encodeURIComponent(klasor)}&ad=${encodeURIComponent(ad)}`,
    );
    if (!response.ok) throw new Error("Çıktı dosyasına ulaşılamadı.");
    if (Number(response.headers.get("content-length")) > ARTIFACT_LIMIT)
      throw new Error("Çıktı boyut sınırını aşıyor.");
    const bytes = new Uint8Array(await response.arrayBuffer());
    if (frame.dataset.requestId !== requestId) return;
    await renderArtifact(
      frame,
      bytes,
      ad,
      () => frame.dataset.requestId === requestId,
    );
  } catch (error) {
    if (frame.dataset.requestId === requestId) {
      const message = error.message || "Çıktı görüntülenemedi.";
      clearArtifact(frame);
      frame.replaceChildren(
        el(
          "p",
          { id: frame.id + "-durum", class: "record-error", role: "alert" },
          message,
        ),
      );
    }
  }
}
function frameBirak(frame) {
  frame.dataset.requestId = "closed";
  clearArtifact(frame);
}

/* ---- güvenli DOM oluşturucu (innerHTML YOK → XSS-bağışık) ----------------
   Tüm metin textContent ile yazılır; dış kaynak metadata'sı (başlık/keyword) asla
   HTML olarak yorumlanmaz. el(tag, attrs, ...children). */
function el(tag, attrs, ...kids) {
  const n = document.createElement(tag);
  if (attrs)
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
      else if (k.startsWith("on") && typeof v === "function")
        n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? "" : String(v));
    }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    n.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return n;
}
function svgEl(tag, attrs) {
  const n = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs || {}))
    n.setAttribute(k, String(v));
  return n;
}

/* ---- yardımcılar -------------------------------------------------------- */
function sn2mmss(sn) {
  if (sn == null || isNaN(sn)) return null;
  const d = Math.floor(sn / 60),
    s = Math.floor(sn % 60);
  return `${d}:${String(s).padStart(2, "0")}`;
}
const IKON = { basari: "✓", atlandi: "–", uyari: "!", hata: "✕" };
function rozetEl(renk, metin) {
  return el(
    "span",
    { class: "rozet", "data-renk": renk },
    el("span", {
      class: "ikon",
      "aria-hidden": "true",
      text: IKON[renk] || "·",
    }),
    metin,
  );
}

// durum string -> insanca Türkçe etiket
const ETIKET = {
  altyazi: "Altyazı",
  asr: "ASR (Whisper)",
  kaynak: "Edinildi",
  tam: "Edinildi",
  fixture: "Demo verisi",
  kismi: "Kısmi içerik",
  auth_gerekli: "Erişim gerekli",
  altyazi_yok: "Altyazı yok",
  icerik_bos: "İçerik boş",
  cevrildi: "Çevrildi",
  atlandi: "Atlandı",
  icerik_yok: "İçerik yok",
  hata: "Hata",
  uretildi: "Üretildi",
  web_yok: "Web yok",
  ses_modeli_yok: "Ses modeli yok",
  anahtar_yok: "Anahtar yok",
  piper: "Piper · yerel",
  windows: "Windows · yerel",
  cloud: "Bulut",
  fake: "Örnek",
  // özet/faithfulness durumları (renk faithRenk(skor)'dan; burada yalnız insanca metin)
  gecti: "Tahmin eşiği sağlandı",
  esik_alti: "Eşik altı",
  yeniden_uretildi: "Yeniden üretildi",
  ozet_yok: "Özet yok",
  kaynak_alintisi: "Birincil kaynak alıntısı",
  aday_inceleme: "Arama incelemesi",
  atlandi_resmi_kaynak: "Birincil metin kullanıldı",
  // kurulum/servis eksiklikleri — ham snake_case kullanıcıya sızmasın
  piper_kurulu_degil: "Piper kurulu değil",
  model_bos: "Model boş döndü",
  web_hata: "Web hatası",
  hepsi_atlandi: "Kişisel veri — atlandı",
};
// durum string -> renk token (bilinmeyen -> atlandi)
const RENK = {
  transkript: {
    altyazi: "basari",
    asr: "basari",
    kaynak: "basari",
    tam: "basari",
    fixture: "basari",
    kismi: "uyari",
    auth_gerekli: "uyari",
    altyazi_yok: "atlandi",
    icerik_bos: "uyari",
    hata: "hata",
  },
  ceviri: {
    cevrildi: "basari",
    atlandi: "atlandi",
    icerik_yok: "uyari",
    hata: "hata",
  },
  durumlu: {
    uretildi: "basari",
    atlandi: "atlandi",
    atlandi_resmi_kaynak: "atlandi",
    model_bos: "uyari",
    icerik_yok: "uyari",
    hata: "hata",
  },
  factcheck: {
    uretildi: "basari",
    web_yok: "uyari",
    web_hata: "uyari",
    hepsi_atlandi: "uyari",
    atlandi: "atlandi",
    atlandi_resmi_kaynak: "atlandi",
    icerik_yok: "uyari",
    hata: "hata",
  },
  harita: {
    uretildi: "basari",
    icerik_yok: "uyari",
    atlandi: "atlandi",
    hata: "hata",
  },
  ses: {
    uretildi: "basari",
    ses_modeli_yok: "uyari",
    piper_kurulu_degil: "uyari",
    anahtar_yok: "uyari",
    icerik_yok: "uyari",
    atlandi: "atlandi",
    hata: "hata",
  },
};
// Bilinmeyen durum -> "uyari" (fail-loud): gelecekteki yeni backend değeri sessizce "atlandı/gri"
// görünmesin (review LOW: aksi hâlde ağır durum sakin-gri yüzeylenir).
const renkBul = (h, d) => h[d] || "uyari";
const etiket = (d) => (ETIKET[d] != null ? ETIKET[d] : d || "bilinmiyor");

const KAYNAKLAR = {
  youtube: {
    ad: "YouTube",
    kod: "YT",
    aciklama: "Video altyazısı veya izinli yerel ASR analiz edilir.",
  },
  github: {
    ad: "GitHub",
    kod: "GH",
    aciklama: "Repository metadata'sı ve README incelenir.",
  },
  arxiv: {
    ad: "arXiv",
    kod: "AX",
    aciklama: "Makale metadata'sı ve abstract incelenir.",
  },
  reddit: {
    ad: "Reddit",
    kod: "RD",
    aciklama: "Onaylı OAuth ile gönderi ve yorum ağacı incelenir.",
  },
  huggingface: {
    ad: "Hugging Face",
    kod: "HF",
    aciklama: "Model, dataset veya Space card'ı incelenir.",
  },
  web: {
    ad: "Web",
    kod: "WB",
    aciklama: "Tek public sayfanın ana içeriği güvenli biçimde çıkarılır.",
  },
};

function kaynakTuruBul(deger) {
  try {
    const u = new URL(String(deger || "").trim());
    if (!["http:", "https:"].includes(u.protocol)) return null;
    const h = u.hostname.toLocaleLowerCase("tr").replace(/^www\./, "");
    if (h === "youtu.be" || h.endsWith("youtube.com")) return "youtube";
    if (h === "github.com" || h.endsWith(".github.com")) return "github";
    if (h === "arxiv.org" || h.endsWith(".arxiv.org")) return "arxiv";
    if (h === "redd.it" || h === "reddit.com" || h.endsWith(".reddit.com"))
      return "reddit";
    if (
      h === "hf.co" ||
      h === "huggingface.co" ||
      h.endsWith(".huggingface.co")
    )
      return "huggingface";
    return "web";
  } catch {
    return null;
  }
}

function kaynakAlgisiniGuncelle() {
  const tur = kaynakTuruBul(urlEl.value);
  const meta = tur ? KAYNAKLAR[tur] : null;
  const cip = $("kaynak-cip");
  cip.classList.toggle("bekliyor", !meta);
  cip.textContent = meta ? `${meta.kod} · ${meta.ad}` : "Kaynak bekleniyor";
  $("kaynak-algilama-aciklama").textContent = meta
    ? meta.aciklama
    : "Bağlantıyı yazdığınızda uygun analiz adaptörü seçilir.";
  $("asr-satir").classList.toggle("gizli", tur !== "youtube");
  if (tur !== "youtube") asrEl.checked = false;
  document.querySelectorAll("#kaynak-listesi [data-kaynak]").forEach((n) => {
    if (n.dataset.kaynak === tur) n.setAttribute("aria-current", "true");
    else n.removeAttribute("aria-current");
  });
  return tur;
}

/* ---- durum makinesi ----------------------------------------------------- */
let veri = null;
let kutuphaneVeri = null; // lazy önbellek; analiz bitince geçersiz kılınır
let kutuphaneYuklendi = false;
let demoAktif = false;
let demoPaket = null;
const motorCip = $("motor-cip"),
  motorMetin = $("motor-metin");
const btn = $("analiz-btn"),
  urlEl = $("url"),
  konuEl = $("konu"),
  asrEl = $("asr");
const modelEl = $("model");
if (modelEl) {
  modelEl.disabled = true;
  modelEl.title =
    "Analiz modeli Ayarlar bölümündeki donanım profiline bağlıdır.";
}
const calismaSerit = $("calisma-serit"),
  hataBant = $("hata-bant"),
  hataMetin = $("hata-metin");
const sonuc = $("sonuc");

function setMotor(durum, metin) {
  motorCip.dataset.durum = durum;
  motorMetin.textContent = metin;
}

/* ---- 1. motor hazırlık poll'u ------------------------------------------- */
async function sidecarHazirla(deneme = 120) {
  setMotor("baslatiliyor", "Motor başlatılıyor…");
  btn.disabled = true;
  btn.setAttribute("aria-disabled", "true");
  for (let i = 0; i < deneme; i++) {
    if (!loginGate?.allowed()) return;
    try {
      const r = await sidecarFetch(`${SIDECAR}/gui/health`, { method: "GET" });
      if (r.ok) {
        setMotor("hazir", "Yerel servis hazır");
        btn.disabled = false;
        btn.setAttribute("aria-disabled", "false");
        modelleriHazirla(); // model dropdown'unu doldur (/gui/modeller)
        kurulumDurumu(); // arama servisi rozeti (/gui/kurulum)
        onboardingKontrol(); // tam özellik hazır değilse Ayarlar'a yönlendir
        productUI.load();
        return;
      }
    } catch {
      /* henüz ayağa kalkmadı */
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  setMotor("hata", "Motor başlatılamadı");
  gosterHata(
    `Motor başlatılamadı: 127.0.0.1:${SIDECAR_PORT} yanıt vermiyor. Ayrıntı için ` +
      "sidecar.log dosyasına bakın (Windows: %APPDATA%\\Rasathane\\logs\\sidecar.log).",
  );
}

/* ---- 2. analiz ---------------------------------------------------------- */
async function analizEt() {
  const url = urlEl.value.trim();
  if (!url) {
    urlEl.setAttribute("aria-invalid", "true");
    urlEl.focus();
    return;
  }
  const kaynakTuru = kaynakAlgisiniGuncelle();
  if (!kaynakTuru) {
    urlEl.setAttribute("aria-invalid", "true");
    gosterHata("Geçerli bir http veya https kaynak bağlantısı girin.");
    urlEl.focus();
    return;
  }
  urlEl.removeAttribute("aria-invalid");
  sonuc.classList.add("gizli");
  hataBant.classList.add("gizli");
  calismaSerit.classList.remove("gizli");
  btn.disabled = true;
  btn.setAttribute("aria-disabled", "true");

  if (demoAktif && demoPaket) {
    const d = demoPaket.demoVerisi(kaynakTuru);
    veri = d;
    render(d);
    btn.disabled = false;
    btn.setAttribute("aria-disabled", "false");
    calismaSerit.classList.add("gizli");
    return;
  }

  try {
    await productUI.analyze({
      url,
      konu: konuEl.value,
      asr_izin: kaynakTuru === "youtube" && asrEl.checked,
    });
  } catch (error) {
    gosterHata(error.message || "Analiz başlatılamadı.");
  } finally {
    btn.disabled = false;
    btn.setAttribute("aria-disabled", "false");
    calismaSerit.classList.add("gizli");
  }
}

function gosterHata(mesaj) {
  hataMetin.textContent = mesaj;
  hataBant.classList.remove("gizli");
  sonuc.classList.add("gizli");
}

/* ---- 3. render (ham JSON ASLA) ------------------------------------------ */
function render(d) {
  const idx = d.index || {};
  renderGuven(d);
  renderKunye(d, idx);
  renderSkor(d.degerleme_puani);
  // Çıktı İÇERİĞİ (Faz 9): özet/kişisel/fact-check metni ekranda inline gösterilir.
  renderOzet(d);
  renderKaynakSinyalleri(d);
  renderKisisel(d);
  renderFactcheck(d);
  renderHarita(d);
  // Durum/metrik sütunu
  renderFaktorler(idx.degerleme_faktorleri || {});
  renderStepper(d);
  renderCikti(d);
  renderTeknik(d);
  sonuc.classList.remove("gizli");
  const hedefler = [
    [$("guven-bant"), 0],
    [sonuc.querySelector(".ozet-blok"), 60],
    [sonuc.querySelector(".sonuc-ana"), 130],
    [sonuc.querySelector(".sonuc-yan"), 200],
  ];
  for (const [node, gecikme] of hedefler) {
    if (!node) continue;
    node.classList.remove("reveal");
    void node.offsetWidth;
    node.style.animationDelay = `${gecikme}ms`;
    node.classList.add("reveal");
  }
  sonuc.scrollIntoView({ behavior: "smooth", block: "start" });
  // analiz bitti: odağı sonuç başlığına taşı → ekran okuyucu "Analiz ediliyor"dan sonra
  // sessiz kalmasın, kullanıcı sonucun geldiğini duysun (review LOW: 4.1.3).
  const bas = $("baslik");
  bas.setAttribute("tabindex", "-1");
  bas.focus({ preventScroll: true });
  kutuphaneYuklendi = false; // yeni analiz → kütüphane önbelleğini geçersiz kıl
  kutuphaneVeri = null;
}

/* ---- çıktı içeriği render'ları (Faz 9: ekranda inline gösterim) --------- */
// Metni paragraflara böl (boş satır = paragraf). "Etiket: …" deseninde etiketi vurgular.
// XSS-bağışık: tüm metin textContent/el() ile yazılır (innerHTML YOK).
function paragrafYaz(hedef, metin) {
  const paragraflar = String(metin || "")
    .split(/\n{2,}/)
    .map((p) => p.replace(/\n/g, " ").trim())
    .filter(Boolean);
  const dugumler = paragraflar.map((p) => {
    const m = p.match(/^([^:\n]{2,42}):\s+(.*)$/s);
    return m
      ? el("p", {}, el("strong", {}, `${m[1]}: `), m[2])
      : el("p", {}, p);
  });
  hedef.replaceChildren(...dugumler);
}

function renderOzet(d) {
  const bolum = $("ozet-bolum");
  const kaynakAlintisi = d.analysis_mode === "source_extracts";
  const abstractOnly =
    (d.kaynak_turu || d.index?.kaynak_turu) === "arxiv" &&
    d.quality_provenance?.source?.text_scope === "abstract_only";
  $("ozet-baslik").textContent = kaynakAlintisi
    ? "Birincil metinden okuma özeti"
    : abstractOnly
      ? "Yayın özeti (abstract) analizi"
      : "Özet";
  const kisa = (d.ozet_kisa || "").trim();
  const detay = (d.ozet_detay || d.ozet_orta || "").trim();
  if (!kisa && !detay) {
    bolum.classList.add("gizli");
    return;
  }
  bolum.classList.remove("gizli");
  $("ozet-kisa").textContent = kisa;
  paragrafYaz($("ozet-detay"), detay || kisa);
  $("ozet-model-not").textContent = kaynakAlintisi
    ? "Madde ve fıkralar birincil metinden alınmıştır. Modelin yeniden yazdığı hukuki hükümler veya doğruluk puanı kullanılmaz."
    : abstractOnly
      ? "Yalnız yayın özeti (abstract) incelendi; tam makale okunmadı. Kısa/orta katmanlar Türkçe model çevirisinden seçilmiş tam cümlelerdir. Detay katmanı yerel model özetidir. Model destek tahmini doğruluk onayı değildir."
      : "Model destek tahmini, detay özet ile analiz metnini karşılaştırır; doğruluk onayı değildir.";
  $("ozet-model-not").classList.toggle(
    "gizli",
    !kaynakAlintisi && !abstractOnly && d.ozet_faithfulness == null,
  );
}

function renderKaynakSinyalleri(d) {
  const bolum = $("kaynak-sinyalleri-bolum");
  const sinyaller = Array.isArray(d.kaynak_sinyalleri)
    ? d.kaynak_sinyalleri
    : [];
  if (!sinyaller.length) {
    bolum.classList.add("gizli");
    return;
  }
  bolum.classList.remove("gizli");
  $("kaynak-sinyalleri-ozet").textContent =
    `${sinyaller.length} açıklanabilir sinyal`;
  $("kaynak-sinyalleri").replaceChildren(
    ...sinyaller
      .slice(0, 8)
      .map((s) =>
        el(
          "div",
          { class: "kaynak-sinyal", "data-durum": s.durum || "bilgi" },
          el("span", { class: "sinyal-ad" }, s.etiket || "Sinyal"),
          el(
            "span",
            { class: "sinyal-deger" },
            s.deger == null ? "—" : String(s.deger),
          ),
          s.aciklama
            ? el("span", { class: "sinyal-aciklama" }, s.aciklama)
            : null,
        ),
      ),
  );
}

function renderKisisel(d) {
  const bolum = $("kisisel-bolum");
  $("kisisel-baslik").textContent =
    d.analysis_mode === "source_extracts" ? "Okuma notları" : "Kişisel analiz";
  const metin = (d.kisisel_analiz || "").trim();
  if (!metin) {
    bolum.classList.add("gizli");
    return;
  }
  bolum.classList.remove("gizli");
  paragrafYaz($("kisisel-icerik"), metin);
}

// karar string -> {token, etiket} (renk + insanca metin). Türkçe büyük-harf normalize.
const FC_KARAR = {
  DESTEKLİYOR: {
    token: "destekliyor",
    renk: "basari",
    etiket: "Destekleniyor",
  },
  ÇELİŞİYOR: { token: "celisiyor", renk: "hata", etiket: "Çelişiyor" },
  BELİRSİZ: { token: "belirsiz", renk: "uyari", etiket: "Belirsiz" },
};
function fcKart(it) {
  const k =
    it.bagimsiz_dogrulama === true
      ? FC_KARAR[(it.karar || "").toLocaleUpperCase("tr")] ||
        FC_KARAR["BELİRSİZ"]
      : FC_KARAR["BELİRSİZ"];
  const legacyDecision =
    it.bagimsiz_dogrulama !== true &&
    (!it.kanit_turu || it.kanit_turu === "bilinmiyor") &&
    ["DESTEKLİYOR", "ÇELİŞİYOR"].includes(
      (it.karar || "").toLocaleUpperCase("tr"),
    );
  const kaynaklar = (it.kaynaklar || [])
    .map((u) => {
      try {
        return new URL(u).hostname.replace(/^www\./, "");
      } catch {
        return null;
      }
    })
    .filter(Boolean);
  return el(
    "div",
    { class: "fc-kart", "data-karar": k.token },
    el(
      "div",
      { class: "fc-ust" },
      el("span", { class: "fc-iddia" }, it.iddia || "—"),
      rozetEl(k.renk, k.etiket),
    ),
    legacyDecision
      ? el(
          "div",
          { class: "fc-gerekce" },
          "Önceki kayıtta model kararı bulunuyor; bu kaydın kaynak kanıtı doğrulanmış değil.",
        )
      : it.gerekce
        ? el("div", { class: "fc-gerekce" }, it.gerekce)
        : null,
    it.bagimsiz_dogrulama !== true
      ? el(
          "p",
          { class: "field-note" },
          "Tam kaynak metnine dayanan bağımsız doğrulama kayıtlı değil; arama sonucu ve model değerlendirmesi doğruluk onayı değildir.",
        )
      : null,
    kaynaklar.length
      ? el(
          "div",
          { class: "fc-kaynaklar" },
          ...kaynaklar.map((h) => el("span", {}, h)),
        )
      : null,
  );
}
function renderFactcheck(d) {
  const bolum = $("factcheck-bolum");
  const iddialar = d.factcheck_iddialar || [];
  if (!iddialar.length) {
    if (d.factcheck_reason) {
      bolum.classList.remove("gizli");
      $("factcheck-ozet").textContent = "birincil kaynak";
      $("factcheck-liste").replaceChildren(
        el("p", { class: "kart field-note" }, d.factcheck_reason),
      );
      return;
    }
    bolum.classList.add("gizli");
    return;
  }
  bolum.classList.remove("gizli");
  const say = { destekliyor: 0, celisiyor: 0, belirsiz: 0 };
  for (const it of iddialar) {
    const k =
      it.bagimsiz_dogrulama === true
        ? FC_KARAR[(it.karar || "").toLocaleUpperCase("tr")]
        : FC_KARAR["BELİRSİZ"];
    if (k) say[k.token]++;
  }
  $("factcheck-ozet").textContent =
    `${iddialar.length} iddia · ${say.destekliyor} destekleniyor · ` +
    `${say.celisiyor} çelişiyor · ${say.belirsiz} belirsiz`;
  $("factcheck-liste").replaceChildren(...iddialar.map(fcKart));
}

function renderHarita(d) {
  const bolum = $("harita-bolum");
  const ad = "05_zihin-haritasi.html";
  if (d.harita_durum !== "uretildi" || !(veri && veri.klasor)) {
    frameBirak($("harita-cerceve"));
    bolum.classList.add("gizli");
    return;
  }
  bolum.classList.remove("gizli");
  if (demoAktif && demoPaket && demoPaket.DEMO_HARITA) {
    const cerceve = $("harita-cerceve");
    const demoBytes = new TextEncoder().encode(demoPaket.DEMO_HARITA);
    renderArtifact(cerceve, demoBytes, ad).catch(() =>
      cerceve.replaceChildren(
        el(
          "p",
          { class: "field-note" },
          "Örnek harita veri ağacı bu biçimde önizlenemiyor.",
        ),
      ),
    );
    $("harita-buyut").onclick = () => {
      const dialog = $("izleyici");
      $("izleyici-ad").textContent = "Zihin haritası · demo";
      $("izleyici-klasor").classList.add("gizli");
      if (!dialog.open) dialog.showModal();
      renderArtifact($("izleyici-cerceve"), demoBytes, ad).catch(() =>
        $("izleyici-cerceve").replaceChildren(
          el(
            "p",
            { class: "field-note" },
            "Örnek harita veri ağacı bu biçimde önizlenemiyor.",
          ),
        ),
      );
    };
    return;
  }
  frameDosyaYukle($("harita-cerceve"), veri.klasor, ad);
  $("harita-buyut").onclick = () => dosyaAc(veri.klasor, ad, "html");
}

function renderGuven(d) {
  const bant = $("guven-bant");
  const cloud =
    typeof d.cloud_cagrisi_sayisi === "number" ? d.cloud_cagrisi_sayisi : null;
  const yerel = cloud === 0;
  bant.classList.toggle("dikkat", !yerel);
  $("guven-baslik").textContent =
    cloud == null
      ? "Bulut LLM kaydı eksik"
      : yerel
        ? "Bulut LLM çağrısı yok"
        : `${cloud} bulut LLM çağrısı`;
  $("guven-alt").textContent =
    cloud == null
      ? "Bu sonuçta bulut dil modeli çağrı sayacı bulunmuyor. Kaynak ve ses aşamaları ayrıca gösterilir."
      : yerel
        ? "Bu sayaç dil modeli çağrılarını gösterir. Kaynak edinimi ve web doğrulaması internet erişimi içerebilir; ses motoru Ses aşamasında belirtilir."
        : "Bu analizde bulut dil modeli kullanıldı. Kaynaklar, kişi-adı koruması ve ses motoru kendi işlem aşamalarında gösterilir.";
  const cipler = [
    el(
      "span",
      { class: `mini-cip ${d.hedef === "local" ? "iyi" : "uyari"}` },
      d.hedef === "local" ? "⌂ yerel" : "☁ bulut",
    ),
  ];
  if (d.karmasiklik)
    cipler.push(
      el("span", { class: "mini-cip" }, `karmaşıklık · ${d.karmasiklik}`),
    );
  if (d.pii_tespit)
    cipler.push(
      el("span", { class: "mini-cip uyari" }, "⊘ kişisel veri tespit edildi"),
    );
  $("guven-cipler").replaceChildren(...cipler);
}

function metrikEtiketi(ad) {
  const sozluk = {
    yildiz: "Yıldız",
    fork: "Fork",
    acik_konu: "Açık konu",
    izleyen: "İzleyen",
    yazar_sayisi: "Yazar",
    kategori_sayisi: "Kategori",
    indirme: "İndirme",
    begeni: "Beğeni",
    puan: "Puan",
    oy_orani: "Oy oranı",
    yorum: "Yorum",
    kelime_sayisi: "Kelime",
    karakter_sayisi: "Karakter",
  };
  return sozluk[ad] || ad.replaceAll("_", " ");
}

function metrikDegeri(v) {
  return typeof v === "number"
    ? v.toLocaleString("tr-TR", { maximumFractionDigits: 2 })
    : String(v);
}

function renderKunye(d, idx) {
  const tur = idx.kaynak_turu || d.kaynak_turu || "youtube";
  const kaynak = KAYNAKLAR[tur] || KAYNAKLAR.web;
  const sahip = idx.kaynak_sahibi || idx.kanal || "";
  const tarihHam = idx.kaynak_tarihi || idx.yayin_tarihi || "";
  const tarih = String(tarihHam).slice(0, 10);
  const kimlik = idx.kaynak_id || idx.video_id || "";
  const kanonikUrl = idx.kaynak_url || idx.video_url || "";
  $("kaynak-hero-etiket").textContent =
    `${kaynak.kod} · ${kaynak.ad} kaynak analizi`;
  $("baslik").textContent = idx.baslik || "Başlık yok";

  const parcalar = [];
  if (sahip) parcalar.push(document.createTextNode(sahip));
  if (tarih) parcalar.push(document.createTextNode(tarih));
  const sure = tur === "youtube" ? sn2mmss(idx.sure_sn) : null;
  if (sure) parcalar.push(el("span", { class: "sure" }, sure));
  const meta = [];
  parcalar.forEach((p, i) => {
    if (i > 0)
      meta.push(el("span", { class: "ayrac", "aria-hidden": "true" }, "·"));
    meta.push(p);
  });
  $("kunye-meta").replaceChildren(...meta);

  const alt = [
    el("span", { class: "kaynak-rozeti" }, kaynak.ad),
    el("span", { class: "pill konu" }, idx.konu || "genel"),
  ];
  if (idx.anadil)
    alt.push(el("span", { class: "pill dil", title: "anadil" }, idx.anadil));
  if (kimlik) {
    const vc = el(
      "button",
      {
        class: "vid-cip",
        type: "button",
        title: "Kaynak kimliğini kopyala",
        onclick: () => {
          navigator.clipboard?.writeText(kanonikUrl || kimlik);
          vc.textContent = "kopyalandı ✓";
          setTimeout(() => (vc.textContent = kimlik), 1200);
        },
      },
      kimlik,
    );
    alt.push(vc);
  }
  $("kunye-alt").replaceChildren(...alt);

  const metrikler = idx.kaynak_metrikleri || {};
  $("kaynak-metrikleri").replaceChildren(
    ...Object.entries(metrikler)
      .slice(0, 6)
      .map(([ad, deger]) =>
        el(
          "span",
          { class: "kaynak-metrik" },
          el("span", { class: "metrik-ad" }, metrikEtiketi(ad)),
          el("span", {}, metrikDegeri(deger)),
        ),
      ),
  );

  const kw = idx.keywords || idx.kaynak_etiketleri || [];
  const cipler = kw.slice(0, 8).map((k) => el("span", { class: "kw" }, k));
  if (kw.length > 8)
    cipler.push(el("span", { class: "kw" }, `+${kw.length - 8}`));
  $("keywords").replaceChildren(...cipler);
}

function renderSkor(puan) {
  const halka = $("skor-halka"),
    dolum = $("skor-dolum"),
    sayi = $("skor-sayi");
  const cevre = 2 * Math.PI * 58;
  dolum.style.strokeDasharray = `${cevre}`;
  if (puan == null) {
    sayi.textContent = "—";
    dolum.style.strokeDashoffset = `${cevre}`;
    halka.style.setProperty("--halka-renk", "var(--metin-devredisi)");
    halka.setAttribute("aria-label", "BilgiDeğeri: veri yok");
    return;
  }
  const p = Math.max(0, Math.min(100, puan));
  halka.title =
    "BilgiDeğeri araştırma önceliğini gösterir; doğruluk oranı değildir.";
  const band = p >= 70 ? "yüksek" : p >= 40 ? "orta" : "düşük";
  halka.style.setProperty(
    "--halka-renk",
    p >= 70 ? "var(--basari)" : p >= 40 ? "var(--uyari)" : "var(--metin-soluk)",
  );
  sayi.textContent = Math.round(p);
  // band metni aria-label'da: nitelik (yüksek/orta/düşük) yalnız renkle iletilmesin (WCAG 1.4.1)
  halka.setAttribute(
    "aria-label",
    `BilgiDeğeri ${Math.round(p)} / 100 — ${band}`,
  );
  dolum.style.strokeDashoffset = `${cevre}`;
  requestAnimationFrame(
    () => (dolum.style.strokeDashoffset = `${cevre * (1 - p / 100)}`),
  );
}

const FAKTOR_AD = {
  novelty: "Özgünlük",
  rarity: "Nadirlik",
  nis: "Niş",
  recency: "Güncellik",
  length: "Uzunluk",
};
function renderFaktorler(f) {
  const satirlar = ["novelty", "rarity", "nis", "recency", "length"].map(
    (k) => {
      const v = f[k];
      const yok = v == null;
      const oran = yok ? 0 : Number(v) > 1 ? Number(v) / 100 : Number(v);
      const pct = Math.max(0, Math.min(100, oran * 100));
      return el(
        "div",
        { class: `faktor ${yok ? "yok" : ""}` },
        el("span", { class: "ad" }, FAKTOR_AD[k]),
        el(
          "span",
          { class: "iz" },
          el("span", { class: "dolum", style: `width:${pct}%` }),
        ),
        el("span", { class: "val" }, yok ? "veri yok" : oran.toFixed(2)),
      );
    },
  );
  $("faktorler").replaceChildren(...satirlar);
}

function faithRenk(v) {
  if (v == null) return "atlandi";
  return v >= 0.5 ? "uyari" : "hata";
}
function renderStepper(d) {
  const kaynakDurumu = d.kaynak_durumu || d.transkript_durumu;
  const tur = d.kaynak_turu || (d.index && d.index.kaynak_turu) || "youtube";
  const kaynakAdi = (KAYNAKLAR[tur] || {}).ad;
  const candidateOnly =
    d.factcheck_durum === "uretildi" &&
    !(d.factcheck_iddialar || []).some(
      (item) => item.bagimsiz_dogrulama === true,
    );
  const asamalar = [
    {
      ad: "İçerik",
      renk: renkBul(RENK.transkript, kaynakDurumu),
      durum: kaynakDurumu,
      alt: [kaynakAdi, d.transkript_kaynak_dil, d.asr_tier]
        .filter(Boolean)
        .join(" · "),
      hata: d.transkript_hata,
    },
    {
      ad: "Çeviri",
      renk: renkBul(RENK.ceviri, d.ceviri_durumu),
      durum: d.ceviri_durumu,
      alt: "",
    },
    {
      ad: "Döküm",
      renk: (d.dokum_segment_sayisi || 0) > 0 ? "basari" : "uyari",
      durum: (d.dokum_segment_sayisi || 0) > 0 ? "uretildi" : "icerik_yok",
      alt: `${d.dokum_segment_sayisi || 0} segment`,
    },
    {
      ad: "Özet",
      renk: faithRenk(d.ozet_faithfulness),
      durum: d.ozet_faithfulness_durum || "—",
      alt:
        d.ozet_faithfulness != null
          ? `%${Math.round(d.ozet_faithfulness * 100)} model destek tahmini`
          : "",
    },
    {
      ad: "İddia",
      renk: candidateOnly
        ? "uyari"
        : renkBul(RENK.factcheck, d.factcheck_durum),
      durum: candidateOnly ? "aday_inceleme" : d.factcheck_durum,
      alt: `${d.factcheck_iddia_sayisi || 0} iddia${candidateOnly ? " · kesin doğrulama yok" : ""}`,
      hata: d.factcheck_hata,
    },
    {
      ad: "Kişisel",
      renk: renkBul(RENK.durumlu, d.kisisel_durum),
      durum: d.kisisel_durum,
      alt: "",
      hata: d.kisisel_hata,
    },
    {
      ad: "Değerleme",
      renk: renkBul(RENK.durumlu, d.degerleme_durum),
      durum: d.degerleme_durum,
      alt: "",
      hata: d.degerleme_hata,
    },
    {
      ad: "Harita",
      renk: renkBul(RENK.harita, d.harita_durum),
      durum: d.harita_durum,
      alt: `${d.harita_dugum_sayisi || 0} düğüm`,
      hata: d.harita_hata,
    },
    {
      ad: "Ses",
      renk: renkBul(RENK.ses, d.ses_durum),
      durum: d.ses_durum,
      alt: d.ses_kaynak ? etiket(d.ses_kaynak) : "",
      hata: d.ses_hata,
    },
  ];
  const liler = asamalar.map((a) => {
    // Hata detayı (2026-08-24): durum=hata ise alt satırda kısa neden, title'da tam metin.
    const hataVar = a.durum === "hata" && a.hata;
    const altMetin = hataVar ? String(a.hata).slice(0, 110) : a.alt || " ";
    return el(
      "li",
      {
        "data-renk": a.renk,
        "aria-label": `${a.ad}: ${etiket(a.durum)}`,
        title: hataVar ? `${a.ad} hatası: ${a.hata}` : undefined,
      },
      el(
        "span",
        { class: "ust" },
        el(
          "span",
          { class: "nokta", "aria-hidden": "true" },
          IKON[a.renk] || "·",
        ),
        el("span", { class: "asama-ad" }, a.ad),
        rozetEl(a.renk, etiket(a.durum)),
      ),
      el("span", { class: hataVar ? "alt hata-detay" : "alt" }, altMetin),
    );
  });
  $("stepper").replaceChildren(...liler);
}

function renderCikti(d) {
  const tur = d.kaynak_turu || (d.index && d.index.kaynak_turu) || "youtube";
  const youtubeMu = tur === "youtube";
  const cevrildi = d.ceviri_durumu === "cevrildi";
  const sesVar = d.ses_durum === "uretildi";
  const sesUzanti = d.ses_kaynak === "cloud" ? "mp3" : "wav"; // cloud TTS .mp3 yazar (node.py)
  const dokumUzantilari = [
    ...new Set(
      (d.artifacts || [])
        .map((artifact) =>
          String(artifact.name || artifact.path || "")
            .split(/[\\/]/)
            .pop()
            .match(/^03_dokum\.([a-z0-9]+)$/i)?.[1]
            ?.toLowerCase(),
        )
        .filter(Boolean),
    ),
  ];
  const dokumTurleri = dokumUzantilari.length
    ? ` (${dokumUzantilari.join(" · ")})`
    : "";
  // [kod, etiket, görüntülenebilir-dosya-adı|null, tür] — dosya verilirse tıklanabilir buton.
  // Zihin haritası artık inline gömülü (harita-bolum) → dosya listesinden çıkarıldı.
  const gruplar = [
    ["Veri", [["00", "Dizin kaydı (index)", null]]],
    [
      youtubeMu ? "Transkript" : "Kaynak",
      [
        [
          "01",
          youtubeMu ? "Orijinal dil transkripti" : "Normalize kaynak içeriği",
          null,
        ],
        ...(cevrildi ? [["02", "Türkçe çeviri", null]] : []),
      ],
    ],
    [
      "Döküm",
      [
        [
          "03",
          `${youtubeMu ? "Kronolojik" : "Yapısal"} döküm${dokumTurleri}`,
          null,
        ],
      ],
    ],
    [
      "Özet",
      [
        ["04", "Özet (md)", null],
        ...(sesVar ? [["04", `Sesli özet (${sesUzanti})`, null]] : []),
        ...(!demoAktif && d.sunum_durum === "uretildi"
          ? [["04", "Sunum — görüntüle (pdf)", "04_ozet-sunum.pdf", "pdf"]]
          : []),
      ],
    ],
    [
      "İnceleme",
      [
        ["06", "İddia incelemesi", null],
        ["07", "Kişisel analiz", null],
        ["08", "Değerleme", null],
      ],
    ],
  ];
  const dugumler = gruplar.map(([grup, dosyalar]) =>
    el(
      "div",
      { class: "dosya-grup" },
      el("div", { class: "gad" }, grup),
      ...dosyalar.map(([dt, ad, dosya, tur]) =>
        dosya
          ? el(
              "button",
              {
                class: "dosya dosya-ac",
                type: "button",
                title: "görüntüle",
                onclick: () => dosyaAc(veri.klasor, dosya, tur),
              },
              el("span", { class: "dt" }, `${dt}_`),
              ad,
            )
          : el(
              "div",
              { class: "dosya" },
              el("span", { class: "dt" }, `${dt}_`),
              ad,
            ),
      ),
    ),
  );
  // Sesli özet için ses modeli yoksa: self-servis indirme affordance'ı (task 5).
  if (d.ses_durum === "ses_modeli_yok")
    dugumler.push(
      el(
        "p",
        { class: "field-note" },
        "Sesli özet için Windows Dil ve Konuşma ayarlarından Türkçe ses kurun.",
      ),
    );
  $("cikti").replaceChildren(...dugumler);
}

function renderTeknik(d) {
  const faith = d.ozet_faithfulness;
  const tur = d.kaynak_turu || (d.index && d.index.kaynak_turu) || "youtube";
  // Motor kökeni (2026-08-24 kullanıcı isteği): backend/model/profil her analizde görünür.
  const m = d.motor || (d.index && d.index.motor) || {};
  const kpi = [
    [
      "Model destek tahmini",
      faith != null ? `%${Math.round(faith * 100)}` : "—",
      faithRenk(faith) === "hata" ? "uyari" : "",
    ],
    [
      "Motor",
      m.backend ? `${m.backend}${m.profil ? " · " + m.profil : ""}` : "—",
      "",
    ],
    ["Dil modeli (LLM)", m.llm_model || "—", ""],
    ["Embedding modeli", m.embedding_model || "—", ""],
    ["Bağlam (ctx)", m.num_ctx || "—", ""],
    ["Döküm segmenti", d.dokum_segment_sayisi ?? "—", ""],
    ["Fact-check iddia", d.factcheck_iddia_sayisi ?? "—", ""],
    ["Harita düğümü", d.harita_dugum_sayisi ?? "—", ""],
    [
      "Kaynak içerik karakter",
      (d.transkript_karakter ?? 0).toLocaleString("tr-TR"),
      "",
    ],
    ["Kaynak", (KAYNAKLAR[tur] || KAYNAKLAR.web).ad, ""],
    [
      m.backend === "llamacpp" ? "llama.cpp ping" : "Ollama ping",
      d.ollama_ping_ms != null ? `${Math.round(d.ollama_ping_ms)} ms` : "—",
      d.ollama_ping_ms > 2000 ? "uyari" : "",
    ],
    ["Hedef", d.hedef || "—", ""],
    ["Karmaşıklık", d.karmasiklik || "—", ""],
    [
      "Bulut token (girdi/çıktı)",
      (d.cloud_girdi_token || 0) === 0 && (d.cloud_cikti_token || 0) === 0
        ? "yerel · yok"
        : `${(d.cloud_girdi_token || 0).toLocaleString("tr-TR")} / ${(d.cloud_cikti_token || 0).toLocaleString("tr-TR")}`,
      (d.cloud_girdi_token || 0) === 0 ? "soluk" : "",
    ],
  ];
  $("kpi-izgara").replaceChildren(
    ...kpi.map(([k, v, s]) =>
      el(
        "div",
        { class: "kpi" },
        el("div", { class: "k" }, k),
        el("div", { class: `v ${s}` }, String(v)),
      ),
    ),
  );
  const onay = [
    ["İndekslendi", d.index_eklendi],
    ["Belleğe eklendi", d.bellek_eklendi],
    ["Commit'lendi", d.commit_yapildi],
  ];
  $("onay-cipler").replaceChildren(
    ...onay.map(([ad, v]) =>
      el(
        "span",
        { class: `mini-cip ${v ? "iyi" : ""}` },
        `${v ? "✓" : "–"} ${ad}`,
      ),
    ),
  );
}

/* ---- 4. klasörü aç (analiz sonucu + kütüphane kartı ortak) -------------- */
async function klasorAc(klasor, geri) {
  if (!klasor) return;
  if (demoAktif) {
    if (geri) {
      geri.textContent = " · demo klasörü";
      geri.className = "klasor-geri iyi";
      setTimeout(() => (geri.textContent = ""), 1800);
    }
    return;
  }
  if (geri) {
    geri.textContent = "";
    geri.className = "klasor-geri";
  }
  try {
    const r = await sidecarFetch(`${SIDECAR}/gui/klasor_ac`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ klasor }),
    });
    if (!geri) return; // kütüphane kartı: sessiz (geri-bildirim alanı yok)
    if (r.status === 404) {
      geri.textContent = " · bu sürümde yok";
      geri.classList.add("kotu");
      return;
    }
    const d = await r.json().catch(() => null);
    if (r.ok) {
      geri.textContent = " · açıldı";
      geri.classList.add("iyi");
      setTimeout(() => (geri.textContent = ""), 2000);
    } else {
      geri.textContent = ` · ${(d && d.hata) || "açılamadı"}`;
      geri.classList.add("kotu");
    }
  } catch {
    if (geri) {
      geri.textContent = " · motora ulaşılamadı";
      geri.classList.add("kotu");
    }
  }
}

/* ---- 5. Yerel canvas / veri ağacı görüntüleyici ----------------------- */
function dosyaAc(klasor, ad, tur) {
  if (!klasor) return;
  const dialog = $("izleyici");
  $("izleyici-ad").textContent = ad;
  $("izleyici-cerceve").setAttribute(
    "aria-label",
    `Çıktı görüntüleyici: ${ad}`,
  );
  frameDosyaYukle($("izleyici-cerceve"), klasor, ad);
  $("izleyici-klasor").onclick = () => klasorAc(klasor);
  if (!dialog.open) dialog.showModal();
}
function izleyiciKapat() {
  frameBirak($("izleyici-cerceve")); // bağlantı/bellek bırak (büyük PDF)
  $("izleyici-klasor").classList.remove("gizli");
  if ($("izleyici").open) $("izleyici").close();
}

/* ---- 6. model seçici + arama servisi rozeti ---------------------------- */
async function modelleriHazirla() {
  if (!modelEl) return;
  if (demoAktif && demoPaket) {
    modelEl.replaceChildren(
      el("option", { value: "" }, "Otomatik (demo)"),
      ...demoPaket.DEMO_MODELLER.map((m) => el("option", { value: m }, m)),
    );
    return;
  }
  // Birleşik analiz modeli API'deki analysis_profile ayarıyla seçilir.
  // Eski Ollama/Gemma dropdown'u bu endpoint'in kullandığı modeli temsil etmez.
}
function modelDurumGuncelle() {
  const opt = modelEl && modelEl.selectedOptions[0];
  const uyari = $("model-uyari");
  if (opt && opt.getAttribute("data-durum") === "asar") {
    uyari.textContent =
      "⚠ Seçilen model 16GB VRAM sınırını aşabilir; analiz yavaşlayabilir veya belleğe taşabilir. Yine de kullanılabilir.";
    uyari.classList.remove("gizli");
  } else {
    uyari.classList.add("gizli");
  }
}
async function kurulumDurumu() {
  const cip = $("arama-cip");
  if (demoAktif) {
    cip.textContent = "arama: demo";
    cip.className = "mini-cip iyi";
    const nerCip = $("ner-cip");
    if (nerCip) {
      nerCip.textContent = "NER: demo";
      nerCip.className = "mini-cip iyi";
    }
    return;
  }
  try {
    const r = await sidecarFetch(`${SIDECAR}/gui/kurulum`);
    if (!r.ok) return;
    const d = await r.json();
    const aktif = !!(
      d.firecrawl_erisilebilir ||
      d.searxng_erisilebilir ||
      d.websearch_anahtar_var
    );
    cip.textContent = aktif ? "Web adaptörü: hazır" : "Web adaptörü: kapalı";
    cip.classList.remove("gizli");
    cip.classList.toggle("iyi", aktif);
    cip.classList.toggle("kapali", !aktif);
    cip.title = aktif
      ? "Dış kaynak bağlantısı kullanılabilir. Web aramasını her araştırmada ayrıca seçin."
      : "Dış kaynak arama bağlantısı bulunamadı. Yerel araştırma kullanılabilir.";
    cip.setAttribute("aria-label", `${cip.textContent} — ${cip.title}`); // ipucu SR'a da

    // NER rozeti: tam web fact-check, kişi-adı koruması (NER) erişilebilir olmasını gerektirir.
    // NER yoksa kişi içeren iddialar fail-closed (web'e/buluta GÖNDERİLMEZ) — KVKK; rozet bunu der.
    const nerCip = $("ner-cip");
    if (nerCip) {
      const nerAktif = !!d.ner_erisilebilir;
      nerCip.textContent = nerAktif ? "NER: aktif" : "NER: yok";
      nerCip.classList.remove("gizli");
      nerCip.classList.toggle("iyi", nerAktif);
      nerCip.classList.toggle("kapali", !nerAktif);
      nerCip.title = nerAktif
        ? "Kişi-adı koruması kullanılabilir. Dış kaynak sorguları ayrıca seçtiğiniz web ayarına bağlıdır."
        : "NER bileşeni kullanılamıyor. Kişi içeren iddialar dış aramaya gönderilmez; yerel analiz kullanılabilir. Ayarlar'daki kurulum durumunu kontrol edin.";
      nerCip.setAttribute(
        "aria-label",
        `${nerCip.textContent} — ${nerCip.title}`,
      );
    }
  } catch {
    /* sessiz */
  }
}

/* ---- 7. görünüm geçişi + kütüphane ------------------------------------- */
const GORUNUMLER = [
  "akis",
  "analiz",
  "arastir",
  "calisma",
  "konular",
  "kaynaklar",
];
function setGorunum(ad) {
  if (!loginGate?.allowed()) return;
  if (ad === "ayarlar") {
    if (!$("gorunum-ayarlar").open) $("gorunum-ayarlar").showModal();
    ayarlarYukle();
    return;
  }
  if (ad === "kutuphane") ad = "calisma";
  if (!GORUNUMLER.includes(ad)) ad = "akis";
  document.body.classList.toggle("research-active", ad === "arastir");
  for (const g of GORUNUMLER) {
    $(`gorunum-${g}`).classList.toggle("gizli", g !== ad);
    const s = $(`sekme-${g}`);
    s.setAttribute("aria-selected", String(g === ad));
    s.tabIndex = g === ad ? 0 : -1; // roving tabindex (WAI-ARIA tab klavye sözleşmesi)
  }
  if (ad === "calisma") kutuphaneYukle();
  productUI.viewChanged(ad);
}

async function kutuphaneYukle(zorla) {
  if (demoAktif && demoPaket) {
    kutuphaneVeri = demoPaket.DEMO_KUTUPHANE;
    kutuphaneYuklendi = true;
    const konular = [
      ...new Set(kutuphaneVeri.map((k) => k.konu).filter(Boolean)),
    ].sort();
    $("kutuphane-konu").replaceChildren(
      el("option", { value: "" }, "Tümü"),
      ...konular.map((k) => el("option", { value: k }, k)),
    );
    kutuphaneRender();
    return;
  }
  if (kutuphaneYuklendi && !zorla) {
    kutuphaneRender();
    return;
  }
  try {
    const r = await sidecarFetch(`${SIDECAR}/gui/kutuphane`);
    if (!r.ok) {
      kutuphaneVeri = [];
      kutuphaneBos("hata");
      return;
    }
    kutuphaneVeri = await r.json();
    kutuphaneYuklendi = true;
    const konular = [
      ...new Set((kutuphaneVeri || []).map((k) => k.konu).filter(Boolean)),
    ].sort();
    $("kutuphane-konu").replaceChildren(
      el("option", { value: "" }, "Tümü"),
      ...konular.map((k) => el("option", { value: k }, k)),
    );
    kutuphaneRender();
  } catch {
    kutuphaneVeri = [];
    kutuphaneBos("hata");
  }
}
function kutuphaneBos(tip) {
  $("kutuphane-izgara").replaceChildren();
  $("kutuphane-sayac").textContent = "";
  const bos = $("kutuphane-bos");
  bos.classList.remove("gizli");
  const icerik = {
    ilk: [
      "Henüz analiz yok",
      "İlk kaynağınızı analiz edin — sonuçlar burada birikecek.",
      "Analize geç",
    ],
    arama: [
      "Eşleşme yok",
      "Arama/filtreyi temizleyince tüm analizler görünür.",
      "Filtreyi temizle",
    ],
    hata: [
      "Yüklenemedi",
      "Motora ulaşılamadı. Sidecar çalışıyor mu?",
      "Tekrar dene",
    ],
  }[tip];
  const aksiyon =
    tip === "ilk"
      ? () => {
          setGorunum("analiz");
          urlEl.focus(); // panel gizlenince odak görünür ögeye taşınsın (WCAG 2.4.3)
        }
      : tip === "arama"
        ? () => {
            $("kutuphane-ara").value = "";
            $("kutuphane-konu").value = "";
            $("kutuphane-kaynak").value = "";
            kutuphaneRender();
          }
        : () => kutuphaneYukle(true);
  bos.replaceChildren(
    el("h3", {}, icerik[0]),
    el("p", {}, icerik[1]),
    el("button", { class: "btn", type: "button", onclick: aksiyon }, icerik[2]),
  );
}
function kutuphaneRender() {
  if (!kutuphaneVeri) return;
  if (!kutuphaneVeri.length) {
    kutuphaneBos("ilk");
    return;
  }
  const q = $("kutuphane-ara").value.trim().toLocaleLowerCase("tr");
  const konu = $("kutuphane-konu").value;
  const kaynak = $("kutuphane-kaynak").value;
  const sirala = $("kutuphane-sirala").value;
  let liste = kutuphaneVeri.filter((k) => {
    if (konu && k.konu !== konu) return false;
    if (kaynak && (k.kaynak_turu || "youtube") !== kaynak) return false;
    if (!q) return true;
    return [k.baslik, k.kaynak_sahibi, k.kanal, k.konu, k.kaynak_turu].some(
      (x) => (x || "").toLocaleLowerCase("tr").includes(q),
    );
  });
  liste = [...liste].sort((a, b) => {
    if (sirala === "puan") return (b.puan ?? -1) - (a.puan ?? -1);
    if (sirala === "baslik")
      return (a.baslik || "").localeCompare(b.baslik || "", "tr");
    return String(b.tarih).localeCompare(String(a.tarih)); // tarih azalan
  });
  $("kutuphane-sayac").textContent = `${liste.length} analiz`;
  if (!liste.length) {
    kutuphaneBos("arama");
    return;
  }
  $("kutuphane-bos").classList.add("gizli");
  $("kutuphane-izgara").replaceChildren(...liste.map(kutuphaneKart));
}
function kutuphaneKart(k) {
  const tur = k.kaynak_turu || "youtube";
  const kaynak = KAYNAKLAR[tur] || KAYNAKLAR.web;
  const meta = [k.kaynak_sahibi || k.kanal, k.tarih]
    .filter(Boolean)
    .join(" · ");
  const puanCls =
    k.puan == null ? "" : k.puan >= 70 ? "iyi" : k.puan >= 40 ? "orta" : "";
  const alt = [el("span", { class: "pill konu" }, k.konu || "genel")];
  if (k.puan != null)
    alt.push(
      el("span", { class: `k-puan ${puanCls}` }, `${Math.round(k.puan)}`),
    );
  alt.push(el("span", { class: "kaynak-rozeti" }, kaynak.ad));
  return el(
    "button",
    {
      class: "kutuphane-kart",
      type: "button",
      onclick: () => klasorAc(k.klasor),
    },
    el("span", { class: "k-baslik" }, k.baslik || "(başlık yok)"),
    el("span", { class: "k-meta" }, meta || "—"),
    el("span", { class: "k-alt" }, ...alt),
  );
}

/* ---- 8. Ayarlar (Ollama yapılandırma + test + model tespit) ------------- */
let ayarOutputBase = "";
let ayarlarYukleniyor = false;

async function ayarlarYukle() {
  if (ayarlarYukleniyor) return;
  const status = $("ayarlar-baglanti-durum");
  ayarlarYukleniyor = true;
  if (status) {
    status.textContent = "Yerel motor ve dosya konumu okunuyor…";
    status.classList.remove("status-error");
  }
  if (demoAktif && demoPaket) {
    const d = demoPaket.DEMO_AYARLAR;
    $("ayar-ollama-host").value = d.ollama_host;
    ayarOutputBase = d.output_base;
    $("ayar-output-base").textContent = d.output_base;
    $("ayar-host-kaynak").textContent = "Kaynak: demo yapılandırması";
    $("ayar-motor-kok").value = d.motor_kok;
    $("ayar-motor-durum").textContent = `Bulundu: ${d.motor_kok}`;
    await renderMotorlar();
    ayarTest();
    ayarlarYukleniyor = false;
    if (status) status.textContent = "Demo yapılandırması gösteriliyor.";
    return;
  }
  try {
    const r = await sidecarFetch(`${SIDECAR}/gui/ayarlar`);
    if (!r.ok) throw new Error("Yerel ayarlar okunamadı. Yeniden yükleyin.");
    if (r.ok) {
      const d = await r.json();
      if ($("ayar-ollama-host").dataset.edited !== "true")
        $("ayar-ollama-host").value = d.ollama_host || "";
      ayarOutputBase = d.output_base || "";
      $("ayar-output-base").textContent = ayarOutputBase || "—";
      const kaynak = {
        env: "OLLAMA_HOST ortam değişkeninden (öncelikli)",
        ayar: "kayıtlı ayardan",
        varsayilan: "varsayılan",
      };
      $("ayar-host-kaynak").textContent =
        `Kaynak: ${kaynak[d.ollama_host_kaynak] || d.ollama_host_kaynak || "yapılandırma bilgisi yok"}`;
      $("ayar-motor-kok").value = d.output_base || "";
      $("ayar-motor-durum").textContent =
        "Yeni analizlerin çalışma dosyaları burada tutulur. Varsayılan konum uygulamanın yerel veri alanıdır. OneDrive gibi eşitleme kapsamındaki bir klasörü seçerseniz o servis dosyaları eşitleyebilir. Veritabanı uygulamanın yerel veri alanında kalır.";
    }
    await renderMotorlar();
    if (status) status.textContent = "Yerel yapılandırma güncel. Bağlantı testleri isteğe bağlıdır.";
  } catch (error) {
    if (status) {
      status.textContent = error.message || "Yerel ayarlar okunamadı. Yeniden yükleyin.";
      status.classList.add("status-error");
    }
  } finally {
    ayarlarYukleniyor = false;
  }
}

async function ayarTest() {
  const input = $("ayar-ollama-host").value.trim();
  const host = input && !input.includes("://") ? `http://${input}` : input;
  const durum = $("ayar-ollama-durum");
  const button = $("ayar-test-btn");
  button.disabled = true;
  durum.className = "ayar-durum bekle";
  durum.textContent = "Test ediliyor…";
  $("ayar-modeller").replaceChildren();
  if (demoAktif && demoPaket) {
    durum.className = "ayar-durum iyi";
    durum.textContent = `✓ Demo motor hazır · ${demoPaket.DEMO_MODELLER.length} model bulundu`;
    $("ayar-modeller").replaceChildren(
      ...demoPaket.DEMO_MODELLER.map((m) => el("span", { class: "kw" }, m)),
    );
    button.disabled = false;
    return;
  }
  try {
    const r = await sidecarFetch(`${SIDECAR}/gui/ollama_test`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ host }),
    });
    const d = await r.json().catch(() => null);
    if (d && d.erisilebilir) {
      durum.className = "ayar-durum iyi";
      durum.textContent = `✓ Bağlandı${d.surum ? " · Ollama " + d.surum : ""} · ${d.model_sayisi} model bulundu`;
      $("ayar-modeller").replaceChildren(
        ...(d.modeller || []).map((m) => el("span", { class: "kw" }, m)),
      );
    } else {
      durum.className = "ayar-durum kotu";
      durum.textContent = `Bağlantı kurulamadı: ${d?.hata || d?.error || "Bu adreste çalışan Ollama bulunamadı."}`;
    }
  } catch (error) {
    durum.className = "ayar-durum kotu";
    durum.textContent = error.message || "Bağlantı testi tamamlanamadı. Yerel servisi kontrol ederek yeniden deneyin.";
  } finally {
    button.disabled = false;
  }
}

async function renderMotorlar() {
  const kap = $("ayar-motorlar");
  const satir = (ad, aktif, detay) =>
    el(
      "div",
      { class: "ayar-motor" },
      el(
        "span",
        { class: `mini-cip ${aktif ? "iyi" : "kapali"}` },
        aktif ? "✓ hazır" : "– yok",
      ),
      el("span", { class: "ayar-motor-ad" }, ad),
      detay ? el("span", { class: "ayar-motor-detay mono" }, detay) : null,
    );
  if (demoAktif) {
    kap.replaceChildren(
      satir("Ollama — yerel LLM / embedding", true, "demo"),
      satir("NER — kişi-adı koruması", true, "demo"),
      satir("Piper — Türkçe ses modeli", true, "demo"),
      satir(
        "Kaynak adapter'ları — YouTube · GitHub · arXiv · Reddit · Hugging Face · Web",
        true,
        "6/6",
      ),
    );
    return;
  }
  try {
    const r = await sidecarFetch(`${SIDECAR}/gui/kurulum`);
    if (!r.ok) throw new Error("Yerel motorların durumu okunamadı.");
    const d = await r.json();
    const ogeler = [
      el(
        "div",
        { class: "ayar-motor" },
        el("span", { class: "ayar-motor-ad" }, "Yerel analiz modelleri"),
        el(
          "span",
          { class: "ayar-motor-detay" },
          "Kurulum ve checksum durumu İlk kurulum ekranında görünür.",
        ),
      ),
      satir(
        "NER — kişi-adı koruması (web fact-check)",
        !!d.ner_erisilebilir,
        d.ner_kaynak,
      ),
      el(
        "div",
        { class: "ayar-motor" },
        el("span", { class: "ayar-motor-ad" }, "Windows Türkçe ses motoru"),
        el(
          "span",
          { class: "ayar-motor-detay" },
          "Durum için Windows Dil ve Konuşma ayarlarını kontrol edin.",
        ),
      ),
    ];
    kap.replaceChildren(...ogeler);
  } catch (error) {
    kap.replaceChildren(el("p", { class: "status-error", role: "status" }, error.message || "Yerel motorların durumu okunamadı. Ayarları yeniden yükleyin."));
    throw error;
  }
}

async function ayarMotorKaydet() {
  const geri = $("ayar-motor-geri");
  if (!window.rasathane?.selectWorkspace) {
    geri.textContent = "Konum seçimi masaüstü uygulamasında kullanılabilir.";
    return;
  }
  try {
    const selected = await window.rasathane.selectWorkspace();
    if (selected.cancelled) return;
    if (selected.path) $("ayar-motor-kok").value = selected.path;
    geri.textContent =
      "Çalışma alanı değişti. Yeni konum yeniden açıldığında kullanılacak; mevcut dosyalar yerinde kalır.";
  } catch (error) {
    geri.textContent = error.message || "Konum seçilemedi.";
  }
}

/* İlk açılış / sonrası: tam özellik hazır değilse onboarding şeridiyle Ayarlar'a yönlendir. */
async function onboardingKontrol() {
  if (demoAktif) {
    $("onboarding-serit").classList.add("gizli");
    return;
  }
  try {
    const r = await sidecarFetch(`${SIDECAR}/gui/kurulum`);
    if (!r.ok) return;
    const d = await r.json();
    const serit = $("onboarding-serit");
    const eksik = [];
    if (window.rasathane?.setupStatus) {
      const setup = await window.rasathane.setupStatus();
      if (!setup.ready) eksik.push("yerel analiz modelleri");
    }
    if (!d.ner_erisilebilir) eksik.push("kişi-adı koruması (NER)");
    if (!eksik.length) {
      serit.classList.add("gizli");
      return;
    }
    $("onboarding-alt").textContent =
      `Eksik bileşenler: ${eksik.join(" · ")}. Ayarlar'dan kontrol edin.`;
    serit.classList.remove("gizli");
  } catch {
    /* sessiz */
  }
}

/* ---- olay bağlama ------------------------------------------------------- */
btn.addEventListener("click", analizEt);
urlEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !btn.disabled) analizEt();
});
urlEl.addEventListener("input", () => {
  urlEl.removeAttribute("aria-invalid");
  kaynakAlgisiniGuncelle();
});
$("tekrar-btn").addEventListener("click", () => {
  hataBant.classList.add("gizli");
  if (urlEl.value.trim()) analizEt();
});
$("klasor-ac").addEventListener("click", () =>
  klasorAc(veri && veri.klasor, $("klasor-geri")),
);
if (modelEl) modelEl.addEventListener("change", modelDurumGuncelle);
for (const view of GORUNUMLER)
  $("sekme-" + view).addEventListener("click", () => setGorunum(view));
$("ayar-test-btn").addEventListener("click", ayarTest);
$("ayar-motor-kaydet").addEventListener("click", ayarMotorKaydet);
$("onboarding-btn").addEventListener("click", () => setGorunum("ayarlar"));
$("ayar-ollama-host").addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    if (!$("ayar-test-btn").disabled) ayarTest();
  }
});
$("ayar-ollama-host").addEventListener("input", () => {
  $("ayar-ollama-host").dataset.edited = "true";
});
window.addEventListener("rasathane:settings-reload", ayarlarYukle);
$("ayar-klasor-ac").addEventListener("click", () =>
  klasorAc(ayarOutputBase, $("ayar-klasor-geri")),
);
// WAI-ARIA tab klavye sözleşmesi: ok-tuşları sekmeler arası gezer + etkinleştirir.
document.querySelector(".sekmeler").addEventListener("keydown", (e) => {
  const sekmeler = GORUNUMLER.map((view) => "sekme-" + view);
  const aktif = sekmeler.findIndex(
    (id) => $(id).getAttribute("aria-selected") === "true",
  );
  let hedef = null;
  if (e.key === "ArrowRight" || e.key === "ArrowDown")
    hedef = (aktif + 1) % sekmeler.length;
  else if (e.key === "ArrowLeft" || e.key === "ArrowUp")
    hedef = (aktif - 1 + sekmeler.length) % sekmeler.length;
  else if (e.key === "Home") hedef = 0;
  else if (e.key === "End") hedef = sekmeler.length - 1;
  if (hedef == null) return;
  e.preventDefault();
  const id = sekmeler[hedef];
  setGorunum($(id).dataset.gorunum);
  $(id).focus();
});
for (const id of [
  "kutuphane-ara",
  "kutuphane-sirala",
  "kutuphane-konu",
  "kutuphane-kaynak",
]) {
  $(id).addEventListener("input", kutuphaneRender);
}
$("izleyici-kapat").addEventListener("click", izleyiciKapat);
$("izleyici").addEventListener("close", () => {
  frameBirak($("izleyici-cerceve"));
  $("izleyici-klasor").classList.remove("gizli");
});
$("izleyici").addEventListener("click", (e) => {
  if (e.target.id === "izleyici") izleyiciKapat(); // backdrop tıklaması
});

const productUI = createProductUI({
  $,
  el,
  request: (path, options = {}) => sidecarFetch(SIDECAR + path, options),
  setView: setGorunum,
  onAnalysis: (result) => {
    veri = result;
    render(result);
  },
  analysisProgress: (text) => {
    $("calisma-metin").textContent = text;
  },
  onSettings: () => {
    modelleriHazirla();
    kurulumDurumu();
  },
});
createProfileSettings({ $, onSettings: () => setGorunum("ayarlar") });
loginGate = createLoginGate({
  $,
  onUnlock: () => {
    productUI.unlock();
    sidecarHazirla();
  },
  onLock: () => {
    productUI.lock();
    clearAllArtifacts();
    veri = null;
    kutuphaneVeri = [];
    kutuphaneYuklendi = false;
    for (const audio of document.querySelectorAll("audio")) {
      audio.pause();
      audio.removeAttribute("src");
      audio.load();
    }
    window.location.reload();
  },
});
window.addEventListener("beforeunload", () => {
  clearAllArtifacts();
});
