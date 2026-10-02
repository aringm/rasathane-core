import type { MetadataRoute } from "next";

const BASE = "https://www.rasathane.ai";

export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date();
  const page = (
    path: string,
    priority: number,
    changeFrequency: "weekly" | "monthly" | "yearly",
  ): MetadataRoute.Sitemap[number] => ({
    url: `${BASE}${path}`,
    lastModified: now,
    changeFrequency,
    priority,
  });

  return [
    page("/", 1, "weekly"),
    page("/hesap", 0.7, "monthly"),
    page("/indir", 0.8, "weekly"),
    page("/kvkk", 0.3, "yearly"),
    page("/gizlilik", 0.3, "yearly"),
    page("/iletisim", 0.5, "monthly"),
  ];
}
