import { getSources } from "@/lib/data";
import { isLocale, t } from "@/lib/i18n";

export const revalidate = 600;

const statusColor: Record<string, string> = {
  success: "text-green-700 dark:text-green-400",
  partial: "text-warn",
  failed: "text-red-700 dark:text-red-400",
};

export default async function Sources({ params }: { params: Promise<{ lang: string }> }) {
  const { lang } = await params;
  if (!isLocale(lang)) return null;
  const m = t(lang);
  const sources = await getSources();

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">{m.sources}</h1>
      <div className="overflow-x-auto rounded-lg border border-line bg-card">
        <table className="w-full text-sm">
          <thead className="bg-muted text-start text-xs text-subtle">
            <tr>
              <th className="p-2 text-start">{m.source}</th>
              <th className="p-2 text-start">{m.role}</th>
              <th className="p-2 text-start">{m.cadence}</th>
              <th className="p-2 text-start">{m.lastObs}</th>
              <th className="p-2 text-start">{m.lastRun}</th>
              <th className="p-2 text-start">{m.validation}</th>
            </tr>
          </thead>
          <tbody>
            {sources.map((s) => (
              <tr key={s.key} className="border-t border-line align-top">
                <td className="p-2">
                  <a href={s.url} className="font-medium underline">{s.name}</a>
                  <div className="text-xs text-subtle" dir="ltr">
                    {s.product} {s.product_version} · {s.spatial_resolution} · {s.period}
                  </div>
                  {s.notes && <div className="text-xs text-subtle mt-1">{s.notes}</div>}
                </td>
                <td className="p-2">{s.enabled ? s.role : m.disabled}</td>
                <td className="p-2">{s.cadence}</td>
                <td className="p-2 tabular-nums">{s.status?.last_obs_date ?? "—"}</td>
                <td className="p-2">
                  {s.status?.last_run_status ? (
                    <span className={statusColor[s.status.last_run_status] ?? ""} title={s.status.last_run_error ?? ""}>
                      {s.status.last_run_status}
                    </span>
                  ) : (
                    <span className="text-subtle">{m.never}</span>
                  )}
                  {s.status?.last_run_at && (
                    <div className="text-xs text-subtle tabular-nums">{s.status.last_run_at.slice(0, 16).replace("T", " ")}</div>
                  )}
                </td>
                <td className="p-2">{m[s.validation_status as keyof typeof m]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
