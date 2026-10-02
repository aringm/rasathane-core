type BrandMarkProps = {
  size?: number;
  className?: string;
  decorative?: boolean;
};

/** Muhakeme ailesinin bakır paletinde bağımsız lens/yörünge işareti. */
export function BrandMark({
  size = 48,
  className,
  decorative = false,
}: BrandMarkProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 96 96"
      className={className}
      role={decorative ? undefined : "img"}
      aria-label={decorative ? undefined : "Rasathane lens ve yörünge işareti"}
      aria-hidden={decorative ? true : undefined}
    >
      <rect width="96" height="96" rx="23" fill="#c86e42" />
      <path
        d="M0 24 39 0H74L96 31 71 72 29 96H23C10 96 0 86 0 73Z"
        fill="#d88855"
      />
      <path d="m39 0 25 38 32-7v42c0 13-10 23-23 23H29l35-58Z" fill="#ae572f" />
      <g
        fill="none"
        stroke="#f7f0df"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <circle cx="48" cy="48" r="22" strokeWidth="3.5" />
        <ellipse
          cx="48"
          cy="48"
          rx="35"
          ry="11"
          transform="rotate(-36 48 48)"
          strokeWidth="2.5"
        />
        <path d="m48 34 12 14-12 14-12-14Z" fill="#f7f0df" strokeWidth="1" />
        <path d="M48 19v7m0 44v7M19 48h7m44 0h7" strokeWidth="2.5" />
      </g>
      <circle
        cx="72"
        cy="30"
        r="4"
        fill="#153d34"
        stroke="#f7f0df"
        strokeWidth="2"
      />
    </svg>
  );
}
