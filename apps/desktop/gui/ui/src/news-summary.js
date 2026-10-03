export function createNewsSummary({ el, api, request }) {
  const active = new Set();
  let generation = 0;
  function stopAll() {
    generation++;
    for (const item of active) {
      item.audio.pause();
      item.audio.removeAttribute("src");
      item.audio.load();
      URL.revokeObjectURL(item.url);
    }
    active.clear();
  }
  function control(article) {
    const summary = el("div", { class: "news-summary", hidden: true });
    const button = el(
      "button",
      { type: "button", class: "btn btn-ikincil mini" },
      "Özetle ve dinle",
    );
    button.addEventListener("click", async () => {
      const current = generation;
      for (const item of active) {
        if (summary.contains(item.audio)) {
          item.audio.pause();
          item.audio.removeAttribute("src");
          item.audio.load();
          URL.revokeObjectURL(item.url);
          active.delete(item);
        }
      }
      button.disabled = true;
      summary.hidden = false;
      summary.replaceChildren(
        el("p", { role: "status" }, "Haber özeti hazırlanıyor…"),
      );
      try {
        const data = await api(
          `/articles/${encodeURIComponent(article.id)}/summary`,
          { method: "POST" },
        );
        if (current !== generation) return;
        const speak = el(
          "button",
          { type: "button", class: "btn btn-ikincil mini" },
          "Sesli oku",
        );
        const audio = el("audio", {
          controls: true,
          hidden: true,
          "aria-label": "Haber özeti sesli okuma",
        });
        const status = el("p", { class: "field-note", role: "status" });
        summary.replaceChildren(
          el("strong", {}, data.label || "Haber özeti"),
          el(
            "p",
            {},
            data.summary ||
              "Bu kayıtta özet oluşturmak için yeterli metin yok.",
          ),
          el("p", { class: "field-note" }, data.notice || ""),
          ...(data.status === "ready" ? [speak] : []),
          audio,
          status,
        );
        speak.addEventListener("click", async () => {
          speak.disabled = true;
          status.textContent = "Türkçe ses hazırlanıyor…";
          try {
            for (const item of active) item.audio.pause();
            const response = await request(
              `/api/rasathane/articles/${encodeURIComponent(article.id)}/speech`,
              { method: "POST" },
            );
            if (!response.ok) {
              let message;
              try {
                message = (await response.json()).error;
              } catch {}
              throw new Error(
                message ||
                  "Türkçe ses üretilemedi. Windows Türkçe ses paketini kontrol edin.",
              );
            }
            const blob = await response.blob();
            if (current !== generation) return;
            const url = URL.createObjectURL(blob);
            active.add({ audio, url });
            audio.src = url;
            audio.hidden = false;
            status.textContent =
              "Ses hazır. Oynatma düğmesiyle dinleyebilirsiniz.";
            speak.hidden = true;
            try {
              await audio.play();
            } catch {
              /* Kullanıcı audio kontrolüyle başlatabilir. */
            }
          } catch (error) {
            if (current === generation) status.textContent = error.message;
          } finally {
            speak.disabled = false;
          }
        });
      } catch (error) {
        if (current === generation)
          summary.replaceChildren(el("p", { role: "alert" }, error.message));
      } finally {
        button.disabled = false;
      }
    });
    return el("div", { class: "news-summary-control" }, button, summary);
  }
  return { control, stopAll };
}
