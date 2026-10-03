"use strict";
const { contextBridge, ipcRenderer } = require("electron");
contextBridge.exposeInMainWorld("rasathane", Object.freeze({
  request: (path, options) => ipcRenderer.invoke("rasathane:request", path, options),
  selectWorkspace: () => ipcRenderer.invoke("rasathane:select-workspace"),
  exportData: (workspaceId) => ipcRenderer.invoke("rasathane:export-data", workspaceId),
  openAccount: () => ipcRenderer.invoke("rasathane:open-account"),
  setupStatus: () => ipcRenderer.invoke("rasathane:setup-status"),
  installModels: () => ipcRenderer.invoke("rasathane:install-models"),
  openSource: (url) => ipcRenderer.invoke("rasathane:open-source", url),
  onAccountChange: listener => {
    if (typeof listener !== "function") throw new TypeError("Hesap dinleyicisi geçersiz.");
    const receive = (_event, value) => listener({ state: value.state, error: value.error, scope: [...(value.scope || [])] });
    ipcRenderer.on("rasathane:account-change", receive);
    return () => ipcRenderer.removeListener("rasathane:account-change", receive);
  },
  accountStatus: () => ipcRenderer.invoke("rasathane:account-status"),
  entitlement: () => ipcRenderer.invoke("rasathane:entitlement"),
  startTrial: () => ipcRenderer.invoke("rasathane:start-trial"),
  signOut: () => ipcRenderer.invoke("rasathane:sign-out"),
}));
