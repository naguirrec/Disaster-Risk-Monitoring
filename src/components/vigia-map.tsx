"use client";

import {
  LngLatBounds,
  Map,
  NavigationControl,
  setWorkerUrl,
  type ImageSource,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

// Turbopack rewrites the library URL, so the default relative worker 404s and
// the basemap stays blank. These files are the upstream worker and its import.
setWorkerUrl("/maplibre-gl-worker.mjs");
import { useEffect, useRef } from "react";

export type ChipOverlay = {
  sarPng: string;
  maskPng: string;
  corners: number[][];
};

type Corner = [number, number];

const styles = [
  "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
  "https://tiles.openfreemap.org/styles/positron",
];

function placeImage(
  map: Map,
  id: string,
  url: string,
  coordinates: [Corner, Corner, Corner, Corner],
  opacity: number,
) {
  const existing = map.getSource(id);
  if (existing?.type === "image") {
    (existing as ImageSource).updateImage({ url, coordinates });
    return;
  }
  map.addSource(id, { type: "image", url, coordinates });
  map.addLayer({
    id,
    type: "raster",
    source: id,
    paint: { "raster-opacity": opacity, "raster-fade-duration": 0 },
  });
}

export function VigiaMap({
  lon,
  lat,
  overlay,
  radarOpacity,
  maskOpacity,
}: {
  lon: number;
  lat: number;
  overlay: ChipOverlay | null;
  radarOpacity: number;
  maskOpacity: number;
}) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<Map | null>(null);
  const overlayRef = useRef(overlay);
  const radarOpacityRef = useRef(radarOpacity);
  const maskOpacityRef = useRef(maskOpacity);
  overlayRef.current = overlay;
  radarOpacityRef.current = radarOpacity;
  maskOpacityRef.current = maskOpacity;

  useEffect(() => {
    const node = container.current;
    if (!node) return;
    const map = new Map({
      container: node,
      style: styles[0],
      center: [lon, lat],
      zoom: 12,
    });
    map.addControl(new NavigationControl({ showCompass: false }), "top-right");
    mapRef.current = map;
    let removed = false;
    let styleIndex = 0;
    let styleReady = false;

    const paint = () => {
      if (removed || !map.isStyleLoaded()) return;
      const point = {
        type: "Feature" as const,
        properties: {},
        geometry: { type: "Point" as const, coordinates: [lon, lat] },
      };
      const watch = map.getSource("watch");
      if (watch?.type === "geojson") {
        watch.setData({ type: "FeatureCollection", features: [point] });
      } else if (!watch) {
        map.addSource("watch", { type: "geojson", data: { type: "FeatureCollection", features: [point] } });
        map.addLayer({
          id: "watch-point",
          type: "circle",
          source: "watch",
          paint: {
            "circle-radius": 6,
            "circle-color": "#9a3412",
            "circle-stroke-width": 2,
            "circle-stroke-color": "#fff7ed",
          },
        });
      }

      const current = overlayRef.current;
      if (current && current.corners.length === 4) {
        const coordinates = current.corners.map((corner) => [corner[0], corner[1]] as Corner) as [
          Corner,
          Corner,
          Corner,
          Corner,
        ];
        placeImage(map, "sar", current.sarPng, coordinates, radarOpacityRef.current);
        placeImage(map, "water", current.maskPng, coordinates, maskOpacityRef.current);
        if (map.getLayer("watch-point")) map.moveLayer("watch-point");
        const bounds = new LngLatBounds();
        for (const corner of current.corners) bounds.extend([corner[0], corner[1]]);
        if (!bounds.isEmpty()) map.fitBounds(bounds, { padding: 48, maxZoom: 15, duration: 500 });
      }
    };

    map.on("style.load", () => {
      styleReady = true;
      paint();
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
      mapRef.current = null;
    };
  }, [lat, lon]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map?.isStyleLoaded() || !overlay || overlay.corners.length !== 4) return;
    const coordinates = overlay.corners.map((corner) => [corner[0], corner[1]] as Corner) as [
      Corner,
      Corner,
      Corner,
      Corner,
    ];
    placeImage(map, "sar", overlay.sarPng, coordinates, radarOpacityRef.current);
    placeImage(map, "water", overlay.maskPng, coordinates, maskOpacityRef.current);
    if (map.getLayer("watch-point")) map.moveLayer("watch-point");
    const bounds = new LngLatBounds();
    for (const corner of overlay.corners) bounds.extend([corner[0], corner[1]]);
    if (!bounds.isEmpty()) map.fitBounds(bounds, { padding: 48, maxZoom: 15, duration: 500 });
  }, [overlay]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map?.getLayer("sar")) return;
    map.setPaintProperty("sar", "raster-opacity", radarOpacity);
  }, [radarOpacity]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map?.getLayer("water")) return;
    map.setPaintProperty("water", "raster-opacity", maskOpacity);
  }, [maskOpacity]);

  return <div ref={container} className="h-full w-full" />;
}
