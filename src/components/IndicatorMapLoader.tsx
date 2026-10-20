"use client";

import dynamic from "next/dynamic";
import type { ComponentProps } from "react";

// Leaflet touches window, so the map only renders in the browser.
const IndicatorMap = dynamic(() => import("./IndicatorMap"), {
  ssr: false,
  loading: () => <div className="h-[36rem] w-full rounded-lg bg-muted" />,
});

export function IndicatorMapLoader(props: ComponentProps<typeof IndicatorMap>) {
  return <IndicatorMap {...props} />;
}
