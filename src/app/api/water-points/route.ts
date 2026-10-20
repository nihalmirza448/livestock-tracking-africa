import { NextResponse } from "next/server";
import { AREA_ID, isConfigured } from "@/lib/data";
import { createPublicClient } from "@/lib/supabase/public";

export const dynamic = "force-dynamic";

type Obs = { water_point_id: string; obs_date: string; water_fraction: number | null };

/** Water points with their latest Sentinel-2 water fraction and recent history. */
export async function GET() {
  if (!isConfigured) return NextResponse.json([], { status: 503 });
  const sb = createPublicClient();
  const [points, obs] = await Promise.all([
    sb.from("water_points_ll").select("id, name, name_ar, kind, source, lon, lat").eq("area_id", AREA_ID),
    sb.from("water_point_observations").select("water_point_id, obs_date, water_fraction")
      .eq("source_key", "s2_water").order("obs_date", { ascending: false }).limit(5000),
  ]);
  if (points.error) return NextResponse.json({ error: points.error.message }, { status: 500 });
  const history = new Map<string, Obs[]>();
  for (const o of (obs.data ?? []) as Obs[]) {
    const list = history.get(o.water_point_id) ?? [];
    if (list.length < 12) list.push(o);
    history.set(o.water_point_id, list);
  }
  const body = (points.data ?? []).map((p) => {
    const h = history.get(p.id) ?? [];
    const latest = h.find((o) => o.water_fraction !== null) ?? h[0] ?? null;
    return { ...p, latest, history: h.map(({ obs_date, water_fraction }) => ({ obs_date, water_fraction })) };
  });
  return NextResponse.json(body, { headers: { "Cache-Control": "public, s-maxage=600, stale-while-revalidate=3600" } });
}
