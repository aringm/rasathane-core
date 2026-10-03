// Kimlik doğrulama main sürecindedir; bu katman ekranları ve odak sırasını yönetir.
export function createLoginGate({ $, onUnlock, onLock }) {
  let unlocked = false;
  let generation = 0;
  let timer;
  let countdown;
  let checking = false;
  let revision = 0;
  let operation = 0;
  let disposed = false;
  let current = { state: "unknown" };
  const bridge = window.rasathane;
  const panel = $("giris-ekrani");
  const status = $("giris-durum");
  const emailForm = $("giris-email-form");
  const codeForm = $("giris-kod-form");
  const email = $("giris-email");
  const code = $("giris-kod");
  const send = $("giris-baslat");
  const verify = $("giris-dogrula");
  const resend = $("giris-tekrar");
  const cancel = $("giris-iptal");
  const available = !!bridge?.sendLoginCode && !!bridge?.verifyLoginCode;
  const errors = {
    wrong_code: "Kod yanlış veya eksik. E-postanıza gelen 6 haneli kodu yeniden girin.",
    expired_code: "Kod geçersiz veya süresi dolmuş. Yeni bir kod isteyin.",
    rate_limited: "Çok sık deneme yapıldı. Sayaç tamamlandığında yeniden deneyin.",
    unavailable: "İşlem tamamlanamadı. Bağlantınızı kontrol ederek yeniden deneyin.",
    invalid_email: "Geçerli ve kalıcı bir e-posta adresi girin.",
    secure_storage: "Windows güvenli oturum deposu kullanılamıyor.",
  };
  const secondsUntil = value => Math.max(0, Math.ceil(((Date.parse(value) || 0) - Date.now()) / 1000));
  const time = seconds => `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
  function controls() {
    const busy = ["sending_code", "verifying_code"].includes(current.state);
    const resendSeconds = secondsUntil(current.login?.resendAt);
    const expirySeconds = secondsUntil(current.login?.expiresAt);
    send.disabled = !available || busy || current.state === "unknown" || resendSeconds > 0;
    email.disabled = busy;
    code.disabled = busy;
    verify.disabled = !available || busy || !expirySeconds || (current.errorCode === "rate_limited" && resendSeconds > 0);
    resend.disabled = !available || busy || resendSeconds > 0;
    resend.textContent = resendSeconds ? `Yeni kod gönder (${time(resendSeconds)})` : "Yeni kod gönder";
    send.textContent = current.state === "sending_code" ? "Kod gönderiliyor…" : resendSeconds && codeForm.hidden ? `Kod gönder (${time(resendSeconds)})` : "Doğrulama kodu gönder";
    verify.textContent = current.state === "verifying_code" ? "Kod doğrulanıyor…" : "Giriş yap";
    cancel.hidden = !busy;
    $("giris-kod-suresi").textContent = current.login?.expiresAt ? expirySeconds ? `Kodun kalan süresi: ${time(expirySeconds)}` : "Kodun süresi doldu. Yeni kod gönderebilirsiniz." : "";
    clearTimeout(countdown);
    if (!disposed && !unlocked && (expirySeconds || resendSeconds)) countdown = setTimeout(controls, 1000);
  }
  function apply(state) {
    if (disposed) return;
    revision++;
    current = state || { state: "failed" };
    const next = current.state === "signed_in";
    const changed = next !== unlocked;
    const wasCode = !codeForm.hidden;
    const codeStep = !next && !!current.login && (!!current.login.expiresAt || (wasCode && current.state === "sending_code"));
    unlocked = next;
    document.body.classList.toggle("session-locked", !next);
    panel.hidden = next;
    emailForm.hidden = codeStep;
    codeForm.hidden = !codeStep;
    if (current.login?.email) email.value = current.login.email;
    $("giris-hedef").textContent = current.login?.email ? `${current.login.email} adresine gönderilen kodu girin.` : "";
    for (const node of document.querySelectorAll(".topbar,.app-sidebar,#app-main,.app-skip")) {
      node.inert = !next;
      node.setAttribute("aria-hidden", String(!next));
    }
    status.textContent = !available
      ? "Güvenli giriş için güncel Rasathane masaüstü uygulamasını açın."
      : errors[current.errorCode] || ({
        unknown: "Oturum kontrol ediliyor…",
        sending_code: "Doğrulama kodu e-posta adresinize gönderiliyor…",
        code_sent: "Kod gönderildi. Gelen kutunuzu ve istenmeyen posta klasörünü kontrol edin.",
        verifying_code: "Doğrulama kodu kontrol ediliyor…",
        signed_in: "Giriş tamamlandı.",
        expired: "Oturumunuzun süresi doldu. E-posta adresinizle yeniden giriş yapın.",
        failed: "Oturum doğrulanamadı. E-posta adresinizle yeniden deneyin.",
      }[current.state] || "Devam etmek için e-posta adresinizi girin.");
    if (next) { email.value = ""; code.value = ""; }
    controls();
    if (codeStep && !wasCode) code.focus();
    if (changed) {
      generation++;
      if (next) onUnlock();
      else {
        for (const dialog of document.querySelectorAll("dialog[open]")) dialog.close();
        code.value = "";
        onLock();
        email.focus();
      }
    }
  }
  async function check() {
    if (checking || disposed) return;
    clearTimeout(timer);
    checking = true;
    const started = revision;
    try {
      const state = bridge ? await bridge.accountStatus() : { state: "unavailable" };
      if (started === revision) apply(state);
    } catch {
      if (started === revision) apply({ state: "failed" });
    } finally {
      checking = false;
      if (!disposed) timer = setTimeout(check, unlocked ? 30000 : 2000);
    }
  }
  async function perform(method, value, state) {
    if (!available || disposed) return;
    const action = ++operation;
    apply(state);
    const started = revision;
    try {
      const result = await bridge[method](value);
      if (action === operation && started === revision) apply(result);
    } catch {
      if (action === operation && started === revision) apply({ ...current, state: "failed", errorCode: "unavailable" });
    }
  }
  emailForm.addEventListener("submit", event => {
    event.preventDefault();
    if (!send.disabled) return perform("sendLoginCode", email.value, { state: "sending_code" });
  });
  codeForm.addEventListener("submit", event => {
    event.preventDefault();
    if (!verify.disabled) return perform("verifyLoginCode", code.value, { ...current, state: "verifying_code", errorCode: null });
  });
  resend.addEventListener("click", () => {
    if (resend.disabled) return;
    code.value = "";
    return perform("sendLoginCode", current.login.email, { ...current, state: "sending_code", errorCode: null });
  });
  function cancelLogin() {
    code.value = "";
    const result = perform("cancelLogin", undefined, { state: "signed_out" });
    email.focus();
    return result;
  }
  cancel.addEventListener("click", cancelLogin);
  $("giris-degistir").addEventListener("click", cancelLogin);
  $("giris-yenile").addEventListener("click", check);
  for (const [id, document] of [["giris-kosullar", "terms"], ["giris-kvkk", "privacy"]]) {
    $(id).disabled = !bridge?.openLoginDocument;
    $(id).addEventListener("click", async () => {
      try { await bridge?.openLoginDocument(document); }
      catch { status.textContent = "Belge açılamadı. İnternet bağlantınızı kontrol edin."; }
    });
  }
  window.addEventListener("rasathane:focus-login", () => { check(); (codeForm.hidden ? email : code).focus(); });
  const unsubscribe = bridge?.onAccountChange?.(apply);
  apply({ state: "unknown" });
  check();
  window.addEventListener("beforeunload", () => {
    disposed = true;
    operation++;
    clearTimeout(timer);
    clearTimeout(countdown);
    code.value = "";
    email.value = "";
    unsubscribe?.();
  });
  return { allowed: () => unlocked, generation: () => generation, check };
}
