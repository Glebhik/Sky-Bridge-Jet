import Link from "next/link";

export default function NotFound() {
  return (
    <main className="status-page">
      <h1>Page not found</h1>
      <p>The page you requested is not available.</p>
      <Link href="/">Return home</Link>
    </main>
  );
}
