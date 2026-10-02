"use client";

/**
 * Scroll-scrub anlatı videosu.
 * - Takımyıldız filmi, anlatı bloğunun scroll ilerlemesine bağlı olarak "çevrilir"
 *   (oynatılmaz): currentTime hedefe yumuşatılarak yaklaştırılır.
 * - Tembel yüklenir: anlatı bloğu yaklaşana kadar src takılmaz, poster gösterilir.
 * - prefers-reduced-motion: video yüklenmez, poster + metin yeterlidir.
 * - Ses yok, otomatik oynatma yok; medya dekoratiftir (aria-hidden).
 */

import { useEffect, useRef } from "react";

const clamp01 = (v: number) => (v < 0 ? 0 : v > 1 ? 1 : v);

export default function ScrollVideo() {
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap) return;
    const video = wrap.querySelector<HTMLVideoElement>("video");
    const narrative = wrap.closest<HTMLElement>(".narrative");
    if (!video || !narrative) return;

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const loadIo = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          if (!video.getAttribute("src")) {
            video.setAttribute("src", video.dataset.src ?? "");
          }
          loadIo.disconnect();
        }
      },
      { rootMargin: "150% 0px" }
    );
    loadIo.observe(narrative);

    if (reduced) return;

    let raf = 0;
    const scrub = () => {
      const rect = narrative.getBoundingClientRect();
      const total = rect.height - window.innerHeight;
      const p = total > 0 ? clamp01(-rect.top / total) : 0;
      const d = video.duration;
      if (d && !video.seeking && video.readyState >= 2) {
        const target = p * Math.max(0, d - 0.08);
        const delta = target - video.currentTime;
        if (Math.abs(delta) > 0.012) {
          video.currentTime = video.currentTime + delta * 0.16;
        }
      }
    };
    const onScroll = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(scrub);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);

    return () => {
      loadIo.disconnect();
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      cancelAnimationFrame(raf);
    };
  }, []);

  return (
    <div className="narrative-media" ref={wrapRef} aria-hidden="true">
      <video
        data-src="/landing/media/narrative.mp4"
        poster="/landing/media/narrative-poster.jpg"
        muted
        playsInline
        preload="metadata"
        tabIndex={-1}
        disablePictureInPicture
      />
    </div>
  );
}
