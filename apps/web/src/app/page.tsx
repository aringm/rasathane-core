import Image from "next/image";
import type { Metadata } from "next";
import Link from "next/link";
import ProductTour from "../components/ProductTour";
import { publicUrunOku } from "../lib/rasathane-hesap";
import "./landing.css";

export const metadata: Metadata = { alternates: { canonical: "/" } };
export const dynamic = "force-dynamic";

const sources = [
  ["RSS ve Atom", "Takip ettiğiniz yayınların yeni içerikleri."],
  ["Web sayfaları", "Paylaştığınız açık sayfanın ana içeriği."],
  ["PDF belgeleri", "Metin içeren PDF bağlantılarından kaynaklı analiz."],
  ["YouTube", "Altyazı; seçiminizle ses çözümleme."],
  ["GitHub", "Açık depo bilgileri ve README içeriği."],
  ["arXiv", "Araştırma bilgileri ve makale özetleri."],
  ["Hugging Face", "Model ve veri seti kartları."],
];

export default async function Home() {
  const product = await publicUrunOku();
  const windows = product?.platforms.find(platform => platform.platform === "win");
  return (
    <main className="landing">
      <section className="hero wrap">
        <div className="hero-copy">
          <span className="overline">Masaüstü araştırma uygulaması</span>
          <h1>
            Bilgiyi izle.
            <br />
            Bağlamı keşfet.
          </h1>
          <p className="hero-lead">
            Kaynakları takip edin, içerikleri karşılaştırın. Rasathane;
            gündeminizi, analizlerinizi ve kaynaklı sohbetlerinizi
            bilgisayarınızda bir araya getirir.
          </p>
          <div className="actions">
            <a className="button" href="#rasathane">
              Nasıl çalışır?
            </a>
            <Link className="text-link" href="/indir" scroll={false}>
              Kurulum ve indirme
            </Link>
          </div>
          <a className="hero-status" href="#yayin">
            <span aria-hidden="true" />
            {windows?.available ? `Windows ${windows.version} · İndirmeye hazır` : "Yayın ve indirme durumunu inceleyin"}
          </a>
        </div>
        <figure className="hero-visual">
          <Image
            src="/media/rasathane-optical.webp"
            alt="Dağınık kaynak çizgilerini ortak bir odakta buluşturan yeşil cam mercek ve pirinç halkalar"
            width={1536}
            height={1024}
            priority
            sizes="(max-width: 760px) 100vw, 55vw"
          />
          <figcaption>
            <span>Kaynak</span>
            <span className="optical-line" aria-hidden="true" />
            <span>Bağlam</span>
            <span className="optical-line" aria-hidden="true" />
            <span>Bilgi</span>
          </figcaption>
        </figure>
        <div className="hero-base">
          <a href="https://www.iotinnbilisim.com/">
            Bir IoT Inn markası
          </a>
          <a href="#rasathane">
            Çalışma düzenini keşfedin <span aria-hidden="true">↓</span>
          </a>
        </div>
      </section>

      <section className="section product-section" id="rasathane">
        <div className="wrap">
          <div className="section-top">
            <div>
              <span className="overline">Akış, analiz ve araştırma</span>
              <h2 className="section-heading">
                Bir bağlantıdan
                <br />
                sürekli araştırmaya.
              </h2>
            </div>
            <p className="section-lead">
              Yeni içerikleri takip edin, bir bağlantıyı inceleyin,
              kaynaklarınıza sorular sorun. Türkçe özetler ve sesli bültenle
              gündemi takip edin; araştırma geçmişinize aynı sohbetten dönün.
            </p>
          </div>
          <ProductTour />
        </div>
      </section>

      <section className="section wrap sources-section" id="kaynaklar">
        <div className="section-top">
          <div>
            <h2 className="section-heading">
              Her kaynağı
              <br />
              kendi bağlamında.
            </h2>
          </div>
          <p className="section-lead">
            İçeriği kaynağın türüne göre inceleyin. Kaynak adresi ve alınma
            bilgisi, araştırmanızın bir parçası olarak kalsın.
          </p>
        </div>
        <div className="sources-grid">
          {sources.map(([title, description]) => (
            <article className="source-item" key={title}>
              <h3>{title}</h3>
              <p>{description}</p>
            </article>
          ))}
        </div>
        <div className="source-note">
          <span className="source-note-symbol" aria-hidden="true">
            ↳
          </span>
          <p>
            Resmî Gazete ve resmî karar bilgileri de takip edilebilir. Reddit
            için onaylı bağlantı gerekir. Alınabilen içerik kaynağa göre
            değişir; karar bilgisi her zaman tam karar metnini içermez.
          </p>
        </div>
      </section>

      <section className="approach section" id="yaklasim">
        <div className="wrap approach-grid">
          <div className="approach-title">
            <span className="overline">Yerel öncelikli, kaynak odaklı</span>
            <h2 className="section-heading">
              Araştırma sizde
              <br />
              biriksin.
            </h2>
            <p>
              Bilginin değerini, kaynağına dönebildiğiniz ve çalışmanızı
              sürdürebildiğiniz bir deneyimde arıyoruz.
            </p>
            <span className="signature">
              Av. Mehmet Arın Gülüm
              <br />
              <small>Kurucu</small>
            </span>
          </div>
          <div className="principles">
            <article>
              <span aria-hidden="true" className="principle-shape circle" />
              <div>
                <h3>Çalışmanız cihazınızda</h3>
                <p>
                  Araştırma geçmişiniz, yerel kitaplığınız ve analiz çıktılarınız
                  bilgisayarınızda tutulur.
                </p>
              </div>
            </article>
            <article>
              <span aria-hidden="true" className="principle-shape ring" />
              <div>
                <h3>Kaynakla bağınız korunsun</h3>
                <p>
                  Bulgularınızı kaynak adresi ve alınma bilgisiyle birlikte
                  yeniden inceleyin. Modelin değerlendirmesini kaynak metniyle
                  karşılaştırın.
                </p>
              </div>
            </article>
            <article>
              <span aria-hidden="true" className="principle-shape square" />
              <div>
                <h3>Bağlantılar açıkça tanımlı</h3>
                <p>
                  İçerik ilgili sitelerden alınır. Web aramasını açtığınızda
                  sorgunuz seçtiğiniz sağlayıcıya gider. Cloud analiz varsayılan
                  olarak kapalıdır.
                </p>
              </div>
            </article>
          </div>
        </div>
      </section>

      <section className="release section" id="yayin">
        <div className="wrap release-grid">
          <div>
            <span className="overline">Yayın ve erişim</span>
            <h2 className="section-heading">
              Rasathane’ye
              <br />
              erişim.
            </h2>
            <p className="section-lead">
              Güncel sürüm, dosya boyutu ve SHA-256 bilgisi indirme sayfasında
              doğrulanır. Kurulum sihirbazı donanımınıza uygun yerel model
              seçeneğini belirler; en az 8 GB RAM hedeflenir.
            </p>
            <dl
              className="release-status"
              aria-label="Platformların yayın durumu"
            >
              <div>
                <dt>Windows</dt>
                <dd>{windows?.available ? `Sürüm ${windows.version} · ${windows.size}` : "Doğrulanmış paket bekleniyor"}</dd>
              </div>
              <div>
                <dt>macOS</dt>
                <dd>{product?.platforms.find(platform => platform.platform === "mac")?.available ? "İndirme sayfasından inceleyin" : "Doğrulanmış paket henüz yayımlanmadı"}</dd>
              </div>
            </dl>
            {!product && <p className="release-checked" role="status">Yayın hizmetine şu anda ulaşılamıyor. Doğrulanmamış indirme bağlantısı sunulmuyor.</p>}
            <div className="actions">
              <Link className="button" href="/indir" scroll={false}>
                Kurulumları inceleyin
              </Link>
              <Link className="text-link" href="/hesap" scroll={false}>Hesabım ve deneme</Link>
            </div>
          </div>
          <div className="release-note" id="lisans">
            <h3>Hesap ve lisans</h3>
            <dl className="access-facts">
              <div>
                <dt>Ortak hesap</dt>
                <dd>
                  Uygulamayı açmak için ücretsiz Muhakeme hesabıyla giriş ve
                  e-posta doğrulama kodu gerekir.
                </dd>
              </div>
              <div>
                <dt>Yerel çalışma</dt>
                <dd>
                  Yerel çekirdek ücretsizdir; ücretli servis aboneliği gerekmez.
                  Kaynaklar, analizler ve araştırma geçmişi cihazınızda tutulur.
                </dd>
              </div>
              <div>
                <dt>Yönetilen servis</dt>
                <dd>KDV dahil 49 TL / ay. 14 günlük ücretsiz servis denemesi
                  uygulamadaki Hesap ve plan bölümünden başlatılır. Otomatik tahsilat yapılmaz.</dd>
              </div>
              <div>
                <dt>Açık kaynak</dt>
                <dd>
                  Yerel çekirdek AGPL-3.0 kapsamında yayımlanır. Ticari lisans
                  için bizimle iletişime geçebilirsiniz.
                </dd>
              </div>
            </dl>
            <a
              className="text-link"
              href="https://github.com/aringm/rasathane-core"
              target="_blank"
              rel="noopener noreferrer"
            >
              Kaynak kodu ve geliştirme
            </a>
          </div>
        </div>
      </section>

      <section className="section wrap brand-family" id="ekosistem">
        <div className="family-owner">
          <div className="family-owner-brand">
            <span className="overline">Ortak kurum, farklı uzmanlıklar</span>
            <Image
              src="/brand/iotinn-lockup-primary.svg"
              alt="IOT INN Bilişim Ticaret A.Ş."
              width={219}
              height={64}
            />
          </div>
          <div>
            <h2>
              Rasathane, IoT Inn’in
              <br />
              araştırma markasıdır.
            </h2>
            <p>
              Veriyi edinmek, anlamlandırmak ve kullanılabilir bilgiye
              dönüştürmek için ürünler geliştiriyoruz.
            </p>
            <a
              className="text-link"
              href="https://www.iotinnbilisim.com/"
            >
              IoT Inn’i tanıyın
            </a>
          </div>
        </div>
        <div className="family-sibling">
          <div>
            <span className="overline">Aynı aileden</span>
            <h3>Hukuk araştırması için Muhakeme</h3>
          </div>
          <div>
            <p>
              İçtihat araştırması ve hukuk çalışma araçları için Muhakeme
              ailesini inceleyin.
            </p>
            <a
              className="text-link"
              href="https://www.muhakeme.ai/"
            >
              Muhakeme’ye geçin
            </a>
          </div>
        </div>
        <div className="family-studies">
          <span>Diğer çalışmalarımız</span>
          <p id="horoskop">
            <strong>Horoskop</strong> Model orkestrasyonu üzerine geliştirme
            çalışması.
          </p>
          <p id="atolye">
            <strong>Atölye</strong> IoT Inn’in ekip içi çalışma alanı.
          </p>
        </div>
      </section>
    </main>
  );
}
