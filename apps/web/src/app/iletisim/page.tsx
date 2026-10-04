import type { Metadata } from "next";
import Image from "next/image";
import "../legal.css";

export const metadata: Metadata = {
  alternates: { canonical: "/iletisim" },
  title: "İletişim",
  description:
    "Rasathane ürün bilgisi, ticari lisans ve kurumsal kullanım için IoT Inn ile iletişime geçin.",
};

export default function IletisimPage() {
  return (
    <main className="contact-page wrap">
      <div className="contact-intro">
        <div>
          <span className="overline">Rasathane ile iletişim</span>
          <h1>Birlikte düşünelim.</h1>
        </div>
        <p>
          Ürün hakkında bilgi almak, kurumsal kullanımınızı konuşmak veya ticari
          lisans talebinizi iletmek için bize yazın.
        </p>
      </div>
      <div className="contact-grid">
        <div className="contact-channels">
          <article>
            <h2>Genel iletişim</h2>
            <p>Ürün soruları ve kurumsal görüşmeler.</p>
            <a href="mailto:bilgi@iotinnbilisim.com">bilgi@iotinnbilisim.com</a>
          </article>
          <article>
            <h2>Lisans ve kurucuya ulaşım</h2>
            <p>Av. Mehmet Arın Gülüm</p>
            <a href="mailto:nemezis@tutamail.com">nemezis@tutamail.com</a>
          </article>
          <article>
            <h2>Kaynak ve geliştirme</h2>
            <p>Açık kaynak çalışmaları ve katkı süreçleri.</p>
            <a
              href="https://github.com/aringm"
              target="_blank"
              rel="noopener noreferrer"
            >
              github.com/aringm
            </a>
          </article>
        </div>
        <aside className="contact-address" aria-label="Şirket bilgileri">
          <Image
            src="/brand/iotinn-lockup-primary.svg"
            alt="IOT INN Bilişim Ticaret A.Ş."
            width={280}
            height={64}
          />
          <address>
            <strong>IOT INN BİLİŞİM TİCARET A.Ş.</strong>
            <br />
            Yıldızevler Mah. Turan Güneş Bul.
            <br />
            No:32/12 Çankaya / Ankara
          </address>
          <p>
            Rasathane ve Muhakeme, IoT Inn’in aynı kaynak odaklı yaklaşımla
            geliştirdiği ürün aileleridir.
          </p>
          <nav aria-label="Diğer markalar">
            <a href="https://www.iotinnbilisim.com/">
              IoT Inn
            </a>
            <a href="https://www.muhakeme.ai/">
              Muhakeme
            </a>
          </nav>
        </aside>
      </div>
      <p className="contact-caption">
        E-posta bağlantıları kullandığınız e-posta uygulamasını açar.
      </p>
    </main>
  );
}
