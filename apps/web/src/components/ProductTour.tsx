"use client";

import {
  useId,
  useRef,
  useState,
  useSyncExternalStore,
  type KeyboardEvent,
} from "react";

const mobileQuery = "(max-width: 760px)";
function subscribeOrientation(notify: () => void) {
  const query = window.matchMedia(mobileQuery);
  query.addEventListener("change", notify);
  return () => query.removeEventListener("change", notify);
}
const isHorizontal = () => window.matchMedia(mobileQuery).matches;
const serverOrientation = () => false;

const sections = [
  {
    name: "Akış",
    title: "Takip ettikleriniz tek yerde.",
    description:
      "Kaynaklarınızı kategorilere ayırın. Yeni haberlerin Türkçe özetini okuyun; kartın üzerindeki kaynağı aç, özetle, seslendir ve derinlemesine analiz et seçeneklerini kullanın.",
    steps: [
      "Kaynağınızı ekleyin.",
      "Yenilikleri inceleyin.",
      "İlginizi çeken kaydı açın.",
    ],
  },
  {
    name: "Analiz",
    title: "Bir bağlantıya daha yakından bakın.",
    description:
      "Desteklenen bir kaynağın içeriğiyle çevirisini, özetini ve değerlendirmesini birlikte okuyun. Rapor ve haritayı çalışmanızda saklayın.",
    steps: [
      "Bağlantıyı ekleyin.",
      "Kaynakla birlikte inceleyin.",
      "Raporunuzu saklayın.",
    ],
  },
  {
    name: "Araştır",
    title: "Sorularınızı kaynaklarla geliştirin.",
    description:
      "Yerel kitaplığınızda arayın; gerektiğinde web kaynakları ekleyin. Devam soruları ve kaynaklar aynı konuşmada kalsın.",
    steps: [
      "Sorunuzu yazın.",
      "Kaynakları karşılaştırın.",
      "Devam sorularıyla derinleşin.",
    ],
  },
  {
    name: "Bülten",
    title: "Gündeminiz okunabilir ve dinlenebilir olsun.",
    description:
      "Yenilenen kaynaklardaki haberleri ilgi alanlarınıza göre değerlendirin. Kişisel gündeminizi bültende okuyun veya Türkçe seslendirmeyle dinleyin.",
    steps: [
      "İlgi alanlarınızı belirtin.",
      "Kaynakları yenileyip gündemi hazırlayın.",
      "Bülteninizi okuyun veya dinleyin.",
    ],
  },
] as const;

export default function ProductTour() {
  const id = useId();
  const [selected, setSelected] = useState(0);
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const horizontal = useSyncExternalStore(
    subscribeOrientation,
    isHorizontal,
    serverOrientation,
  );

  function handleKeyDown(
    event: KeyboardEvent<HTMLButtonElement>,
    index: number,
  ) {
    let next: number;

    switch (event.key) {
      case "ArrowRight":
      case "ArrowDown":
        next = (index + 1) % sections.length;
        break;
      case "ArrowLeft":
      case "ArrowUp":
        next = (index - 1 + sections.length) % sections.length;
        break;
      case "Home":
        next = 0;
        break;
      case "End":
        next = sections.length - 1;
        break;
      default:
        return;
    }

    event.preventDefault();
    setSelected(next);
    tabRefs.current[next]?.focus();
  }

  return (
    <div className="product-tour">
      <div
        className="tour-tabs"
        role="tablist"
        aria-label="Rasathane çalışma bölümleri"
        aria-orientation={horizontal ? "horizontal" : "vertical"}
      >
        {sections.map((section, index) => (
          <button
            key={section.name}
            ref={(element) => {
              tabRefs.current[index] = element;
            }}
            type="button"
            role="tab"
            id={`${id}-tab-${index}`}
            aria-controls={`${id}-panel-${index}`}
            aria-selected={selected === index}
            tabIndex={selected === index ? 0 : -1}
            className={`tour-tab${selected === index ? " is-active" : ""}`}
            onClick={() => setSelected(index)}
            onKeyDown={(event) => handleKeyDown(event, index)}
          >
            {section.name}
          </button>
        ))}
      </div>

      {sections.map((section, index) => (
        <section
          key={section.name}
          role="tabpanel"
          id={`${id}-panel-${index}`}
          aria-labelledby={`${id}-tab-${index}`}
          className="tour-panel"
          hidden={selected !== index}
          style={selected !== index ? { display: "none" } : undefined}
          tabIndex={0}
        >
          <span className="tour-label">{section.name}</span>
          <h3>{section.title}</h3>
          <p>{section.description}</p>
          <ol className="tour-steps">
            {section.steps.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
        </section>
      ))}

      <p className="tour-footnote">
        Rasathane’nin kaynak takibi, yerel analiz ve araştırma akışı.
      </p>
    </div>
  );
}
