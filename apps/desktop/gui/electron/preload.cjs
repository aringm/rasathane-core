"use strict";
const { contextBridge, ipcRenderer } = require("electron");
contextBridge.exposeInMainWorld("rasathane", Object.freeze({
  request: (path, options) => ipcRenderer.invoke("rasathane:request", path, options),
  selectWorkspace: () => ipcRenderer.invoke("rasathane:select-workspace"),
  exportData: () => ipcRenderer.invoke("rasathane:export-data"),
  openAccount: () => ipcRenderer.invoke("rasathane:open-account"),
  sendLoginCode: email => ipcRenderer.invoke("rasathane:send-login-code", email),
  verifyLoginCode: code => ipcRenderer.invoke("rasathane:verify-login-code", code),
  cancelLogin: () => ipcRenderer.invoke("rasathane:cancel-login"),
  openLoginDocument: document => ipcRenderer.invoke("rasathane:open-login-document", document),
  setupStatus: () => ipcRenderer.invoke("rasathane:setup-status"),
  installModels: () => ipcRenderer.invoke("rasathane:install-models"),
  openSource: (url) => ipcRenderer.invoke("rasathane:open-source", url),
  onAccountChange: listener => {
    if (typeof listener !== "function") throw new TypeError("Hesap dinleyicisi geçersiz.");
    const receive = (_event, value) => listener({ state: value.state, error: value.error, scope: [...(value.scope || [])], errorCode: value.errorCode || null, login: value.login ? { email: value.login.email, expiresAt: value.login.expiresAt, resendAt: value.login.resendAt } : null });
    ipcRenderer.on("rasathane:account-change", receive);
    return () => ipcRenderer.removeListener("rasathane:account-change", receive);
  },
  accountStatus: () => ipcRenderer.invoke("rasathane:account-status"),
  entitlement: () => ipcRenderer.invoke("rasathane:entitlement"),
  startTrial: () => ipcRenderer.invoke("rasathane:start-trial"),
  signOut: () => ipcRenderer.invoke("rasathane:sign-out"),
}));
