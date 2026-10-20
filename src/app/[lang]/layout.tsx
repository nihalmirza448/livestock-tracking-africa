import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { isLocale, locales, t } from "@/lib/i18n";
import "../globals.css";

export const metadata: Metadata = {
  title: "SLEWCIS",
  description: "Sudan Livestock Early Warning and Climate Intelligence System, Phase 1 prototype",
};

export function generateStaticParams() {
  return locales.map((lang) => ({ lang }));
}

export default async function RootLayout({
  children,
  params,
}: Readonly<{ children: React.ReactNode; params: Promise<{ lang: string }> }>) {
  const { lang } = await params;
  if (!isLocale(lang)) notFound();
  const m = t(lang);
  const other = lang === "ar" ? "en" : "ar";
  return (
    <html lang={lang} dir={lang === "ar" ? "rtl" : "ltr"}>
      <body className="antialiased min-h-screen">
        <header className="border-b border-line">
          <div className="mx-auto max-w-6xl px-4 py-3 flex flex-wrap items-center gap-x-6 gap-y-2">
            <div>
              <div className="font-semibold">{m.appName}</div>
              <div className="text-xs text-subtle">{m.tagline}</div>
            </div>
            <nav className="flex gap-4 text-sm">
              <Link href={`/${lang}`} className="hover:underline">{m.overview}</Link>
              <Link href={`/${lang}/sources`} className="hover:underline">{m.sources}</Link>
            </nav>
            <Link href={`/${other}`} className="ms-auto text-sm rounded border border-line px-2 py-1 hover:bg-muted">
              {m.switchLang}
            </Link>
          </div>
        </header>
        <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
      </body>
    </html>
  );
}
