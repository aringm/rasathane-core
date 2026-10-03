export function createResearchChat({ $, el, api, waitJob, sourceLink }) {
  let conversation = null;
  let epoch = 0;
  let busy = false;
  let nextBefore = null;
  const messages = $("arastir-sonuc");
  const status = $("arastir-durum");
  const input = $("arastir-sorgu");
  const form = $("arastir-form");
  const history = $("arastir-gecmis");
  const historyPanel = $("arastir-gecmis-panel");
  const historyToggle = $("arastir-gecmis-ac");
  const historySearch = $("arastir-gecmis-ara");
  let historyItems = [];
  function closeHistory(restore = false) {
    historyPanel.hidden = true;
    historyToggle.setAttribute("aria-expanded", "false");
    if (restore) historyToggle.focus();
  }
  historyToggle.addEventListener("click", () => {
    if (!historyPanel.hidden) return closeHistory();
    historyPanel.hidden = false;
    historyToggle.setAttribute("aria-expanded", "true");
    historySearch.focus();
    refreshHistory();
  });
  historyPanel.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      closeHistory(true);
    }
  });
  document.addEventListener("pointerdown", (event) => {
    if (!historyPanel.contains(event.target) && !historyToggle.contains(event.target)) closeHistory();
  });
  historyPanel.addEventListener("focusout", () => queueMicrotask(() => {
    if (!historyPanel.contains(document.activeElement) && document.activeElement !== historyToggle) closeHistory();
  }));
  function renderHistory() {
    const query = historySearch.value.trim().toLocaleLowerCase("tr-TR");
    const items = historyItems.filter(item => (item.title || "Araştırma konuşması").toLocaleLowerCase("tr-TR").includes(query));
    history.replaceChildren(...items.map(item => el("button", {
      type: "button", class: "chat-history-item", "aria-current": String(item.id === conversation),
      onclick: async () => {
        if (busy) return;
        await open(item.id);
        input.focus();
      }, disabled: busy,
    }, item.title || "Araştırma konuşması")));
    if (!items.length) history.append(el("p", { class: "field-note" }, query ? "Bu aramayla eşleşen konuşma yok." : "İlk sorunuzla konuşma geçmişiniz oluşur."));
  }
  historySearch.addEventListener("input", renderHistory);
  function resizeInput() {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
  }
  input.addEventListener("input", resizeInput);
  function bubble(message, target = messages) {
    const result = message.result || {};
    const sources = result.citations?.length
      ? result.citations
      : [...(result.local_results || []), ...(result.web_results || [])];
    const node = el(
      "article",
      { class: `chat-message chat-${message.role}` },
      el(
        "div",
        { class: "chat-role" },
        message.role === "user" ? "Siz" : "Rasathane",
      ),
      el(
        "p",
        { class: "chat-content" },
        message.content || "Kaynaklar inceleniyor…",
      ),
      message.role === "assistant" && result.answer_kind === "source_extracts"
        ? el("p", { class: "field-note" }, "Kaynaklara dayalı alıntılı yanıt")
        : null,
      sources.length
        ? el(
            "details",
            { class: "chat-sources" },
            el("summary", {}, `Kaynakları incele (${sources.length})`),
            ...sources.map((item, index) =>
              el(
                "div",
                { class: "chat-source" },
                el(
                  "strong",
                  {},
                  `${index + 1}. ${item.title || "Yerel kayıt"}`,
                ),
                el(
                  "p",
                  {},
                  item.quote || item.excerpt || item.summary || item.body || "",
                ),
                sourceLink(item.url, "Kaynağı aç"),
              ),
            ),
          )
        : null,
      message.status === "failed" || message.status === "cancelled"
        ? el(
            "p",
            { class: "record-error" },
            message.status === "cancelled"
              ? "Bu yanıt iptal edildi."
              : "Bu yanıt tamamlanamadı; yeniden deneyebilirsiniz.",
          )
        : null,
      ...(result.errors || []).map((error) =>
        el("p", { class: "field-note" }, String(error)),
      ),
    );
    target.append(node);
    if (target === messages) messages.scrollTop = messages.scrollHeight;
  }
  function olderButton() {
    if (!nextBefore) return;
    const button = el(
      "button",
      { type: "button", class: "btn btn-ikincil mini chat-older" },
      "Önceki mesajları yükle",
    );
    button.addEventListener("click", async () => {
      const current = epoch;
      button.disabled = true;
      try {
        const data = await api(
          `/conversations/${encodeURIComponent(conversation)}?before=${encodeURIComponent(nextBefore)}`,
        );
        if (current !== epoch) return;
        const height = messages.scrollHeight;
        const previous = document.createDocumentFragment();
        for (const message of data.messages || []) bubble(message, previous);
        button.remove();
        messages.prepend(previous);
        nextBefore = data.next_before;
        olderButton();
        messages.scrollTop += messages.scrollHeight - height;
      } catch (error) {
        if (current === epoch) status.textContent = error.message;
      } finally {
        button.disabled = false;
      }
    });
    messages.prepend(button);
  }
  function welcome() {
    messages.replaceChildren(
      el(
        "div",
        { class: "chat-welcome" },
        el("h2", {}, "Neyi birlikte inceleyelim?"),
        el(
          "p",
          {},
          "Bir soru sorun. Yerel kayıtlarınızı tarayın, kaynaklara dönün ve aynı konuşmada devam edin.",
        ),
      ),
    );
  }
  async function refreshHistory() {
    const current = epoch;
    try {
      const data = await api("/conversations");
      if (current !== epoch) return;
      historyItems = data.items || [];
      renderHistory();
    } catch (error) {
      if (current === epoch) status.textContent = error.message;
    }
  }
  async function open(id) {
    const current = ++epoch;
    try {
      const data = await api(`/conversations/${encodeURIComponent(id)}`);
      if (current !== epoch) return;
      conversation = data.id;
      $("arastir-baslik").textContent = data.title || "Araştırma konuşması";
      closeHistory();
      $("arastir-alan").value = data.workspace_id || "";
      controls();
      messages.replaceChildren();
      for (const message of data.messages || []) bubble(message);
      nextBefore = data.next_before;
      olderButton();
      if (!data.messages?.length) welcome();
      status.textContent = "Konuşma cihazınızdaki kayıttan açıldı.";
      refreshHistory();
    } catch (error) {
      if (current === epoch) status.textContent = error.message;
    }
  }
  function controls() {
    $("arastir-btn").disabled = busy;
    $("arastir-yeni").disabled = busy;
    $("arastir-alan").disabled = busy || !!conversation;
    $("arastir-alan-not").textContent = conversation
      ? "Bu konuşmanın çalışma alanı sabittir. Başka bir alan için yeni konuşma açın."
      : "Çalışma alanı konuşma boyunca aynı kalır.";
    for (const button of history.querySelectorAll("button"))
      button.disabled = busy;
  }
  function reset() {
    ++epoch;
    conversation = null;
    nextBefore = null;
    busy = false;
    input.value = "";
    input.style.height = "";
    historySearch.value = "";
    historyItems = [];
    closeHistory();
    $("arastir-baslik").textContent = "Yeni konuşma";
    history.replaceChildren();
    welcome();
    controls();
  }
  $("arastir-yeni").addEventListener("click", () => {
    if (busy) return;
    reset();
    refreshHistory();
    input.focus();
    status.textContent = "Yeni konuşma. Çalışma alanını seçip sorunuzu yazın.";
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      if (!busy) form.requestSubmit();
    }
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const query = input.value.trim();
    if (!query || busy) return;
    const current = epoch;
    busy = true;
    controls();
    if (!conversation) messages.replaceChildren();
    bubble({ role: "user", content: query });
    input.value = "";
    resizeInput();
    try {
      const job = await api("/research", {
        method: "POST",
        body: {
          query,
          workspace_id: $("arastir-alan").value || null,
          web: $("arastir-web").checked,
          ...(conversation ? { conversation_id: conversation } : {}),
        },
      });
      if (current !== epoch) return;
      conversation = job.request?.conversation_id || conversation;
      const result = await waitJob(job, status);
      if (current !== epoch) return;
      conversation = result?.conversation_id || conversation;
      if (conversation) await open(conversation);
      else
        bubble({
          role: "assistant",
          content: result?.answer || "Bu soruya kaynaklı bir yanıt bulunamadı.",
          result,
        });
    } catch (error) {
      if (current !== epoch) return;
      status.textContent = error.message;
      if (conversation) await open(conversation);
      else
        bubble({ role: "assistant", content: error.message, status: "failed" });
      input.value = query;
      resizeInput();
    } finally {
      busy = false;
      controls();
      refreshHistory();
    }
  });
  welcome();
  return {
    refreshHistory,
    open,
    reset,
    showResult: (result) => {
      if (result.conversation_id) return open(result.conversation_id);
      reset();
      messages.replaceChildren();
      bubble({ role: "user", content: result.query });
      bubble({
        role: "assistant",
        content:
          result.answer ||
          "Bu eski araştırma kaydının kaynaklarını aşağıdan inceleyebilirsiniz.",
        result,
      });
    },
  };
}
