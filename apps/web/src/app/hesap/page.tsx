import type { Metadata } from "next";
import Link from "next/link";
import { RASATHANE_HESAP_URL } from "../../lib/rasathane-hesap";
import "../legal.css";

export const metadata: Metadata = { title: "Rasathane hesabı", description: "Rasathane hesabınızı Muhakeme üyeliğinizle yönetin." };
export default function HesapPage() {
  return (
    <main className="legal">
      <Link className="legal-back" href="/">← Ana sayfaya dön</Link>
      <span className="legal-kicker">Hesap</span>
      <h1>Tek hesapla Rasathane.</h1>
      <p>Muhakeme hesabınızla giriş yaparak Rasathane indirmelerini, 14 günlük ücretsiz denemenizi ve kullanım dönemlerinizi yönetebilirsiniz.</p>
      <p>Deneme yalnız hesabınızdaki <strong>Denemeyi başlat</strong> düğmesine bastığınızda başlar. Hesap açmak ya da bu sayfayı ziyaret etmek süreyi başlatmaz.</p>
      <h2>49 TL / ay</h2>
      <p>KDV dahil toplam bedel 49 TL’dir. Ödeme bir aylık dönemi açar; otomatik yenileme veya tahsilat yapılmaz. Rasathane diğer Muhakeme ürünlerinden ayrı bir üründür.</p>
      <p><a href={RASATHANE_HESAP_URL}>Muhakeme hesabıyla devam et →</a></p>
      <p><Link href="/indir">Kurulum ve indirme bilgileri →</Link></p>
      <p className="legal-updated">Av. Mehmet Arın Gülüm · IOT INN BİLİŞİM TİCARET A.Ş.</p>
    </main>
  );
}
