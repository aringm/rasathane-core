"use strict";

// Opt-in acceptance in the actual packaged main/preload/sidecar path.
// Uses Electron's test input, stays hidden, and never supplies an auth bypass.
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
async function verifyProductUI(window) {
  const web = window.webContents;
  const js = source => web.executeJavaScript(source, true);
  async function wait(source) {
    const until = Date.now() + 30000;
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
}

module.exports = { verifyProductUI };
