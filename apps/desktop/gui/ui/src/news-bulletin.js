// Bültenler seçilen yerel haberlerin kaynak bağlı, kalıcı anlık görüntüleridir.
export function bulletinCandidates(items, days, limit, now = Date.now()) {
  return items.filter((item) => {
    if (!days) return true;
    const timestamp = Date.parse(item.published_at || item.fetched_at || item.created_at || "");
    return Number.isFinite(timestamp) && timestamp <= now && timestamp >= now - days * 86400000;
  }).slice(0, limit);
}

export function bulletinSourceGroups(items = []) {
  const groups = new Map();
  for (const item of items) {
    const name = item.source_name || "Diğer kaynaklar";
    if (!groups.has(name)) groups.set(name, []);
    groups.get(name).push(item);
  }
  return [...groups].map(([name, entries]) => ({ name, entries }));
}

export function recentBulletins(items = []) {
  return [...items].sort((a, b) => (Date.parse(b.created_at) || 0) - (Date.parse(a.created_at) || 0));
}

export function createNewsBulletin({ el, api, request, sourceLink, beforePlay }) {
  let items = [], current = null, saved = [], epoch = 0, audioEpoch = 0, audioURL = null, busy = false, speechBusy = false;
  const formatDate = (value) => {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "Tarih belirtilmemiş" : date.toLocaleDateString("tr-TR", { day: "numeric", month: "long", year: "numeric" });
  };
  const title = el("input", { type: "text", id: "bulten-baslik", maxlength: 120, value: "Gündem bülteni" });
  const period = el("select", { id: "bulten-donem" },
    el("option", { value: "1" }, "Son 24 saat"),
    el("option", { value: "7" }, "Son 7 gün"),
    el("option", { value: "0" }, "Yüklenen tüm tarihler"));
  const limit = el("select", { id: "bulten-adet" },
    ...[5, 10, 20].map((n) => el("option", { value: n }, `En fazla ${n} haber`)));
  const count = el("p", { class: "field-note", id: "bulten-kapsam" });
  const preview = el("ul", { class: "bulletin-preview" });
  const create = el("button", { type: "submit", form: "bulten-form", class: "btn", id: "bulten-olustur" }, "Bülten oluştur");
  const status = el("p", { class: "field-note bulletin-status", role: "status", "aria-live": "polite", id: "bulten-durum" });
  const result = el("section", { id: "bulten-sonuc", hidden: true, "aria-label": "Kaydedilmiş bülten" });
  const history = el("select", { id: "bulten-gecmis", "aria-label": "Tarihe göre kayıtlı bülten aç" }, el("option", { value: "" }, "Önceki bültenler"));
  const historyList = el("div", { class: "bulletin-history-list" });
  const historySection = el("section", { class: "bulletin-history", hidden: true, "aria-label": "Önceki bültenler" },
    el("div", { class: "bulletin-history-heading" }, el("h3", {}, "Önceki bültenler"), history), historyList);
  const audio = el("audio", { controls: true, id: "bulten-ses", "aria-label": "Bülten seslendirmesi", preload: "metadata" });
  const speed = el("select", { id: "bulten-ses-hizi", "aria-label": "Okuma hızı" },
    ...[1, 1.25, 1.5, 1.75, 2].map((value) => el("option", { value }, `${value}×`)));
  const download = el("a", { class: "bulletin-download", download: "rasathane-bulten.wav" }, "Sesi indir");
  const player = el("div", { class: "bulletin-player", hidden: true }, audio,
    el("label", {}, "Hız", speed), download);
  const speak = el("button", { type: "button", class: "btn btn-ikincil", id: "bulten-seslendir", disabled: true }, "Dinle");
  const read = el("button", { type: "button", class: "btn btn-ikincil", id: "bulten-oku", hidden: true, "aria-expanded": "false", "aria-controls": "bulten-sonuc" }, "Bülteni oku");
  const dateHeading = el("p", { class: "bulletin-date" }, formatDate(Date.now()));
  const heading = el("h2", { id: "bulten-heading" }, "Gündem bülteni");
  const introduction = el("p", { class: "field-note bulletin-intro" }, "Günün haberlerini bir arada okuyun veya dinleyin.");
  const empty = el("p", { class: "bulletin-empty" }, "Henüz bülten yok. Akıştaki haberlerden ilk bülteninizi oluşturun.");
  const summary = el("p", { class: "bulletin-lead", hidden: true });
  const form = el("form", { class: "bulletin-form", id: "bulten-form" },
    el("div", { class: "bulletin-options" },
      el("label", {}, "Bülten adı", title), el("label", {}, "Tarih aralığı", period), el("label", {}, "Uzunluk", limit)),
    count, el("details", {}, el("summary", {}, "Bültene alınacak haberler"), preview));
  const content = el("div", { id: "bulten-panel", hidden: true }, form);
  const toggle = el("button", { id: "bulten-ac", type: "button", class: "bulletin-options-toggle", "aria-expanded": "false", "aria-controls": "bulten-panel" }, "Bülten seçenekleri");
  const node = el("section", { class: "news-bulletin", "aria-labelledby": "bulten-heading" },
    el("div", { class: "bulletin-heading" },
      el("div", {}, dateHeading, heading, introduction),
      el("div", { class: "bulletin-actions" }, read, speak, create)),
    summary, empty, player, status, result,
    el("div", { class: "bulletin-options-row" }, toggle), content, historySection);

  function candidates() { return bulletinCandidates(items, Number(period.value), Number(limit.value)); }
  function update() {
    const selected = candidates();
    create.disabled = busy || !selected.length;
    create.textContent = busy ? "Bülten açılıyor…" : current ? "Yeni bülten oluştur" : "Bülten oluştur";
    speak.disabled = busy || speechBusy || !current;
    speak.textContent = speechBusy ? "Ses hazırlanıyor…" : "Dinle";
    read.disabled = busy;
    toggle.disabled = busy;
    history.disabled = busy;
    for (const button of historyList.querySelectorAll("button")) button.disabled = busy;
    count.textContent = `${selected.length} haber seçildi. Akışın kategori ve kaynak filtreleri uygulanır; yalnız yüklenen kayıtlar kullanılır.`;
    preview.replaceChildren(...selected.map((item) => el("li", {}, item.title || "Başlıksız haber")));
    if (!current) empty.textContent = selected.length
      ? `${selected.length} haber bülten için hazır. Oluşturduğunuz bülten burada saklanır.`
      : "Bu tarih aralığında haber bulunamadı. Akışı yenileyin veya bülten seçeneklerinden tarih aralığını genişletin.";
  }
  function stopAudio() {
    audioEpoch++; speechBusy = false;
    audio.pause(); audio.removeAttribute("src"); audio.load(); player.hidden = true;
    download.removeAttribute("href");
    if (audioURL) URL.revokeObjectURL(audioURL);
    audioURL = null;
    update();
  }
  function showReading(show) {
    result.hidden = !show;
    read.setAttribute("aria-expanded", String(show));
    read.textContent = show ? "Metni daralt" : "Bülteni oku";
  }
  function render(data, expanded = false) {
    stopAudio(); current = data; empty.hidden = true; read.hidden = false;
    heading.textContent = data.title || "Gündem bülteni";
    dateHeading.textContent = formatDate(data.created_at);
    introduction.textContent = `${data.article_count} haber · Kaynaklardan derleme`;
    const first = (data.items || []).find((item) => item.summary);
    summary.textContent = first?.summary || data.notice || "Kaynakların başlıklarını ve açıklamalarını bir arada inceleyin.";
    summary.hidden = false;
    const groups = bulletinSourceGroups(data.items);
    result.replaceChildren(...[
      data.notice ? el("p", { class: "field-note bulletin-notice" }, data.notice) : null,
      el("ol", { class: "bulletin-items" }, ...(data.items || []).map((item) =>
        el("li", {}, el("p", { class: "bulletin-item-source" }, item.source_name || "Kaynak"), el("h4", {}, item.title),
          el("p", {}, item.summary || item.notice || "Bu kaynakta özetlenecek haber metni bulunmuyor."),
          item.summary && item.notice ? el("p", { class: "field-note" }, item.notice) : null,
          sourceLink(item.url, "Haberi aç")))),
      el("details", { class: "bulletin-sources" },
        el("summary", {}, `Kullanılan kaynaklar · ${groups.length} kaynak · ${data.article_count} haber`),
        ...groups.map((group) => el("section", {}, el("h4", {}, `${group.name} (${group.entries.length})`),
          el("ul", {}, ...group.entries.map((item) => el("li", {}, sourceLink(item.url, item.title || "Haberi aç")))))))].filter(Boolean));
    showReading(expanded);
    history.value = data.id;
    renderHistory();
    update();
  }
  function renderHistory() {
    historySection.hidden = !saved.length;
    historyList.replaceChildren(...saved.filter((item) => item.id !== current?.id).slice(0, 3).map((item) =>
      el("button", { type: "button", class: "bulletin-history-item", onclick: () => openBulletin(item.id), disabled: busy },
        el("span", {}, formatDate(item.created_at)), el("strong", {}, item.title || "Gündem bülteni"),
        el("span", { class: "field-note" }, `${item.article_count || 0} haber`))));
  }
  async function openBulletin(id, expanded = true) {
    if (!id || busy) return;
    const generation = ++epoch; busy = true; stopAudio(); update();
    status.textContent = "Kayıtlı bülten açılıyor…";
    try {
      const data = await api(`/bulletins/${encodeURIComponent(id)}`);
      if (generation !== epoch) return;
      render(data, expanded); status.textContent = "";
    } catch (error) { if (generation === epoch) status.textContent = error.message; }
    finally { if (generation === epoch) { busy = false; update(); } }
  }
  async function refreshHistory() {
    const generation = epoch;
    try {
      const data = await api("/bulletins");
      if (generation !== epoch) return;
      saved = recentBulletins(data.items);
      history.replaceChildren(el("option", { value: "" }, "Önceki bültenler"),
        ...saved.map((item) => el("option", { value: item.id }, `${formatDate(item.created_at)} · ${item.title}`)));
      if (current) history.value = current.id;
      renderHistory();
      if (!current && !busy && saved.length) await openBulletin(saved[0].id, false);
    } catch (error) { if (generation === epoch) status.textContent = error.message; }
  }
  form.addEventListener("submit", async (event) => {
    event.preventDefault(); if (busy || !candidates().length) return;
    const generation = ++epoch; busy = true; stopAudio(); update(); create.textContent = "Bülten hazırlanıyor…";
    status.textContent = "Kaynaklardan bülten hazırlanıyor…";
    try {
      const data = await api("/bulletins", { method: "POST", body: { title: title.value.trim() || "Gündem bülteni", article_ids: candidates().map((item) => item.id) } });
      if (generation !== epoch) return;
      render(data, true); content.hidden = true; toggle.setAttribute("aria-expanded", "false");
      status.textContent = "Bülten kaydedildi. Okuyabilir veya Dinle düğmesiyle seslendirebilirsiniz.";
      await refreshHistory();
    } catch (error) { if (generation === epoch) status.textContent = error.message; }
    finally { if (generation === epoch) { busy = false; update(); } }
  });
  toggle.addEventListener("click", () => { content.hidden = !content.hidden; toggle.setAttribute("aria-expanded", String(!content.hidden)); });
  read.addEventListener("click", () => showReading(result.hidden));
  history.addEventListener("change", () => openBulletin(history.value));
  speed.addEventListener("change", () => { audio.playbackRate = Number(speed.value); });
  speak.addEventListener("click", async () => {
    if (!current || busy || speechBusy) return;
    if (audioURL) {
      beforePlay?.(); player.hidden = false;
      try { await audio.play(); } catch { status.textContent = "Dinlemek için oynatıcıdaki Oynat düğmesine basın."; }
      return;
    }
    stopAudio();
    const generation = epoch, voiceGeneration = audioEpoch, bulletinId = current.id;
    speechBusy = true; update(); beforePlay?.();
    status.textContent = "Türkçe bülten sesi hazırlanıyor…";
    try {
      const response = await request(`/api/rasathane/bulletins/${encodeURIComponent(bulletinId)}/speech`, { method: "POST" });
      if (!response.ok) { const error = await response.json().catch(() => ({})); throw new Error(error.error || "Bülten seslendirilemedi."); }
      const blob = await response.blob();
      if (generation !== epoch || voiceGeneration !== audioEpoch || current?.id !== bulletinId) return;
      audioURL = URL.createObjectURL(blob); audio.src = audioURL; audio.playbackRate = Number(speed.value); player.hidden = false;
      download.href = audioURL;
      status.textContent = "Ses hazır. Dinleme hızını değiştirebilir veya ses dosyasını indirebilirsiniz.";
      try { await audio.play(); } catch { /* Kullanıcı yerel oynatıcıdan başlatabilir. */ }
    } catch (error) { if (generation === epoch && voiceGeneration === audioEpoch) status.textContent = error.message; }
    finally { if (generation === epoch && voiceGeneration === audioEpoch) { speechBusy = false; update(); } }
  });
  for (const select of [period, limit]) select.addEventListener("change", update);
  update();
  return { node, refreshHistory, updateItems(value) { items = value; update(); }, stopAudio,
    reset() {
      epoch++; busy = false; current = null; items = []; saved = []; stopAudio();
      result.replaceChildren(); result.hidden = true; content.hidden = true;
      heading.textContent = "Gündem bülteni"; dateHeading.textContent = formatDate(Date.now());
      introduction.textContent = "Günün haberlerini bir arada okuyun veya dinleyin.";
      title.value = "Gündem bülteni"; period.value = "1"; limit.value = "5"; speed.value = "1";
      summary.textContent = ""; summary.hidden = true; empty.hidden = false; read.hidden = true; showReading(false);
      toggle.setAttribute("aria-expanded", "false"); history.replaceChildren(el("option", { value: "" }, "Önceki bültenler"));
      historyList.replaceChildren(); historySection.hidden = true; status.textContent = ""; update();
    } };
}
