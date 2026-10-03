export const workspaceExamples = Object.freeze([
  {
    name: "Örnek · İş hukuku araştırması",
    note: {
      title: "Örnek araştırma planı · İşçilik alacakları",
      body: "Bu örnek, çalışma alanını denemek için hazırlanmış bir araştırma planıdır. Gerçek bir dosya, karar veya hukuki değerlendirme içermez.\n\nAraştırma sorusu: İşçilik alacakları ve kıdem tazminatı konusunda yerel arşivde hangi kaynaklar var?\n\n1. Araştır ekranında bu çalışma alanını seçin.\n2. Web aramasını kapatıp ‘İşçilik alacakları araştırma planı’ sorusunu sorun; bu not yerel kaynak olarak bulunabilir.\n3. Web aramasını açarak güncel kaynakları arayın. Kaynağı açıp tarihini ve metin kapsamını kontrol edin.\n4. Bulguları ayrı notlara kaydedin. Çalışma alanını JSON olarak dışa aktarın.\n\nİlgili konu takibi: Örnek · İşçilik kararlarını takip et. Konu takibi geneldir; bu çalışma alanına otomatik bağlanmaz. Takip ilk kez ‘Şimdi kontrol et’ ile başlatılır.",
    },
    topic: {
      name: "Örnek · İşçilik kararlarını takip et",
      query: "Yargıtay işçilik alacakları kıdem tazminatı",
    },
  },
  {
    name: "Örnek · Yapay zekâ ve veri koruma",
    note: {
      title: "Örnek araştırma planı · Yapay zekâ ve veri koruma",
      body: "Bu örnek, çalışma alanını denemek için hazırlanmış bir araştırma planıdır. Gerçek kişi bilgisi, karar veya hukuki görüş içermez.\n\nAraştırma sorusu: Yapay zekâ uygulamalarında veri koruma hakkında hangi resmî kaynaklar var?\n\n1. Araştır ekranında bu çalışma alanını seçin.\n2. Web aramasını kapatıp ‘Yapay zekâ veri koruma araştırma planı’ sorusunu sorun.\n3. Web aramasını açıp Kurumun yayımladığı kaynakları arayın. Yayın tarihi, kaynağın niteliği ve erişilebilen metni kontrol edin.\n4. İncelenen kaynaklar ve açık sorular için ayrı notlar oluşturun. Kaynak bağlantılarını notunuza ekleyin.\n\nİlgili konu takibi: Örnek · Yapay zekâ duyurularını takip et. Konu takibi geneldir; bu çalışma alanına otomatik bağlanmaz. İlk kontrolü siz başlatırsınız. Uygulama açıkken sonraki kontroller Ayarlar’daki aralıkla yapılır.",
    },
    topic: {
      name: "Örnek · Yapay zekâ duyurularını takip et",
      query: "site:kvkk.gov.tr yapay zekâ",
    },
  },
]);

const pending = new WeakMap();

// Re-read persisted records on every attempt: a failed response may still have
// committed a record. Reusing a matching name never implies ownership of it.
export function ensureExamples(api) {
  if (pending.has(api)) return pending.get(api);
  const operation = installExamples(api).finally(() => pending.delete(api));
  pending.set(api, operation);
  return operation;
}

async function installExamples(api) {
  const receipt = {
    created: { workspaces: 0, notes: 0, topics: 0 },
    reused: { workspaces: 0, notes: 0, topics: 0 },
    workspaceIds: [],
  };
  const post = (path, body) =>
    api(path, { method: "POST", body });
  try {
    const workspaces = (await api("/workspaces")).items || [];
    const topics = (await api("/topics")).items || [];
    for (const example of workspaceExamples) {
      let workspace = workspaces.find((item) => item.name === example.name);
      if (workspace) receipt.reused.workspaces++;
      else {
        workspace = await post("/workspaces", { name: example.name });
        workspaces.push(workspace);
        receipt.created.workspaces++;
      }
      receipt.workspaceIds.push(workspace.id);
      const notes = (
        await api(`/notes?workspace_id=${encodeURIComponent(workspace.id)}`)
      ).items || [];
      if (notes.some((item) => item.title === example.note.title)) {
        receipt.reused.notes++;
      } else {
        await post("/notes", {
          workspace_id: workspace.id,
          ...example.note,
        });
        receipt.created.notes++;
      }
      if (
        topics.some(
          (item) =>
            item.name === example.topic.name &&
            item.query === example.topic.query,
        )
      ) {
        receipt.reused.topics++;
      } else {
        topics.push(await post("/topics", example.topic));
        receipt.created.topics++;
      }
    }
    return receipt;
  } catch (cause) {
    const error = new Error(
      "Örnek kurulumu tamamlanamadı. Bağlantı hazır olduğunda yeniden deneyin; kaydedilmiş örnekler tekrar oluşturulmaz.",
      { cause },
    );
    error.receipt = receipt;
    throw error;
  }
}

export function createWorkspaceExamples({ el, api, onCreated }) {
  const button = el(
    "button",
    { type: "button", class: "btn btn-ikincil mini" },
    "Örnek çalışma alanlarını kur",
  );
  const status = el("p", {
    class: "field-note",
    role: "status",
    "aria-live": "polite",
  });
  const node = el(
    "div",
    { class: "workspace-examples" },
    button,
    el(
      "p",
      { class: "field-note" },
      "İki örnek çalışma alanı, araştırma planı ve takip sorgusu ekler. İlk web kontrolünü siz başlatırsınız.",
    ),
    status,
  );
  let running = null;
  function install() {
    if (running) return running;
    button.disabled = true;
    status.textContent = "Örnekler hazırlanıyor…";
    running = (async () => {
      let receipt;
      try {
        receipt = await ensureExamples(api);
        const { created, reused } = receipt;
        status.textContent =
          `${created.workspaces} çalışma alanı, ${created.notes} not ve ${created.topics} konu eklendi.` +
          (Object.values(reused).some(Boolean)
            ? " Eşleşen mevcut kayıtlar korundu."
            : " Örnek notlar araştırma planıdır; gerçek haber içermez.");
        return receipt;
      } catch (error) {
        receipt = error.receipt;
        status.textContent = error.message;
        throw error;
      } finally {
        try {
          await onCreated?.(receipt);
        } finally {
          button.disabled = false;
          running = null;
        }
      }
    })();
    return running;
  }
  button.addEventListener("click", () => install().catch(() => {}));
  return { node, button, status, install };
}
