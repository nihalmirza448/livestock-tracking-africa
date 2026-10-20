import { NextResponse } from "next/server";
import { AREA_ID, isConfigured } from "@/lib/data";
import { createPublicClient } from "@/lib/supabase/public";

export const dynamic = "force-dynamic";

type Obs = { water_point_id: string; obs_date: string; water_fraction: number | null };

/** Water points with their latest Sentinel-2 water fraction and recent history. */
export async function GET() {
  if (!isConfigured) return NextResponse.json([], { status: 503 });
  const sb = createPublicClient();
  // PostgREST caps a request at 1,000 rows; page through both tables.
  const all = async <T,>(build: (from: number, to: number) => PromiseLike<{ data: T[] | null; error: { message: string } | null }>) => {
    const out: T[] = [];
    for (let from = 0; ; from += 1000) {
      const { data, error } = await build(from, from + 999);
      if (error) throw new Error(error.message);
      out.push(...(data ?? []));
      if (!data || data.length < 1000) return out;
    }
  };
  let points: { id: string; name: string | null; name_ar: string | null; kind: string; source: string | null; lon: number; lat: number }[];
  let obsRows: Obs[];
  try {
    [points, obsRows] = await Promise.all([
      all((a, b) => sb.from("water_points_ll").select("id, name, name_ar, kind, source, lon, lat").eq("area_id", AREA_ID).order("id").range(a, b)),
      all<Obs>((a, b) => sb.from("water_point_observations").select("water_point_id, obs_date, water_fraction")
        .eq("source_key", "s2_water").order("obs_date", { ascending: false }).order("water_point_id").range(a, b)),
    ]);
  } catch (e) {
    return NextResponse.json({ error: (e as Error).message }, { status: 500 });
  }
  const history = new Map<string, Obs[]>();
  for (const o of obsRows) {
    const list = history.get(o.water_point_id) ?? [];
    if (list.length < 12) list.push(o);
    history.set(o.water_point_id, list);
  }
  const body = points.map((p) => {
    const h = history.get(p.id) ?? [];
    const latest = h.find((o) => o.water_fraction !== null) ?? h[0] ?? null;
    return { ...p, latest, history: h.map(({ obs_date, water_fraction }) => ({ obs_date, water_fraction })) };
  });
  return NextResponse.json(body, { headers: { "Cache-Control": "public, s-maxage=600, stale-while-revalidate=3600" } });
}
