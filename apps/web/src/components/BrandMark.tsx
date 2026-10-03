import Image from "next/image";

type BrandMarkProps = {
  size?: number;
  className?: string;
  decorative?: boolean;
};

/** Canlı web sitesiyle aynı küçük r işareti; desktop ile ortak SVG. */
export function BrandMark({ size = 48, className, decorative = false }: BrandMarkProps) {
  return (
    <Image
      src="/brand/rasathane-mark.svg"
      width={size}
      height={size}
      className={className}
      alt={decorative ? "" : "Rasathane"}
      aria-hidden={decorative ? true : undefined}
      unoptimized
    />
  );
}
