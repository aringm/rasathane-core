/**
 * rasathane.ai — logo adayları (Logo Laboratuvarı)
 * Tasarım: Codex (gpt-5.6-sol) delegasyonu, docs/redesign/prompts/
 * codex-logo-brief.md brief'i ile; geometri koordinatları birebir.
 * Ortak dil: currentColor gövde + var(--accent) altın vurgu.
 */

/** A — Meridyen Halkası: kalibre çember, yataklar, nişangah kanadı. Varsayılan. */
export function LogoMeridyen({
  size = 64,
  className,
}: {
  size?: number;
  className?: string;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      className={className}
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

/** B — Deklinasyon Kadranı: gök kataloğu plotlayıcısı, altın katalog hücresi. */
export function LogoKadran({
  size = 64,
  className,
}: {
  size?: number;
  className?: string;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      className={className}
      role="img"
      aria-label="rasathane.ai işareti: deklinasyon kadranı"
    >
      <path fill="currentColor" d="M7.5 8H12.5V51.5H56V56.5H7.5Z" />
      <path
        fill="none"
        stroke="currentColor"
        strokeWidth="5"
        strokeLinecap="butt"
        d="M10 40A14 14 0 0 1 24 54M10 28A26 26 0 0 1 36 54M10 16A38 38 0 0 1 48 54"
      />
      <path
        fill="var(--accent, #c9a227)"
        d="M36.9 23.1L40.9 27.1L36.9 31.1L32.9 27.1Z"
      />
    </svg>
  );
}

/** C — Geometrik R: modernist monogram, altın kalibrasyon ucu. */
export function LogoMonogram({
  size = 64,
  className,
}: {
  size?: number;
  className?: string;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      className={className}
      role="img"
      aria-label="rasathane.ai işareti: geometrik R"
    >
      <path
        fill="currentColor"
        fillRule="evenodd"
        d="M9 8H32A16 16 0 0 1 32 40H18V56H9ZM18 16H31A8 8 0 0 1 31 32H18Z"
      />
      <path fill="currentColor" d="M28.2 39.8L33.8 34.2L49.8 50.2L44.2 55.8Z" />
      <path
        fill="var(--accent, #c9a227)"
        d="M49.8 50.2L53.8 54.2L48.2 59.8L44.2 55.8Z"
      />
    </svg>
  );
}
