import type { Metadata } from "next";
import Link from "next/link";

import "./globals.css";

export const metadata: Metadata = {
  title: "Sky Bridge Jet",
  description: "Premium Private Aviation Marketplace",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en">
      <body>
        <header className="site-header">
          <nav aria-label="Primary navigation" className="navigation">
            <Link href="/" className="brand">
              Sky Bridge Jet
            </Link>
            <span className="foundation-label">Engineering foundation</span>
          </nav>
        </header>
        {children}
      </body>
    </html>
  );
}
