"use client";

import { LngLatBounds, Map, NavigationControl, type MapMouseEvent } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useRouter } from "next/navigation";
import { useEffect, useRef } from "react";

type FeatureCollection = {
  type: "FeatureCollection";
  features: Array<{
    type: "Feature";
    properties: Record<string, string | number>;
    geometry: { type: "Polygon"; coordinates: number[][][] };
  }>;
};

export function EventMap({
  events,
  chips,
  focusBounds,
}: {
  events: FeatureCollection;
  chips?: FeatureCollection;
  focusBounds?: number[];
}) {
  const container = useRef<HTMLDivElement>(null);
  const router = useRouter();

  useEffect(() => {
    const node = container.current;
    if (!node) return;
    const styles = [
      "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
      "https://tiles.openfreemap.org/styles/positron",
    ];
    const map = new Map({
      container: node,
      style: styles[0],
      center: [10, 12],
      zoom: 1.3,
    });
    map.addControl(new NavigationControl({ showCompass: false }), "top-right");

    let removed = false;
    let styleIndex = 0;
    const draw = () => {
      if (removed || map.getSource("events")) return;
      map.addSource("events", { type: "geojson", data: events });
      map.addLayer({
        id: "events-fill",
        type: "fill",
        source: "events",
        paint: { "fill-color": "#1d6d78", "fill-opacity": 0.28 },
      });
      map.addLayer({
        id: "events-line",
        type: "line",
        source: "events",
        paint: { "line-color": "#13464e", "line-width": 1.5 },
      });

      if (chips && chips.features.length > 0) {
        map.addSource("chips", { type: "geojson", data: chips });
        map.addLayer({
          id: "chips-fill",
          type: "fill",
          source: "chips",
          paint: {
            "fill-color": [
              "case",
              ["==", ["get", "hasFixture"], 1],
              "#c47b2b",
              "#8aa0a6",
            ],
            "fill-opacity": 0.55,
          },
        });
        map.addLayer({
          id: "chips-line",
          type: "line",
          source: "chips",
          paint: { "line-color": "#3d2a12", "line-width": 1 },
        });
      }

      const bounds = new LngLatBounds();
      if (focusBounds) {
        bounds.extend([focusBounds[0], focusBounds[1]]);
        bounds.extend([focusBounds[2], focusBounds[3]]);
      } else {
        for (const feature of events.features) {
          for (const ring of feature.geometry.coordinates) {
            for (const position of ring) bounds.extend([position[0], position[1]]);
          }
        }
      }
      if (!bounds.isEmpty()) {
        map.fitBounds(bounds, { padding: 36, maxZoom: focusBounds ? 8 : 3.2, duration: 0 });
      }
    };
    const layersFor = () =>
      chips && chips.features.length > 0 ? ["chips-fill", "events-fill"] : ["events-fill"];
    map.on("click", (event: MapMouseEvent) => {
      if (!map.getLayer("events-fill")) return;
      const found = map.queryRenderedFeatures(event.point, { layers: layersFor() });
      const chip = found.find((feature) => feature.layer.id === "chips-fill");
      const flood = found.find((feature) => feature.layer.id === "events-fill");
      const chipId = chip?.properties?.chipId;
      const slug = flood?.properties?.slug;
      if (typeof chipId === "string") router.push(`/chips/${chipId}`);
      else if (typeof slug === "string") router.push(`/eventos/${slug}`);
    });
    map.on("mousemove", (event: MapMouseEvent) => {
      if (!map.getLayer("events-fill")) return;
      const found = map.queryRenderedFeatures(event.point, { layers: layersFor() });
      map.getCanvas().style.cursor = found.length ? "pointer" : "";
    });
    let styleReady = false;
    map.on("style.load", () => {
      styleReady = true;
      draw();
    });
    map.on("error", (event) => {
      if (removed || styleIndex > 0 || styleReady) return;
      const message = String(event.error?.message ?? "");
      if (/style|ajax|fetch|sprite|glyph/i.test(message)) {
        styleIndex = 1;
        map.setStyle(styles[1]);
      }
    });
    const observer = new ResizeObserver(() => map.resize());
    observer.observe(node);

    return () => {
      removed = true;
      observer.disconnect();
      map.remove();
    };
  }, [chips, events, focusBounds, router]);

  return <div ref={container} className="h-full w-full" />;
}
