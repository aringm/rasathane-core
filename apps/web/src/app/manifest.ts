import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Rasathane — Takip, analiz ve araştırma",
    short_name: "Rasathane",
    description:
      "Kaynak takibi, Türkçe bülten, yerel içerik analizi ve araştırma sohbeti.",
    start_url: "/",
    display: "standalone",
    background_color: "#F7F0DF",
    theme_color: "#153D34",
    lang: "tr",
    icons: [
      { src: "/brand/rasathane-icon.svg", sizes: "any", type: "image/svg+xml" },
    ],
  };
}
export const dynamic = "force-static";
