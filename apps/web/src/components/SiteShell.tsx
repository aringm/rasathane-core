"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

const sectionIds = ["rasathane", "yaklasim", "yayin", "ekosistem"];
const routeKey = (path: string) => path.replace(/\/$/, "") || "/";

function hashTarget(hash: string): HTMLElement | null {
  if (!hash) return null;
  try {
    return document.getElementById(decodeURIComponent(hash.slice(1)));
  } catch {
    return null;
  }
}

function focusContent(target: HTMLElement | null) {
  if (!target) return;
  if (!target.hasAttribute("tabindex")) target.setAttribute("tabindex", "-1");
  target.focus({ preventScroll: true });
}

function Navigation({
  pathname,
  activeSection,
}: {
  pathname: string;
  activeSection: string | null;
}) {
  const [open, setOpen] = useState(false);
  const toggle = useRef<HTMLButtonElement>(null);
  const nav = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        toggle.current?.focus();
      }
    };
    const outside = (event: PointerEvent) => {
      if (
        event.target instanceof Node &&
        !nav.current?.contains(event.target) &&
        !toggle.current?.contains(event.target)
      )
        setOpen(false);
    };
    document.addEventListener("keydown", close);
    document.addEventListener("pointerdown", outside);
    return () => {
      document.removeEventListener("keydown", close);
      document.removeEventListener("pointerdown", outside);
    };
  }, [open]);

  return (
    <>
      <button
        ref={toggle}
        className="menu-toggle"
        type="button"
        aria-expanded={open}
        aria-controls="site-nav"
        onClick={() => setOpen(!open)}
      >
        {open ? "Kapat" : "Menü"}
        <span aria-hidden="true">{open ? "×" : "+"}</span>
      </button>
      <nav
        ref={nav}
        id="site-nav"
        aria-label="Ana gezinme"
        className={open ? "site-nav is-open" : "site-nav"}
        onClick={() => setOpen(false)}
        onBlur={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget))
            setOpen(false);
        }}
      >
        <Link
          href="/#rasathane"
          scroll={false}
          aria-current={
            pathname === "/" && activeSection === "rasathane"
              ? "location"
              : undefined
          }
        >
          Rasathane
        </Link>
        <Link
          href="/#yaklasim"
          scroll={false}
          aria-current={
            pathname === "/" && activeSection === "yaklasim"
              ? "location"
              : undefined
          }
        >
          Yaklaşım
        </Link>
        <Link
          href="/#yayin"
          scroll={false}
          aria-current={
            pathname === "/" && activeSection === "yayin"
              ? "location"
              : undefined
          }
        >
          İndir ve erişim
        </Link>
        <Link
          href="/#ekosistem"
          scroll={false}
          aria-current={
            pathname === "/" && activeSection === "ekosistem"
              ? "location"
              : undefined
          }
        >
          Ekosistem
        </Link>
        <Link href="/hesap" scroll={false} aria-current={routeKey(pathname) === "/hesap" ? "page" : undefined}>Hesabım</Link>
        <Link href="/indir" scroll={false} aria-current={routeKey(pathname) === "/indir" ? "page" : undefined}>İndir</Link>
        <Link
          href="/iletisim/"
          className="nav-contact"
          scroll={false}
          aria-current={routeKey(pathname) === "/iletisim" ? "page" : undefined}
        >
          İletişim
        </Link>
      </nav>
    </>
  );
}

export default function SiteShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const scroll = useRef<HTMLDivElement>(null);
  const keyboardDestination = useRef<{ pathname: string; hash: string } | null>(
    null,
  );
  const [activeSection, setActiveSection] = useState<string | null>(null);

  useEffect(() => {
    const frames = new Set<number>();
    const schedule = (callback: () => void) => {
      const id = requestAnimationFrame(() => {
        frames.delete(id);
        callback();
      });
      frames.add(id);
    };
    const goToHash = () => {
      if (window.location.hash) {
        hashTarget(window.location.hash)?.scrollIntoView({ block: "start" });
      } else scroll.current?.scrollTo({ top: 0, behavior: "instant" });
    };
    schedule(() => {
      goToHash();
      const pending = keyboardDestination.current;
      if (pending && pending.pathname === routeKey(pathname)) {
        keyboardDestination.current = null;
        focusContent(
          hashTarget(pending.hash) ?? document.getElementById("main-content"),
        );
      }
    });
    window.addEventListener("hashchange", goToHash);
    // Next hash links may update history without a hashchange event.
    const onLink = (event: MouseEvent) => {
      const link =
        event.target instanceof Element
          ? event.target.closest("a[href]")
          : null;
      if (
        !link ||
        event.ctrlKey ||
        event.metaKey ||
        event.shiftKey ||
        event.altKey
      )
        return;
      if (
        event.button !== 0 ||
        link.getAttribute("target") === "_blank" ||
        link.hasAttribute("download")
      )
        return;
      let url: URL;
      try {
        url = new URL(link.getAttribute("href")!, window.location.href);
      } catch {
        return;
      }
      if (url.origin !== window.location.origin) return;
      const keyboard = event.detail === 0;
      const destination = routeKey(url.pathname);
      // Capture before React commits the route, so only keyboard activation transfers focus.
      keyboardDestination.current = keyboard
        ? { pathname: destination, hash: url.hash }
        : null;
      if (destination === routeKey(pathname)) {
        schedule(() => {
          if (url.hash) {
            const target = hashTarget(url.hash);
            target?.scrollIntoView({ block: "start" });
            if (keyboard) focusContent(target);
          } else {
            scroll.current?.scrollTo({ top: 0, behavior: "instant" });
            if (keyboard) focusContent(document.getElementById("main-content"));
          }
          keyboardDestination.current = null;
        });
      }
    };
    document.addEventListener("click", onLink, true);
    return () => {
      frames.forEach(cancelAnimationFrame);
      window.removeEventListener("hashchange", goToHash);
      document.removeEventListener("click", onLink, true);
    };
  }, [pathname]);

  useEffect(() => {
    const pane = scroll.current;
    if (!pane) return;
    let frame = 0;
    const update = () => {
      frame = 0;
      const marker =
        pane.getBoundingClientRect().top + pane.clientHeight * 0.28;
      let current: string | null = null;
      let closest = -Infinity;
      if (pathname === "/") {
        for (const id of sectionIds) {
          const top = document.getElementById(id)?.getBoundingClientRect().top;
          if (top !== undefined && top <= marker && top > closest) {
            closest = top;
            current = id;
          }
        }
      }
      setActiveSection((previous) =>
        previous === current ? previous : current,
      );
    };
    const queue = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };
    queue();
    pane.addEventListener("scroll", queue, { passive: true });
    window.addEventListener("resize", queue);
    return () => {
      cancelAnimationFrame(frame);
      pane.removeEventListener("scroll", queue);
      window.removeEventListener("resize", queue);
    };
  }, [pathname]);

  return (
    <>
      <a className="skip-link" href="#main-content">
        İçeriğe geç
      </a>
      <header className="site-header family-header">
        <div className="family-header-inner">
          <Link
            className="brand"
            href="/"
            aria-label="Rasathane ana sayfa"
            scroll={false}
            onClick={() =>
              scroll.current?.scrollTo({ top: 0, behavior: "instant" })
            }
          >
            <Image
              src="/brand/rasathane-primary.svg"
              alt="rasathane.ai"
              width={307}
              height={64}
              priority
            />
          </Link>
          <Navigation
            key={pathname}
            pathname={pathname}
            activeSection={activeSection}
          />
        </div>
      </header>
      <div
        className="site-scroll"
        ref={scroll}
        tabIndex={0}
        role="region"
        aria-label="Sayfa içeriği"
      >
        <div id="main-content" tabIndex={-1}>
          {children}
        </div>
        <footer className="site-footer">
          <div className="footer-family">
            <Link
              href="/"
              className="footer-logo"
              aria-label="Rasathane ana sayfa"
              scroll={false}
              onClick={() =>
                scroll.current?.scrollTo({ top: 0, behavior: "instant" })
              }
            >
              <Image
                src="/brand/rasathane-reverse.svg"
                alt="rasathane.ai"
                width={260}
                height={55}
              />
            </Link>
            <p>
              Bilgiyi anlamlı kılan
              <br />
              ortak bir yaklaşım.
            </p>
            <a
              href="https://www.iotinnbilisim.com/"
              className="parent-brand"
            >
              <span>Bir IoT Inn markası</span>
              <span>IOT INN Bilişim Ticaret A.Ş.</span>
            </a>
          </div>
          <div className="footer-links">
            <nav aria-label="Marka ailesi">
              <span>Marka ailesi</span>
              <a href="https://www.iotinnbilisim.com/">
                IoT Inn
              </a>
              <Link href="/" scroll={false}>
                Rasathane
              </Link>
              <a href="https://www.muhakeme.ai/">
                Muhakeme
              </a>
            </nav>
            <nav aria-label="Bilgi">
              <span>Bilgi ve iletişim</span>
              <Link href="/iletisim/" scroll={false}>
                İletişim
              </Link>
              <Link href="/gizlilik/" scroll={false}>
                Gizlilik politikası
              </Link>
              <Link href="/kvkk/" scroll={false}>
                KVKK aydınlatma metni
              </Link>
            </nav>
          </div>
          <div className="footer-bottom">
            <span>© 2026 IOT INN BİLİŞİM TİCARET A.Ş.</span>
            <span>Kurucu: Av. Mehmet Arın Gülüm</span>
            <a
              href="https://github.com/aringm/rasathane-core"
              target="_blank"
              rel="noopener noreferrer"
            >
              Açık kaynak
            </a>
          </div>
        </footer>
      </div>
    </>
  );
}
