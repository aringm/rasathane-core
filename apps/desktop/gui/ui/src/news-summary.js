export function createNewsSummary({ el, api, request, pause = ms => new Promise(resolve => setTimeout(resolve, ms)) }) {
  const active = new Set();
  let generation = 0;
  function release(item) {
    item.audio.pause(); item.audio.removeAttribute("src"); item.audio.load();
    URL.revokeObjectURL(item.url); active.delete(item);
  }
  function stopAll() { generation++; for (const item of [...active]) release(item); }
  function control(article, { source, onAnalyze, onSummary, analysisSupported = true } = {}) {
    let data = null, summaryPromise = null, voiceBusy = false, ownedAudio = null;
    const summary = el("div", { class: "news-summary", hidden: true });
    const content = el("div", { class: "news-summary-text" });
    const audio = el("audio", { controls: true, hidden: true, "aria-label": "Haber özeti sesli okuma" });
    const status = el("p", { class: "field-note", role: "status", "aria-live": "polite" });
    summary.append(content, audio, status);
    const button = el("button", { type: "button", class: "btn btn-ikincil mini news-summarize", disabled: !article.id }, "Özetle");
    const speak = el("button", { type: "button", class: "btn btn-ikincil mini news-speak", disabled: !article.id }, "Seslendir");
    const analyze = el("button", { type: "button", class: "btn btn-ikincil mini news-analyze", disabled: !analysisSupported,
      title: analysisSupported ? "Kaynağın analizini başlat" : "Bu kayıt yalnız karar künyesi veya yönetilen özet içeriyor." }, "Derinlemesine analiz et");
    analyze.addEventListener("click", async () => { if (!analysisSupported || !onAnalyze) return; analyze.disabled = true; try { await onAnalyze(); } finally { analyze.disabled = !analysisSupported; } });
    const actions = el("div", { class: "news-actions" }, source || el("button", { type: "button", class: "btn btn-ikincil mini", disabled: true }, "Kaynağı aç"), button, speak, analyze);
    function clearAudio() { if (ownedAudio) release(ownedAudio); ownedAudio = null; audio.hidden = true; }
    async function summarize(force = false) {
      if (summaryPromise) return summaryPromise;
      if (data && !force) return data;
      const current = generation; button.disabled = true; summary.hidden = false;
      status.textContent = "Türkçe haber özeti hazırlanıyor…";
      summaryPromise = (async () => {
        try {
          let result = await api(`/articles/${encodeURIComponent(article.id)}/summary`, { method: "POST" });
          for (let attempt = 0; result.status === "pending" && attempt < 400; attempt++) {
            if (current !== generation) return null;
            const id = result.job_id || result.job?.id;
            if (!id) throw new Error("Özet hazırlığının işlem kaydı alınamadı.");
            status.textContent = "Türkçe haber özeti hazırlanıyor…";
            await pause(1500);
            if (current !== generation) return null;
            const job = await api(`/jobs/${encodeURIComponent(id)}`);
            if (["failed", "cancelled", "interrupted"].includes(job.status)) throw new Error(job.error || "Türkçe haber özeti tamamlanamadı.");
            if (job.status === "completed") result = await api(`/articles/${encodeURIComponent(article.id)}/summary`, { method: "POST" });
          }
          if (result.status === "pending") throw new Error("Özet hazırlığı sürüyor. Biraz sonra yeniden deneyin.");
          if (current !== generation) return null;
          if (result.status === "ready" && result.language !== "tr") throw new Error("Türkçe özet doğrulanamadı. Haberi kaynağından açabilirsiniz.");
          data = result; const shownInline = onSummary?.(result) === true;
          if (source?.tagName === "A" && result.url) {
            try { const url = new URL(result.url); if (["https:", "http:"].includes(url.protocol) && !url.username && !url.password) source.href = url.href; } catch {}
          }
          content.hidden = shownInline; summary.hidden = shownInline && !voiceBusy;
          content.replaceChildren(el("strong", {}, result.label || "Haber özeti"),
            el("p", {}, result.summary || "Bu kayıtta özet oluşturmak için yeterli metin yok."),
            result.notice ? el("p", { class: "field-note" }, result.notice) : null);
          status.textContent = ""; speak.disabled = voiceBusy || result.status !== "ready";
          return result;
        } catch (error) { if (current === generation) status.textContent = error.message; return null; }
        finally { summaryPromise = null; button.disabled = false; }
      })();
      return summaryPromise;
    }
    button.addEventListener("click", async () => { clearAudio(); await summarize(true); });
    speak.addEventListener("click", async () => {
      if (voiceBusy) return;
      const current = generation; voiceBusy = true; speak.disabled = true; summary.hidden = false;
      try {
        if (ownedAudio && active.has(ownedAudio)) { for (const item of active) item.audio.pause(); audio.hidden = false; await audio.play().catch(() => {}); return; }
        const result = await summarize();
        if (current !== generation || result?.status !== "ready") return;
        status.textContent = "Türkçe ses hazırlanıyor…";
        for (const item of active) item.audio.pause();
        const response = await request(`/api/rasathane/articles/${encodeURIComponent(article.id)}/speech`, { method: "POST" });
        if (!response.ok) { const error = await response.json().catch(() => ({})); throw new Error(error.error || "Türkçe ses üretilemedi. Windows Türkçe ses paketini kontrol edin."); }
        const blob = await response.blob(); if (current !== generation) return;
        clearAudio(); const url = URL.createObjectURL(blob); ownedAudio = { audio, url }; active.add(ownedAudio);
        audio.src = url; audio.hidden = false; status.textContent = "";
        try { await audio.play(); } catch { status.textContent = "Oynatma düğmesiyle dinleyebilirsiniz."; }
      } catch (error) { if (current === generation) status.textContent = error.message; }
      finally { voiceBusy = false; speak.disabled = data?.status !== "ready" && data !== null; }
    });
    return el("div", { class: "news-summary-control" }, actions, summary);
  }
  return { control, stopAll, pauseAll() { for (const item of active) item.audio.pause(); } };
}
