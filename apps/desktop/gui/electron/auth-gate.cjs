"use strict";

// Her işlem main'deki oturuma bağlıdır. Renderer'dan gelen durum veya bayraklar
// yetki oluşturmaz; çıkıştan sonra eski işlemin sonucu yeni oturuma aktarılamaz.
function createAuthGate(account) {
  const pending = new Set();
  const unsubscribe = account.subscribe(state => {
    for (const operation of pending) {
      if (state.state !== "signed_in" || !account.isCurrent(operation.generation)) operation.controller.abort();
    }
  });
  async function run(work) {
    const generation = await account.requireSession();
    const operation = { generation, controller: new AbortController() };
    const assertCurrent = () => {
      if (operation.controller.signal.aborted || !account.isCurrent(generation)) throw new Error("Muhakeme hesabına giriş gerekli.");
    };
    pending.add(operation);
    try {
      assertCurrent();
      const result = await work({ signal: operation.controller.signal, assertCurrent });
      assertCurrent();
      return result;
    } finally { pending.delete(operation); }
  }
  return { run, close: () => { unsubscribe(); for (const operation of pending) operation.controller.abort(); pending.clear(); } };
}

module.exports = { createAuthGate };
