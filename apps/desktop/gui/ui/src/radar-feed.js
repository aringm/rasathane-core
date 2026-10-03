import { categoryLabel } from "./source-manager.js";

export function createRadarFeed({ $, el, api, news, bulletin, renderRecord, onSources }) {
  let sources = [], offset = 0, total = 0, epoch = 0, timer, summaryTimer, selectedCategory = "", locked = false;
  let loadingPromise = null, queuedLoad = null, activeLoad = null, renderedKey = null;
  let records = new Map();
  const pageSize = 25;
  const list = $("akis-liste");
  const search = el("input", { id: "akis-ara", type: "search", maxlength: 200, placeholder: "Haber başlığı veya özette ara", "aria-label": "Akışta ara" });
  const source = el("select", { id: "akis-kaynak-filter", "aria-label": "Akış kaynağı" });
  const period = el("select", { id: "akis-tarih-filter", "aria-label": "Akış tarih aralığı" },
    el("option", { value: "0" }, "Tüm tarihler"), el("option", { value: "1" }, "Son 24 saat"), el("option", { value: "7" }, "Son 7 gün"), el("option", { value: "30" }, "Son 30 gün"));
  const pills = el("div", { class: "radar-categories", "aria-label": "Haber kategorileri" });
  const status = el("p", { class: "radar-feed-status", id: "akis-sonuc-durum", role: "status" });
  const previous = el("button", { type: "button", class: "btn btn-ikincil mini", id: "akis-onceki" }, "Önceki sayfa");
  const next = el("button", { type: "button", class: "btn btn-ikincil mini", id: "akis-sonraki" }, "Sonraki sayfa");
  const pagination = el("div", { class: "radar-pagination" }, status, el("div", { class: "form-actions" }, previous, next));
  $("akis-icerik-baslik").closest(".radar-stream-heading").after(
    el("div", { class: "radar-feed-toolbar" }, search, source, period,
      el("button", { type: "button", class: "btn btn-ikincil", onclick: onSources }, "Kaynakları yönet")), pills);
  list.after(pagination);
  const sourceOverview = $("akis-kaynak-ozet");
  function categories() {
    const values = [...new Set(sources.map(item => item.category || "genel"))];
    pills.replaceChildren(...["", ...values].map(value => el("button", {
      type: "button", class: "category-pill", "aria-pressed": String(selectedCategory === value),
      onclick: () => { selectedCategory = value; offset = 0; categories(); void load(); },
    }, value ? categoryLabel(value) : "Tümü")));
  }
  function filters(limit, start) {
    const params = new URLSearchParams({ limit: String(limit), offset: String(start), days: period.value });
    if (source.value) params.set("source_id", source.value);
    if (selectedCategory) params.set("category", selectedCategory);
    if (search.value.trim()) params.set("query", search.value.trim());
    return `/articles?${params}`;
  }
  function inputIdentity(item) { return JSON.stringify([item.title, item.summary, item.url, item.provenance]); }
  function changedInput(record, item) {
    if (record.input !== inputIdentity(item)) return true;
    const before = record.item.summary_display, after = item.summary_display;
    return before?.status === "ready" && after?.status === "ready" && before.source_hash && after.source_hash && before.source_hash !== after.source_hash;
  }
  function updateRecord(record, item) {
    const ready = record.item.summary_display;
    Object.assign(record.item, item);
    if (ready?.status === "ready" && item.summary_display?.status !== "ready") record.item.summary_display = ready;
    record.row.querySelector(".radar-entry-excerpt").textContent = articlePreview(record.item);
    record.row.querySelector("h3").textContent = record.item.summary_display?.title || item.title || "Başlıksız içerik";
  }
  function load() {
    if (locked) return Promise.resolve();
    const page = filters(pageSize, offset), candidates = offset === 0 ? filters(200, 0) : null;
    const key = `${page}|${candidates || ""}`;
    const latest = queuedLoad || activeLoad;
    if (latest?.key === key && latest.generation === epoch) return loadingPromise;
    queuedLoad = { key, page, candidates, start: offset, generation: ++epoch };
    if (loadingPromise) return loadingPromise;
    loadingPromise = (async () => {
      while (queuedLoad && !locked) {
        activeLoad = queuedLoad; queuedLoad = null;
        await fetchPage(activeLoad);
      }
    })().finally(() => { loadingPromise = null; activeLoad = null; });
    return loadingPromise;
  }
  async function fetchPage(snapshot) {
    const { generation, key, start } = snapshot;
    previous.disabled = next.disabled = true;
    list.setAttribute("aria-busy", "true"); status.classList.remove("status-error");
    status.textContent = "Haberler yükleniyor…";
    try {
      const replies = await Promise.allSettled([
        api(snapshot.page), snapshot.candidates ? api(snapshot.candidates) : Promise.resolve(null),
      ]);
      const failed = replies.find(reply => reply.status === "rejected");
      if (failed) throw failed.reason;
      const [data, candidates] = replies.map(reply => reply.value);
      if (generation !== epoch || locked) return;
      total = data.total ?? data.items?.length ?? 0;
      if (start && !data.items?.length && total) { offset = 0; void load(); return; }
      if (renderedKey !== null && renderedKey !== key) { news.stopAll(); for (const record of records.values()) record.control.dispose?.(); records.clear(); }
      renderedKey = key;
      if (candidates) bulletin.updateItems(candidates.items || []);
      const retained = new Map();
      const nodes = data.items?.length ? data.items.map(item => {
        const existing = records.get(item.id);
        if (existing && changedInput(existing, item)) existing.control.dispose?.();
        if (existing && !changedInput(existing, item)) {
          // Keep the controls and their running summary/audio operation attached.
          updateRecord(existing, item);
          retained.set(item.id, existing);
          return existing.node;
        }
        const details = el("article", { class: "radar-entry", "data-article-id": item.id });
        const row = el("div", { class: "radar-entry-heading" },
          el("div", { class: "radar-entry-meta" }, el("span", { class: "radar-source-name" }, item.source_name || sources.find(s => s.id === item.source_id)?.name || "Kayıtlı kaynak"),
            el("span", { class: "source-category" }, categoryLabel(item.category)),
            el("time", {}, item.published_at ? new Date(item.published_at).toLocaleDateString("tr-TR", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "Yayın tarihi belirtilmemiş")),
          el("h3", {}, item.summary_display?.title || item.title || "Başlıksız içerik"),
          el("p", { class: "radar-entry-excerpt" }, articlePreview(item)));
        const body = el("div", { class: "radar-entry-body" });
        details.append(row, body);
        const control = renderRecord(item, result => {
          item.summary_display = result;
          if (result.url) item.url = result.url;
          row.querySelector(".radar-entry-excerpt").textContent = articlePreview(item);
          row.querySelector("h3").textContent = result.title || item.title || "Başlıksız içerik";
        });
        body.append(control);
        retained.set(item.id, { item, row, control, node: details, input: inputIdentity(item) });
        return details;
      }) : [el("div", { class: "radar-empty" }, el("h3", {}, "Bu filtrede haber bulunamadı"),
        el("p", {}, "Tüm tarihleri veya başka bir kaynağı seçin. Yeni haber almak için Akışı yenile düğmesini kullanın."),
        el("button", { type: "button", class: "btn btn-ikincil", onclick: () => { search.value = ""; source.value = ""; period.value = "0"; selectedCategory = ""; offset = 0; categories(); void load(); } }, "Filtreleri temizle"))];
      for (const [id, record] of records) if (!retained.has(id)) record.control.dispose?.();
      for (const child of [...list.children]) if (!nodes.includes(child)) child.remove();
      nodes.forEach((node, index) => {
        const before = list.children[index] || null;
        if (before === node) return;
        // moveBefore preserves media playback/focus when reordered within the list.
        if (node.parentElement === list && list.moveBefore) list.moveBefore(node, before);
        else list.insertBefore(node, before);
      });
      records = retained;
      scheduleSummaryRefresh(data.items || [], generation);
      status.textContent = total ? `${offset + 1}–${Math.min(offset + pageSize, total)} / ${total.toLocaleString("tr-TR")} haber` : "0 haber";
      previous.disabled = offset === 0; next.disabled = offset + pageSize >= total;
    } catch (error) {
      if (generation !== epoch || locked) return;
      status.textContent = `Akış yüklenemedi: ${error.message}`; status.classList.add("status-error");
      const retry = el("button", { type: "button", class: "btn btn-ikincil", onclick: () => void load() }, "Yeniden dene");
      if (renderedKey === key && records.size) status.append(retry);
      else {
        for (const record of records.values()) record.control.dispose?.();
        records.clear(); renderedKey = null; list.replaceChildren(retry);
      }
    } finally { if (generation === epoch) list.removeAttribute("aria-busy"); }
  }
  function scheduleSummaryRefresh(items, generation) {
    clearTimeout(summaryTimer);
    if (locked || !items.some(item => item.summary_display?.status === "pending" && item.summary_display?.job_id)) return;
    summaryTimer = setTimeout(async () => {
      if (locked || generation !== epoch) return;
      try {
        const data = await api(filters(pageSize, offset));
        if (locked || generation !== epoch) return;
        if ((data.items || []).some(item => records.has(item.id) && changedInput(records.get(item.id), item))) { void load(); return; }
        for (const item of data.items || []) {
          const record = records.get(item.id);
          if (record) updateRecord(record, item);
        }
        scheduleSummaryRefresh(data.items || [], generation);
      } catch { if (!locked && generation === epoch) summaryTimer = setTimeout(() => scheduleSummaryRefresh(items, generation), 10000); }
    }, 2500);
  }
  search.addEventListener("input", () => { clearTimeout(timer); offset = 0; epoch++; bulletin.updateItems([]); timer = setTimeout(() => void load(), 250); });
  for (const filter of [source, period]) filter.addEventListener("change", () => { offset = 0; void load(); });
  previous.addEventListener("click", () => { offset = Math.max(0, offset - pageSize); void load(); });
  next.addEventListener("click", () => { offset += pageSize; void load(); });
  return {
    update(state) {
      locked = false; sources = state.sources || [];
      const selected = source.value;
      source.replaceChildren(el("option", { value: "" }, "Tüm kaynaklar"), ...sources.map(item => el("option", { value: item.id }, item.name)));
      if (sources.some(item => item.id === selected)) source.value = selected;
      categories();
      sourceOverview.textContent = `${sources.filter(item => item.enabled).length} kaynak takipte · ${sources.filter(item => item.last_error).length} kaynak kontrol bekliyor`;
      return load();
    },
    filterSource(id) { source.value = id; selectedCategory = ""; offset = 0; categories(); void load(); },
    reset() { locked = true; epoch++; queuedLoad = null; clearTimeout(timer); clearTimeout(summaryTimer); offset = 0; sources = []; for (const record of records.values()) record.control.dispose?.(); records.clear(); renderedKey = null; news.stopAll(); list.replaceChildren(); status.textContent = sourceOverview.textContent = ""; },
  };
}


// Eski RSS kayıtlarındaki HN sayaç/link dökümü haber metni değildir.
export function articlePreview(item) {
  const display = item.summary_display;
  if (display?.status === "ready" && display.language === "tr") return String(display.summary || "").trim().slice(0, 600) || "Bu kayıtta özetlenebilecek metin yok.";
  if (display?.status === "pending" && display.job_id) return "Türkçe haber özeti hazırlanıyor…";
  if (display?.status === "unavailable") return "Bu kayıtta özetlenebilecek haber metni bulunmuyor.";
  return "Türkçe özeti hazırlamak için Özetle’ye basın.";
}
