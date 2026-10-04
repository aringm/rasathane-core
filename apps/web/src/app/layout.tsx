import type { Metadata } from "next";
import localFont from "next/font/local";
import SiteShell from "../components/SiteShell";
import { Analytics } from "@vercel/analytics/next";
import "./globals.css";
import "./brand-family.css";

const inter = localFont({
  src: "../../public/fonts/inter.woff2",
  variable: "--font-inter",
  display: "swap",
  weight: "100 900",
});
const cormorant = localFont({
  src: "../../public/fonts/cormorant.woff2",
  variable: "--font-cormorant",
  display: "swap",
  weight: "300 700",
});
const siteUrl = "https://www.rasathane.ai";
const description =
  "Kaynak takibi, Türkçe bülten, yerel içerik analizi ve kaynaklı araştırma sohbeti. Rasathane, IoT Inn'in bilgi araştırmasına odaklanan ürünüdür.";

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: {
    default: "Rasathane — Takip, analiz ve araştırma",
    template: "%s · Rasathane",
  },
  description,
  applicationName: "Rasathane",
  authors: [{ name: "Av. Mehmet Arın Gülüm" }],
  creator: "Av. Mehmet Arın Gülüm",
  publisher: "IOT INN BİLİŞİM TİCARET A.Ş.",
  robots: {
    index: true,
    follow: true,
    googleBot: { index: true, follow: true, "max-image-preview": "large" },
  },
  openGraph: {
    title: "Rasathane — Takip, analiz ve araştırma",
    description,
    siteName: "Rasathane",
    locale: "tr_TR",
    type: "website",
    images: [
      {
        url: "/media/rasathane-optical.webp",
        width: 1536,
        height: 1024,
        alt: "Dağınık çizgileri tek odakta buluşturan optik mercek",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "Rasathane — Takip, analiz ve araştırma",
    description,
    images: ["/media/rasathane-optical.webp"],
  },
};

const jsonLd = {
  "@context": "https://schema.org",
  "@type": "WebSite",
  name: "Rasathane",
  url: siteUrl,
  inLanguage: "tr-TR",
  publisher: {
    "@type": "Organization",
    name: "IoT Inn",
    legalName: "IOT INN BİLİŞİM TİCARET A.Ş.",
    founder: { "@type": "Person", name: "Av. Mehmet Arın Gülüm" },
    sameAs: [
      "https://www.iotinnbilisim.com",
      "https://www.muhakeme.ai",
      "https://www.rasathane.ai",
    ],
  },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="tr" className={inter.variable + " " + cormorant.variable}>
      <body>
        <SiteShell>{children}</SiteShell>
        <Analytics />
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
        />
      </body>
    </html>
  );
}
