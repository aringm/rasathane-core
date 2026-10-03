// Bültenler seçilen yerel haberlerin kaynak bağlı, kalıcı anlık görüntüleridir.
export function bulletinCandidates(items, days, limit, now = Date.now()) {
  return items.filter((item) => {
    if (!days) return true;
    const timestamp = Date.parse(item.published_at || item.fetched_at || item.created_at || "");
    return Number.isFinite(timestamp) && timestamp <= now && timestamp >= now - days * 86400000;
  }).slice(0, limit);
}

export function createNewsBulletin({ el, api, request, sourceLink, beforePlay }) {
  let items = [], current = null, epoch = 0, audioURL = null, busy = false, speechBusy = false;
  const title = el("input", { type: "text", id: "bulten-baslik", maxlength: 120, value: "Gündem bülteni" });
  const period = el("select", { id: "bulten-donem" },
    el("option", { value: "0" }, "Yüklenen tüm tarihler"),
    el("option", { value: "1" }, "Son 24 saat"),
    el("option", { value: "7" }, "Son 7 gün"));
  const limit = el("select", { id: "bulten-adet" },
    ...[5, 10, 20].map((n) => el("option", { value: n }, `En fazla ${n} haber`)));
  const count = el("p", { class: "field-note", id: "bulten-kapsam" });
  const preview = el("ul", { class: "bulletin-preview" });
  const create = el("button", { type: "submit", class: "btn", id: "bulten-olustur" }, "Bülten oluştur");
  const status = el("p", { class: "field-note", role: "status", "aria-live": "polite", id: "bulten-durum" });
  const result = el("section", { id: "bulten-sonuc", hidden: true, "aria-label": "Kaydedilmiş bülten" });
  const history = el("select", { id: "bulten-gecmis", "aria-label": "Kayıtlı bültenler" }, el("option", { value: "" }, "Kayıtlı bültenler"));
  const audio = el("audio", { controls: true, hidden: true, id: "bulten-ses", "aria-label": "Bülten seslendirmesi" });
  const speak = el("button", { type: "button", class: "btn btn-ikincil", id: "bulten-seslendir" }, "Bülteni seslendir");
  const form = el("form", { class: "bulletin-form", id: "bulten-form" },
    el("div", { class: "bulletin-options" },
      el("label", {}, "Bülten adı", title), el("label", {}, "Tarih aralığı", period), el("label", {}, "Uzunluk", limit)),
    count, el("details", {}, el("summary", {}, "Bültene alınacak haberler"), preview),
    el("div", { class: "form-actions" }, create, history), status);
  const content = el("div", { id: "bulten-panel", hidden: true }, form, result);
  const toggle = el("button", { id: "bulten-ac", type: "button", class: "btn btn-ikincil", "aria-expanded": "false", "aria-controls": "bulten-panel" }, "Bülten hazırla / aç");
  toggle.addEventListener("click", () => { content.hidden = !content.hidden; toggle.setAttribute("aria-expanded", String(!content.hidden)); if (content.hidden) { epoch++; speechBusy = false; stopAudio(); update(); } });
  const node = el("section", { class: "news-bulletin", "aria-labelledby": "bulten-heading" },
    el("div", { class: "bulletin-heading" },
      el("div", {}, el("h2", { id: "bulten-heading" }, "Gündemi bültene dönüştür"),
        el("p", { class: "field-note" }, "Akıştaki haberleri tek metinde toplayın, kaydedin ve Türkçe dinleyin.")), toggle),
    content);

  function candidates() { return bulletinCandidates(items, Number(period.value), Number(limit.value)); }
  function update() {
    const selected = candidates();
    create.disabled = busy || !selected.length;
    speak.disabled = busy || speechBusy || !current;
    toggle.disabled = busy;
    count.textContent = `${selected.length} haber seçildi. Aşağıdaki akış filtreleri uygulanır; yalnız yüklenmiş kayıtlar kullanılır.`;
    preview.replaceChildren(...selected.map((item) => el("li", {}, item.title || "Başlıksız haber")));
  }
  function stopAudio() {
    audio.pause(); audio.removeAttribute("src"); audio.load(); audio.hidden = true;
    if (audioURL) URL.revokeObjectURL(audioURL);
    audioURL = null;
  }
  function render(data) {
    stopAudio(); current = data; speechBusy = false; result.hidden = false; speak.hidden = false;
    result.replaceChildren(
      el("div", { class: "bulletin-heading" }, el("h3", {}, data.title), speak),
      el("p", { class: "field-note" }, `${new Date(data.created_at).toLocaleString("tr-TR")} · ${data.article_count} haber · Kaynaklardan derleme`),
      el("p", { class: "field-note" }, data.notice),
      el("ol", { class: "bulletin-items" }, ...(data.items || []).map((item) =>
        el("li", {}, el("h4", {}, item.title), el("p", {}, item.summary || item.notice || "Bu kaynakta özetlenecek metin bulunmuyor."),
          item.summary && item.notice ? el("p", { class: "field-note" }, item.notice) : null,
          el("div", { class: "record-meta" }, item.source_name || "Kaynak", sourceLink(item.url))))), audio);
  }
  async function refreshHistory() {
    const generation = epoch;
    try {
      const data = await api("/bulletins");
      if (generation !== epoch) return;
      history.replaceChildren(el("option", { value: "" }, "Kayıtlı bültenler"),
        ...(data.items || []).map((item) => el("option", { value: item.id }, `${item.title} · ${new Date(item.created_at).toLocaleString("tr-TR")}`)));
      if (current) history.value = current.id;
    } catch (error) { if (generation === epoch) status.textContent = error.message; }
  }
  form.addEventListener("submit", async (event) => {
    event.preventDefault(); if (busy || !candidates().length) return;
    const generation = ++epoch; busy = true; speechBusy = false; stopAudio(); update(); history.disabled = true;
    status.textContent = "Kaynaklardan bülten hazırlanıyor…";
    try {
      const data = await api("/bulletins", { method: "POST", body: { title: title.value.trim() || "Gündem bülteni", article_ids: candidates().map((item) => item.id) } });
      if (generation !== epoch) return;
      render(data); status.textContent = "Bülten bu bilgisayara kaydedildi. İsterseniz seslendirebilirsiniz.";
      await refreshHistory();
    } catch (error) { if (generation === epoch) status.textContent = error.message; }
    finally { if (generation === epoch) { busy = false; history.disabled = false; update(); } }
  });
  history.addEventListener("change", async () => {
    if (!history.value || busy) return;
    const generation = ++epoch; busy = true; speechBusy = false; update(); history.disabled = true; stopAudio();
    status.textContent = "Kayıtlı bülten açılıyor…";
    try {
      const data = await api(`/bulletins/${encodeURIComponent(history.value)}`);
      if (generation !== epoch) return;
      render(data); status.textContent = "Bülten, oluşturulduğu sıradaki kaynak metinleriyle açıldı.";
    } catch (error) { if (generation === epoch) status.textContent = error.message; }
    finally { if (generation === epoch) { busy = false; history.disabled = false; update(); } }
  });
  speak.addEventListener("click", async () => {
    if (!current || busy || speechBusy) return;
    const generation = epoch, bulletinId = current.id; speechBusy = true; update(); stopAudio(); beforePlay?.();
    status.textContent = "Türkçe bülten sesi hazırlanıyor…";
    try {
      const response = await request(`/api/rasathane/bulletins/${encodeURIComponent(current.id)}/speech`, { method: "POST" });
      if (!response.ok) { const error = await response.json().catch(() => ({})); throw new Error(error.error || "Bülten seslendirilemedi."); }
      const blob = await response.blob();
      if (generation !== epoch || current?.id !== bulletinId) return;
      audioURL = URL.createObjectURL(blob); audio.src = audioURL; audio.hidden = false;
      status.textContent = "Ses hazır. Oynatma düğmeleriyle duraklatabilir ve kaldığınız yerden dinleyebilirsiniz.";
      try { await audio.play(); } catch { /* Yerel oynatıcıdan yeniden başlatılabilir. */ }
    } catch (error) { if (generation === epoch) status.textContent = error.message; }
    finally { if (generation === epoch) { speechBusy = false; update(); } }
  });
  for (const select of [period, limit]) select.addEventListener("change", update);
  update();
  return { node, refreshHistory, updateItems(value) { items = value; update(); }, stopAudio,
    reset() { epoch++; busy = false; speechBusy = false; current = null; items = []; stopAudio(); result.replaceChildren(); result.hidden = true; content.hidden = true; toggle.setAttribute("aria-expanded", "false"); history.replaceChildren(el("option", { value: "" }, "Kayıtlı bültenler")); history.disabled = false; status.textContent = ""; update(); } };
}
