/** Profile and settings presentation; account credentials stay in Electron main. */
export function createProfileSettings({ $, onSettings }) {
  const trigger = $("profil-ac");
  const menu = $("profil-menu");
  const dialog = $("gorunum-ayarlar");
  const menuItems = [...menu.querySelectorAll('[role="menuitem"]')];
  function closeMenu(restore = false) {
    menu.hidden = true;
    trigger.setAttribute("aria-expanded", "false");
    if (restore) trigger.focus();
  }
  function openMenu() {
    menu.hidden = false;
    trigger.setAttribute("aria-expanded", "true");
    menuItems[0].focus();
  }
  trigger.addEventListener("click", () => menu.hidden ? openMenu() : closeMenu());
  trigger.addEventListener("keydown", (event) => {
    if (event.key === "ArrowUp" || event.key === "ArrowDown") {
      event.preventDefault();
      openMenu();
    }
  });
  menu.addEventListener("keydown", (event) => {
    const index = menuItems.indexOf(document.activeElement);
    let next;
    if (event.key === "ArrowDown") next = (index + 1) % menuItems.length;
    if (event.key === "ArrowUp") next = (index - 1 + menuItems.length) % menuItems.length;
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = menuItems.length - 1;
    if (next !== undefined) {
      event.preventDefault();
      menuItems[next].focus();
    }
    if (event.key === "Escape") {
      event.preventDefault();
      closeMenu(true);
    }
  });
  document.addEventListener("focusin", (event) => {
    // Close after the new focus is known. A temporary blur during a mouse press
    // must not remove the destination menu item before its click is delivered.
    if (event.target === document.body || event.target === document.documentElement) return;
    if (!menu.contains(event.target) && event.target !== trigger) closeMenu();
  });
  document.addEventListener("pointerdown", (event) => {
    if (!menu.contains(event.target) && !trigger.contains(event.target)) closeMenu();
  });
  $("hesap-ac").addEventListener("click", () => closeMenu());
  $("profil-ayarlar").addEventListener("click", () => {
    closeMenu();
    onSettings();
  });
  $("header-ayarlar").addEventListener("click", () => { closeMenu(); onSettings(); });
  $("profil-cikis").addEventListener("click", () => {
    closeMenu();
    $("hesap-cikis").click();
  });
  window.addEventListener("rasathane:profile-update", (event) => {
    const detail = event.detail || {};
    const name = typeof detail.name === "string" && detail.name.trim()
      ? detail.name.trim().slice(0, 120) : "Muhakeme hesabı";
    const plan = typeof detail.plan === "string" && detail.plan.trim()
      ? detail.plan.trim().slice(0, 100) : "Hesap ve ayarlar";
    $("profil-ad").textContent = $("profil-menu-ad").textContent = name;
    $("profil-plan").textContent = $("profil-menu-plan").textContent = plan;
    $("profil-avatar").textContent = name[0].toLocaleUpperCase("tr-TR");
    trigger.title = name;
  });

  const heading = dialog.querySelector(".settings-heading");
  const form = $("urun-ayar-form");
  const diagnostics = document.createElement("div");
  diagnostics.className = "settings-diagnostics";
  const diagnosticsStatus = document.createElement("span");
  diagnosticsStatus.id = "ayarlar-baglanti-durum";
  diagnosticsStatus.setAttribute("role", "status");
  diagnosticsStatus.setAttribute("aria-live", "polite");
  const reload = document.createElement("button");
  reload.type = "button";
  reload.className = "btn btn-ikincil mini";
  reload.id = "ayarlar-yenile";
  reload.textContent = "Durumu yenile";
  reload.addEventListener("click", () => window.dispatchEvent(new Event("rasathane:settings-reload")));
  diagnostics.append(diagnosticsStatus, reload);
  const sections = [...dialog.querySelectorAll(":scope > section")];
  const content = document.createElement("div");
  content.className = "settings-content";
  const nav = document.createElement("nav");
  nav.className = "settings-nav";
  nav.setAttribute("role", "tablist");
  nav.setAttribute("aria-orientation", "vertical");
  nav.setAttribute("aria-label", "Ayar bölümleri");
  const layout = document.createElement("div");
  layout.className = "settings-layout";
  layout.append(nav, content);
  heading.after(layout);
  const pages = new Map();
  function page(id, title) {
    const button = document.createElement("button");
    button.type = "button";
    button.id = `ayar-sekme-${id}`;
    button.textContent = title;
    button.setAttribute("role", "tab");
    button.setAttribute("aria-controls", `ayar-panel-${id}`);
    const panel = document.createElement("section");
    panel.id = `ayar-panel-${id}`;
    panel.className = "settings-panel";
    panel.setAttribute("role", "tabpanel");
    panel.setAttribute("aria-labelledby", button.id);
    panel.tabIndex = 0;
    const titleNode = document.createElement("h3");
    titleNode.textContent = title;
    panel.append(titleNode);
    nav.append(button);
    content.append(panel);
    pages.set(id, { button, panel });
    button.addEventListener("click", () => select(id));
    return panel;
  }
  function select(id) {
    for (const [key, { button, panel }] of pages) {
      const active = key === id;
      button.setAttribute("aria-selected", String(active));
      button.tabIndex = active ? 0 : -1;
      panel.hidden = !active;
    }
    content.scrollTop = 0;
  }
  const appearance = page("gorunum", "Görünüm");
  const network = page("arama", "Web ve konu takibi");
  const models = page("modeller", "Yerel modeller");
  const files = page("dosyalar", "Dosyalar ve veri");
  const account = page("hesap", "Hesap ve plan");
  function moveField(id, target) {
    const field = $(id);
    field.setAttribute("form", form.id);
    target.append(field.closest(".alan"));
  }
  moveField("urun-tema", appearance);
  moveField("urun-profil", models);
  moveField("urun-arama-saglayici", network);
  moveField("urun-takip-sikligi", network);
  const web = $("urun-web");
  web.setAttribute("form", form.id);
  const webLabel = web.closest("label");
  const webNote = webLabel.nextElementSibling;
  network.append(webLabel, webNote);
  for (const section of sections) {
    if (section.id === "ayarlar-hesap-icerik") account.append(section);
    else if (section.querySelector("#ayar-ollama-host")) {
      const advanced = document.createElement("details");
      advanced.className = "settings-advanced";
      const summary = document.createElement("summary");
      summary.textContent = "Gelişmiş: Ollama bağlantısını test et";
      section.querySelector("h3").textContent = "İsteğe bağlı bağlantı testi";
      section.querySelector(".field-note").textContent = "Bu alan yalnız bu bilgisayardaki Ollama servisine erişimi test eder. Girilen adres kaydedilmez ve Rasathane'nin analiz motorunu değiştirmez. Birleşik analiz, yukarıdaki donanım profilinin yerel motorunu kullanır.";
      section.querySelector('label[for="ayar-ollama-host"]').textContent = "Test edilecek yerel servis adresi";
      $("ayar-test-btn").textContent = "Bağlantıyı test et";
      advanced.append(summary, section);
      models.append(advanced);
    }
    else if (section.querySelector("#ayar-motorlar")) models.append(section);
    else files.append(section);
  }
  models.prepend($("ilk-kurulum-btn"));
  form.querySelector(".settings-grid").remove();
  form.className = "settings-save";
  const discard = document.createElement("button");
  discard.type = "button";
  discard.className = "btn btn-ikincil";
  discard.id = "ayarlar-vazgec";
  discard.textContent = "Değişiklikleri geri al";
  discard.disabled = true;
  discard.addEventListener("click", () => {
    window.dispatchEvent(new Event("rasathane:settings-discard"));
    $("urun-ayar-sonuc").textContent = "Kayıtlı ayarlar geri yüklendi.";
  });
  const save = form.querySelector('button[type="submit"]');
  save.id = "ayarlar-kaydet";
  save.disabled = true;
  save.after(discard);
  const draftStatus = document.createElement("span");
  draftStatus.id = "ayarlar-taslak-durum";
  draftStatus.className = "field-note";
  draftStatus.setAttribute("role", "status");
  form.prepend(draftStatus);
  window.addEventListener("rasathane:settings-state", ({ detail }) => {
    discard.disabled = !detail?.dirty;
    save.disabled = !detail?.ready || form.dataset.submitting === "true";
    draftStatus.textContent = detail?.dirty ? "Kaydedilmemiş değişiklikler var." : "";
  });
  for (const eventName of ["input", "change"]) {
    dialog.addEventListener(eventName, (event) => {
      if (event.target.form !== form) return;
      $("urun-ayar-sonuc").textContent = "";
      window.dispatchEvent(new Event("rasathane:settings-edited"));
    });
  }
  dialog.append(diagnostics, form);
  select("gorunum");
  nav.addEventListener("keydown", (event) => {
    const entries = [...pages.entries()];
    const index = entries.findIndex(([, item]) => item.button === document.activeElement);
    let next;
    if (event.key === "ArrowDown") next = (index + 1) % entries.length;
    if (event.key === "ArrowUp") next = (index - 1 + entries.length) % entries.length;
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = entries.length - 1;
    if (next === undefined) return;
    event.preventDefault();
    select(entries[next][0]);
    entries[next][1].button.focus();
  });
  // Invalid controls may live on another category: reveal before native focus.
  form.addEventListener("invalid", (event) => {
    for (const [id, { panel }] of pages) if (panel.contains(event.target)) select(id);
  }, true);
  // External form controls do not bubble through their owner form.
  dialog.addEventListener("invalid", (event) => {
    for (const [id, { panel }] of pages) if (panel.contains(event.target)) select(id);
  }, true);
  $("ayarlar-kapat").addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (event) => {
    if (event.target !== dialog) return;
    const rect = dialog.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
  });
  dialog.addEventListener("close", () => trigger.focus());
  return { closeMenu };
}
