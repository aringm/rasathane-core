"use client";

/**
 * Fasıl navigasyonu — sabit ilerleme çubuğu + masaüstünde sol ray.
 * Aktif fasıl IntersectionObserver ile, ilerleme scroll ile izlenir.
 */

import { useEffect, useState } from "react";

export type ChapterDef = { id: string; no: string; label: string };

export default function ChapterNav({ chapters }: { chapters: ChapterDef[] }) {
  const [active, setActive] = useState(chapters[0]?.id ?? "");
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    const sections = chapters
      .map((c) => document.getElementById(c.id))
      .filter((el): el is HTMLElement => el !== null);

    const io = new IntersectionObserver(
      (entries) => {
        let best: IntersectionObserverEntry | null = null;
        for (const e of entries) {
          if (e.isIntersecting && (!best || e.intersectionRatio > best.intersectionRatio)) {
            best = e;
          }
        }
        if (best) setActive((best.target as HTMLElement).id);
      },
      { rootMargin: "-42% 0px -42% 0px", threshold: [0, 0.2, 0.6, 1] }
    );
    sections.forEach((s) => io.observe(s));

    let raf = 0;
    const update = () => {
      const h = document.documentElement;
      const max = h.scrollHeight - h.clientHeight;
      setProgress(max > 0 ? Math.min(1, Math.max(0, h.scrollTop / max)) : 0);
    };
    const onScroll = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(update);
    };
    update();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);

    return () => {
      io.disconnect();
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      cancelAnimationFrame(raf);
    };
  }, [chapters]);

  const current = chapters.find((c) => c.id === active);

  return (
    <>
      <div className="nav-progress" aria-hidden="true">
        <span style={{ transform: `scaleX(${progress})` }} />
      </div>
      <nav className="chapter-nav" aria-label="Bölümler">
        <ol>
          {chapters.map((c) => (
            <li key={c.id}>
              <a href={`#${c.id}`} aria-current={active === c.id ? "true" : undefined}>
                <span className="cn-no" aria-hidden="true">
                  {c.no}
                </span>
                <span className="cn-label">{c.label}</span>
              </a>
            </li>
          ))}
        </ol>
        {current && (
          <span className="cn-current" aria-hidden="true">
            {current.no} · {current.label}
          </span>
        )}
      </nav>
    </>
  );
}
