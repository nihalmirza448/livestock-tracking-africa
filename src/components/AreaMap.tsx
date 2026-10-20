"use client";

import "leaflet/dist/leaflet.css";
import { MapContainer, Rectangle, TileLayer } from "react-leaflet";
import type { PilotArea } from "@/lib/data";

export default function AreaMap({ area }: { area: PilotArea }) {
  const bounds: [[number, number], [number, number]] = [
    [area.min_lat, area.min_lon],
    [area.max_lat, area.max_lon],
  ];
  return (
    <MapContainer bounds={bounds} boundsOptions={{ padding: [24, 24] }} scrollWheelZoom={false} className="h-72 w-full rounded-lg">
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <Rectangle bounds={bounds} pathOptions={{ color: "#b45309", weight: 2, fillOpacity: 0.08 }} />
    </MapContainer>
  );
}
