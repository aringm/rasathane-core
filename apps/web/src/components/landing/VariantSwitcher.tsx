"use client";

/**
 * Tasarım iterasyonu seçici — redesign süreci için geçici önizleme aracı.
 * Seçim data-v niteliği + localStorage + URL (?v=) üzerinden taşınır;
 * aktif düğme görünümleri CSS'in [data-v] alt-seçicileriyle belirlenir
 * (React state'i gerektirmez — sayfa boyamadan önce inline script uygular).
 */

const VARIANTS = [
  { v: "1", name: "Yıldız Haritası" },
  { v: "2", name: "Defter" },
  { v: "3", name: "Enstrüman" },
] as const;

export default function VariantSwitcher() {
  function choose(v: string) {
    document.querySelector(".landing")?.setAttribute("data-v", v);
    try {
      window.localStorage.setItem("rasathane-v", v);
    } catch {
      /* özel mod: sessizce geç */
    }
    const url = new URL(window.location.href);
    url.searchParams.set("v", v);
    window.history.replaceState(null, "", url);
  }

  return (
    <div
      className="variant-switcher"
      role="group"
      aria-label="Tasarım iterasyonunu seç"
    >
      <span className="vs-title">iterasyon</span>
      {VARIANTS.map(({ v, name }) => (
        <button
          key={v}
          type="button"
          data-vv={v}
          title={`İterasyon ${v}: ${name}`}
          onClick={() => choose(v)}
        >
          <span className="vs-no" aria-hidden="true">
            {v}
          </span>
          <span className="vs-name">{name}</span>
        </button>
      ))}
    </div>
  );
}
