import type { Metadata } from "next";
import Link from "next/link";
import "../legal.css";

export const metadata: Metadata = {
  title: "İletişim",
  description:
    "rasathane.ai ile iletişim — IOT INN BİLİŞİM TİCARET A.Ş. adres ve e-posta bilgileri.",
};

export default function IletisimPage() {
  return (
    <main className="legal">
      <Link href="/" className="legal-back">
        ← Ana sayfaya dön
      </Link>

      <span className="legal-kicker">İletişim</span>
      <h1>İletişim</h1>

      <p>
        Ürünlere ilişkin sorularınız, ticari lisans talepleriniz ve diğer tüm
        konular için bize aşağıdaki kanallardan ulaşabilirsiniz.
      </p>

      <address>
        <strong>IOT INN BİLİŞİM TİCARET A.Ş.</strong>
        <br />
        Yıldızevler Mah. Turan Güneş Bul. No:32/12 Çankaya/Ankara
      </address>

      <h2>E-posta</h2>
      <ul>
        <li>
          Genel sorular ve kurumsal iletişim:{" "}
          <a href="mailto:bilgi@iotinnbilisim.com">bilgi@iotinnbilisim.com</a>
        </li>
        <li>
          Ticari lisans, hukuk ve kurucu ile doğrudan iletişim:{" "}
          <a href="mailto:nemezis@tutamail.com">nemezis@tutamail.com</a>
        </li>
      </ul>

      <h2>Açık Kaynak</h2>
      <p>
        Ürünlerin açık kaynak depoları ve katkı süreçleri için:{" "}
        <a href="https://github.com/aringm" target="_blank" rel="noopener">
          github.com/aringm
        </a>
      </p>

      <h2>Kardeş Site</h2>
      <p>
        Türk Hukuku için geliştirdiğimiz ürün takımı için:{" "}
        <a href="https://www.muhakeme.ai" target="_blank" rel="noopener">
          www.muhakeme.ai
        </a>
      </p>

      <p className="legal-updated">Son güncelleme: 11 Temmuz 2026</p>
    </main>
  );
}
