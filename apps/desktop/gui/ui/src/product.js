import { createSourceManager } from "./source-manager.js";
import { createRadarFeed } from "./radar-feed.js";
import { createSettingsDraft } from "./settings-controller.js";
import { createResearchChat } from "./research-chat.js";
import { createNewsSummary } from "./news-summary.js";
import { createNewsBulletin } from "./news-bulletin.js";
import { createWorkspaceExamples } from "./workspace-examples.js";
// Birleşik ürünün gerçek kayıtları. Dış metinler yalnız güvenli DOM helper'ıyla yazılır.
import { recordDate } from "./record-provenance.js";

export function createProductUI({
  $,
  el,
  request,
  setView,
  onAnalysis,
  analysisProgress,
  onSettings,
}) {
  let state = null;
  let unlocked = false;
  let authEpoch = 0;
  let activeWorkspace = null;
  let currentView = "akis";
  let lastSuccess = null;
  let loadingPromise = null;
  let setupDismissed = false;
  let modelTimer = null;
  let modelStatusPending = null;
  let advancedProfileReady = false;
  let accountTimer = null;
  let accountLoading = false;
  let accountState = "unknown";
  let entitlement = null;
  const pendingJobs = new Set();
  const terminal = new Set(["completed", "failed", "cancelled", "interrupted"]);
  const jobLabels = {
    queued: "Sırada",
    running: "Çalışıyor",
    cancel_requested: "İptal bekleniyor",
    cancelled: "İptal edildi",
    completed: "Tamamlandı",
    failed: "Başarısız",
    interrupted: "Kesildi",
  };
  const stageLabels = {
    queued: "İşlem sıraya alındı",
    acquiring: "Kaynak ediniliyor",
    analyzing: "Kaynak analiz ediliyor",
    analysis: "Kaynak analiz ediliyor",
    searching: "Kaynaklar aranıyor",
    local_search: "Yerel kayıtlar aranıyor",
    web_search: "Web kaynakları aranıyor",
    saving: "Sonuç kaydediliyor",
    completed: "İşlem tamamlandı",
  };
  const kindLabels = {
    analysis: "Analiz",
    research: "Araştırma",
    note: "Not",
    article: "Kaynak",
    web: "Web kaynağı",
    web_source: "Konu / web kaynağı",
    bulletin: "Bülten",
  };
  const feedRefresh = $("kaynak-kontrol-btn");
  const jobList = el("div", { id: "islem-liste", class: "record-list" });
  $("gorunum-akis").append(
    el(
      "details",
      { class: "jobs-overview" },
      el("summary", {}, "İşlem kaydı"),
      jobList,
    ),
  );
  const accountNotice = el("div", {
    id: "hesap-durum",
    class: "product-status",
    role: "status",
    "aria-live": "polite",
  });
  const accountPlan = el("div", { id: "hesap-plan", class: "account-plan" });
  const accountLogin = el(
    "button",
    { id: "hesap-giris", type: "button", class: "btn" },
    "E-posta ile giriş yap",
  );
  const accountRefresh = el(
    "button",
    { id: "hesap-yenile", type: "button", class: "btn btn-ikincil" },
    "Durumu yenile",
  );
  const accountTrial = el(
    "button",
    { id: "hesap-deneme", type: "button", class: "btn" },
    "14 günlük denemeyi başlat",
  );
  const accountLogout = el(
    "button",
    { id: "hesap-cikis", type: "button", class: "btn btn-ikincil" },
    "Çıkış yap",
  );
  const accountClose = el(
    "button",
    { type: "button", class: "btn btn-ikincil" },
    "Kapat",
  );
  const accountDialog = el(
    "dialog",
    {
      id: "hesap-dialog",
      class: "setup-dialog",
      "aria-labelledby": "hesap-baslik",
    },
    el("h2", { id: "hesap-baslik" }, "Hesap ve plan"),
    el(
      "p",
      { class: "field-note" },
      "Yerel çekirdek ücretsizdir. Yönetilen hizmet aylık KDV dahil toplam 49 TL’dir; otomatik yenileme veya tahsilat yapılmaz. 14 günlük deneme yalnız aşağıdaki düğmeyle başlatılır.",
    ),
    accountNotice,
    accountPlan,
    el(
      "div",
      { class: "form-actions" },
      accountLogin,
      accountRefresh,
      accountTrial,
      accountLogout,
    ),
    el(
      "p",
      { class: "field-note" },
      el(
        "a",
        {
          href: "https://www.muhakeme.ai/hesap?urun=rasathane",
          target: "_blank",
          rel: "noopener noreferrer",
        },
        "Hesap ve ödeme sayfasını aç",
      ),
    ),
    el("div", { class: "form-actions" }, accountClose),
  );
  document.body.append(accountDialog);
  const settingsAccountNotice = el(
    "p",
    { class: "field-note" },
    "Muhakeme hesabınızın planını ve hizmet erişimini buradan yönetin.",
  );
  const settingsAccountButton = el(
    "button",
    { type: "button", class: "btn btn-ikincil" },
    "Hesap ve planı aç",
  );
  $("ayarlar-hesap-icerik").append(
    el(
      "section",
      { class: "account-settings kart" },
      el("h2", {}, "Muhakeme hesabı"),
      settingsAccountNotice,
      settingsAccountButton,
    ),
  );

  const errorMessage = (error, fallback = "İşlem tamamlanamadı.") => {
    const value =
      typeof error === "string"
        ? error
        : error?.message ||
          error?.hata ||
          error?.error?.message ||
          error?.detail;
    return typeof value === "string" ? value.slice(0, 350) : fallback;
  };
  async function api(path, { method = "GET", body } = {}) {
    if (!unlocked) throw new Error("Devam etmek için giriş yapın.");
    const epoch = authEpoch;
    if (
      body !== undefined &&
      new TextEncoder().encode(JSON.stringify(body)).byteLength > 8192
    ) {
      throw new Error(
        "Metin bu işlem için çok uzun. Kaydetmeden önce kısaltın.",
      );
    }
    const response = await request("/api/rasathane" + path, {
      method,
      ...(body === undefined
        ? {}
        : {
            body: JSON.stringify(body),
            headers: { "Content-Type": "application/json" },
          }),
    });
    const data = await response.json().catch(() => null);
    if (!unlocked || epoch !== authEpoch) throw new Error("Oturum kapandı.");
    if (!response.ok)
      throw new Error(
        errorMessage(
          data,
          `Yerel servis isteği tamamlanamadı (HTTP ${response.status}).`,
        ),
      );
    return data;
  }
  function safeURL(value) {
    try {
      const url = new URL(value);
      return ["http:", "https:"].includes(url.protocol) ? url.href : null;
    } catch {
      return null;
    }
  }
  const date = (value, empty = "Henüz kontrol edilmedi", onlyDate = false) => {
    const parsed = value ? new Date(value) : null;
    return parsed && !Number.isNaN(parsed.getTime())
      ? parsed.toLocaleString("tr-TR", {
          dateStyle: "short",
          ...(onlyDate ? {} : { timeStyle: "short" }),
        })
      : empty;
  };
  const count = (value) =>
    typeof value === "number" && Number.isFinite(value)
      ? value.toLocaleString("tr-TR")
      : "—";
  const empty = (text) => el("div", { class: "empty-state" }, text);
  function message(node, text, isError = false) {
    node.replaceChildren(el("span", {}, text));
    node.classList.toggle("status-error", isError);
  }
  function sourceLink(url, label = "Kaynağı aç") {
    const href = safeURL(url);
    return href
      ? el(
          "a",
          {
            href,
            target: "_blank",
            rel: "noopener noreferrer",
            class: "record-link",
          },
          label,
        )
      : null;
  }
  function record(item, { full = false, action = null } = {}) {
    const body = item.summary || item.excerpt || item.body || "";
    const provenance = item.provenance || {};
    const sourceType = state?.sources?.find(
      (source) => source.id === item.source_id,
    )?.kind;
    const officialMetadata = provenance.text_scope === "official_metadata";
    const managedSummary = provenance.text_scope === "managed_summary";
    const shownDate = recordDate(item, sourceType);
    const summaryLabel =
      provenance.summary_kind === "ai_generated"
        ? "AI tarafından oluşturulmuş özet"
        : provenance.summary_kind === "source_excerpt"
          ? "Kaynak alıntısı"
          : null;
    return el(
      "article",
      { class: "record" },
      el(
        "div",
        { class: "record-meta" },
        managedSummary
          ? "Muhakeme · Karar özeti"
          : officialMetadata
            ? "Karar künyesi"
            : sourceType === "resmi_gazete"
              ? "Resmî Gazete"
              : kindLabels[item.kind] || "Kaynak",
        el(
          "span",
          {},
          `${shownDate.label}${date(
            shownDate.value,
            "Tarih kaydı yok",
            shownDate.dayOnly,
          )}`,
        ),
      ),
      el("h3", {}, item.title || "Başlıksız kayıt"),
      summaryLabel ? el("p", { class: "field-note" }, summaryLabel) : null,
      body
        ? el(
            "p",
            { class: full ? "note-body" : "record-excerpt" },
            full ? body : String(body).slice(0, 420),
          )
        : null,
      item.body_truncated
        ? el(
            "p",
            { class: "field-note" },
            "Kısaltılmış önizleme. Tam kayıt dışa aktarma dosyasında korunur.",
          )
        : null,
      officialMetadata &&
        !String(body).toLocaleLowerCase("tr-TR").includes("tam metni")
        ? el(
            "p",
            { class: "field-note" },
            "Resmî karar künyesi gösteriliyor. Kararın tam metni bu kayıtta bulunmaz.",
          )
        : null,
      managedSummary
        ? el(
            "p",
            { class: "field-note" },
            "Özet gösteriliyor. Kararın tam metni bu kayıtta bulunmaz; özeti kaynak kararı açarak kontrol edin.",
          )
        : null,
      el(
        "div",
        { class: "record-actions" },
        sourceLink(item.provenance?.portal_url || item.url),
        action,
      ),
    );
  }
  function renderFeed() {
    sourcesUI.update(state?.sources || []);
    dashboard.update(state || {});
  }
  function renderTopics() {
    const topics = state?.topics || [];
    $("konu-liste").replaceChildren(
      ...(topics.length
        ? topics.map((topic) => {
            const webEnabled = !!state?.settings?.web_enabled;
            const button = el(
              "button",
              {
                type: "button",
                class: "btn btn-ikincil mini",
                disabled: !webEnabled,
                title: webEnabled
                  ? "Konu için web kaynaklarını kontrol et"
                  : "Konu kontrolü için Ayarlar'da web aramasını açın",
              },
              "Şimdi kontrol et",
            );
            button.addEventListener("click", async () => {
              button.disabled = true;
              try {
                const job = await api(
                  `/topics/${encodeURIComponent(topic.id)}/refresh`,
                  { method: "POST" },
                );
                await waitJob(job, $("konu-durum"));
                await load();
                message(
                  $("konu-durum"),
                  "Konu kontrolü tamamlandı. Bulunan kaynakları Sonuçları aç düğmesiyle inceleyebilirsiniz.",
                );
              } catch (error) {
                message($("konu-durum"), errorMessage(error), true);
              } finally {
                button.disabled = false;
              }
            });
            const results = el("button", { type: "button", class: "btn btn-ikincil mini topic-results", onclick: async () => {
              results.disabled = true;
              try {
                const data = await api(`/topics/${encodeURIComponent(topic.id)}`);
                const result = data.latest_result;
                topicResultBody.replaceChildren(
                  el("h3", {}, topic.name),
                  el("p", { class: "field-note" }, topic.query),
                  ...(result ? [
                    el("p", {}, `${(result.web_results || []).length} kaynak · Son başarılı kontrolün sonuçları`),
                    ...(result.web_results || []).map((item) => record(item)),
                    ...(!result.web_results?.length ? [empty("Son kontrol bu sorguyla kaynak bulamadı.")] : []),
                    ...(result.errors || []).map((text) => el("p", { class: "field-note" }, text)),
                  ] : [empty("Henüz tamamlanmış kontrol yok. Web aramasını açıp Şimdi kontrol et düğmesini kullanın.")]),
                );
                topicResultDialog.showModal();
              } catch (error) { message($("konu-durum"), errorMessage(error), true); }
              finally { results.disabled = false; }
            } }, "Sonuçları aç");
            return el(
              "article",
              { class: "record topic-record" },
              el(
                "div",
                {},
                el("h3", {}, topic.name),
                el("p", {}, topic.query),
                el(
                  "div",
                  { class: "record-meta" },
                  date(topic.last_refreshed_at),
                  el("span", {}, `Yeni kaynak: ${count(topic.new_count)}`),
                ),
                topic.last_error
                  ? el(
                      "p",
                      { class: "record-error" },
                      errorMessage(topic.last_error),
                    )
                  : null,
                !webEnabled
                  ? el(
                      "p",
                      { class: "field-note" },
                      "Konu kontrolü için Ayarlar'da web aramasını açın.",
                    )
                  : null,
              ),
              el("div", { class: "form-actions" }, button, results),
            );
          })
        : [
            empty("Henüz takip konusu yok. Bir isim ve arama sorgusu ekleyin."),
          ]),
    );
  }
  function renderWorkspaces() {
    const workspaces = state?.workspaces || [];
    if (
      activeWorkspace &&
      !workspaces.some((item) => item.id === activeWorkspace)
    )
      activeWorkspace = null;
    if (!activeWorkspace && workspaces.length)
      activeWorkspace = workspaces[0].id;
    $("calisma-alanlar").replaceChildren(
      ...(workspaces.length
        ? workspaces.map((workspace) =>
            el(
              "button",
              {
                type: "button",
                class: "workspace-button",
                "aria-pressed": String(workspace.id === activeWorkspace),
                onclick: () => {
                  activeWorkspace = workspace.id;
                  renderWorkspaces();
                  loadNotes();
                },
              },
              workspace.name,
            ),
          )
        : [empty("Henüz çalışma alanı yok.")]),
    );
    const previous = $("arastir-alan").value;
    $("arastir-alan").replaceChildren(
      el("option", { value: "" }, "Tüm yerel kayıtlar"),
      ...workspaces.map((workspace) =>
        el("option", { value: workspace.id }, workspace.name),
      ),
    );
    if (workspaces.some((workspace) => workspace.id === previous))
      $("arastir-alan").value = previous;
    $("not-form").classList.toggle("gizli", !activeWorkspace);
    $("calisma-export").disabled = !state;
    const selected = workspaces.find(
      (workspace) => workspace.id === activeWorkspace,
    );
    message(
      $("calisma-durum"),
      selected
        ? `${selected.name} çalışma alanı`
        : "Bir çalışma alanı oluşturun. Notlarınız ve araştırma kayıtlarınız bu alanda birikir.",
    );
    renderLibrary();
  }
  function renderLibrary() {
    const items = (state?.library || []).filter(
      (item) =>
        item.kind !== "note" &&
        (!activeWorkspace ||
          item.workspace_id === activeWorkspace ||
          item.workspace_id == null),
    );
    $("yerel-kitaplik").replaceChildren(
      ...(items.length
        ? items.map((item) =>
            record(item, {
              action: item.provenance
                ? el(
                    "details",
                    { class: "source-provenance" },
                    el("summary", {}, "Kaynak kaydı"),
                    ...Object.entries(item.provenance)
                      .filter(([, value]) =>
                        ["string", "number", "boolean"].includes(typeof value),
                      )
                      .map(([key, value]) =>
                        el(
                          "p",
                          {},
                          `${{ source_id: "Kaynak kimliği", version_id: "Kaynak sürümü", content_hash: "İçerik hash'i", provider: "Edinim sağlayıcısı", url: "Kaynak adresi", fetch_status: "Edinim durumu" }[key] || key}: ${String(value).slice(0, 300)}`,
                        ),
                      ),
                  )
                : null,
            }),
          )
        : [
            empty(
              "Bu alanda kayıtlı kaynak yok. Bir araştırma başlatın veya bağlantıyı analiz edin.",
            ),
          ]),
    );
  }
  function renderJobs() {
    const jobs = state?.jobs || [];
    jobList.replaceChildren(
      ...(jobs.length
        ? jobs.slice(0, 12).map((job) => {
            let action = null;
            if (!terminal.has(job.status)) {
              action = el(
                "button",
                {
                  type: "button",
                  class: "btn btn-ikincil mini",
                  disabled: job.status === "cancel_requested",
                },
                job.status === "cancel_requested"
                  ? "İptal bekleniyor"
                  : "İptal et",
              );
              action.addEventListener("click", async () => {
                action.disabled = true;
                try {
                  await api(`/jobs/${encodeURIComponent(job.id)}/cancel`, {
                    method: "POST",
                  });
                  await load();
                } catch (error) {
                  message($("urun-durum"), errorMessage(error), true);
                  action.disabled = false;
                }
              });
            } else if (
              job.status === "completed" &&
              (job.has_result || job.result) &&
              ["analysis", "research"].includes(job.kind)
            ) {
              action = el(
                "button",
                {
                  type: "button",
                  class: "btn btn-ikincil mini",
                  onclick: async () => {
                    action.disabled = true;
                    action.textContent = "Sonuç okunuyor…";
                    try {
                      const fullJob = await api(
                        `/jobs/${encodeURIComponent(job.id)}`,
                      );
                      if (fullJob.status !== "completed" || !fullJob.result)
                        throw new Error(
                          "Tamamlanmış işlem sonucu okunamadı. Akışı yenileyin.",
                        );
                      if (job.kind === "analysis") {
                        onAnalysis(fullJob.result);
                        setView("analiz");
                      } else {
                        renderResearch(fullJob.result);
                        setView("arastir");
                      }
                    } catch (error) {
                      message($("urun-durum"), errorMessage(error), true);
                    } finally {
                      action.disabled = false;
                      action.textContent = "Sonucu aç";
                    }
                  },
                },
                "Sonucu aç",
              );
            }
            return el(
              "article",
              { class: "record job-record" },
              el(
                "div",
                {},
                el(
                  "h3",
                  {},
                  `${kindLabels[job.kind] || (job.kind === "refresh" ? "Konu kontrolü" : "Kaynak kontrolü")} · ${jobLabels[job.status] || "Durum bilinmiyor"}`,
                ),
                el(
                  "p",
                  { class: "record-meta" },
                  date(job.created_at),
                  el("span", {}, stageLabels[job.stage] || ""),
                ),
                job.error
                  ? el("p", { class: "record-error" }, errorMessage(job.error))
                  : null,
              ),
              action,
            );
          })
        : [empty("Henüz başlatılan işlem yok.")]),
    );
  }
  async function loadNotes() {
    const workspace = activeWorkspace;
    if (!workspace) {
      $("not-liste").replaceChildren(
        empty("Not yazmak için bir çalışma alanı oluşturun."),
      );
      return;
    }
    $("not-liste").replaceChildren(empty("Notlar yükleniyor…"));
    try {
      const result = await api(
        `/notes?workspace_id=${encodeURIComponent(workspace)}`,
      );
      if (workspace !== activeWorkspace) return;
      const items = result.items || [];
      $("not-liste").replaceChildren(
        ...(items.length
          ? items.map((item) =>
              record({ ...item, kind: "note" }, { full: true }),
            )
          : [
              empty(
                "Henüz not yok. İlk bulgunuzu yukarıdaki editöre kaydedin.",
              ),
            ]),
      );
    } catch (error) {
      if (workspace === activeWorkspace)
        $("not-liste").replaceChildren(empty(errorMessage(error)));
    }
  }
  function applyTheme(theme) {
    const dark =
      theme === "dark" ||
      (theme === "system" &&
        window.matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.dataset.theme = dark ? "dark" : "light";
  }
  function renderSettings() {
    const settings = state?.settings || {};
    draft.receive(settings);
    $("model").replaceChildren(
      el(
        "option",
        { value: settings.analysis_profile || "ram8" },
        {
          ram8: "8 GB RAM profili",
          ram16: "16 GB ve üzeri RAM profili",
          auto: "Otomatik donanım profili",
        }[settings.analysis_profile || "ram8"] || "Profil okunamadı",
      ),
    );
    $("arastir-web").disabled = !settings.web_enabled;
    if (!settings.web_enabled) $("arastir-web").checked = false;
    applyTheme(settings.theme || "system");
  }
  async function load() {
    if (!unlocked) return;
    if (loadingPromise) {
      await loadingPromise;
      return load();
    }
    loadingPromise = (async () => {
      const loadStatus = currentView === "kaynaklar" ? $("kaynak-yonetim-durum") : $("urun-durum");
      message(
        loadStatus,
        lastSuccess ? "Kayıtlar yenileniyor…" : "Yerel kayıtlar yükleniyor…",
      );
      try {
        state = await api("/state");
        lastSuccess = new Date().toISOString();
        renderFeed();
        renderTopics();
        renderWorkspaces();
        renderSettings();
        renderJobs();
        // İlk açılışta motor hazır olmadan geçmiş isteği gönderme.
        research.refreshHistory();
        bulletin.refreshHistory();
        const counts = state.counts || {};
        message(
          loadStatus,
          `${count(counts.articles)} içerik · ${count(counts.workspaces)} çalışma alanı · Son okuma: ${date(lastSuccess)}`,
        );
        if (currentView === "calisma") await loadNotes();
        try {
          if (
            !setupDismissed &&
            localStorage.getItem("rasathane-setup-v1") !== "complete" &&
            !$("ilk-kurulum").open
          )
            $("ilk-kurulum").showModal();
        } catch {
          /* Kalıcı tercih erişimi yoksa Ayarlar'dan ilk kurulum açılabilir. */
        }
        return true;
      } catch (error) {
        message(
          loadStatus,
          `${errorMessage(error, "Yerel kayıtlar okunamadı.")}${lastSuccess ? ` Son başarılı okuma: ${date(lastSuccess)}. Son bilinen kayıtlar gösteriliyor.` : " Yenile düğmesiyle tekrar deneyin."}`,
          true,
        );
        if (!state) {
          $("akis-liste").replaceChildren(
            empty(
              "Kayıtlar yüklenemedi. Yerel servis hazır olduğunda Yenile'ye basın.",
            ),
          );
          $("kaynak-liste").replaceChildren(empty("Kaynak durumu okunamadı."));
        }
        return false;
      }
    })();
    try {
      return await loadingPromise;
    } finally {
      loadingPromise = null;
    }
  }
  async function waitJob(initial, statusNode, progress) {
    if (!initial?.id) throw new Error("İşlem kimliği alınamadı.");
    pendingJobs.add(initial.id);
    let job = initial;
    const cancel = el(
      "button",
      { type: "button", class: "btn btn-ikincil mini" },
      "İptal et",
    );
    cancel.addEventListener("click", async () => {
      cancel.disabled = true;
      try {
        await api(`/jobs/${encodeURIComponent(job.id)}/cancel`, {
          method: "POST",
        });
        cancel.textContent = "İptal bekleniyor";
      } catch (error) {
        cancel.textContent = errorMessage(error, "İptal isteği gönderilemedi.");
        cancel.disabled = false;
      }
    });
    try {
      for (let iteration = 0; iteration < 1800; iteration++) {
        const label =
          stageLabels[job.stage] || jobLabels[job.status] || "İşlem sürüyor";
        if (statusNode) {
          statusNode.replaceChildren(
            el("span", progress ? { id: "calisma-metin" } : {}, label),
            ...(terminal.has(job.status) ? [] : [cancel]),
          );
          statusNode.classList.remove("status-error");
        }
        progress?.(label);
        if (job.status === "completed") return job.result;
        if (terminal.has(job.status))
          throw new Error(
            errorMessage(
              job.error,
              jobLabels[job.status] || "İşlem tamamlanamadı.",
            ),
          );
        await new Promise((resolve) => setTimeout(resolve, 1500));
        const fresh = await api(`/jobs/${encodeURIComponent(initial.id)}`);
        if (fresh.id !== initial.id)
          throw new Error(
            "İşlem kaydı okunamadı. Akışı yenileyin; işlem yeniden başlatılmadı.",
          );
        job = fresh;
      }
      throw new Error(
        "İşlem hâlâ sürüyor. Yerel servis kayıtlarını kontrol edin; aynı işlem yeniden başlatılmadı.",
      );
    } finally {
      pendingJobs.delete(initial.id);
    }
  }
  async function analyze(body) {
    const job = await api("/analysis", { method: "POST", body });
    const result = await waitJob(job, $("calisma-serit"), analysisProgress);
    if (!result || typeof result !== "object")
      throw new Error("Analiz çıktısı okunamadı.");
    onAnalysis(result);
    await load();
  }
  const research = createResearchChat({ $, el, api, waitJob, sourceLink });
  const news = createNewsSummary({ el, api, request });
  const bulletin = createNewsBulletin({ el, api, request, sourceLink, beforePlay: () => news.pauseAll() });
  const sourcesUI = createSourceManager({ $, el, api, sourceLink, date, onChange: async () => { if (!await load()) throw new Error("Kaynak kaydedildi ancak liste yenilenemedi. Listeyi yenile düğmesini kullanın."); }, onRefresh: refreshFeeds,
    onFilter: id => { setView("akis"); dashboard.filterSource(id); } });
  const dashboard = createRadarFeed({ $, el, api, news, bulletin, onSources: () => setView("kaynaklar"),
    renderRecord: item => record(item, { action: el("div", { class: "news-actions" }, news.control(item),
      safeURL(item.url) && item.analysis_supported !== false && item.provenance?.analysis_supported !== false && !["official_metadata", "managed_summary"].includes(item.provenance?.text_scope)
        ? el("button", { type: "button", class: "btn btn-ikincil mini", onclick: () => { $("url").value = item.url; $("url").dispatchEvent(new Event("input")); setView("analiz"); $("url").focus(); } }, "Derinlemesine analiz") : null) }) });
  const draft = createSettingsDraft({
    read: () => ({ theme: $("urun-tema").value, analysis_profile: $("urun-profil").value, search_provider: $("urun-arama-saglayici").value, topic_refresh_minutes: Number($("urun-takip-sikligi").value), web_enabled: $("urun-web").checked }),
    write: value => { $("urun-tema").value = value.theme; $("urun-profil").value = value.analysis_profile; $("urun-arama-saglayici").value = value.search_provider; $("urun-takip-sikligi").value = value.topic_refresh_minutes; $("urun-web").checked = value.web_enabled; },
    onState: detail => window.dispatchEvent(new CustomEvent("rasathane:settings-state", { detail })),
  });
  window.addEventListener("rasathane:settings-edited", () => draft.changed());
  window.addEventListener("rasathane:settings-discard", () => draft.reset());

  document.addEventListener("play", (event) => {
    if (event.target instanceof HTMLMediaElement)
      for (const audio of document.querySelectorAll("audio")) if (audio !== event.target) audio.pause();
  }, true);
  $("gorunum-akis").querySelector(".feed-layout").before(bulletin.node);
  const bulletinStyle = el("link", { rel: "stylesheet", href: "./bulletin.css" });
  document.head.append(bulletinStyle);
  const topicResultBody = el("div", { class: "record-list", id: "konu-sonuc-liste" });
  const topicResultClose = el("button", { type: "button", class: "btn btn-ikincil", onclick: () => topicResultDialog.close() }, "Kapat");
  const topicResultDialog = el("dialog", { class: "setup-dialog", id: "konu-sonuc-dialog", "aria-labelledby": "konu-sonuc-baslik" },
    el("div", { class: "page-heading" }, el("h2", { id: "konu-sonuc-baslik" }, "Takip sonuçları"), topicResultClose), topicResultBody);
  document.body.append(topicResultDialog);
  const examples = createWorkspaceExamples({ el, api, onCreated: async () => { await load(); await loadNotes(); } });
  $("gorunum-calisma").querySelector(".page-heading").after(examples.node);
  $("gorunum-calisma").querySelector(".page-heading p").textContent = "Notlarınızı ve bu alana bağlı araştırmaları bir arada tutun. Konu takibi tüm alanlardan bağımsız çalışır.";
  $("yerel-kitaplik").before(el("p", { class: "field-note" }, "Bu alana bağlı araştırmalar ve ortak kitaplıktaki kayıtlar gösterilir. Araştır’da alan seçtiğinizde o alanın not ve kaynaklarıyla genel haberler aranır; ortak konu kaynaklarını aramak için Tüm yerel kayıtlar’ı seçin."));
  function renderResearch(result) {
    research.showResult(result);
  }
  async function submit(form, status, action) {
    const button = form.querySelector('button[type="submit"]');
    if (form.dataset.submitting === "true") return;
    form.dataset.submitting = "true";
    if (button) button.disabled = true;
    message(status, "İstek gönderiliyor…");
    try {
      await action();
    } catch (error) {
      message(status, errorMessage(error), true);
    } finally {
      delete form.dataset.submitting;
      if (button) button.disabled = false;
    }
  }
  async function refreshFeeds(id, button) {
    const statusNode = currentView === "kaynaklar" ? $("kaynak-yonetim-durum") : $("urun-durum");
    button.disabled = true;
    message(statusNode, "Kaynak kontrolü başlatılıyor…");
    try {
      const job = await api(
        `/sources/${encodeURIComponent(id || "all")}/refresh`,
        { method: "POST" },
      );
      await waitJob(job, statusNode);
      await load();
      const failed = (state?.sources || []).some(
        (source) => (!id || source.id === id) && source.last_error,
      );
      message(
        statusNode,
        failed
          ? "Bazı kaynaklara ulaşılamadı. Son kontrol zamanı ve erişim hataları kaynak listesinde görünür."
          : "Kaynak kontrolü tamamlandı. Yeni kayıtlar ve son kontrol zamanı akışta görünür.",
        failed,
      );
    } catch (error) {
      message(statusNode, errorMessage(error), true);
    } finally {
      button.disabled = false;
    }
  }
  feedRefresh.addEventListener("click", () => refreshFeeds(null, feedRefresh));
  $("akis-yenile").addEventListener("click", load);
  $("kaynaklar-yenile").addEventListener("click", load);
  $("kaynaklar-kontrol").addEventListener("click", event => refreshFeeds(null, event.currentTarget));
  $("akis-kaynaklar-git").addEventListener("click", () => setView("kaynaklar"));
  $("calisma-ekle-form").addEventListener("submit", (event) => {
    event.preventDefault();
    submit(event.currentTarget, $("calisma-durum"), async () => {
      const created = await api("/workspaces", {
        method: "POST",
        body: { name: $("calisma-ad").value.trim() },
      });
      $("calisma-ad").value = "";
      await load();
      activeWorkspace = created.id;
      renderWorkspaces();
      await loadNotes();
    });
  });
  $("not-form").addEventListener("submit", (event) => {
    event.preventDefault();
    submit(event.currentTarget, $("not-sonuc"), async () => {
      if (!activeWorkspace) throw new Error("Önce bir çalışma alanı seçin.");
      await api("/notes", {
        method: "POST",
        body: {
          workspace_id: activeWorkspace,
          title: $("not-baslik").value.trim(),
          body: $("not-govde").value.trim(),
        },
      });
      $("not-baslik").value = "";
      $("not-govde").value = "";
      message($("not-sonuc"), "Not kaydedildi.");
      await loadNotes();
    });
  });
  $("konu-form").addEventListener("submit", (event) => {
    event.preventDefault();
    submit(event.currentTarget, $("konu-durum"), async () => {
      await api("/topics", {
        method: "POST",
        body: {
          name: $("konu-ad").value.trim(),
          query: $("konu-sorgu").value.trim(),
        },
      });
      $("konu-ad").value = "";
      $("konu-sorgu").value = "";
      await load();
      message(
        $("konu-durum"),
        state?.settings?.web_enabled
          ? "Konu eklendi. İlk kontrol için Şimdi kontrol et'e basın."
          : "Konu eklendi. Kontrol başlatmak için Ayarlar'da web aramasını açın.",
      );
    });
  });
  $("urun-ayar-form").addEventListener("submit", (event) => {
    event.preventDefault();
    submit(event.currentTarget, $("urun-ayar-sonuc"), async () => {
      if (!state?.settings) throw new Error("Ayarlar henüz okunamadı. Yerel durumu yenileyip yeniden deneyin.");
      if ($("urun-profil").value === "ram16" && !advancedProfileReady)
        throw new Error(
          "Gelişmiş model doğrulanmadı. Bu paket için temel 8 GB profilini seçin.",
        );
      const submitted = draft.read();
      const saved = await api("/settings", { method: "POST", body: submitted });
      draft.saved(saved, submitted);
      state.settings = saved;
      applyTheme(saved.theme);
      await load();
      message($("urun-ayar-sonuc"), draft.hasChanges() ? "Önceki değişiklikler kaydedildi; yeni değişiklikler henüz kaydedilmedi." : "Ayarlar kaydedildi.");
      onSettings?.();
    });
  });
  $("calisma-export").addEventListener("click", async () => {
    const button = $("calisma-export");
    button.disabled = true;
    try {
      if (window.rasathane) {
        if (!window.rasathane.exportData)
          throw new Error(
            "Bu uygulama sürümünde yerel dışa aktarma bağlantısı bulunamadı.",
          );
        const receipt = await window.rasathane.exportData(
          activeWorkspace || null,
        );
        if (receipt.cancelled) {
          message($("calisma-durum"), "Dışa aktarma iptal edildi.");
          return;
        }
        if (!receipt.saved || !receipt.path || !receipt.sha256)
          throw new Error("Dışa aktarma makbuzu doğrulanamadı.");
        message(
          $("calisma-durum"),
          `Dışa aktarma kaydedildi: ${receipt.path} (${count(receipt.bytes)} bayt). SHA256: ${receipt.sha256}`,
        );
        return;
      }
      const data = await api(
        "/export" +
          (activeWorkspace
            ? `?workspace_id=${encodeURIComponent(activeWorkspace)}`
            : ""),
      );
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }),
      );
      const anchor = el("a", {
        href: url,
        download: "rasathane-calisma-alani.json",
      });
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      message($("calisma-durum"), "JSON indirmesi tarayıcıya iletildi.");
    } catch (error) {
      message($("calisma-durum"), errorMessage(error), true);
    } finally {
      button.disabled = false;
    }
  });
  function accountMessage(text, isError = false) {
    message(accountNotice, text, isError);
    settingsAccountNotice.textContent = text;
  }
  function accountControls() {
    const native = !!window.rasathane?.accountStatus;
    accountLogin.classList.toggle("gizli", accountState === "signed_in");
    accountLogout.classList.toggle(
      "gizli",
      !["signed_in", "waiting"].includes(accountState),
    );
    accountTrial.classList.toggle("gizli", !entitlement);
    accountLogin.disabled =
      !native || accountLoading || accountState === "waiting";
    accountRefresh.disabled = !native || accountLoading;
    accountLogout.disabled = !native || accountLoading;
    accountTrial.disabled =
      !native || accountLoading || entitlement?.deneme_baslatilabilir !== true;
    accountTrial.title =
      entitlement?.deneme_baslatilabilir === true
        ? "Deneme süresi bu işlemle başlar"
        : "Bu hesap için yeni deneme başlatılamaz";
  }
  function showEntitlement(response) {
    const item = Array.isArray(response?.urunler)
      ? response.urunler.find((product) => product.urun === "rasathane")
      : null;
    const labels = {
      yok: "Ücretli hizmet henüz etkin değil",
      deneme: "Ücretsiz hizmet denemesi etkin",
      lisansli: "Ücretli hizmet dönemi etkin",
      "suresi-dolmus": "Hizmet dönemi sona ermiş",
    };
    if (
      !item ||
      !Object.hasOwn(labels, item.durum) ||
      typeof item.deneme_baslatilabilir !== "boolean"
    )
      throw new Error("Rasathane hizmet durumu doğrulanamadı.");
    entitlement = item;
    const end = item.bitis ? Date.parse(item.bitis) : NaN;
    const server = response.sunucu_zamani
      ? Date.parse(response.sunucu_zamani)
      : NaN;
    const remaining =
      Number.isFinite(end) && Number.isFinite(server)
        ? Math.max(0, end - server)
        : null;
    const period =
      remaining == null
        ? null
        : remaining < 86400000
          ? `Sunucu kaydına göre yaklaşık ${Math.ceil(remaining / 3600000)} saat kaldı.`
          : `Sunucu kaydına göre yaklaşık ${Math.ceil(remaining / 86400000)} gün kaldı.`;
    accountPlan.replaceChildren(
      el("h3", {}, labels[item.durum]),
      Number.isFinite(end)
        ? el("p", {}, `Dönem sonu: ${date(item.bitis)}`)
        : null,
      period ? el("p", {}, period) : null,
      el(
        "p",
        { class: "field-note" },
        item.deneme_baslatilabilir
          ? "14 günlük deneme henüz başlamadı. Başlatmak için aşağıdaki düğmeye basın."
          : "Bu hesapta yeni deneme başlatılamaz. Yerel çekirdek ücretsiz kullanılmaya devam eder.",
      ),
      el(
        "p",
        { class: "field-note" },
        `Son sunucu doğrulaması: ${date(response.sunucu_zamani, "Sunucu zamanı bildirilmedi")}`,
      ),
    );
  }
  async function refreshAccount() {
    if (accountLoading) return;
    clearTimeout(accountTimer);
    accountLoading = true;
    entitlement = null;
    accountPlan.replaceChildren();
    accountControls();
    if (!window.rasathane?.accountStatus) {
      accountState = "unavailable";
      accountMessage(
        "Hesap bağlantısı masaüstü uygulamasında yapılır. Hesap ve ödeme sayfasını aşağıdaki bağlantıyla açabilirsiniz.",
      );
      accountLoading = false;
      accountControls();
      return;
    }
    try {
      const status = await window.rasathane.accountStatus();
      accountState = status.state;
      if (accountState === "signed_in") {
        accountMessage(
          "Cihazdaki oturum bulundu. Hizmet durumu sunucudan doğrulanıyor…",
        );
        showEntitlement(await window.rasathane.entitlement());
        accountMessage(
          "Rasathane hesabı ve hizmet durumu sunucudan doğrulandı.",
        );
      } else if (["sending_code", "code_sent", "verifying_code", "waiting"].includes(accountState))
        accountMessage(
          "Giriş ekranında e-postanıza gelen doğrulama kodunu girin. Deneme otomatik başlamaz.",
        );
      else if (accountState === "failed")
        accountMessage(
          errorMessage(
            status.error,
            "Hesap bağlanamadı. Yeniden giriş yapmayı deneyin.",
          ),
          true,
        );
      else if (accountState === "signed_out")
        accountMessage(
          "Muhakeme hesabına giriş yapılmadı. Ekranları kullanmak için giriş yapın.",
        );
      else accountMessage("Hesap bağlantısının durumu okunamadı.", true);
    } catch (error) {
      entitlement = null;
      try {
        accountState = (await window.rasathane.accountStatus()).state;
      } catch {
        accountState = "unknown";
      }
      accountMessage(
        `${errorMessage(error, "Hesap durumu doğrulanamadı.")} Hesap durumunu yeniden kontrol edin.`,
        true,
      );
    } finally {
      accountLoading = false;
      accountControls();
      if (accountDialog.open && accountState === "waiting")
        accountTimer = setTimeout(refreshAccount, 2000);
    }
  }
  async function openAccountDialog() {
    if (!accountDialog.open) accountDialog.showModal();
    await refreshAccount();
  }
  settingsAccountButton.addEventListener("click", openAccountDialog);
  accountClose.addEventListener("click", () => accountDialog.close());
  accountDialog.addEventListener("close", () => clearTimeout(accountTimer));
  accountRefresh.addEventListener("click", refreshAccount);
  accountLogin.addEventListener("click", () => {
    accountDialog.close();
    window.dispatchEvent(new Event("rasathane:focus-login"));
  });
  accountTrial.addEventListener("click", async () => {
    if (accountLoading || entitlement?.deneme_baslatilabilir !== true) return;
    accountLoading = true;
    accountControls();
    accountMessage("Deneme isteği sunucuya gönderiliyor…");
    try {
      await window.rasathane.startTrial();
      accountLoading = false;
      await refreshAccount();
    } catch (error) {
      accountLoading = false;
      await refreshAccount();
      accountMessage(
        entitlement?.durum === "deneme"
          ? "Sunucudan yenilenen kayda göre hizmet denemesi etkin."
          : errorMessage(
              error,
              "Deneme başlatılamadı. Hesap sayfasından hizmet durumunu kontrol edin.",
            ),
        entitlement?.durum !== "deneme",
      );
    } finally {
      accountLoading = false;
      accountControls();
    }
  });
  accountLogout.addEventListener("click", async () => {
    accountLoading = true;
    accountControls();
    let result = null,
      problem = null;
    try {
      result = await window.rasathane.signOut();
    } catch (error) {
      problem = error;
    } finally {
      accountLoading = false;
      await refreshAccount();
      if (problem)
        accountMessage(errorMessage(problem, "Çıkış tamamlanamadı."), true);
      else if (result?.remoteRevoked === false)
        accountMessage("Yerel çıkış tamamlandı; sunucuya ulaşılamadı.", true);
    }
  });
  accountControls();

  function modelStatus() {
    if (modelStatusPending) return modelStatusPending;
    modelStatusPending = readModelStatus().finally(() => {
      modelStatusPending = null;
    });
    return modelStatusPending;
  }
  async function readModelStatus() {
    const button = $("model-kur-btn");
    if (!window.rasathane?.setupStatus) {
      message(
        $("model-kurulum-durum"),
        "Model kurulumu masaüstü uygulamasında kullanılabilir.",
      );
      button.disabled = true;
      return;
    }
    button.disabled = true;
    if (!modelTimer)
      message(
        $("model-kurulum-durum"),
        "Model dosyaları ve checksum kontrol ediliyor…",
      );
    try {
      const status = await window.rasathane.setupStatus();
      advancedProfileReady = (status.models || []).some(
        (model) =>
          model.ready &&
          (model.profile === "ram16" ||
            model.name === "gemma-4-12B-it-qat-UD-Q4_K_XL.gguf"),
      );
      for (const id of ["urun-profil", "kurulum-profil"]) {
        const option = $(id).querySelector('option[value="ram16"]');
        option.disabled = !advancedProfileReady;
        option.textContent = advancedProfileReady
          ? "16 GB ve üzeri · geniş profil"
          : "16 GB ve üzeri · ek model gerekir";
        option.title = advancedProfileReady
          ? "Yerel gelişmiş model doğrulandı"
          : "Gelişmiş model doğrulanmadı";
        $(`${id}-not`).classList.toggle("gizli", advancedProfileReady);
      }
      $("model-kurulum-liste").replaceChildren(
        ...(status.models || []).map((model) =>
          el(
            "div",
            { class: "model-record" },
            el("span", {}, model.name),
            el("span", {}, model.ready ? "Doğrulandı" : "Henüz kurulmadı"),
            el("span", {}, model.license || "Lisans kaydına bakın"),
          ),
        ),
      );
      const busy = status.state === "downloading";
      button.disabled = busy || status.ready || !$("model-kosul").checked;
      button.textContent = status.ready
        ? "Modeller hazır"
        : busy
          ? "İndiriliyor…"
          : "Yerel modelleri kur";
      const progress = $("model-kurulum-ilerleme");
      progress.classList.toggle("gizli", !busy);
      const measurable =
        typeof status.total === "number" &&
        status.total > 0 &&
        typeof status.received === "number";
      if (measurable)
        progress.value = Math.min(100, (status.received / status.total) * 100);
      else progress.removeAttribute("value");
      const size = measurable
        ? ` ${(status.received / 1024 ** 2).toFixed(0)} / ${(status.total / 1024 ** 2).toFixed(0)} MB`
        : "";
      const text = status.ready
        ? "Yerel modeller checksum ile doğrulandı."
        : busy
          ? `${status.model || "Model"} indiriliyor.${size}`
          : status.state === "failed"
            ? errorMessage(
                status.error,
                "Model kurulamadı. Bağlantıyı ve boş disk alanını kontrol edin.",
              )
            : "Lisans bildirimlerini okuyun ve model indirmesini onaylayın.";
      message($("model-kurulum-durum"), text, status.state === "failed");
      if (busy) {
        clearTimeout(modelTimer);
        modelTimer = setTimeout(modelStatus, 2000);
      }
    } catch (error) {
      message(
        $("model-kurulum-durum"),
        errorMessage(error, "Model durumu okunamadı."),
        true,
      );
      button.disabled = !$("model-kosul").checked;
    }
  }
  $("model-kosul").addEventListener("change", modelStatus);
  $("model-kur-btn").addEventListener("click", async () => {
    if (!$("model-kosul").checked) {
      message(
        $("model-kurulum-durum"),
        "Önce lisans bildirimlerini okuyun ve model indirmesini onaylayın.",
      );
      return;
    }
    if (!window.rasathane?.installModels) return;
    $("model-kur-btn").disabled = true;
    try {
      await window.rasathane.installModels();
      await modelStatus();
    } catch (error) {
      message(
        $("model-kurulum-durum"),
        errorMessage(error, "Model indirmesi başlatılamadı."),
        true,
      );
      $("model-kur-btn").disabled = false;
    }
  });
  $("ilk-kurulum-btn").addEventListener("click", () => {
    $("ilk-kurulum").showModal();
    modelStatus();
  });
  $("kurulum-kapat").addEventListener("click", () => {
    setupDismissed = true;
    $("ilk-kurulum").close();
  });
  $("ilk-kurulum").addEventListener("cancel", () => {
    setupDismissed = true;
  });
  $("kurulum-form").addEventListener("submit", (event) => {
    event.preventDefault();
    submit(event.currentTarget, $("kurulum-durum"), async () => {
      if ($("kurulum-profil").value === "ram16" && !advancedProfileReady)
        throw new Error(
          "Gelişmiş model doğrulanmadı. Bu paket için temel 8 GB profilini seçin.",
        );
      await api("/settings", {
        method: "POST",
        body: {
          analysis_profile: $("kurulum-profil").value,
          web_enabled: $("kurulum-web").checked,
        },
      });
      try {
        localStorage.setItem("rasathane-setup-v1", "complete");
      } catch {
        /* Tercih kayıt edilemese de backend ayarı kaydedildi. */
      }
      setupDismissed = true;
      $("ilk-kurulum").close();
      await load();
      onSettings?.();
    });
  });
  $("hesap-ac").addEventListener("click", openAccountDialog);
  window
    .matchMedia("(prefers-color-scheme: dark)")
    .addEventListener("change", () => {
      if (state?.settings?.theme === "system") applyTheme("system");
    });
  return {
    unlock() {
      unlocked = true;
      modelStatus();
    },
    lock() {
      unlocked = false;
      authEpoch++;
      state = null;
      lastSuccess = null;
      activeWorkspace = null;
      clearTimeout(modelTimer);
      pendingJobs.clear();
      research.reset();
      news.stopAll();
      bulletin.reset();
      dashboard.reset();
      sourcesUI.reset();
      topicResultBody.replaceChildren();
      topicResultDialog.close();
      for (const id of [
        "akis-liste",
        "kaynak-liste",
        "not-liste",
        "konu-liste",
        "calisma-alanlar",
      ])
        $(id).replaceChildren();
    },
    load,
    analyze,
    viewChanged(view) {
      if (!unlocked) return;
      if (view === "arastir") research.refreshHistory();
      currentView = view;
      if (view === "calisma") loadNotes();
      if ((view === "akis" || view === "konular" || view === "kaynaklar") && !pendingJobs.size) load();
    },
  };
}
