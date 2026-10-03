// Kimlik doğrulama main sürecindedir; bu katman ekranları ve odak sırasını yönetir.
export function createLoginGate({ $, onUnlock, onLock }) {
  let unlocked = false;
  let generation = 0;
  let timer;
  let checking = false;
  let revision = 0;
  const bridge = window.rasathane;
  const panel = $("giris-ekrani");
  const status = $("giris-durum");
  const login = $("giris-baslat");
  function apply(state) {
    revision++;
    const next = state?.state === "signed_in";
    const changed = next !== unlocked;
    unlocked = next;
    document.body.classList.toggle("session-locked", !next);
    panel.hidden = next;
    for (const node of document.querySelectorAll(
      ".topbar,.app-sidebar,#app-main,.app-skip",
    )) {
      node.inert = !next;
      node.setAttribute("aria-hidden", String(!next));
    }
    login.disabled = !bridge || state?.state === "waiting";
    status.textContent =
      state?.state === "waiting"
        ? "Tarayıcıda Muhakeme girişini tamamlayın. Bu ekran otomatik açılacak."
        : state?.state === "failed" || state?.state === "expired"
          ? "Oturum doğrulanamadı. Yeniden giriş yapın."
          : bridge
            ? "Devam etmek için Muhakeme hesabınıza giriş yapın."
            : "Güvenli giriş için Rasathane masaüstü uygulamasını açın.";
    if (changed) {
      generation++;
      if (next) onUnlock();
      else {
        for (const dialog of document.querySelectorAll("dialog[open]"))
          dialog.close();
        onLock();
        login.focus();
      }
    }
  }
  async function check() {
    if (checking) return;
    clearTimeout(timer);
    checking = true;
    const started = revision;
    try {
      const state = bridge
        ? await bridge.accountStatus()
        : { state: "unavailable" };
      if (started === revision) apply(state);
    } catch {
      if (started === revision) apply({ state: "failed" });
    } finally {
      checking = false;
      timer = setTimeout(check, unlocked ? 30000 : 2000);
    }
  }
  login.addEventListener("click", async () => {
    login.disabled = true;
    try {
      await bridge.openAccount();
      await check();
    } catch {
      status.textContent =
        "Giriş başlatılamadı. İnternet bağlantınızı kontrol edip yeniden deneyin.";
      login.disabled = false;
    }
  });
  $("giris-yenile").addEventListener("click", check);
  const unsubscribe = bridge?.onAccountChange?.(apply);
  apply({ state: "unknown" });
  check();
  window.addEventListener("beforeunload", () => {
    clearTimeout(timer);
    unsubscribe?.();
  });
  return { allowed: () => unlocked, generation: () => generation, check };
}
