import type { Metadata } from "next";
import { Inter, Cormorant_Garamond, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";
import { Analytics } from "@vercel/analytics/next";

const inter = Inter({
  subsets: ["latin", "latin-ext"],
  weight: ["300", "400", "500", "600", "700"],
  variable: "--font-inter",
  display: "swap",
});

const cormorant = Cormorant_Garamond({
  subsets: ["latin", "latin-ext"],
  weight: ["400", "500", "600"],
  style: ["normal", "italic"],
  variable: "--font-cormorant",
  display: "swap",
});

const plexMono = IBM_Plex_Mono({
  subsets: ["latin", "latin-ext"],
  weight: ["400", "500"],
  variable: "--font-plex-mono",
  display: "swap",
});

const fontVars = `${inter.variable} ${cormorant.variable} ${plexMono.variable}`;

export const metadata: Metadata = {
  metadataBase: new URL("https://www.rasathane.ai"),
  title: { default: "Rasathane — Takip, analiz ve araştırma", template: "%s · Rasathane" },
  description: "Kaynak takibi, ayrıntılı analiz, web araştırması ve yerel çalışma alanı tek Rasathane uygulamasında. Açık yerel çekirdek ve bağımsız yönetilen hizmet.",
  applicationName: "Rasathane",
  keywords: ["Rasathane", "yerel yapay zekâ", "kaynak takibi", "içerik analizi", "web araştırması", "yerel kitaplık", "açık kaynak"],
  authors: [{ name: "Av. Mehmet Arın Gülüm" }],
  creator: "Av. Mehmet Arın Gülüm",
  publisher: "IOT INN BİLİŞİM TİCARET A.Ş.",
  alternates: { canonical: "/" },
  robots: { index: true, follow: true, googleBot: { index: true, follow: true, "max-image-preview": "large" } },
  openGraph: { title: "Rasathane — Takip, analiz ve araştırma", description: "Kaynaklardan araştırmaya, tek yerel çalışma alanı.", url: "https://www.rasathane.ai", siteName: "Rasathane", locale: "tr_TR", type: "website" },
  twitter: { card: "summary", title: "Rasathane — Takip, analiz ve araştırma", description: "Kaynaklardan araştırmaya, tek yerel çalışma alanı." },
  icons: { icon: "/brand/rasathane-mark.svg", apple: "/brand/rasathane-mark.svg" },
};

const jsonLd = {
  "@context": "https://schema.org",
  "@graph": [
    { "@type": "Organization", "@id": "https://www.rasathane.ai/#org", name: "Rasathane", legalName: "IOT INN BİLİŞİM TİCARET A.Ş.", url: "https://www.rasathane.ai", logo: "https://www.rasathane.ai/brand/rasathane-mark.svg", founder: { "@type": "Person", name: "Av. Mehmet Arın Gülüm" }, sameAs: ["https://github.com/aringm/rasathane-core", "https://www.muhakeme.ai"] },
    { "@type": "WebSite", "@id": "https://www.rasathane.ai/#website", url: "https://www.rasathane.ai", name: "Rasathane", inLanguage: "tr-TR", publisher: { "@id": "https://www.rasathane.ai/#org" } },
  ],
};
export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="tr" className={`${fontVars} antialiased`}>
      <body className="min-h-screen">
        {children}
        <Analytics />
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
        />
      </body>
    </html>
  );
}
