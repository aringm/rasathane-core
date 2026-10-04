import type { Metadata } from "next";
import Link from "next/link";
import "../legal.css";

export const metadata: Metadata = {
  alternates: { canonical: "/gizlilik" },
  title: "Gizlilik Politikası",
  description:
    "rasathane.ai web sitesinde hangi verilerin işlendiği, çerez kullanımı ve üçüncü taraf hizmet sağlayıcılara ilişkin gizlilik politikası.",
};

export default function GizlilikPage() {
  return (
    <main className="legal">
      <Link href="/" className="legal-back">
        ← Ana sayfaya dön
      </Link>

      <span className="legal-kicker">Gizlilik</span>
      <h1>Gizlilik Politikası ve Çerez Bildirimi</h1>

      <p>
        Bu politika, rasathane.ai web sitesini ziyaret ettiğinizde verilerinizin
        nasıl işlendiğini ve çerez kullanımını açıklar. rasathane.ai; Rasathane,
        Horoskop ve Atölye ürünlerinin tanıtıldığı bir web sitesidir — üyelik,
        form veya benzeri bir veri giriş noktası içermez. Kişisel verilerinizin
        işlenmesine ilişkin ayrıntılı bilgi için{" "}
        <Link href="/kvkk">KVKK Aydınlatma Metni</Link> sayfasını
        inceleyebilirsiniz.
      </p>

      <h2>1. Hangi Verileri İşliyoruz</h2>
      <ul>
        <li>
          <strong>Site ziyareti:</strong> sizi bireysel olarak tanımlayan bir
          kayıt tutmayız. Kullanım ölçümü, Vercel Analytics&apos;in çerezsiz
          altyapısıyla anonim ve toplu (aggregate) istatistikler düzeyinde
          yapılır.
        </li>
        <li>
          <strong>E-posta iletişimi:</strong> bize e-posta gönderirseniz,
          e-posta adresiniz ve mesajınızın içeriği yalnızca talebinizi
          yanıtlamak için işlenir.
        </li>
      </ul>

      <h2>2. Çerezler</h2>
      <p>
        Bu site <strong>çerez kullanmaz</strong>. Oturum, tercih, pazarlama
        veya üçüncü taraf takip (tracking) çerezi yerleştirilmez. Kullanım
        ölçümü için yararlandığımız Vercel Analytics, çerez yerleştirmeden ve
        ziyaretçiler arasında kalıcı tanımlayıcı oluşturmadan çalışır.
      </p>

      <h2>3. Üçüncü Taraf Hizmet Sağlayıcılar</h2>
      <p>
        Siteyi sunabilmek için tek bir hizmet sağlayıcıdan yararlanırız; bu
        sağlayıcı yurt dışında yerleşiktir:
      </p>
      <ul>
        <li>
          <strong>Vercel</strong> — web sitesinin barındırılması (hosting) ve
          çerezsiz kullanım ölçümü (Vercel Analytics).
        </li>
      </ul>

      <h2>4. İndirilebilir Ürünler</h2>
      <p>
        Bu sitede tanıtılan Rasathane, Horoskop ve Atölye yerel-öncelikli
        çalışır: analiz ve işleme, varsayılan olarak kendi cihazınızda yapılır.
        Ürünlerin veri uygulamaları kendi belgelerinde (depo README ve lisans
        dosyaları) açıklanır; bu politika yalnızca bu web sitesini kapsar.
      </p>

      <h2>5. Veri Güvenliği</h2>
      <p>
        Site trafiği şifreli bağlantılar (HTTPS) üzerinden iletilir. E-posta
        yazışmaları yalnızca yetkili kişilerin erişebileceği şekilde saklanır.
        Buna karşın internet üzerinden yapılan hiçbir iletimin yüzde yüz
        güvenli olduğunu garanti etmenin mümkün olmadığını hatırlatırız.
      </p>

      <h2>6. Haklarınız ve İletişim</h2>
      <p>
        KVKK md. 11 kapsamındaki haklarınız (bilgi talep etme, düzeltme,
        silme, işlemeye itiraz etme ve diğerleri) saklıdır; ayrıntısı için{" "}
        <Link href="/kvkk">KVKK Aydınlatma Metni</Link> sayfasına
        bakabilirsiniz. Gizlilik uygulamalarımıza ilişkin sorularınızı{" "}
        <a href="mailto:bilgi@iotinnbilisim.com">bilgi@iotinnbilisim.com</a>{" "}
        veya{" "}
        <a href="mailto:nemezis@tutamail.com">nemezis@tutamail.com</a>{" "}
        adresine iletebilirsiniz.
      </p>

      <p className="legal-updated">Son güncelleme: 11 Temmuz 2026</p>
    </main>
  );
}
