import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PointCheck",
  description: "Automated WCAG 2.1 Level AA accessibility testing powered by OLMo2 and Molmo2",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className="h-full">
      <body className="min-h-full flex flex-col bg-slate-50 text-slate-900 antialiased">
        <header className="bg-white border-b border-slate-200 px-6 py-4 flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center text-white font-bold text-sm">
            PC
          </div>
          <div>
            <h1 className="font-semibold text-slate-900 leading-none">PointCheck</h1>
            <p className="text-xs text-slate-500 mt-0.5">WCAG 2.1 Level AA — Powered by OLMo2 &amp; Molmo2</p>
          </div>
        </header>
        <main className="flex-1 flex flex-col">{children}</main>
      </body>
    </html>
  );
}
