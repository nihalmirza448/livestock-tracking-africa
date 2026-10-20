import { NotConfigured } from "@/components/NotConfigured";
import { AREA_ID, isConfigured } from "@/lib/data";
import { isLocale, t, type Messages } from "@/lib/i18n";
import { createPublicClient } from "@/lib/supabase/public";

export const revalidate = 300;

type Flow = { monitoring_point_id: string; name: string; code: string | null; species: string; week: string;
  head_count: number; submissions: number };
type Check = { obs_date: string; lon: number; lat: number; pasture_condition: number | null;
  water_condition: number | null; route_condition: string | null };

const SPECIES = ["cattle", "sheep", "goats", "camels", "other"] as const;

export default async function Field({ params }: { params: Promise<{ lang: string }> }) {
  const { lang } = await params;
  if (!isLocale(lang)) return null;
  const m = t(lang);
  if (!isConfigured) return <NotConfigured />;
  const sb = createPublicClient();
  const since = new Date(Date.now() - 28 * 86_400_000).toISOString().slice(0, 10);
  const [flows, checks] = await Promise.all([
    sb.from("flow_summary").select("*").gte("week", since).order("week", { ascending: false }),
    sb.from("field_check_summary").select("*").eq("area_id", AREA_ID).order("obs_date", { ascending: false }).limit(30),
  ]);
  const rows = (flows.data ?? []) as Flow[];
  const byPoint = new Map<string, { name: string; weeks: Map<string, Record<string, number>> }>();
  for (const r of rows) {
    const p = byPoint.get(r.monitoring_point_id) ?? { name: r.name, weeks: new Map() };
    const w = p.weeks.get(r.week) ?? {};
    w[r.species] = (w[r.species] ?? 0) + r.head_count;
    w.__n = (w.__n ?? 0) + r.submissions;
    p.weeks.set(r.week, w);
    byPoint.set(r.monitoring_point_id, p);
  }
  const fmt = new Intl.NumberFormat(lang === "ar" ? "ar-SD" : "en");

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">{m.fieldTitle}</h1>
        <p className="text-sm text-subtle mt-1 max-w-3xl">{m.fieldIntro}</p>
      </div>

      {byPoint.size === 0 ? (
        <p className="rounded-lg border border-line bg-card p-4 text-sm text-subtle">{m.noFieldData}</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-line bg-card">
          <table className="w-full text-sm">
            <thead className="bg-muted text-xs text-subtle">
              <tr>
                <th className="p-2 text-start">{m.monitoringPoint}</th>
                <th className="p-2 text-start">{m.week}</th>
                {SPECIES.map((s) => <th key={s} className="p-2 text-end">{m[s as keyof Messages]}</th>)}
                <th className="p-2 text-end">{m.submissions}</th>
              </tr>
            </thead>
            <tbody>
              {[...byPoint.entries()].flatMap(([id, p]) =>
                [...p.weeks.entries()].sort(([a], [b]) => (a < b ? 1 : -1)).map(([week, w]) => (
                  <tr key={id + week} className="border-t border-line">
                    <td className="p-2">{p.name}</td>
                    <td className="p-2 tabular-nums">{week}</td>
                    {SPECIES.map((s) => <td key={s} className="p-2 text-end tabular-nums">{w[s] ? fmt.format(w[s]) : "—"}</td>)}
                    <td className="p-2 text-end tabular-nums">{fmt.format(w.__n ?? 0)}</td>
                  </tr>
                )),
              )}
            </tbody>
          </table>
        </div>
      )}

      <section className="space-y-2">
        <h2 className="text-lg font-medium">{m.fieldChecks}</h2>
        {(checks.data ?? []).length === 0 ? (
          <p className="text-sm text-subtle">—</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-line bg-card">
            <table className="w-full text-sm">
              <thead className="bg-muted text-xs text-subtle">
                <tr>
                  <th className="p-2 text-start">{m.date}</th>
                  <th className="p-2 text-start">lat / lon</th>
                  <th className="p-2 text-end">{m.pasture} (1–5)</th>
                  <th className="p-2 text-end">{m.water} (1–5)</th>
                  <th className="p-2 text-start">{m.route}</th>
                </tr>
              </thead>
              <tbody>
                {((checks.data ?? []) as Check[]).map((c, i) => (
                  <tr key={i} className="border-t border-line">
                    <td className="p-2 tabular-nums">{c.obs_date}</td>
                    <td className="p-2 tabular-nums" dir="ltr">{c.lat.toFixed(2)}, {c.lon.toFixed(2)}</td>
                    <td className="p-2 text-end">{c.pasture_condition ?? "—"}</td>
                    <td className="p-2 text-end">{c.water_condition ?? "—"}</td>
                    <td className="p-2">{c.route_condition ? m[c.route_condition as keyof Messages] : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
