import type { Metadata } from "next";
import Link from "next/link";
import "./logo-lab.css";
import {
  LogoMeridyen,
  LogoKadran,
  LogoMonogram,
} from "@/components/landing/logo-candidates";

export const metadata: Metadata = {
  title: "Logo Laboratuvarı",
  robots: { index: false, follow: false },
};

const CANDIDATES = [
  {
    id: "meridyen",
    name: "A — Meridyen Halkası",
    note: "Kalibre edilmiş gözlem enstrümanı: halka, yataklar, altın nişangah kanadı. Ürün işaretleri bu sistemden türedi. Hero'da şu an bu var.",
    Mark: LogoMeridyen,
  },
  {
    id: "kadran",
    name: "B — Deklinasyon Kadranı",
    note: "Gök kataloğu plotlayıcısı: L eksen, üç konsantrik yay, altın katalog hücresi. En editoryal/diyagramatik.",
    Mark: LogoKadran,
  },
  {
    id: "monogram",
    name: "C — Geometrik R",
    note: "Modernist monogram: yarım çember çanak, dik gövde, altın kalibrasyon uçlu bacak. En tescil edilebilir.",
    Mark: LogoMonogram,
  },
];

const SIZES = [128, 64, 32, 16];

export default function LogoLab() {
  return (
    <main className="logolab">
      <header className="ll-head">
        <p className="ll-kicker">redesign · tur 2</p>
        <h1>Logo Laboratuvarı</h1>
        <p className="ll-desc">
          Üç aday, üç zeminde, dört boyutta — tasarım Codex (gpt-5.6-sol)
          delegasyonuyla hazırlandı. Seçimini bildir: <strong>A</strong>{" "}
          (meridyen halkası), <strong>B</strong> (kadran) veya <strong>C</strong>{" "}
          (monogram). Hero&apos;da şimdilik A gösteriliyor.
        </p>
        <p className="ll-links">
          <Link href="/">← Ana sayfaya dön (tasarım iterasyonları)</Link>
        </p>
      </header>

      {CANDIDATES.map(({ id, name, note, Mark }) => (
        <section className="ll-candidate" key={id} id={id}>
          <div className="ll-cand-head">
            <h2>{name}</h2>
            <p>{note}</p>
          </div>

          <div className="ll-row">
            <div className="ll-cell ll-night">
              {SIZES.map((s) => (
                <Mark key={s} size={s} />
              ))}
            </div>
            <div className="ll-cell ll-paper">
              {SIZES.map((s) => (
                <Mark key={s} size={s} />
              ))}
            </div>
            <div className="ll-cell ll-gold">
              {SIZES.map((s) => (
                <Mark key={s} size={s} />
              ))}
            </div>
          </div>

          <div className="ll-row ll-lockups">
            <div className="ll-cell ll-night ll-lockup">
              <Mark size={44} />
              <span className="ll-word serif">rasathane.ai</span>
            </div>
            <div className="ll-cell ll-paper ll-lockup">
              <Mark size={44} />
              <span className="ll-word serif">rasathane.ai</span>
            </div>
            <div className="ll-cell ll-night ll-lockup">
              <Mark size={44} />
              <span className="ll-word mono">rasathane.ai</span>
            </div>
          </div>
        </section>
      ))}

      <footer className="ll-foot">
        <p>
          Favicon ve hero, seçim sonrası kazanan adayla güncellenecek; üç ürün
          işareti (kubbe · yörünge · kanban) aynı dilden türetilecek.
        </p>
      </footer>
    </main>
  );
}
