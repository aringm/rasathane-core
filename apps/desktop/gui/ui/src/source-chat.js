/** Source configuration uses a narrow, authenticated API; publisher text cannot issue commands. */
export function createSourceChat({ el, api, onChanged, sourceLink }) {
  let epoch = 0, locked = true, busy = false, turns = [], retry = null, historyRevision = 0, mutationRevision = 0;
  const history = el("div", { class: "source-chat-history", id: "kaynak-sohbet-gecmis", "aria-live": "polite" });
  const input = el("textarea", { id: "kaynak-sohbet-mesaj", maxlength: 2000, required: true, "aria-label": "Kaynak yapılandırma isteğiniz", placeholder: "Örneğin: https://example.org/feed adresini Hukuk kategorisine ekle" });
  const send = el("button", { type: "submit", class: "btn", id: "kaynak-sohbet-gonder" }, "Uygula");
  const status = el("p", { class: "source-chat-status", id: "kaynak-sohbet-durum", role: "status" });
  const form = el("form", { id: "kaynak-sohbet-form" }, input, send);
  const node = el("details", { class: "source-chat", open: true },
    el("summary", {}, "Kaynak asistanı"),
    el("p", { class: "source-chat-intro" }, "Bir web adresi verin; yayın bağlantısını bulup ekleyeyim. Kaynakları kategorilere ayırabilir, takibi açıp duraklatabilirim. Ne yaptığımı burada görebilirsiniz."), history, form, status);
  function render() {
    history.replaceChildren(...turns.map(turn => el("article", { class: "source-chat-turn" },
      el("p", { class: "user-message" }, turn.message),
      el("p", { class: turn.status === "applied" ? "action-receipt" : "" }, turn.reply),
      ...(turn.actions || []).map(action => {
        const source = action.source || action.after || action;
        return source.url ? el("p", { class: "field-note" }, sourceLink(source.url, source.name || source.url)) : null;
      }),
      turn.suggestions?.length ? el("div", { class: "source-chat-suggestions" }, ...turn.suggestions.map(suggestion =>
        el("button", { type: "button", class: "btn btn-ikincil mini", disabled: busy,
          onclick: () => { input.value = suggestion.prompt || `${suggestion.url} adresini ${suggestion.category || "Genel"} kategorisine ekle`; form.requestSubmit(); } }, `${suggestion.name || suggestion.title || suggestion.url} ekle`))) : null)));
    history.scrollTop = history.scrollHeight;
  }
  function mergeTurns(incoming) {
    // Receipts are immutable. A history response started before a POST must not
    // erase the receipt that arrived while that history request was in flight.
    const merged = new Map((incoming || []).map(turn => [turn.id, turn]));
    for (const turn of turns) merged.set(turn.id, turn);
    turns = [...merged.values()].sort((a, b) => String(a.created_at).localeCompare(String(b.created_at))).slice(-100);
  }
  async function refresh() {
    if (locked) return;
    const generation = epoch, revision = ++historyRevision, mutation = mutationRevision;
    try {
      const data = await api("/source-assistant/history");
      if (generation !== epoch || revision !== historyRevision) return;
      mergeTurns(data.items); render();
    } catch (error) { if (generation === epoch && revision === historyRevision && mutation === mutationRevision) status.textContent = `Kaynak sohbeti açılamadı: ${error.message}`; }
  }
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const message = input.value.trim();
    if (busy || locked || !message) return;
    const generation = epoch, submittedDraft = input.value;
    mutationRevision++;
    busy = true; send.disabled = true; status.textContent = "Kaynak yapılandırması inceleniyor…";
    render();
    if (!retry || retry.message !== message) retry = { message, request_id: crypto.randomUUID() };
    try {
      const receipt = await api("/source-assistant", { method: "POST", body: retry });
      if (generation !== epoch) return;
      mergeTurns([receipt]);
      retry = null;
      if (input.value === submittedDraft) input.value = "";
      render();
      status.textContent = receipt.status === "applied" ? "Yapılandırma kaydedildi; kaynak listesi yenileniyor…" : "";
      if (receipt.status === "applied") { await onChanged(); if (generation === epoch) status.textContent = "Kaynak listesi güncel."; }
    } catch (error) { if (generation === epoch) status.textContent = error.message; }
    finally { if (generation === epoch) { busy = false; send.disabled = false; render(); } }
  });
  input.addEventListener("keydown", event => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); form.requestSubmit(); }
  });
  return { node, unlock() { if (locked) { locked = false; void refresh(); } }, refresh,
    reset() { epoch++; locked = true; busy = false; retry = null; turns = []; input.value = ""; status.textContent = ""; send.disabled = false; render(); } };
}
