import Link from "next/link";

export default function Home() {
  return (
    <div className="landing">
      <header className="site-header">
        <nav aria-label="Primary navigation" className="navigation">
          <Link href="/" className="brand">
            Sky Bridge Jet
          </Link>
          <Link href="/portal" className="landing__signin">
            Sign in
          </Link>
        </nav>
      </header>
      <main className="hero">
        <p className="eyebrow">Customer portal</p>
        <h1>Sky Bridge Jet</h1>
        <p className="positioning">Premium Private Aviation Marketplace</p>
        <p className="summary">
          Sign in to review your trip requests, bookings, and account.
        </p>
        <p className="landing__cta">
          <Link href="/portal" className="button button--primary">
            Enter the portal
          </Link>
        </p>
      </main>
    </div>
  );
}
