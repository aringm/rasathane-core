import type { Metadata } from "next";
import Link from "next/link";
import "../legal.css";

export const metadata: Metadata = { title: "Rasathane hesabı", description: "Rasathane uygulamasına e-posta koduyla giriş ve uygulama içinden ücretsiz deneme." };
export default function HesapPage() {
  return (
    <main className="legal">
      <Link className="legal-back" href="/">← Ana sayfaya dön</Link>
      <span className="legal-kicker">Hesap</span>
      <h1>Tek hesapla Rasathane.</h1>
      <p>Uygulamayı açmak için ücretsiz hesapla giriş ve e-posta doğrulama kodu gerekir. AGPL-3.0 yerel çekirdek ücretsizdir; ücretli servis aboneliği gerektirmez.</p>
      <p>Kurulum dosyasını indirme sayfasından ortak Muhakeme hesabınızla alın. Rasathane’yi açtıktan sonra e-postanızı yazıp gelen doğrulama koduyla uygulamaya giriş yapın.</p>
      <h2>Denemeyi uygulamadan başlatın</h2>
      <p>Rasathane masaüstü uygulamasında profil kartını açın, <strong>Hesap ve plan</strong> bölümüne girip <strong>14 günlük denemeyi başlat</strong> düğmesine basın. Deneme yalnız bu işlemle başlar; hesap açmak ya da bu sayfayı ziyaret etmek süreyi başlatmaz.</p>
      <h2>Yönetilen servis · 49 TL / ay</h2>
      <p>KDV dahil toplam bedel 49 TL’dir. Ödeme bir aylık dönemi açar; otomatik yenileme veya tahsilat yapılmaz. Rasathane diğer Muhakeme ürünlerinden ayrı bir üründür.</p>
      <p><Link href="/indir">Kurulum ve indirme bilgileri →</Link></p>
      <p className="legal-updated">Av. Mehmet Arın Gülüm · IOT INN BİLİŞİM TİCARET A.Ş.</p>
    </main>
  );
}
