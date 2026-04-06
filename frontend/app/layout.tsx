import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "WCAG 2.1 Accessibility Tester",
  description: "Automated WCAG 2.1 Level AA compliance testing using MolmoWeb",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className="h-full">
      <body className="min-h-full flex flex-col bg-slate-50 text-slate-900 antialiased">
        <header className="bg-white border-b border-slate-200 px-6 py-4 flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center text-white font-bold text-sm">
            A11Y
          </div>
          <div>
            <h1 className="font-semibold text-slate-900 leading-none">WCAG 2.1 Tester</h1>
            <p className="text-xs text-slate-500 mt-0.5">Level AA Compliance — Powered by MolmoWeb</p>
          </div>
        </header>
        <main className="flex-1 flex flex-col">{children}</main>
      </body>
    </html>
  );
}
