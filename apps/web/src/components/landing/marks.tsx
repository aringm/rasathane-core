/**
 * rasathane.ai — marka işaretleri
 * Tasarım: Codex (gpt-5.6-sol) delegasyonundan Meridyen Halkası sistemi;
 * ürün işaretleri aynı halka dilinden türetilmiştir (32 viewBox).
 */

export function BrandMark({
  className,
  size = 64,
}: {
  className?: string;
  size?: number;
}) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 64 64"
      role="img"
      aria-label="rasathane.ai işareti: meridyen halkası"
    >
      <path fill="currentColor" d="M4 28H12V36H4ZM52 28H60V36H52Z" />
      <path
        fill="currentColor"
        fillRule="evenodd"
        d="M55 32A23 23 0 1 1 9 32A23 23 0 1 1 55 32ZM45 32A13 13 0 1 1 19 32A13 13 0 1 1 45 32Z"
      />
      <path
        fill="var(--accent, #c9a227)"
        d="M23.6 37.6L37.6 23.6L40.4 26.4L26.4 40.4Z"
      />
    </svg>
  );
}

export function ProductMark({
  name,
  className,
  size = 32,
}: {
  name: "rasathane" | "horoskop" | "atolye";
  className?: string;
  size?: number;
}) {
  const common = {
    className,
    width: size,
    height: size,
    viewBox: "0 0 32 32",
    fill: "none",
    "aria-hidden": true as const,
  };

  // ortak halka: dış r11.5 / iç r6.5, merkez (16,16), yataklar
  const ring = (
    <>
      <path fill="currentColor" d="M2 14H6V18H2ZM26 14H30V18H26Z" />
      <path
        fill="currentColor"
        fillRule="evenodd"
        d="M27.5 16A11.5 11.5 0 1 1 4.5 16A11.5 11.5 0 1 1 27.5 16ZM22.5 16A6.5 6.5 0 1 1 9.5 16A6.5 6.5 0 1 1 22.5 16Z"
      />
    </>
  );

  if (name === "rasathane") {
    return (
      <svg {...common}>
        {ring}
        {/* nişangah kanadı — gözlem */}
        <path
          fill="var(--accent, #c9a227)"
          d="M11.8 18.8L18.8 11.8L20.2 13.2L13.2 20.2Z"
        />
      </svg>
    );
  }

  if (name === "horoskop") {
    return (
      <svg {...common}>
        {ring}
        {/* üç kollu seçici — orkestrasyon */}
        <g fill="var(--accent, #c9a227)">
          <circle cx="16" cy="16" r="2" />
          <rect x="15" y="7.5" width="2" height="6" />
          <rect x="15" y="7.5" width="2" height="6" transform="rotate(120 16 16)" />
          <rect x="15" y="7.5" width="2" height="6" transform="rotate(240 16 16)" />
        </g>
      </svg>
    );
  }

  return (
    <svg {...common}>
      {ring}
      {/* modüler L blok — atölye */}
      <path
        fill="var(--accent, #c9a227)"
        d="M12 12H20V16H16V20H12Z"
      />
    </svg>
  );
}
