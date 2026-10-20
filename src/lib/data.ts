import { supabaseKey, supabaseUrl } from "@/lib/supabase/env";
import { createPublicClient } from "@/lib/supabase/public";

export const AREA_ID = "south_kordofan";

export type Indicator = {
  variable: string;
  source: string;
  fallback?: string;
  maxAgeDays: number; // older than this and the fallback is shown
  digits: number;
};

// What the conditions view shows, in order. Sources are keys in data_sources.
export const INDICATORS: Indicator[] = [
  { variable: "precipitation", source: "gpm_imerg", fallback: "chirps3", maxAgeDays: 3, digits: 1 },
  { variable: "ndvi", source: "modis_ndvi", maxAgeDays: 40, digits: 3 },
  { variable: "soil_moisture_rootzone", source: "gldas_clsm", maxAgeDays: 120, digits: 0 },
  { variable: "groundwater_storage", source: "gldas_clsm", maxAgeDays: 120, digits: 0 },
  { variable: "water_storage_anomaly", source: "grace_mascon", maxAgeDays: 150, digits: 1 },
  { variable: "evapotranspiration", source: "modis_et", maxAgeDays: 30, digits: 1 },
  { variable: "air_temperature", source: "gldas_clsm", maxAgeDays: 120, digits: 1 },
];

export type Obs = { obs_date: string; value: number | null; unit: string };

export type SourceRow = {
  key: string;
  name: string;
  variable: string;
  provider: string;
  product: string;
  product_version: string | null;
  spatial_resolution: string | null;
  cadence: string;
  period: string | null;
  url: string;
  role: string;
  enabled: boolean;
  validation_status: string;
  notes: string | null;
};

export type StatusRow = {
  key: string;
  last_obs_date: string | null;
  last_run_status: string | null;
  last_run_at: string | null;
  last_run_error: string | null;
};

export type PilotArea = {
  id: string;
  name_en: string;
  name_ar: string;
  min_lon: number;
  min_lat: number;
  max_lon: number;
  max_lat: number;
};

const supabase = () => createPublicClient();

// False when the Supabase env vars are missing, e.g. not set for this Vercel environment.
export const isConfigured = Boolean(supabaseUrl && supabaseKey);

export async function getSeries(source: string, variable: string): Promise<Obs[]> {
  const { data, error } = await supabase()
    .from("eo_observations")
    .select("obs_date, value, unit")
    .eq("area_id", AREA_ID)
    .eq("source_key", source)
    .eq("variable", variable)
    .eq("stat", "mean")
    .order("obs_date", { ascending: false })
    .limit(90);
  if (error) throw error;
  return (data ?? []).reverse();
}

export async function getSources() {
  const [sources, status] = await Promise.all([
    supabase().from("data_sources").select("*").order("role").order("key"),
    supabase().from("source_status").select("key, last_obs_date, last_run_status, last_run_at, last_run_error"),
  ]);
  if (sources.error) throw sources.error;
  if (status.error) throw status.error;
  const byKey = new Map((status.data as StatusRow[]).map((s) => [s.key, s]));
  return (sources.data as SourceRow[]).map((s) => ({ ...s, status: byKey.get(s.key) }));
}

export async function getArea(): Promise<PilotArea> {
  const { data, error } = await supabase()
    .from("pilot_areas")
    .select("id, name_en, name_ar, min_lon, min_lat, max_lon, max_lat")
    .eq("id", AREA_ID)
    .single();
  if (error) throw error;
  return data;
}

export function ageDays(isoDate: string) {
  return (Date.now() - new Date(isoDate + "T00:00:00Z").getTime()) / 86_400_000;
}
