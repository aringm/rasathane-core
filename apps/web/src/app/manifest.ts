import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Rasathane",
    short_name: "Rasathane",
    description:
      "Kaynakları takip edin, içerikleri analiz edin ve araştırmalarınızı cihazınızda saklayın.",
    start_url: "/",
    display: "standalone",
    background_color: "#f7f0df",
    theme_color: "#153d34",
    lang: "tr",
    icons: [{ src: "/icon.svg", sizes: "any", type: "image/svg+xml" }],
  };
}
