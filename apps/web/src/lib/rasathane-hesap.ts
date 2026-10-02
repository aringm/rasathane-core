/** Public ürün sözleşmesi. Hesap ve indirme tek güvenilir Muhakeme alanında açılır. */
export const HESAP_TABANI = "https://www.muhakeme.ai";
export const RASATHANE_HESAP_URL = `${HESAP_TABANI}/hesap?urun=rasathane`;
export const RASATHANE_URUN_URL = `${HESAP_TABANI}/api/rasathane/urun`;
export type Platform = "win" | "mac";
export interface PlatformYayini {
  platform: Platform;
  available: boolean;
  version: string | null;
  sha256: string | null;
  size: string | null;
}
export interface RasathaneUrun {
  schema_version: "1.0";
  product: "rasathane";
  released: boolean;
  currency: "TRY";
  monthly_total_kurus: 4900;
  tax_included: true;
  recurring: false;
  trial_days: 14;
  platforms: PlatformYayini[];
}

export function urunSozlesmesi(ham: unknown): RasathaneUrun | null {
  if (!ham || typeof ham !== "object") return null;
  const v = ham as Record<string, unknown>;
  if (v.schema_version !== "1.0" || v.product !== "rasathane" || typeof v.released !== "boolean" || v.currency !== "TRY" || v.monthly_total_kurus !== 4900 || v.tax_included !== true || v.recurring !== false || v.trial_days !== 14 || !Array.isArray(v.platforms) || v.platforms.length !== 2) return null;
  const platforms: PlatformYayini[] = [];
  for (const hamPlatform of v.platforms) {
    if (!hamPlatform || typeof hamPlatform !== "object") return null;
    const p = hamPlatform as Record<string, unknown>;
    if ((p.platform !== "win" && p.platform !== "mac") || typeof p.available !== "boolean" || platforms.some(x => x.platform === p.platform)) return null;
    if (p.available) {
      if (!v.released || typeof p.version !== "string" || !/^\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?$/.test(p.version) || typeof p.sha256 !== "string" || !/^[a-f0-9]{64}$/.test(p.sha256) || typeof p.size !== "string" || p.size.length > 120) return null;
    } else if (p.version !== null || p.sha256 !== null || p.size !== null) return null;
    platforms.push({ platform: p.platform, available: p.available, version: p.version as string | null, sha256: p.sha256 as string | null, size: p.size as string | null });
  }
  return { schema_version: "1.0", product: "rasathane", released: v.released, currency: "TRY", monthly_total_kurus: 4900, tax_included: true, recurring: false, trial_days: 14, platforms };
}

export function indirmeUrl(platform: Platform): string {
  // Yanıttan URL alınmaz; product ve platform sabit allowlist'ten üretilir.
  if (platform !== "win" && platform !== "mac") throw new Error("Geçersiz platform.");
  return `${HESAP_TABANI}/api/download?urun=rasathane&platform=${platform}`;
}

export async function publicUrunOku(fetcher: typeof fetch = fetch): Promise<RasathaneUrun | null> {
  try {
    const response = await fetcher(RASATHANE_URUN_URL, { cache: "no-store", redirect: "error", signal: AbortSignal.timeout(6000) });
    if (!response.ok) return null;
    return urunSozlesmesi(await response.json());
  } catch { return null; }
}
