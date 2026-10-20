// Map layers: which stored grid each one shows and how it is coloured.
// Shared by the API route (server) and the map (client); holds no secrets.

export type Cadence = "daily" | "8-day" | "16-day" | "monthly" | "static";

export type Layer = {
  id: string;
  variable: string; // eo_grids.variable
  source: string; // data_sources.key
  fallback?: string; // used for dates the primary source lacks
  unit: string;
  cadence: Cadence;
  kind: "sequential" | "diverging";
  // Fixed value range so colours mean the same thing on every date; null = from data.
  domain: [number, number] | null;
  ramp: string[]; // light -> dark for sequential; low -> neutral -> high for diverging
  digits: number;
};

// Single-hue ramps (light -> dark) so colour reads as "more"; one hue per layer.
const BLUES = ["#dbeafe", "#93c5fd", "#60a5fa", "#3b82f6", "#1d4ed8", "#1e3a8a"];
const GREENS = ["#ecfccb", "#bef264", "#84cc16", "#4d7c0f", "#365314", "#1a2e05"];
const TEALS = ["#ccfbf1", "#5eead4", "#14b8a6", "#0f766e", "#134e4a", "#042f2e"];
const PURPLES = ["#ede9fe", "#c4b5fd", "#a78bfa", "#7c3aed", "#5b21b6", "#2e1065"];
const ORANGES = ["#ffedd5", "#fdba74", "#fb923c", "#ea580c", "#9a3412", "#431407"];
const CYANS = ["#cffafe", "#67e8f9", "#22d3ee", "#0891b2", "#155e75", "#083344"];
const GRAYS = ["#f5f5f4", "#d6d3d1", "#a8a29e", "#78716c", "#44403c", "#1c1917"];
// Diverging: dry brown -> neutral gray -> wet blue.
const DRY_WET = ["#9a3412", "#d9a066", "#e5e7eb", "#7fb3e0", "#1d4ed8"];

export const LAYERS: Layer[] = [
  { id: "rainfall", variable: "precipitation", source: "gpm_imerg", fallback: "chirps3", unit: "mm/day",
    cadence: "daily", kind: "sequential", domain: [0, 25], ramp: BLUES, digits: 1 },
  { id: "vegetation", variable: "ndvi", source: "modis_ndvi", unit: "NDVI",
    cadence: "16-day", kind: "sequential", domain: [0.1, 0.8], ramp: GREENS, digits: 2 },
  { id: "soil_moisture", variable: "soil_moisture_rootzone", source: "gldas_clsm", unit: "kg/m²",
    cadence: "daily", kind: "sequential", domain: [100, 450], ramp: TEALS, digits: 0 },
  { id: "groundwater", variable: "groundwater_storage", source: "gldas_clsm", unit: "mm",
    cadence: "daily", kind: "sequential", domain: null, ramp: PURPLES, digits: 0 },
  { id: "surface_temperature", variable: "surface_temperature", source: "gldas_clsm", unit: "°C",
    cadence: "daily", kind: "sequential", domain: [20, 45], ramp: ORANGES, digits: 1 },
  { id: "evapotranspiration", variable: "evapotranspiration", source: "modis_et", unit: "mm / 8 days",
    cadence: "8-day", kind: "sequential", domain: [0, 40], ramp: CYANS, digits: 1 },
  { id: "water_anomaly", variable: "water_storage_anomaly", source: "grace_mascon", unit: "cm",
    cadence: "monthly", kind: "diverging", domain: [-25, 25], ramp: DRY_WET, digits: 1 },
  { id: "elevation", variable: "elevation", source: "aster_dem", unit: "m",
    cadence: "static", kind: "sequential", domain: [300, 1500], ramp: GRAYS, digits: 0 },
];

export type Grid = {
  nx: number;
  ny: number;
  west: number;
  south: number;
  dx: number;
  dy: number;
  values: (number | null)[]; // row-major, first row is the northern edge
};

export type GridResponse = {
  layer: string;
  dates: string[]; // ascending
  date: string;
  period_end: string | null;
  source: string;
  usedFallback: boolean;
  unit: string;
  grid: Grid;
  domain: [number, number];
};

function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

/** Colour for a value: piecewise-linear between ramp stops. */
export function colorFor(value: number, domain: [number, number], ramp: string[]): [number, number, number] {
  const [lo, hi] = domain;
  const t = Math.min(1, Math.max(0, (value - lo) / (hi - lo || 1)));
  const pos = t * (ramp.length - 1);
  const i = Math.min(ramp.length - 2, Math.floor(pos));
  const f = pos - i;
  const a = hexToRgb(ramp[i]);
  const b = hexToRgb(ramp[i + 1]);
  return [Math.round(a[0] + (b[0] - a[0]) * f), Math.round(a[1] + (b[1] - a[1]) * f), Math.round(a[2] + (b[2] - a[2]) * f)];
}

/** 2nd–98th percentile of the grid, used when a layer has no fixed domain. */
export function dataDomain(values: (number | null)[]): [number, number] {
  const v = values.filter((x): x is number => x !== null).sort((a, b) => a - b);
  if (v.length < 2) return [0, 1];
  const lo = v[Math.floor(v.length * 0.02)];
  const hi = v[Math.min(v.length - 1, Math.ceil(v.length * 0.98))];
  return lo === hi ? [lo - 1, hi + 1] : [lo, hi];
}
