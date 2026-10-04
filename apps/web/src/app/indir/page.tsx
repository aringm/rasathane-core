import type { Metadata } from "next";
import Link from "next/link";
import { indirmeUrl, publicUrunOku } from "../../lib/rasathane-hesap";
import "../legal.css";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Rasathane indir", description: "Sürümü ve SHA-256 bilgisi doğrulanmış Rasathane kurulumları." };
export default async function IndirPage() {
  const product = await publicUrunOku();
  return (
    <main className="legal">
      <Link className="legal-back" href="/">← Ana sayfaya dön</Link>
      <span className="legal-kicker">İndir</span>
      <h1>Rasathane’yi bilgisayarınıza kurun.</h1>
      <p>En az 8 GB RAM ile bağımsız çalışması hedeflenen masaüstü uygulaması. Kurulum sihirbazı donanımınıza uygun yerel analiz seçeneğini belirler.</p>
      {!product && <p role="status">Yayın hizmetinden doğrulanmış kurulum bilgisi henüz alınamadı. Hazır olmayan bir paket için indirme bağlantısı sunulmuyor.</p>}
      {product && !product.released && <p role="status">Rasathane kurulumu kullanıcı akışı ve paket doğrulamasından sonra yayımlanacak.</p>}
      {product?.platforms.map(platform => (
        <section key={platform.platform}>
          <h2>{platform.platform === "win" ? "Windows" : "macOS"}</h2>
          {platform.available ? (
            <>
              <p>Sürüm {platform.version} · {platform.size}</p>
              <p><a href={indirmeUrl(platform.platform)}>Hesabımla güvenli indir →</a></p>
              <p>SHA-256: <code style={{ overflowWrap: "anywhere" }}>{platform.sha256}</code></p>
            </>
          ) : <p>Bu platformun doğrulanmış kurulum paketi henüz yayımlanmadı.</p>}
        </section>
      ))}
      <h2>Hesap ve deneme</h2>
      <p>Ücretsiz hesapla e-posta kodlu giriş uygulamada yapılır. 14 günlük servis denemesi Rasathane masaüstü uygulamasındaki profil kartından <strong>Hesap ve plan → 14 günlük denemeyi başlat</strong> adımıyla açılır. Yönetilen servis aylık KDV dahil 49 TL’dir; otomatik tahsilat yapılmaz.</p>
      <p><Link href="/hesap">Uygulamada giriş ve deneme adımları →</Link></p>
      <p>İndirmeyi Muhakeme hesap hizmeti açar. Üyelik bilgileri bu siteye aktarılmaz; kurulum dosyası süreli, imzalı bağlantıyla teslim edilir.</p>
      <p className="legal-updated">Av. Mehmet Arın Gülüm · IOT INN BİLİŞİM TİCARET A.Ş.</p>
    </main>
  );
}
