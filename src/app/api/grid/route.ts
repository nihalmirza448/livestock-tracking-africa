import { NextRequest, NextResponse } from "next/server";
import { AREA_ID, isConfigured } from "@/lib/data";
import { LAYERS, dataDomain, type GridResponse } from "@/lib/layers";
import { createPublicClient } from "@/lib/supabase/public";

export const dynamic = "force-dynamic";

const CACHE = { "Cache-Control": "public, s-maxage=600, stale-while-revalidate=3600" };

export async function GET(req: NextRequest) {
  const params = req.nextUrl.searchParams;
  const layer = LAYERS.find((l) => l.id === params.get("layer"));
  if (!layer) return NextResponse.json({ error: "unknown layer" }, { status: 404 });
  if (!isConfigured) return NextResponse.json({ error: "Supabase not configured" }, { status: 503 });

  const sb = createPublicClient();
  const datesFor = async (source: string) => {
    const { data, error } = await sb
      .from("eo_grids")
      .select("obs_date")
      .eq("area_id", AREA_ID)
      .eq("source_key", source)
      .eq("variable", layer.variable)
      .order("obs_date", { ascending: false })
      .limit(400);
    if (error) throw error;
    return (data ?? []).map((r) => r.obs_date as string);
  };

  const primary = new Set(await datesFor(layer.source));
  const fallback = new Set(layer.fallback ? await datesFor(layer.fallback) : []);
  const dates = [...new Set([...primary, ...fallback])].sort();
  if (!dates.length) return NextResponse.json({ error: "no grids yet" }, { status: 404, headers: CACHE });

  const requested = params.get("date");
  const date = requested && dates.includes(requested) ? requested : dates[dates.length - 1];
  const source = primary.has(date) ? layer.source : layer.fallback!;

  const { data, error } = await sb
    .from("eo_grids")
    .select("nx, ny, west, south, dx, dy, values, unit, period_end")
    .eq("area_id", AREA_ID)
    .eq("source_key", source)
    .eq("variable", layer.variable)
    .eq("obs_date", date)
    .single();
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  const grid = { nx: data.nx, ny: data.ny, west: data.west, south: data.south, dx: data.dx, dy: data.dy,
    values: data.values as (number | null)[] };
  const body: GridResponse = {
    layer: layer.id,
    dates,
    date,
    period_end: data.period_end,
    source,
    usedFallback: source !== layer.source,
    unit: layer.unit || data.unit,
    grid,
    domain: layer.domain ?? dataDomain(grid.values),
  };
  return NextResponse.json(body, { headers: CACHE });
}
