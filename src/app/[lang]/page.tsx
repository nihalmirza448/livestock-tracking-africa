import { AreaMapLoader } from "@/components/AreaMapLoader";
import { Sparkline } from "@/components/Sparkline";
import { INDICATORS, ageDays, getArea, getSeries, getSources, type Indicator } from "@/lib/data";
import { isLocale, t, type Locale, type Messages } from "@/lib/i18n";

export const revalidate = 1800;

type Sources = Awaited<ReturnType<typeof getSources>>;

async function loadIndicator(ind: Indicator) {
  const primary = await getSeries(ind.source, ind.variable);
  const last = primary.at(-1);
  if (ind.fallback && (!last || ageDays(last.obs_date) > ind.maxAgeDays)) {
    const fb = await getSeries(ind.fallback, ind.variable);
    const fbLast = fb.at(-1);
    if (fbLast && (!last || fbLast.obs_date > last.obs_date)) {
      return { ind, series: fb, sourceKey: ind.fallback, usedFallback: true };
    }
  }
  return { ind, series: primary, sourceKey: ind.source, usedFallback: false };
}

export default async function Overview({ params }: { params: Promise<{ lang: string }> }) {
  const { lang } = await params;
  if (!isLocale(lang)) return null;
  const m = t(lang);
  const [area, sources, cards] = await Promise.all([getArea(), getSources(), Promise.all(INDICATORS.map(loadIndicator))]);

  return (
    <div className="space-y-6">
      <section className="grid gap-4 md:grid-cols-3">
        <div className="md:col-span-1">
          <div className="text-xs text-subtle">{m.pilotArea}</div>
          <h1 className="text-2xl font-semibold">{lang === "ar" ? area.name_ar : area.name_en}</h1>
          <p className="mt-2 text-sm text-subtle">{m.boundaryNote}</p>
        </div>
        <div className="md:col-span-2">
          <AreaMapLoader area={area} />
        </div>
      </section>

      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {cards.map((c) => (
          <IndicatorCard key={c.ind.variable} card={c} sources={sources} m={m} lang={lang} />
        ))}
      </section>
    </div>
  );
}

function IndicatorCard({
  card,
  sources,
  m,
  lang,
}: {
  card: Awaited<ReturnType<typeof loadIndicator>>;
  sources: Sources;
  m: Messages;
  lang: Locale;
}) {
  const { ind, series, sourceKey, usedFallback } = card;
  const source = sources.find((s) => s.key === sourceKey);
  const last = series.filter((o) => o.value !== null).at(-1);
  const label = m[ind.variable as keyof Messages] ?? ind.variable;
  const stale = last ? ageDays(last.obs_date) > ind.maxAgeDays : false;
  const fmt = new Intl.NumberFormat(lang === "ar" ? "ar-SD" : "en", { maximumFractionDigits: ind.digits });

  return (
    <article className="rounded-lg border border-line bg-card p-4 flex flex-col gap-2">
      <h2 className="text-sm font-medium">{label}</h2>
      {last ? (
        <>
          <div className="text-3xl font-semibold tabular-nums">
            {fmt.format(last.value!)} <span className="text-sm font-normal text-subtle">{last.unit}</span>
          </div>
          <div className={`text-xs ${stale ? "text-warn" : "text-subtle"}`}>
            {stale ? m.lastValid : m.latest}: {last.obs_date}
          </div>
          <Sparkline series={series} label={m.trend} />
        </>
      ) : (
        <p className="text-sm text-subtle">{m.noData}</p>
      )}
      <dl className="mt-auto pt-2 border-t border-line text-xs text-subtle space-y-1">
        {usedFallback && <div className="text-warn">{m.fallbackUsed} {source?.name}</div>}
        <div>
          <dt className="inline">{m.source}: </dt>
          <dd className="inline">
            {source ? <a href={source.url} className="underline">{source.name}</a> : sourceKey}
          </dd>
        </div>
        <div>
          <dt className="inline">{m.validation}: </dt>
          <dd className="inline">{m[(source?.validation_status ?? "unvalidated") as keyof Messages]}</dd>
        </div>
      </dl>
    </article>
  );
}
