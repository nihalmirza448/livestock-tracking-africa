"use client";

import "leaflet/dist/leaflet.css";
import { useEffect, useMemo, useState } from "react";
import { GeoJSON, ImageOverlay, MapContainer, Rectangle, TileLayer, useMapEvents } from "react-leaflet";
import type { LatLngBoundsExpression, LeafletMouseEvent } from "leaflet";
import type { Feature } from "geojson";
import type { PilotArea } from "@/lib/data";
import type { Locale, Messages } from "@/lib/i18n";
import { LAYERS, colorFor, type GridResponse, type Layer } from "@/lib/layers";

type Props = { area: PilotArea; lang: Locale; m: Messages; sourceNames: Record<string, string> };

const PX = 4; // image pixels per cell edge

const merc = (lat: number) => Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360));
const invMerc = (y: number) => ((2 * Math.atan(Math.exp(y)) - Math.PI / 2) * 180) / Math.PI;

/** Draw the grid to an image in Web Mercator so cells land exactly under the base map. */
function render(res: GridResponse, layer: Layer): { url: string; bounds: LatLngBoundsExpression } {
  const { nx, ny, west, south, dx, dy, values } = res.grid;
  const north = south + ny * dy;
  const east = west + nx * dx;
  const w = nx * PX;
  const h = Math.max(ny * PX, 64);
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d")!;
  const img = ctx.createImageData(w, h);
  const yN = merc(north);
  const yS = merc(south);
  for (let j = 0; j < h; j++) {
    const lat = invMerc(yN + ((j + 0.5) / h) * (yS - yN));
    const row = Math.min(ny - 1, Math.max(0, Math.floor((north - lat) / dy)));
    for (let i = 0; i < w; i++) {
      const col = Math.min(nx - 1, Math.floor(i / PX));
      const v = values[row * nx + col];
      const o = (j * w + i) * 4;
      if (v === null || v === undefined) {
        img.data[o + 3] = 0;
        continue;
      }
      const [r, g, b] = colorFor(v, res.domain, layer.ramp);
      img.data[o] = r;
      img.data[o + 1] = g;
      img.data[o + 2] = b;
      img.data[o + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
  return { url: canvas.toDataURL(), bounds: [[south, west], [north, east]] };
}

function cellValue(res: GridResponse, lat: number, lng: number): number | null | undefined {
  const { nx, ny, west, south, dx, dy, values } = res.grid;
  const col = Math.floor((lng - west) / dx);
  const row = Math.floor((south + ny * dy - lat) / dy);
  if (col < 0 || col >= nx || row < 0 || row >= ny) return undefined;
  return values[row * nx + col];
}

function Probe({ onMove, onClick }: { onMove: (e: LeafletMouseEvent) => void; onClick: (e: LeafletMouseEvent) => void }) {
  useMapEvents({ mousemove: onMove, click: onClick, mouseout: () => onMove(null as unknown as LeafletMouseEvent) });
  return null;
}

export default function IndicatorMap({ area, lang, m, sourceNames }: Props) {
  const [layerId, setLayerId] = useState(LAYERS[0].id);
  const [date, setDate] = useState<string | null>(null);
  const [res, setRes] = useState<GridResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [opacity, setOpacity] = useState(0.75);
  const [probe, setProbe] = useState<{ lat: number; lng: number; v: number | null | undefined } | null>(null);
  const layer = LAYERS.find((l) => l.id === layerId)!;

  useEffect(() => {
    let live = true;
    setLoading(true);
    setError(null);
    const q = new URLSearchParams({ layer: layerId, ...(date ? { date } : {}) });
    fetch(`/api/grid?${q}`)
      .then(async (r) => (r.ok ? r.json() : Promise.reject((await r.json()).error ?? r.statusText)))
      .then((d: GridResponse) => { if (live) { setRes(d); setDate(d.date); } })
      .catch((e) => { if (live) { setRes(null); setError(String(e)); } })
      .finally(() => live && setLoading(false));
    return () => { live = false; };
  }, [layerId, date]);

  const image = useMemo(() => (res ? render(res, layer) : null), [res, layer]);
  const fmt = new Intl.NumberFormat(lang === "ar" ? "ar-SD" : "en", { maximumFractionDigits: layer.digits });
  const dates = res?.dates ?? [];
  const idx = res ? dates.indexOf(res.date) : -1;
  const daysBehind = res ? Math.floor((Date.now() - new Date(dates[dates.length - 1] + "T00:00:00Z").getTime()) / 86_400_000) : null;
  const bbox: LatLngBoundsExpression = [[area.min_lat, area.min_lon], [area.max_lat, area.max_lon]];
  const boundary = area.boundary_geojson as Feature | null;
  const cadenceKey = `cadence_${layer.cadence.replace("-", "")}` as keyof Messages;

  const onMove = (e: LeafletMouseEvent | null) => {
    if (!e || !res) return setProbe(null);
    setProbe({ lat: e.latlng.lat, lng: e.latlng.lng, v: cellValue(res, e.latlng.lat, e.latlng.lng) });
  };

  return (
    <div className="rounded-lg border border-line bg-card overflow-hidden">
      <div className="flex flex-wrap gap-1 p-2 border-b border-line" role="tablist" aria-label={m.mapLayers}>
        {LAYERS.map((l) => (
          <button
            key={l.id}
            role="tab"
            aria-selected={l.id === layerId}
            onClick={() => { setLayerId(l.id); setDate(null); }}
            className={`text-xs rounded-full px-3 py-1 border ${l.id === layerId ? "bg-foreground text-background border-foreground" : "border-line hover:bg-muted"}`}
          >
            <span className="inline-block w-2 h-2 rounded-full me-1 align-middle" style={{ background: l.ramp[Math.floor(l.ramp.length * 0.7)] }} />
            {m[l.variable as keyof Messages] ?? l.variable}
          </button>
        ))}
      </div>

      <div className="relative">
        <MapContainer bounds={bbox} boundsOptions={{ padding: [16, 16] }} scrollWheelZoom={false} className="h-[28rem] w-full">
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          {image && <ImageOverlay url={image.url} bounds={image.bounds} opacity={opacity} className="pixelated" />}
          {boundary ? (
            <GeoJSON data={boundary} style={{ color: "#1c1917", weight: 2, fill: false, dashArray: undefined }} />
          ) : (
            <Rectangle bounds={bbox} pathOptions={{ color: "#1c1917", weight: 1.5, fill: false, dashArray: "6 4" }} />
          )}
          <Probe onMove={onMove} onClick={onMove} />
        </MapContainer>
        {(loading || error) && (
          <div className="absolute inset-x-0 top-0 z-[500] p-2 text-xs text-center bg-card/90">
            {loading ? "…" : error === "no grids yet" ? m.noData : error}
          </div>
        )}
        <div className="absolute bottom-2 start-2 z-[500] rounded bg-card/95 border border-line px-2 py-1 text-xs min-w-[11rem]">
          {probe ? (
            <>
              <div className="font-medium tabular-nums">
                {probe.v === null || probe.v === undefined ? m.noDataCell : `${fmt.format(probe.v)} ${res?.unit ?? ""}`}
              </div>
              <div className="text-subtle tabular-nums" dir="ltr">{probe.lat.toFixed(2)}°N {probe.lng.toFixed(2)}°E</div>
            </>
          ) : (
            <span className="text-subtle">{m.hoverHint}</span>
          )}
        </div>
      </div>

      <div className="p-3 grid gap-3 md:grid-cols-[1fr_auto] items-start text-xs">
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <button className="rounded border border-line px-2 py-0.5 disabled:opacity-40" disabled={idx <= 0}
              onClick={() => setDate(dates[idx - 1])} aria-label={m.previous}>{lang === "ar" ? "›" : "‹"}</button>
            <input type="range" min={0} max={Math.max(0, dates.length - 1)} value={Math.max(0, idx)}
              onChange={(e) => setDate(dates[Number(e.target.value)])} className="flex-1 accent-accent" aria-label={m.date} />
            <button className="rounded border border-line px-2 py-0.5 disabled:opacity-40" disabled={idx < 0 || idx >= dates.length - 1}
              onClick={() => setDate(dates[idx + 1])} aria-label={m.next}>{lang === "ar" ? "‹" : "›"}</button>
            <span className="tabular-nums font-medium min-w-[6.5rem] text-end">
              {res?.date ?? "—"}{res?.period_end ? ` → ${res.period_end}` : ""}
            </span>
          </div>
          <div className="text-subtle">
            {m[cadenceKey]}
            {daysBehind !== null && layer.cadence !== "static" && ` · ${m.latest}: ${dates[dates.length - 1]} (${m.daysBehind.replace("{n}", String(daysBehind))})`}
            {res && (
              <>
                {" · "}{m.source}: {sourceNames[res.source] ?? res.source}
                {res.usedFallback && <span className="text-warn"> ({m.fallbackShort})</span>}
              </>
            )}
            {dates.length > 0 && ` · ${dates.length} ${m.datesAvailable}`}
          </div>
        </div>

        <div className="space-y-1 min-w-[14rem]">
          <div className="flex justify-between text-subtle">
            <span>{m.legend} ({res?.unit ?? layer.unit})</span>
            <label className="flex items-center gap-1">
              {m.opacity}
              <input type="range" min={0.2} max={1} step={0.05} value={opacity} onChange={(e) => setOpacity(Number(e.target.value))} className="w-16 accent-accent" />
            </label>
          </div>
          <div className="h-3 rounded" style={{ background: `linear-gradient(to right, ${layer.ramp.join(", ")})` }} />
          <div className="flex justify-between tabular-nums" dir="ltr">
            {res ? (
              <>
                <span>{fmt.format(res.domain[0])}</span>
                <span>{fmt.format((res.domain[0] + res.domain[1]) / 2)}</span>
                <span>{fmt.format(res.domain[1])}{layer.domain ? "+" : ""}</span>
              </>
            ) : <span>—</span>}
          </div>
          <div className="text-subtle">{m.noDataLegend}</div>
        </div>
      </div>
    </div>
  );
}
