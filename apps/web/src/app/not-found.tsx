import Link from "next/link";

export default function NotFound() {
  return (
    <main className="not-found wrap">
      <span className="overline">404</span>
      <h1>Bu sayfa bulunamadı.</h1>
      <p>
        Bağlantı değişmiş olabilir. Rasathane’nin ana sayfasından devam
        edebilirsiniz.
      </p>
      <div className="actions">
        <Link className="button" href="/" scroll={false}>
          Ana sayfaya dön
        </Link>
        <Link className="text-link" href="/iletisim/" scroll={false}>
          İletişim
        </Link>
      </div>
    </main>
  );
}
