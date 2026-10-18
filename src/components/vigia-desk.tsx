"use client";

import { useEffect, useMemo, useState } from "react";
import { VigiaMap, type ChipOverlay } from "@/components/vigia-map";
import { Button } from "@/components/ui/button";
import type { Watch } from "@/lib/watches";

type Status = {
  configured: boolean;
  inference: boolean;
  message: string;
};

type Scene = {
  id: string;
  name: string;
  start: string;
  end: string;
};

type SegmentResult = {
  area_km2: number;
  threshold_area_km2: number;
  backend: string;
  device?: string;
  span_km: number;
  tiles: number;
  corners: number[][];
  sar_png: string;
  mask_png: string;
  preview_png: string;
};

function formatStart(value: string) {
  if (!value) return "fecha sin publicar";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("es", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

export function VigiaDesk({ watches }: { watches: Watch[] }) {
  const [status, setStatus] = useState<Status | null>(null);
  const [slug, setSlug] = useState(watches[0]?.slug ?? "");
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [searching, setSearching] = useState(false);
  const [segmenting, setSegmenting] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [result, setResult] = useState<SegmentResult | null>(null);
  const [radarOpacity, setRadarOpacity] = useState(0.55);
  const [maskOpacity, setMaskOpacity] = useState(0.85);

  const selected = watches.find((watch) => watch.slug === slug) ?? watches[0];
  const configured = status?.configured === true && status.inference;
  const overlay = useMemo<ChipOverlay | null>(() => {
    if (!result || result.corners.length !== 4) return null;
    return { sarPng: result.sar_png, maskPng: result.mask_png, corners: result.corners };
  }, [result]);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/copernicus/estado", { cache: "no-store" })
      .then((response) => response.json())
      .then((body: Status) => {
        if (!cancelled) setStatus(body);
      })
      .catch(() => {
        if (!cancelled) {
          setStatus({
            configured: false,
            inference: false,
            message: "No se pudo comprobar la cuenta de Copernicus.",
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function search() {
    if (!selected) return;
    setError("");
    setResult(null);
    setScenes([]);
    setSearching(true);
    try {
      const response = await fetch("/api/copernicus/buscar", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          bounds: [
            selected.lon - 0.04,
            selected.lat - 0.03,
            selected.lon + 0.04,
            selected.lat + 0.03,
          ],
          lon: selected.lon,
          lat: selected.lat,
          start: selected.desde,
          end: selected.hasta,
        }),
      });
      const body = await response.json();
      if (!response.ok) {
        setError(body.message || body.error || "La búsqueda no se completó.");
        return;
      }
      setScenes(body.scenes ?? []);
      if (!body.scenes?.length) {
        setError("El catálogo no devolvió un GRD IW que cubra este punto en esas fechas.");
      }
    } catch {
      setError("La búsqueda no llegó al servicio.");
    } finally {
      setSearching(false);
    }
  }

  async function segment(scene: Scene) {
    if (!selected) return;
    setError("");
    setSegmenting(scene.id);
    setResult(null);
    try {
      const response = await fetch("/api/copernicus/segmentar", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          product_id: scene.id,
          lon: selected.lon,
          lat: selected.lat,
          vh_threshold: selected.vhThreshold,
          tiles: 2,
        }),
      });
      const body = await response.json();
      if (!response.ok) {
        setError(body.message || body.error || "No se pudo segmentar la escena.");
        return;
      }
      setResult(body as SegmentResult);
    } catch {
      setError("La descarga o el recorte se interrumpió.");
    } finally {
      setSegmenting(null);
    }
  }

  return (
    <div className="grid min-h-[calc(100vh-4.5rem)] lg:grid-cols-[380px_minmax(0,1fr)]">
      <aside className="flex max-h-[calc(100vh-4.5rem)] flex-col gap-4 overflow-auto border-b border-border px-4 py-5 lg:border-r lg:border-b-0">
        <div>
          <p className="text-sm font-medium tracking-wide text-primary uppercase">Vigía</p>
          <h1 className="mt-2 font-heading text-3xl tracking-tight">Radar de ahora, puesto en el mapa</h1>
          <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
            Se pide una escena Sentinel-1 que cubra el pueblo, se calibra a sigma0 con la tabla del
            propio producto y se coloca con sus puntos de control. El mosaico mide unos 10 km. El
            velo cian es el agua que marca el modelo.
          </p>
        </div>

        <StatusLine status={status} />

        <label className="flex flex-col gap-1 text-sm">
          <span className="text-muted-foreground">Lugar</span>
          <select
            className="h-9 rounded-lg border border-input bg-background px-2"
            value={selected?.slug}
            onChange={(event) => {
              setSlug(event.target.value);
              setScenes([]);
              setResult(null);
              setError("");
            }}
          >
            {watches.map((watch) => (
              <option key={watch.slug} value={watch.slug}>
                {watch.nombre}
              </option>
            ))}
          </select>
        </label>
        {selected && <p className="text-sm leading-relaxed text-muted-foreground">{selected.resumen}</p>}

        <Button type="button" disabled={!configured || searching || !selected} onClick={() => void search()}>
          {searching ? "Buscando en el catálogo…" : "Buscar pasadas"}
        </Button>

        {scenes.length > 0 && (
          <ul className="flex flex-col gap-2">
            {scenes.map((scene) => (
              <li key={scene.id} className="rounded-xl bg-card px-3 py-3 ring-1 ring-foreground/10">
                <p className="text-sm font-medium">{formatStart(scene.start)}</p>
                <p className="mt-1 text-xs break-all text-muted-foreground">{scene.name}</p>
                <Button
                  type="button"
                  className="mt-3"
                  variant="secondary"
                  disabled={segmenting !== null}
                  onClick={() => void segment(scene)}
                >
                  {segmenting === scene.id ? "Descargando y midiendo…" : "Medir el agua"}
                </Button>
              </li>
            ))}
          </ul>
        )}

        {segmenting && (
          <p className="text-sm text-muted-foreground">
            Una escena GRD pesa cerca de 1,7 GB. Después se recorta un mosaico de cuatro chips de
            512×512, centrado en {selected?.lugar}.
          </p>
        )}
        {error && <p className="text-sm text-destructive">{error}</p>}
        {result && (
          <div className="flex flex-col gap-2 rounded-xl bg-card px-3 py-3 ring-1 ring-foreground/10">
            <p className="font-heading text-2xl tracking-tight">{result.area_km2.toFixed(2)} km²</p>
            <p className="text-sm text-muted-foreground">
              Agua según el U-Net, dentro de {result.span_km.toFixed(1)} km de lado. El umbral VH
              del lugar marca {result.threshold_area_km2.toFixed(2)} km². Backend: {result.backend}
              {result.device ? ` (${result.device})` : ""}.
            </p>
            <p className="text-xs leading-relaxed text-muted-foreground">
              En el falso color, el rojo es VV, el verde es VH y el azul el cociente. El agua lisa
              queda oscura. El recuadro va girado porque el radar no mira al norte.
            </p>
            <img
              src={result.preview_png}
              alt="Falso color Sentinel-1 con la máscara de agua"
              className="mt-1 w-full rounded-lg"
            />
          </div>
        )}
      </aside>
      <div className="relative h-[70vh] lg:h-[calc(100vh-4.5rem)]">
        {selected && (
          <VigiaMap
            lon={selected.lon}
            lat={selected.lat}
            overlay={overlay}
            radarOpacity={radarOpacity}
            maskOpacity={maskOpacity}
          />
        )}
        {overlay && (
          <div className="absolute bottom-3 left-3 z-10 flex w-56 flex-col gap-2 rounded-xl bg-background/95 px-3 py-3 text-sm shadow-sm ring-1 ring-foreground/10">
            <OpacitySlider label="Radar" value={radarOpacity} onChange={setRadarOpacity} />
            <OpacitySlider label="Máscara" value={maskOpacity} onChange={setMaskOpacity} />
          </div>
        )}
      </div>
    </div>
  );
}

function OpacitySlider({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
}) {
  return (
    <label className="flex items-center gap-3">
      <span className="w-16 text-muted-foreground">{label}</span>
      <input
        type="range"
        min={0}
        max={1}
        step={0.05}
        value={value}
        aria-label={`Opacidad del ${label.toLowerCase()}`}
        onChange={(event) => onChange(Number(event.target.value))}
        className="w-full"
      />
    </label>
  );
}

function StatusLine({ status }: { status: Status | null }) {
  if (!status) return <p className="text-sm text-muted-foreground">Comprobando la cuenta…</p>;
  if (status.configured && status.inference) {
    return (
      <p className="text-sm text-muted-foreground">
        Cuenta de Copernicus lista. La contraseña no sale de este ordenador.
      </p>
    );
  }
  return (
    <p className="text-sm text-destructive">
      {status.message || "Sin cuenta de Copernicus, el vigía no puede pedir escenas."}
    </p>
  );
}
