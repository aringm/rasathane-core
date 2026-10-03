import { categoryLabel } from "./source-manager.js";

export function createRadarFeed({ $, el, api, news, bulletin, renderRecord, onSources }) {
  let sources = [], offset = 0, total = 0, epoch = 0, timer, selectedCategory = "", locked = false;
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
  async function load() {
    if (locked) return;
    const generation = ++epoch;
    if (offset === 0) bulletin.updateItems([]);
    previous.disabled = next.disabled = true;
    list.setAttribute("aria-busy", "true"); status.classList.remove("status-error");
    status.textContent = "Haberler yükleniyor…";
    try {
      const [data, candidates] = await Promise.all([
        api(filters(pageSize, offset)), offset === 0 ? api(filters(200, 0)) : Promise.resolve(null),
      ]);
      if (generation !== epoch || locked) return;
      total = data.total ?? data.items?.length ?? 0;
      if (offset && !data.items?.length && total) { offset = 0; void load(); return; }
      news.stopAll();
      if (candidates) bulletin.updateItems(candidates.items || []);
      list.replaceChildren(...(data.items?.length ? data.items.map(item => {
        const details = el("details", { class: "radar-entry", "data-article-id": item.id });
        const row = el("summary", {},
          el("div", { class: "radar-entry-meta" }, el("span", { class: "radar-source-name" }, item.source_name || sources.find(s => s.id === item.source_id)?.name || "Kayıtlı kaynak"),
            el("span", { class: "source-category" }, categoryLabel(item.category)),
            el("time", {}, item.published_at ? new Date(item.published_at).toLocaleDateString("tr-TR", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "Yayın tarihi belirtilmemiş")),
          el("h3", {}, item.title || "Başlıksız içerik"),
          el("p", { class: "radar-entry-excerpt" }, String(item.summary || item.excerpt || "Kaydı açarak kaynak bilgilerini inceleyin.").slice(0, 220)),
          el("span", { class: "radar-expand-label" }, "Özet, ses ve analiz"));
        const body = el("div", { class: "radar-entry-body" });
        details.append(row, body);
        details.addEventListener("toggle", () => {
          if (!details.open || body.childElementCount) return;
          body.append(renderRecord(item));
        });
        return details;
      }) : [el("div", { class: "radar-empty" }, el("h3", {}, "Bu filtrede haber bulunamadı"),
        el("p", {}, "Tüm tarihleri veya başka bir kaynağı seçin. Yeni haber almak için Akışı yenile düğmesini kullanın."),
        el("button", { type: "button", class: "btn btn-ikincil", onclick: () => { search.value = ""; source.value = ""; period.value = "0"; selectedCategory = ""; offset = 0; categories(); void load(); } }, "Filtreleri temizle"))]));
      status.textContent = total ? `${offset + 1}–${Math.min(offset + pageSize, total)} / ${total.toLocaleString("tr-TR")} haber` : "0 haber";
      previous.disabled = offset === 0; next.disabled = offset + pageSize >= total;
    } catch (error) {
      if (generation !== epoch || locked) return;
      status.textContent = `Akış yüklenemedi: ${error.message}`; status.classList.add("status-error");
      list.replaceChildren(el("button", { type: "button", class: "btn btn-ikincil", onclick: () => void load() }, "Yeniden dene"));
    } finally { if (generation === epoch) list.removeAttribute("aria-busy"); }
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
      void load();
    },
    filterSource(id) { source.value = id; selectedCategory = ""; offset = 0; categories(); void load(); },
    reset() { locked = true; epoch++; clearTimeout(timer); offset = 0; sources = []; news.stopAll(); list.replaceChildren(); status.textContent = sourceOverview.textContent = ""; },
  };
}
