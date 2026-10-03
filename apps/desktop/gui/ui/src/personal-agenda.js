export function createPersonalAgenda({ el, api, bulletin, onChanged }) {
  let epoch = 0, locked = true, saving = false, busy = false, timer, profile = null, dirty = false, latestId = null, latest = null, openWhenReady = false, jobId = null;
  const status = el("p", { class: "agenda-status", id: "gundem-durum", role: "status", "aria-live": "polite" });
  const statusDetails = el("p", { class: "field-note", id: "gundem-kaynak-durum" });
  const modelNotice = el("details", { class: "agenda-model-notice", hidden: true }, el("summary", {}, "Model değerlendirmesi eksik kaldı; değerlendirilemeyen haberlerde konu eşleşmesi kullanıldı."));
  const modelError = el("p", { class: "field-note" }); modelNotice.append(modelError);
  const generate = el("button", { type: "button", class: "btn", id: "gundem-yenile", onclick: () => void run() }, "Kaynakları yenile ve gündem hazırla");
  const latestButton = el("button", { type: "button", class: "agenda-latest-link", id: "gundem-son-ac", hidden: true,
    onclick: () => { if (latest && bulletin.showBulletin(latest, true)) { latestId = latest.id; latestButton.textContent = "Son kişisel gündemi aç"; } } }, "Son kişisel gündemi aç");
  const cancel = el("button", { type: "button", class: "btn btn-ikincil", id: "gundem-iptal", hidden: true, onclick: async () => {
    if (!jobId || locked) return;
    const generation = epoch; cancel.disabled = true;
    try { await api(`/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST", body: {} }); if (generation === epoch) { openWhenReady = false; await refresh(); } }
    catch (error) { if (generation === epoch) status.textContent = error.message; }
    finally { if (generation === epoch) cancel.disabled = false; }
  } }, "Gündemi iptal et");
  const interests = el("textarea", { id: "gundem-ilgiler", maxlength: 3000, placeholder: "Takip etmek istediğiniz konular, coğrafyalar ve öncelikler" });
  const projects = el("textarea", { id: "gundem-projeler", maxlength: 4000, placeholder: "Üzerinde çalıştığınız projeler ve karar verirken önem verdiğiniz noktalar" });
  const enabled = el("input", { id: "gundem-otomatik", type: "checkbox" });
  const model = el("input", { id: "gundem-yerel-model", type: "checkbox" });
  const interval = el("select", { id: "gundem-siklik" }, ...[15, 30, 60, 180, 360, 720, 1440].map(value => el("option", { value }, value < 60 ? `${value} dakikada bir` : `${value / 60} saatte bir`)));
  const windowHours = el("select", { id: "gundem-aralik" }, ...[6, 12, 24, 48, 72, 168].map(value => el("option", { value }, value <= 24 ? `Son ${value} saat` : `Son ${value / 24} gün`)));
  const limit = el("select", { id: "gundem-adet" }, ...[3, 5, 8, 10, 15, 20].map(value => el("option", { value }, `${value} haber`)));
  const saveStatus = el("p", { class: "field-note full-row", id: "gundem-profil-durum", role: "status" });
  const save = el("button", { type: "submit", class: "btn", id: "gundem-profil-kaydet" }, "Profili kaydet");
  const form = el("form", { id: "gundem-profil-form" },
    el("label", {}, "İlgi alanlarım", interests), el("label", {}, "Projelerim ve önceliklerim", projects),
    el("label", {}, "Kontrol sıklığı", interval), el("label", {}, "Haber aralığı", windowHours), el("label", {}, "Bülten uzunluğu", limit),
    el("p", { class: "field-note full-row" }, "8 GB RAM profilinde bülten en çok 8 haber içerir. Daha uzun bültenler için Ayarlar’dan daha yüksek RAM profili seçebilirsiniz; yerel model ilk 8 haberi değerlendirir."),
    el("label", { class: "check-line" }, enabled, "Uygulama açıkken otomatik güncelle"),
    el("label", { class: "check-line" }, model, "Bu bilgisayardaki modelle değerlendir"),
    el("p", { class: "field-note full-row" }, "İlgi alanlarınız ve proje bağlamınız bu bilgisayardaki modelde işlenir. Model kullanılamazsa konu eşleşmeleri gösterilir; bunun model değerlendirmesi olmadığı belirtilir."),
    el("div", { class: "form-actions full-row" }, save,
      el("button", { type: "button", class: "btn btn-ikincil", onclick: () => { if (profile && !saving) { dirty = false; write(profile); saveStatus.textContent = "Kayıtlı profil geri yüklendi."; } } }, "Değişiklikleri geri al")), saveStatus);
  const details = el("details", { class: "agenda-profile", id: "gundem-profil" }, el("summary", {}, "İlgi alanlarım ve proje bağlamım"), form);
  const node = el("section", { class: "personal-agenda", "aria-label": "Kişisel gündem" },
    el("div", { class: "agenda-controls" }, generate, cancel, latestButton), status, statusDetails, modelNotice, details);
  function write(value) {
    interests.value = value.interests || ""; projects.value = value.project_context || "";
    enabled.checked = !!value.enabled; model.checked = !!value.use_local_model;
    for (const [field, number] of [[interval, value.refresh_minutes], [windowHours, value.window_hours], [limit, value.max_items]]) {
      if (![...field.options].some(option => option.value === String(number))) field.append(el("option", { value: number }, String(number)));
      field.value = number;
    }
  }
  function read() { return { enabled: enabled.checked, interests: interests.value.trim(), project_context: projects.value.trim(), refresh_minutes: Number(interval.value), window_hours: Number(windowHours.value), max_items: Number(limit.value), use_local_model: model.checked }; }
  form.addEventListener("input", () => { dirty = true; saveStatus.textContent = "Kaydedilmemiş profil değişiklikleri var."; });
  form.addEventListener("change", () => { dirty = true; saveStatus.textContent = "Kaydedilmemiş profil değişiklikleri var."; });
  form.addEventListener("submit", async event => {
    event.preventDefault(); if (saving || locked) return;
    const generation = epoch, submitted = read(); saving = true; save.disabled = true;
    saveStatus.textContent = "Profil kaydediliyor…";
    try {
      const result = await api("/agenda-profile", { method: "POST", body: submitted });
      if (generation !== epoch) return;
      profile = result.profile || result;
      if (JSON.stringify(read()) === JSON.stringify(submitted)) { dirty = false; write(profile); }
      saveStatus.textContent = dirty ? "Profil kaydedildi; sonraki değişiklikleriniz henüz kaydedilmedi." : "Profil kaydedildi. Güncel kaynaklardan kişisel gündem hazırlayabilirsiniz.";
      await refresh();
    } catch (error) { if (generation === epoch) saveStatus.textContent = error.message; }
    finally { if (generation === epoch) { saving = false; save.disabled = false; } }
  });
  const timestamp = value => value ? new Date(value).toLocaleString("tr-TR", { dateStyle: "short", timeStyle: "short" }) : "Henüz yok";
  function update(data) {
    if (!data || locked) return;
    profile = data.profile;

    if (!dirty && profile) write(profile);
    const info = data.status || {}, job = info.job;
    modelError.textContent = (data.latest?.model_error || info.model_error || "").slice(0, 350);
    modelNotice.hidden = !modelError.textContent;
    jobId = job?.id || null;
    busy = !!job && ["queued", "running", "cancel_requested"].includes(job.status);
    cancel.hidden = !busy;
    cancel.disabled = job?.status === "cancel_requested";
    if (job && ["failed", "cancelled", "interrupted"].includes(job.status)) openWhenReady = false;
    generate.disabled = busy;
    const stages = { queued: "Sırada", source_refresh: "Kaynaklar yenileniyor", feed_fetch: "Kaynaklar yenileniyor", agenda_select: "İlgili haberler seçiliyor", agenda_evaluate: "Proje bağlamında değerlendiriliyor", agenda_compose: "Gündem hazırlanıyor", agenda_sources: "Kaynaklar yenileniyor", agenda_model: "Yerel model değerlendiriyor" };
    generate.textContent = busy ? "Gündem hazırlanıyor…" : "Kaynakları yenile ve gündem hazırla";
    status.textContent = busy ? `${info.source_batch?.active ? `Kaynaklar yenileniyor (${info.source_batch.completed}/${info.source_batch.total})` : stages[job.stage] || "Gündem hazırlanıyor"}. İşlem tamamlanınca sonuç burada görünecek.`
      : info.error || info.last_error || (job?.status === "failed" ? job.error : "") || (profile?.enabled ? "Otomatik gündem açık. Yeni içerikler ilgi ve projelerinize göre değerlendirilecek." : "Otomatik gündem kapalı. İstediğinizde elle güncelleyebilirsiniz.");
    statusDetails.textContent = `${info.source_count || 0} kaynak · ${info.source_error_count || 0} erişim sorunu · Son başarılı kaynak kontrolü: ${timestamp(info.last_source_success_at)} · Son gündem: ${timestamp(info.last_success_at)} · Sonraki kontrol: ${profile?.enabled ? timestamp(info.next_check_at) : "Kapalı"}`;
    if (data.latest) {
      latest = data.latest; latestButton.hidden = false;
      if (!latestId || (openWhenReady && !busy)) { if (bulletin.showBulletin(latest, true)) { latestId = latest.id; openWhenReady = false; latestButton.textContent = "Son kişisel gündemi aç"; } }
      else if (latestId !== latest.id) { latestId = latest.id; latestButton.textContent = "Yeni kişisel gündem hazır — aç"; }
    } else {
      latest = latestId = null; latestButton.hidden = true;
      if (!busy) openWhenReady = false;
      if (!busy) status.textContent += ` ${info.notice || "Bu profil ve tarih aralığı için henüz kişisel gündem yok."}`;
    }
    if (profile && !profile.interests && !profile.project_context) details.open = true;
    schedule();
  }
  function schedule() { clearTimeout(timer); if (!locked) timer = setTimeout(() => void refresh(), busy ? 1800 : 30000); }
  async function refresh() {
    if (locked) return;
    const generation = epoch;
    try { const data = await api("/agenda"); if (generation === epoch) update(data); }
    catch (error) { if (generation === epoch) { status.textContent = `Gündem durumu alınamadı: ${error.message}`; schedule(); } }
  }
  async function run() {
    if (locked || busy) return;
    if (dirty) { details.open = true; saveStatus.textContent = "Önce profil değişikliklerinizi kaydedin."; save.focus(); return; }
    const generation = epoch; busy = true; openWhenReady = true; generate.disabled = true; status.textContent = "Kaynak kontrolü ve kişisel değerlendirme başlatılıyor…";
    try { await api("/agenda", { method: "POST", body: { refresh_sources: true } }); if (generation === epoch) { await refresh(); onChanged?.(); } }
    catch (error) { if (generation === epoch) { status.textContent = error.message; openWhenReady = false; busy = false; generate.disabled = false; } }
  }
  return { node, update, run, unlock() { locked = false; }, reset() { epoch++; locked = true; clearTimeout(timer); profile = latest = latestId = jobId = null; dirty = busy = saving = openWhenReady = false; form.reset(); status.textContent = statusDetails.textContent = saveStatus.textContent = modelError.textContent = ""; latestButton.hidden = cancel.hidden = modelNotice.hidden = true; generate.disabled = save.disabled = false; } };
}
