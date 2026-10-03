import Link from "next/link";
import { BrandMark } from "@/components/BrandMark";
import "./landing.css";

const workflow = [
  {
    title: "Takip et",
    text: "Kaynakları ve konuları seç. Yeni içerikleri ortak akışta gör; son kontrol zamanı ve kaynak hatası görünür kalsın.",
    detail: "Kaynak akışı · Konu takibi",
  },
  {
    title: "Çözümle",
    text: "Bir bağlantıyı ayrıntılı incelemeye dönüştür. Özet, bilgi değeri, doğrulama ve zihin haritasını aynı raporda değerlendir.",
    detail: "Çok kaynaklı analiz · Yerel motor",
  },
  {
    title: "Araştır",
    text: "Yerel kitaplığında ara. İstersen web kaynaklarını araştırmaya ekle; kaynak adresi ve edinim bilgisini sonuçla birlikte koru.",
    detail: "Web arama · Kaynak kaydı",
  },
  {
    title: "Biriktir",
    text: "Notları ve kaynakları çalışma alanında tut. Araştırmanı yeniden aç, kaldığın yerden sürdür ve kayıtlarını dışa aktar.",
    detail: "Çalışma alanı · Yerel kitaplık",
  },
];

function ObservationDiagram() {
  return (
    <div
      className="observation"
      aria-label="Farklı kaynaklar tek analiz odağında buluşur ve yerel çalışma alanına kaydedilir"
    >
      <svg
        viewBox="0 0 560 420"
        className="observation-lines"
        aria-hidden="true"
      >
        <ellipse cx="280" cy="194" rx="202" ry="132" />
        <ellipse
          cx="280"
          cy="194"
          rx="202"
          ry="72"
          transform="rotate(-34 280 194)"
        />
        <circle cx="280" cy="194" r="73" />
        <path d="M280 122v144M208 194h144M280 267v69" />
        <circle cx="110" cy="122" r="5" />
        <circle cx="435" cy="277" r="5" />
      </svg>
      <span className="source-label source-web">Web kaynakları</span>
      <span className="source-label source-paper">Makale ve repository</span>
      <span className="source-label source-law">Karar ve mevzuat</span>
      <span className="source-label source-video">Video ve içerik</span>
      <div className="observation-center">
        <BrandMark size={68} decorative />
        <strong>Tek inceleme odağı</strong>
        <span>Kaynak, analiz, kanıt</span>
      </div>
      <div className="observation-library">
        <span className="library-lines" aria-hidden="true">
          <i />
          <i />
          <i />
        </span>
        <div>
          <strong>Çalışma alanınız</strong>
          <span>Notlar ve kaynaklar cihazınızda</span>
        </div>
      </div>
      <span className="diagram-caption">Rasathane&apos;nin çalışma düzeni</span>
    </div>
  );
}

export default function Home() {
  return (
    <div className="rasathane-site">
      <a className="site-skip" href="#main">
        İçeriğe atla
      </a>
      <header className="site-header">
        <Link className="site-brand" href="/" aria-label="Rasathane ana sayfa">
          <BrandMark size={40} decorative />
          <span>Rasathane</span>
        </Link>
        <nav aria-label="Ana gezinme">
          <a href="#urun">Ürün</a>
          <a href="#veri">Veri ve kaynak</a>
          <a href="#fiyat">Fiyat</a>
        </nav>
        <div className="header-actions">
          <Link href="/hesap" className="account-link">
            Hesabım
          </Link>
          <Link href="/indir" className="site-button compact">
            İndirme
          </Link>
        </div>
      </header>
      <main id="main">
        <section className="site-hero">
          <div className="hero-copy">
            <p className="hero-context">
              Takipten araştırmaya, tek çalışma alanı.
            </p>
            <h1>
              Kaynakları izle.
              <br />
              Bağlantıyı çözümle.
              <br />
              Araştırmanı biriktir.
            </h1>
            <p className="hero-description">
              Rasathane, takip ettiğiniz içeriği anlamlı bir araştırmaya
              dönüştürür. Ayrıntılı analiz, web arama ve yerel kitaplık aynı
              masaüstü uygulamasında buluşur.
            </p>
            <div className="hero-actions">
              <Link href="/indir" className="site-button">
                İndirme durumunu gör
              </Link>
              <a href="#urun" className="text-link">
                Çalışma düzenini incele
              </a>
            </div>
            <p className="hero-footnote">
              Windows masaüstü · 8 GB RAM için yerel profil
            </p>
          </div>
          <ObservationDiagram />
        </section>
        <section
          className="product-workflow"
          id="urun"
          aria-labelledby="workflow-title"
        >
          <div className="section-intro">
            <h2 id="workflow-title">
              Bir kaynakla başlar.
              <br />
              Bir araştırmaya dönüşür.
            </h2>
            <p>
              Ayrı araçlarda dağılan takibi, incelemeyi ve notları tek yerde
              sürdürün. Her adımın sonucu bir sonraki adımda kullanılabilir.
            </p>
          </div>
          <ol className="workflow-steps">
            {workflow.map((item, i) => (
              <li key={item.title}>
                <span className="workflow-number" aria-hidden="true">
                  {i + 1}
                </span>
                <div>
                  <h3>{item.title}</h3>
                  <p>{item.text}</p>
                  <span className="workflow-detail">{item.detail}</span>
                </div>
              </li>
            ))}
          </ol>
        </section>
        <section className="analysis-feature" aria-labelledby="analysis-title">
          <div className="analysis-copy">
            <h2 id="analysis-title">
              Özetin arkasını
              <br />
              da görün.
            </h2>
            <p>
              Bir sonucu değerlendirirken yalnız cevaba bakmayın. Kaynak
              künyesi, inceleme aşamaları ve doğrulama bulguları aynı analiz
              ekranında yer alır.
            </p>
            <p>
              Kısa ve ayrıntılı özetin yanında kişisel analiz, bilgi değeri ve
              zihin haritası bulunur. Üretilmeyen çıktının nedeni görünür kalır.
            </p>
            <a href="#veri" className="text-link">
              Kaynak ve veri yaklaşımı
            </a>
          </div>
          <div
            className="analysis-outline"
            aria-label="Analiz raporunun bölümleri"
          >
            <div className="outline-head">
              <span>Analiz raporu</span>
              <BrandMark size={30} decorative />
            </div>
            <div className="outline-source">
              <span>Kaynak künyesi</span>
              <strong>Başlık, adres ve edinim bilgisi</strong>
            </div>
            <div className="outline-body">
              <div>
                <span className="outline-section">İnceleme</span>
                <p>Kısa ve ayrıntılı özet</p>
                <p>Kaynak sinyalleri</p>
                <p>Kişisel analiz</p>
                <p>Doğrulama ve zihin haritası</p>
              </div>
              <div>
                <span className="outline-section">İşlem kaydı</span>
                <p>Bilgi değeri</p>
                <p>İşlem aşamaları</p>
                <p>Model ve veri kökeni</p>
                <p>Yerel çıktılar</p>
              </div>
            </div>
            <div className="outline-note">
              Bu şema ürünün rapor yapısını gösterir; örnek bir analiz sonucu
              değildir.
            </div>
          </div>
        </section>
        <section
          className="data-section"
          id="veri"
          aria-labelledby="data-title"
        >
          <div className="section-intro">
            <h2 id="data-title">
              Veri işleme görünür.
              <br />
              Kontrol sizde.
            </h2>
            <p>
              Yerel çalışma ile web ve yönetilen hizmet kullanımını ayırt edin.
              İnternet erişimi gerektiren işlemleri seçerek başlatın.
            </p>
          </div>
          <div className="data-principles">
            <article>
              <h3>Yerel çalışma alanı</h3>
              <p>
                Notlar, araştırma kayıtları ve analiz çıktıları cihazınızda
                tutulur. Çalışma alanınızı dışa aktarabilirsiniz.
              </p>
            </article>
            <article>
              <h3>Kaynağa bağlı sonuç</h3>
              <p>
                Web bulgularının adresi, edinim durumu ve içerik kaydı korunur.
                Ulaşılamayan kaynak doğrulanmış bilgi diye gösterilmez.
              </p>
            </article>
            <article>
              <h3>Açık çekirdek, bağımsız hizmet</h3>
              <p>
                Yerel çekirdeğin kodu ve veri işleme mimarisi denetime açılır.
                Marka, yönetilen hizmet ve abonelik koşulları ayrı düzenlenir.
              </p>
            </article>
          </div>
        </section>
        <section
          className="pricing-section"
          id="fiyat"
          aria-labelledby="pricing-title"
        >
          <div className="pricing-intro">
            <h2 id="pricing-title">
              Yerel çekirdek ücretsiz.
              <br />
              Sürdürülebilir hizmet
              <br />
              sembolik bir ücretle.
            </h2>
            <p>
              Açık kaynak kullanım hakkı ile yönetilen hizmet aboneliği ayrı
              kapsamlar taşır. Yerel çekirdeğin ücretsiz kullanımı aboneliğe
              bağlı değildir.
            </p>
            <Link href="/hesap" className="text-link">
              Üyelik ve deneme durumunu gör
            </Link>
          </div>
          <div className="price-panel">
            <h3>Rasathane hizmeti</h3>
            <div className="price">
              <strong>49</strong>
              <span>TL / ay</span>
            </div>
            <p className="price-total">KDV dahil aylık toplam ücret</p>
            <ul>
              <li>Yönetilen hizmetlere üyelik</li>
              <li>Hesap ve plan durumu</li>
              <li>14 günlük ücretsiz hizmet denemesi</li>
            </ul>
            <Link className="site-button" href="/hesap">
              Deneme koşullarını incele
            </Link>
            <p className="price-note">
              Deneme, ücretli hizmet kapsamına aittir. Yerel çekirdek ücretsiz
              kalır. Üyelik ekranı etkin hizmet ve ödeme durumunu gösterir.
            </p>
          </div>
        </section>
        <section className="release-section" aria-labelledby="release-title">
          <BrandMark size={56} decorative />
          <div>
            <h2 id="release-title">Tek ürün. Tek Rasathane.</h2>
            <p>
              Sürüm ve indirme durumunu, dosya doğrulama bilgileriyle birlikte
              indirme sayfasından takip edin.
            </p>
          </div>
          <Link href="/indir" className="site-button secondary">
            Sürüm durumunu kontrol et
          </Link>
        </section>
      </main>
      <footer className="site-footer">
        <div>
          <Link className="site-brand" href="/">
            <BrandMark size={32} decorative />
            <span>Rasathane</span>
          </Link>
          <p>
            Bir IOT INN BİLİŞİM TİCARET A.Ş. ürünü.
            <br />
            Av. Mehmet Arın Gülüm
          </p>
        </div>
        <nav aria-label="Alt gezinme">
          <Link href="/gizlilik">Gizlilik</Link>
          <Link href="/kvkk">KVKK</Link>
          <Link href="/iletisim">İletişim</Link>
          <a
            href="https://www.muhakeme.ai"
            target="_blank"
            rel="noopener noreferrer"
          >
            muhakeme.ai
          </a>
          <a
            href="https://github.com/aringm/rasathane-core"
            target="_blank"
            rel="noopener noreferrer"
          >
            Kaynak kodu
          </a>
        </nav>
      </footer>
    </div>
  );
}
