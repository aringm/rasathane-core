export const CATEGORY_LABELS = {
  genel: "Genel", resmi_mevzuat: "Resmî mevzuat", turk_hukuku: "Türk hukuku",
  dunya_ai: "Dünya AI", turkiye_ai: "Türkiye AI", legaltech: "Legaltech",
  muhakeme_stack: "Geliştirme", china_ai_models: "Çin AI", east_asia_ai_models: "Doğu Asya AI",
  open_weight_models: "Açık modeller", model_infra: "Model altyapısı", social_watch: "Sosyal medya",
};
export const categoryLabel = value => CATEGORY_LABELS[value] || value || "Genel";
const KINDS = { rss: "RSS / Atom", arxiv: "arXiv", reddit: "Reddit", youtube_channel: "YouTube kanalı", resmi_gazete: "Resmî Gazete", yargitay_public: "Yargıtay karar künyeleri", yargitay: "Yargıtay bağlantısı", mevzuat: "Mevzuat bağlantısı" };

export function createSourceManager({ $, el, api, sourceLink, date, onChange, onRefresh, onFilter }) {
  let sources = [], editing = null, epoch = 0, busy = false;
  const container = $("kaynak-yonetimi");
  const list = $("kaynak-liste");
  const search = el("input", { id: "kaynak-ara", type: "search", placeholder: "Kaynak adı veya adresi", "aria-label": "Kaynaklarda ara" });
  const scope = el("select", { id: "kaynak-durum-filter", "aria-label": "Kaynak durumu" },
    el("option", { value: "all" }, "Tüm kaynaklar"), el("option", { value: "enabled" }, "Takip edilenler"),
    el("option", { value: "paused" }, "Duraklatılanlar"), el("option", { value: "error" }, "Kontrol gerekenler"));
  const count = el("p", { class: "source-overview", id: "kaynak-sayac", role: "status" });
  const status = el("p", { class: "product-status", id: "kaynak-yonetim-durum", role: "status" });
  container.prepend(count, el("div", { class: "source-toolbar" }, search, scope));
  container.append(status);
  const name = el("input", { id: "yeni-kaynak-ad", required: true, maxlength: 120, autocomplete: "off" });
  const url = el("input", { id: "yeni-kaynak-url", type: "url", required: true, maxlength: 2048, placeholder: "https://…" });
  const kind = el("select", { id: "yeni-kaynak-tur" });
  const category = el("select", { id: "yeni-kaynak-kategori" });
  const enabled = el("input", { id: "yeni-kaynak-aktif", type: "checkbox" });
  const formStatus = el("p", { id: "kaynak-form-durum", role: "status", class: "product-status" });
  const save = el("button", { type: "submit", id: "kaynak-kaydet", class: "btn" }, "Kaynağı ekle");
  const close = el("button", { type: "button", class: "btn btn-ikincil", onclick: () => { if (!busy) dialog.close(); } }, "Vazgeç");
  const heading = el("h2", { id: "kaynak-form-baslik" }, "Kaynak ekle");
  const form = el("form", { id: "kaynak-ekle-form", class: "source-editor" },
    el("label", {}, "Kaynak adı", name), el("label", {}, "Kaynak adresi", url),
    el("div", { class: "source-form-columns" }, el("label", {}, "Tür", kind), el("label", {}, "Kategori", category)),
    el("label", { class: "source-check" }, enabled, "Bu kaynağı takip et"),
    el("p", { class: "field-note" }, "Seçtiğiniz türe uygun RSS/Atom, arXiv, Reddit, YouTube kanalı veya resmî kaynak adresini girin. Duraklatmak mevcut haberleri silmez."),
    formStatus, el("div", { class: "form-actions" }, close, save));
  const dialog = el("dialog", { id: "kaynak-duzenle-dialog", class: "source-dialog", "aria-labelledby": heading.id }, heading, form);
  document.body.append(dialog);
  dialog.addEventListener("cancel", event => { if (busy) event.preventDefault(); });
  function message(node, text, error = false) { node.textContent = text; node.classList.toggle("status-error", error); }
  function open(source = null) {
    editing = source; form.reset(); formStatus.textContent = "";
    name.value = source?.name || ""; url.value = source?.url || ""; enabled.checked = source?.enabled ?? true;
    kind.replaceChildren(...Object.entries(KINDS).map(([value, label]) => el("option", { value }, label)));
    if (source && !KINDS[source.kind]) kind.append(el("option", { value: source.kind }, `${source.kind} · bu sürümde desteklenmiyor`));
    kind.value = source?.kind || "rss";
    const categories = new Set([...Object.keys(CATEGORY_LABELS), ...sources.map(s => s.category || "genel")]);
    category.replaceChildren(...[...categories].map(value => el("option", { value }, categoryLabel(value))));
    category.value = source?.category || "genel";
    heading.textContent = source ? "Kaynağı düzenle" : "Kaynak ekle";
    save.textContent = source ? "Değişiklikleri kaydet" : "Kaynağı ekle";
    dialog.showModal(); name.focus();
  }
  $("kaynak-ekle-ac").addEventListener("click", () => open());
  kind.addEventListener("change", () => {
    if (editing) return;
    const presets = { resmi_gazete: ["Resmî Gazete", "https://www.resmigazete.gov.tr/", "resmi_mevzuat"], yargitay_public: ["Yargıtay karar künyeleri", "https://mevzuat.adalet.gov.tr/", "turk_hukuku"] };
    if (presets[kind.value]) [name.value, url.value, category.value] = presets[kind.value];
  });
  form.addEventListener("submit", async event => {
    event.preventDefault(); if (busy) return;
    const generation = epoch; busy = true; save.disabled = close.disabled = true;
    message(formStatus, "Kaynak kaydediliyor…");
    const body = { name: name.value.trim(), url: url.value.trim(), enabled: enabled.checked, category: category.value };
    if (!editing || editing.kind !== kind.value || KINDS[kind.value]) body.kind = kind.value;
    try {
      await api(editing ? `/sources/${encodeURIComponent(editing.id)}/update` : "/sources", { method: "POST", body });
      if (generation !== epoch) return;
      await onChange(); dialog.close();
      if (generation === epoch) message(status, "Kaynak kaydedildi. Kontrol et düğmesiyle yeni içerikleri alabilirsiniz.");
    } catch (error) { if (generation === epoch) message(formStatus, error.message, true); }
    finally { if (generation === epoch) { busy = false; save.disabled = close.disabled = false; } }
  });
  async function toggle(source, button) {
    const generation = epoch; button.disabled = true;
    try {
      await api(`/sources/${encodeURIComponent(source.id)}/update`, { method: "POST", body: { enabled: !source.enabled } });
      if (generation !== epoch) return;
      await onChange();
      if (generation === epoch) message(status, `${source.name}: ${source.enabled ? "takip duraklatıldı. Kayıtlı haberler korundu." : "takip açıldı."}`);
    } catch (error) { if (generation === epoch) message(status, error.message, true); }
    finally { button.disabled = false; }
  }
  function render() {
    const q = search.value.trim().toLocaleLowerCase("tr-TR");
    const filtered = sources.filter(s => (!q || `${s.name} ${s.url}`.toLocaleLowerCase("tr-TR").includes(q)) &&
      (scope.value === "all" || (scope.value === "enabled" && s.enabled) || (scope.value === "paused" && !s.enabled) || (scope.value === "error" && (s.last_error || s.supported === false))));
    count.textContent = `${sources.length} kaynak · ${sources.filter(s => s.enabled).length} takipte · ${sources.filter(s => !s.enabled).length} duraklatıldı`;
    const table = el("table", { class: "source-table" },
      el("thead", {}, el("tr", {}, ...["Kaynak", "Kategori / tür", "Son kontrol", "Takip", "İşlemler"].map(label => el("th", { scope: "col" }, label)))),
      el("tbody", {}, ...filtered.map(source => el("tr", { "data-source-id": source.id },
        el("td", {}, el("strong", {}, source.name), sourceLink(source.url, source.url),
          el("span", { class: "field-note" }, `${source.article_count || 0} kayıtlı içerik`)),
        el("td", {}, el("span", { class: "source-category" }, categoryLabel(source.category)),
          el("small", {}, KINDS[source.kind] || source.kind),
          source.supported === false ? el("span", { class: "record-error" }, "Bu kaynak türü için RSS adresi ekleyin.") : null),
        el("td", {}, el("time", {}, date(source.last_refreshed_at, "Henüz kontrol edilmedi")),
          source.last_error ? el("details", { class: "source-error" }, el("summary", {}, "Erişim hatasını gör"), el("p", {}, String(source.last_error).slice(0, 500))) : null),
        el("td", {}, el("button", { type: "button", class: "source-switch", role: "switch", "aria-checked": String(!!source.enabled), "aria-label": `${source.name} takibi`, onclick: event => toggle(source, event.currentTarget) }, source.enabled ? "Takipte" : "Duraklatıldı")),
        el("td", {}, el("div", { class: "source-row-actions" },
          el("button", { type: "button", class: "btn btn-ikincil mini source-edit", onclick: () => open(source) }, "Düzenle"),
          el("button", { type: "button", class: "btn btn-ikincil mini", disabled: !source.enabled || source.supported === false, onclick: event => onRefresh(source.id, event.currentTarget) }, "Kontrol et"),
          el("button", { type: "button", class: "source-feed-link", onclick: () => onFilter(source.id) }, "Haberlerini gör"))),
      ))));
    list.replaceChildren(filtered.length ? table : el("p", { class: "empty-state" }, "Bu filtreyle eşleşen kaynak yok."));
  }
  search.addEventListener("input", render); scope.addEventListener("change", render);
  return { update(value) { sources = value || []; render(); }, reset() { epoch++; busy = false; sources = []; list.replaceChildren(); dialog.close(); form.reset(); status.textContent = count.textContent = formStatus.textContent = ""; save.disabled = close.disabled = false; } };
}
