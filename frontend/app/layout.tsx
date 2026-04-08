import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PointCheck",
  description: "Automated WCAG 2.1 Level AA accessibility testing powered by OLMo2 and Molmo2",
  icons: {
    icon: "/logo.svg",
    shortcut: "/logo.svg",
    apple: "/logo.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className="h-full">
      <body className="min-h-full flex flex-col antialiased" style={{ background: "var(--bg)", color: "var(--text)" }}>
        <header style={{ background: "var(--surface)", borderBottom: "1px solid var(--border)" }}
          className="px-6 py-4 flex items-center gap-3">
          <img
            src="/logo.svg"
            alt="PointCheck"
            className="w-10 h-10"
            style={{ display: "block" }}
          />
          <div>
            <h1 className="font-semibold leading-none tracking-tight" style={{ color: "var(--text)" }}>
              PointCheck
            </h1>
            <p className="text-xs mt-0.5" style={{ color: "var(--muted)" }}>
              WCAG 2.1 Level AA — Powered by OLMo2 &amp; Molmo2
            </p>
          </div>
        </header>
        <main className="flex-1 flex flex-col">{children}</main>
      </body>
    </html>
  );
}
