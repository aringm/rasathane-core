"use strict";

// Opt-in acceptance in the actual packaged main/preload/sidecar path.
// Uses Electron's test input, stays hidden, and never supplies an auth bypass.
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
async function verifyProductUI(window) {
  const web = window.webContents;
  const js = source => web.executeJavaScript(source, true);
  async function wait(source, timeout = 30000) {
    const until = Date.now() + timeout;
    while (Date.now() < until) { if (await js(`Boolean(${source})`)) return; await pause(150); }
    throw new Error("Ürün UI kabul kontrolü zaman aşımı: " + source.slice(0, 120));
  }
  async function pointer(selector) {
    const point = await js(`(() => { const n = document.querySelector(${JSON.stringify(selector)}); if (!n || n.disabled) throw Error('Kontrol hazır değil'); n.scrollIntoView({block:'nearest'}); const r=n.getBoundingClientRect(); if (!r.width || !r.height) throw Error('Kontrol görünür değil'); return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)}; })()`);
    web.sendInputEvent({ type: "mouseMove", ...point });
    web.sendInputEvent({ type: "mouseDown", button: "left", clickCount: 1, ...point });
    await pause(60);
    web.sendInputEvent({ type: "mouseUp", button: "left", clickCount: 1, ...point });
    await pause(150);
  }
  await wait(`!document.body.classList.contains('session-locked') && document.querySelector('#gundem-durum')?.textContent && document.querySelector('#kaynak-sohbet-form')`);
  const shell = await js(`(() => {
    const nav=document.querySelector('.app-nav').getBoundingClientRect();
    return {tabs:document.querySelectorAll('.app-nav [data-gorunum]').length,
      retiredPresent:!!document.querySelector('#sekme-calisma,#sekme-konular,#gorunum-calisma,#gorunum-konular,#arastir-alan,#urun-takip-sikligi'),
      centered:Math.abs(nav.x+nav.width/2-document.documentElement.clientWidth/2)<2,
      overflow:document.documentElement.scrollWidth>innerWidth+1,
      analysisArchive:!!document.querySelector('#gorunum-analiz #analiz-arsivi')};
  })()`);
  if (shell.tabs!==4 || shell.retiredPresent || !shell.centered || shell.overflow || !shell.analysisArchive) throw new Error("Sade gezinme ve header kabulü doğrulanamadı.");
  const before = await js(`window.rasathane.request('/api/rasathane/settings')`);
  if (!before.ok) throw new Error("Ayar readback alınamadı.");
  await js(`for(const d of document.querySelectorAll('dialog[open]'))d.close()`);
  await pointer("#header-ayarlar");
  await wait(`document.querySelector('#gorunum-ayarlar').open && !document.querySelector('#ayarlar-kaydet').disabled`);
  await pointer("#ayarlar-kaydet");
  await wait(`document.querySelector('#urun-ayar-sonuc').textContent.includes('Ayarlar kaydedildi')`);
  const after = await js(`window.rasathane.request('/api/rasathane/settings')`);
  if (!after.ok || JSON.stringify(before.data) !== JSON.stringify(after.data)) throw new Error("Mevcut ayarları kaydetme readback'i eşleşmedi.");
  await pointer("#ayarlar-kapat");
  await pointer("#profil-ac");
  await wait(`!document.querySelector('#profil-menu').hidden`);
  await pointer("#profil-ayarlar");
  await wait(`document.querySelector('#gorunum-ayarlar').open`);
  await pointer("#ayarlar-kapat");
  await pointer('[data-gorunum="kaynaklar"]');
  await wait(`!document.querySelector('#gorunum-kaynaklar').classList.contains('gizli')`);
  const sources = await js(`({categories:document.querySelectorAll('#kaynak-kategori-filter button').length, groups:document.querySelectorAll('.source-group').length, rows:document.querySelectorAll('[data-source-id]').length})`);
  if (sources.rows && (sources.categories < 2 || sources.groups < 1)) throw new Error("Kaynak kategorileri arayüzde doğrulanamadı.");
  await pointer('[data-gorunum="akis"]');
  const agenda = await js(`window.rasathane.request('/api/rasathane/agenda')`);
  if (!agenda.ok || !agenda.data.profile || !agenda.data.status) throw new Error("Kişisel gündem IPC readback alınamadı.");
  console.log(JSON.stringify({smoke:"product-settings-pointer", authenticated:true, headerSettings:true, profileSettings:true, unchangedSettingsSaveReadback:true, agendaProfilePresent:true, categorizedSources:sources, productShell:shell}));
  if (process.env.RASATHANE_SMOKE_NEWS_ITEM) {
    const item = JSON.parse(process.env.RASATHANE_SMOKE_NEWS_ITEM);
    if (typeof item.id !== "string" || typeof item.title !== "string" || !item.id || !item.title) throw new Error("Haber smoke kaydı geçersiz.");
    await pointer('[data-gorunum="akis"]');
    await js(`(() => { const input=document.querySelector('#akis-ara'); input.value=${JSON.stringify(item.title)}; input.dispatchEvent(new Event('input',{bubbles:true})); })()`);
    const card = `.radar-entry[data-article-id=${JSON.stringify(item.id)}]`;
    await wait(`document.querySelector(${JSON.stringify(card)})`, 30000);
    const started = Date.now();
    await pointer(card + " .news-summarize");
    const deadline = started + 10 * 60000;
    let saved;
    while (Date.now() < deadline) {
      const response = await js(`window.rasathane.request(${JSON.stringify(`/api/rasathane/articles?query=${encodeURIComponent(item.title)}&limit=25`)})`);
      if (!response.ok) throw new Error("Türkçe haber readback alınamadı.");
      saved = response.data.items.find(row => row.id === item.id)?.summary_display;
      if (saved?.status === "ready") break;
      if (["failed", "unavailable"].includes(saved?.status)) throw new Error("Gerçek Türkçe haber özeti hazırlanamadı: " + (saved.error || saved.notice || saved.status));
      await pause(1500);
    }
    if (saved?.status !== "ready" || saved.language !== "tr" || saved.method !== "local_model" ||
        !saved.summary?.trim() || !/^[a-f0-9]{64}$/.test(saved.source_hash || "") ||
        !saved.evidence_quote || !saved.source_excerpt?.includes(saved.evidence_quote) || saved.url !== item.url) {
      throw new Error("Gerçek haberin Türkçe özeti ve kaynak alıntısı doğrulanamadı.");
    }
    await wait(`document.querySelector(${JSON.stringify(card + " .radar-entry-excerpt")})?.textContent.includes(${JSON.stringify(saved.summary.slice(0, 80))}) && !document.querySelector(${JSON.stringify(card + " .news-summarize")})?.disabled`, 15000);
    await pointer(card + " .news-speak");
    await wait(`document.querySelector(${JSON.stringify(card + " audio")})?.readyState>=2 && document.querySelector(${JSON.stringify(card + " audio")})?.duration>0`, 90000);
    const visible = await js(`(() => { const node=document.querySelector(${JSON.stringify(card)}); const audio=node.querySelector('audio'); return {actions:node.querySelector('.news-actions').children.length,sourceURL:node.querySelector('.news-actions a').href,excerpt:node.querySelector('.radar-entry-excerpt').textContent,speechSeconds:audio.duration}; })()`);
    if (visible.actions !== 4 || visible.sourceURL !== item.url || visible.excerpt.includes("Article URL:")) throw new Error("Haber kartının doğrudan eylemleri doğrulanamadı.");
    console.log(JSON.stringify({smoke:"product-news-summary-speech", articleId:item.id, url:item.url, durationMs:Date.now()-started, method:saved.method, language:saved.language, sourceHash:saved.source_hash, groundedQuote:true, cachedReadback:true, inlineSummary:true, actions:visible.actions, speechSeconds:visible.speechSeconds}));
  }
  if (process.env.RASATHANE_SMOKE_SOURCE_URL) {
    const sourceURL = new URL(process.env.RASATHANE_SMOKE_SOURCE_URL);
    if (!["https:", "http:"].includes(sourceURL.protocol) || sourceURL.username || sourceURL.password) throw new Error("Smoke kaynak adresi geçersiz.");
    const url = sourceURL.href;
    const previous = await js(`window.rasathane.request('/api/rasathane/jobs')`);
    if (!previous.ok) throw new Error("Analiz öncesi işlem kaydı okunamadı.");
    const known = new Set((previous.data.items || []).map(job => job.id));
    await pointer('[data-gorunum="analiz"]');
    await js(`(() => { const input=document.querySelector('#url'); input.value=${JSON.stringify(url)}; input.dispatchEvent(new Event('input',{bubbles:true})); })()`);
    await wait(`!document.querySelector('#analiz-btn').disabled`);
    const started = Date.now();
    await pointer('#analiz-btn');
    const deadline = started + 10 * 60000;
    let selected = null, completed = null;
    while (Date.now() < deadline) {
      if (!selected) {
        const response = await js(`window.rasathane.request('/api/rasathane/jobs')`);
        if (!response.ok) throw new Error("Analiz işlem listesi okunamadı.");
        selected = (response.data.items || []).find(job => job.kind === "analysis" && !known.has(job.id));
      }
      if (selected) {
        const response = await js(`window.rasathane.request(${JSON.stringify(`/api/rasathane/jobs/${selected.id}`)})`);
        if (!response.ok) throw new Error("Analiz kalıcı işlem kaydı okunamadı.");
        const job = response.data;
        if (["failed", "cancelled", "interrupted"].includes(job.status)) {
          console.log(JSON.stringify({smoke:"product-source-analysis", url, jobId:job.id, status:job.status, error:job.error, durationMs:Date.now()-started}));
          throw new Error("Gerçek kaynak analizi tamamlanamadı.");
        }
        if (job.status === "completed") { completed = job; break; }
      }
      const error = await js(`(() => { const node=document.querySelector('#hata-bant'); return node&&!node.classList.contains('gizli') ? document.querySelector('#hata-metin')?.textContent : ''; })()`);
      if (error) throw new Error(`Analiz ekranı hata verdi: ${String(error).slice(0, 350)}`);
      await pause(1500);
    }
    if (!completed) throw new Error("Gerçek UI kaynak analizi 10 dakika içinde tamamlanamadı.");
    const receipt = pdfAcceptanceReceipt(completed, url);
    await wait(`!document.querySelector('#sonuc').classList.contains('gizli') && document.querySelector('#kaynak-icerik-kapsami').dataset.format==='pdf' && !document.querySelector('#analiz-btn').disabled`, 15000);
    const visible = await js(`(() => { const node=document.querySelector('#kaynak-icerik-kapsami'); return {format:node.dataset.format,pages:Number(node.dataset.pages),textPages:Number(node.dataset.textPages),sha256:node.dataset.sha256,notice:node.textContent,summary:document.querySelector('#ozet-detay')?.textContent,hero:document.querySelector('#kaynak-hero-etiket')?.textContent}; })()`);
    if (visible.pages!==receipt.pages || visible.textPages!==receipt.textPages || visible.sha256!==receipt.bytesSha256 || !visible.summary?.trim() || !visible.hero.includes("PDF") || !visible.notice.includes("OCR yapılmadı")) throw new Error("PDF kaynak künyesi, kapsamı ve özeti UI üzerinden doğrulanamadı.");
    console.log(JSON.stringify({smoke:"product-source-analysis", ...receipt, durationMs:Date.now()-started, savedJob:true, visibleSourceScope:visible.notice, visibleSummary:true}));
  }

}

function pdfAcceptanceReceipt(job, url) {
  const result = job.result || {}, index = result.index || {}, source = result.quality_provenance?.source || {};
  const extra = index.kaynak_ozel || {}, motor = result.motor || index.motor || {};
  if (job.status !== "completed" || job.request?.url !== url || result.stub !== false ||
      (result.kaynak_turu || index.kaynak_turu) !== "web" || source.source_format !== "pdf" ||
      extra.source_format !== "pdf" || source.text_scope !== "pdf_text_layer" ||
      source.extraction_method !== "pypdf_text_layer" || source.ocr_performed !== false ||
      !Number.isInteger(source.page_count) || source.page_count < 1 || source.page_count !== extra.page_count ||
      !Number.isInteger(source.text_page_count) || source.text_page_count < 1 || source.text_page_count > source.page_count ||
      !/^[a-f0-9]{64}$/.test(source.bytes_sha256 || "") ||
      !/^[a-f0-9]{64}$/.test(source.original_text_sha256 || "") ||
      motor.backend !== "llamacpp" || result.cloud_cagrisi_sayisi !== 0 ||
      !String(result.ozet_detay || "").trim() ||
      !result.artifacts?.some(file => file.bytes > 0 && /^[a-f0-9]{64}$/.test(file.sha256 || ""))) {
    throw new Error("Kalıcı PDF analizinin metin kapsamı, yerel motoru veya çıktı makbuzu doğrulanamadı.");
  }
  const partial = source.full_text_extracted === false || (source.truncation_reasons || []).length > 0;
  if ((source.text_page_count < source.page_count || partial) && !source.notice) throw new Error("Kısmi PDF kapsam uyarısı eksik.");
  return { url, jobId:job.id, status:job.status, pages:source.page_count, textPages:source.text_page_count, bytesSha256:source.bytes_sha256, originalTextSha256:source.original_text_sha256, partial, provenance:source, modelBackend:motor.backend, artifactCount:result.artifacts.length };
}

module.exports = { verifyProductUI, pdfAcceptanceReceipt };
