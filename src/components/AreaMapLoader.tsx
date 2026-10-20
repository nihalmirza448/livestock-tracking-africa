"use client";

import dynamic from "next/dynamic";
import type { PilotArea } from "@/lib/data";

// Leaflet touches window, so it only renders in the browser.
const AreaMap = dynamic(() => import("./AreaMap"), {
  ssr: false,
  loading: () => <div className="h-72 w-full rounded-lg bg-muted" />,
});

export function AreaMapLoader({ area }: { area: PilotArea }) {
  return <AreaMap area={area} />;
}
