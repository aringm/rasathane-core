// Keeps a settings draft stable while unrelated feed/state requests complete.
const fields = ["theme", "analysis_profile", "search_provider", "web_enabled"];
const pick = (value) => Object.fromEntries(fields.map((key) => [key, value[key]]));
const equal = (left, right) => !!left && !!right && fields.every((key) => left[key] === right[key]);

export function createSettingsDraft({ read, write, onState = () => {} }) {
  let persisted = null;
  let baseline = null;
  const hasChanges = () => !!baseline && !equal(read(), baseline);
  const changed = () => onState({ dirty: hasChanges(), ready: persisted !== null });
  return {
    read: () => pick(read()),
    hasChanges,
    changed,
    receive(settings) {
      const dirty = hasChanges();
      persisted = pick(settings);
      if (!dirty) {
        baseline = pick(settings);
        write(persisted);
      }
      changed();
    },
    saved(settings, submitted) {
      if (!settings || !equal(settings, submitted)) {
        throw new Error("Kaydedilen ayarlar doğrulanamadı. Değişiklikleriniz ekranda korunuyor; yeniden deneyin.");
      }
      const current = pick(read());
      persisted = pick(settings);
      baseline = pick(settings);
      // An edit made after clicking Save belongs to the next save operation.
      if (equal(current, submitted)) write(persisted);
      changed();
    },
    reset() {
      if (!persisted) return;
      baseline = pick(persisted);
      write(persisted);
      changed();
    },
  };
}
