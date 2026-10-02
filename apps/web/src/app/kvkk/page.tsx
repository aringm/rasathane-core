import type { Metadata } from "next";
import Link from "next/link";
import "../legal.css";

export const metadata: Metadata = {
  title: "KVKK Aydınlatma Metni",
  description:
    "rasathane.ai web sitesi kapsamında kişisel verilerinizin nasıl işlendiğine ilişkin KVKK aydınlatma metni.",
};

export default function KvkkPage() {
  return (
    <main className="legal">
      <Link href="/" className="legal-back">
        ← Ana sayfaya dön
      </Link>

      <span className="legal-kicker">Kişisel Verilerin Korunması</span>
      <h1>KVKK Aydınlatma Metni</h1>

      <p>
        Bu metin, 6698 sayılı Kişisel Verilerin Korunması Kanunu (KVKK) md. 10
        kapsamında, rasathane.ai web sitesi ziyaretçilerini kişisel verilerinin
        işlenmesi konusunda bilgilendirmek amacıyla hazırlanmıştır.
        rasathane.ai; Rasathane, Horoskop ve Atölye ürünlerinin tanıtıldığı
        bir web sitesidir. Sitede üyelik, form, yorum alanı veya benzeri bir
        veri giriş noktası bulunmaz; ziyaret için hesap oluşturulmaz.
      </p>

      <h2>1. Veri Sorumlusunun Kimliği</h2>
      <p>
        Kişisel verileriniz, veri sorumlusu sıfatıyla aşağıdaki kurum
        tarafından işlenmektedir:
      </p>
      <address>
        <strong>IOT INN BİLİŞİM TİCARET A.Ş.</strong>
        <br />
        Yıldızevler Mah. Turan Güneş Bul. No:32/12 Çankaya/Ankara
        <br />
        Yetkili / kurucu: Av. Mehmet Arın Gülüm
        <br />
        E-posta:{" "}
        <a href="mailto:bilgi@iotinnbilisim.com">bilgi@iotinnbilisim.com</a>
        {" · "}
        <a href="mailto:nemezis@tutamail.com">nemezis@tutamail.com</a>
        <br />
        Web: <a href="https://www.rasathane.ai">https://www.rasathane.ai</a>
      </address>

      <h2>2. İşlenen Kişisel Veriler</h2>
      <p>Bu sitenin veri işleme kapsamı bilinçli olarak dar tutulmuştur:</p>
      <ul>
        <li>
          <strong>Site ziyareti sırasında:</strong> sizi bireysel olarak
          tanımlayan bir kayıt tutulmaz. Kullanım ölçümü, Vercel
          Analytics&apos;in <strong>çerezsiz</strong> altyapısıyla anonim ve
          toplu (aggregate) istatistikler düzeyinde yapılır; ziyaretçiler
          arasında kalıcı bir tanımlayıcı ile eşleştirme yapılmaz.
        </li>
        <li>
          <strong>Bize e-posta ile ulaşmanız halinde:</strong> e-posta
          adresiniz, adınız (paylaşmanız halinde) ve mesajınızın içeriği.
        </li>
      </ul>

      <h2>3. Kişisel Verilerin İşlenme Amaçları</h2>
      <ul>
        <li>İletişim taleplerinizin alınması ve yanıtlanması.</li>
        <li>
          Ticari lisans başvuruları başta olmak üzere, ürünlere ilişkin
          taleplerin değerlendirilmesi.
        </li>
        <li>
          Sitenin kullanımının anonim istatistiklerle izlenmesi ve
          iyileştirilmesi.
        </li>
      </ul>

      <h2>4. İşlemenin Hukuki Sebepleri</h2>
      <p>
        Kişisel verileriniz, KVKK md. 5 kapsamında aşağıdaki hukuki sebeplere
        dayanılarak işlenir:
      </p>
      <ul>
        <li>
          <strong>Sözleşmenin kurulması veya ifası:</strong> talebiniz üzerine
          sözleşme öncesi iletişimin yürütülmesi (md. 5/2-c).
        </li>
        <li>
          <strong>Veri sorumlusunun meşru menfaati:</strong> sitenin
          işletilmesi, güvenliğinin sağlanması ve anonim kullanım ölçümü
          (md. 5/2-f).
        </li>
      </ul>

      <h2>5. Kişisel Verilerin Aktarılması (Yurt İçi / Yurt Dışı)</h2>
      <p>
        Sitenin teknik altyapısı, yurt dışında yerleşik{" "}
        <strong>Vercel</strong> üzerinde barındırılmaktadır (hosting ve
        çerezsiz analitik). Bu nedenle site trafiğine ilişkin teknik veriler
        yurt dışında işlenebilir. Aktarım, KVKK&apos;nın yurt dışına aktarıma
        ilişkin md. 9 hükümleri çerçevesinde; yalnızca bu metinde belirtilen
        amaçlarla, gerekli güvenlik tedbirleri alınarak ve hizmetin sunulması
        için zorunlu olan ölçüde gerçekleştirilir.
      </p>
      <p>
        Bu sitede tanıtılan ürünleri indirip kullanmanız halinde oluşabilecek
        veri akışları bu aydınlatma metninin kapsamı dışındadır; ürünler
        yerel-öncelikli çalışır ve veri uygulamaları kendi belgelerinde
        açıklanır.
      </p>

      <h2>6. Saklama Süresi</h2>
      <p>
        E-posta yazışmaları, iletişimin gerektirdiği süre boyunca ve ilgili
        mevzuatın öngördüğü saklama yükümlülükleri çerçevesinde tutulur.
        Saklama amacının ortadan kalkması halinde verileriniz silinir, yok
        edilir veya anonim hale getirilir. Anonim kullanım istatistikleri
        kişisel veri niteliği taşımaz.
      </p>

      <h2>7. İlgili Kişinin Hakları</h2>
      <p>
        KVKK md. 11 uyarınca, veri sorumlusuna başvurarak aşağıdaki
        haklarınızı kullanabilirsiniz:
      </p>
      <ul>
        <li>Kişisel verinizin işlenip işlenmediğini öğrenme.</li>
        <li>İşlenmişse buna ilişkin bilgi talep etme.</li>
        <li>
          İşlenme amacını ve verilerin amacına uygun kullanılıp
          kullanılmadığını öğrenme.
        </li>
        <li>
          Yurt içinde veya yurt dışında verilerin aktarıldığı üçüncü kişileri
          bilme.
        </li>
        <li>Eksik veya yanlış işlenmiş verilerin düzeltilmesini isteme.</li>
        <li>
          Mevzuattaki şartlar çerçevesinde verilerin silinmesini veya yok
          edilmesini isteme.
        </li>
        <li>
          Düzeltme, silme ve yok etme işlemlerinin, verilerin aktarıldığı
          üçüncü kişilere bildirilmesini isteme.
        </li>
        <li>
          İşlenen verilerin münhasıran otomatik sistemlerle analizi sonucu
          aleyhinize bir sonuç ortaya çıkmasına itiraz etme.
        </li>
        <li>
          Verilerin hukuka aykırı işlenmesi nedeniyle zarara uğramanız halinde
          zararın giderilmesini talep etme.
        </li>
      </ul>

      <h2>8. Başvuru Yöntemi</h2>
      <p>
        Yukarıdaki haklarınıza ilişkin taleplerinizi{" "}
        <a href="mailto:bilgi@iotinnbilisim.com">bilgi@iotinnbilisim.com</a>{" "}
        veya{" "}
        <a href="mailto:nemezis@tutamail.com">nemezis@tutamail.com</a>{" "}
        adresine iletebilirsiniz. Başvurunuz, KVKK ve ilgili mevzuatta
        öngörülen süreler içinde değerlendirilerek yanıtlanır. Başvurunuzu
        değerlendirebilmemiz için talebinizin konusunu ve kimliğinizi açık
        şekilde belirtmenizi rica ederiz.
      </p>

      <p className="legal-updated">Son güncelleme: 11 Temmuz 2026</p>
    </main>
  );
}
