"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export type CopernicusEvent = {
  slug: string;
  nombre: string;
  s1DateEs: string;
  bounds: number[];
  centroid: number[];
  vhThreshold: number;
};

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
  backend: string;
  device?: string;
  preview_png: string;
  product_id: string;
  water_pixels: number;
};

function formatStart(value: string) {
  if (!value) return "fecha sin publicar";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("es", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

export function CopernicusPanel({ events }: { events: CopernicusEvent[] }) {
  const [status, setStatus] = useState<Status | null>(null);
  const [slug, setSlug] = useState(events.find((event) => event.slug === "espana")?.slug ?? events[0]?.slug);
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [searching, setSearching] = useState(false);
  const [segmenting, setSegmenting] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [result, setResult] = useState<SegmentResult | null>(null);

  const selected = events.find((event) => event.slug === slug) ?? events[0];
  const configured = status?.configured === true && status.inference;

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

  async function loadStatus() {
    const response = await fetch("/api/copernicus/estado", { cache: "no-store" });
    const body = (await response.json()) as Status;
    setStatus(body);
    return body;
  }

  async function search() {
    setError("");
    setResult(null);
    setScenes([]);
    const current = status ?? (await loadStatus());
    if (!current.configured || !current.inference) return;
    if (!selected) return;
    setSearching(true);
    try {
      const response = await fetch("/api/copernicus/buscar", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bounds: selected.bounds }),
      });
      const body = await response.json();
      if (!response.ok) {
        setError(body.message || body.error || "La búsqueda no se completó.");
        if (body.configured === false) setStatus({ ...current, configured: false, message: body.message });
        return;
      }
      setScenes(body.scenes ?? []);
      if (!body.scenes?.length) {
        setError("El catálogo no devolvió escenas GRD IW recientes sobre esa huella.");
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
          lon: selected.centroid[0],
          lat: selected.centroid[1],
          vh_threshold: selected.vhThreshold,
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
    <div className="flex flex-col gap-4">
      <StatusBanner status={status} />
      <Card>
        <CardHeader>
          <CardTitle>Buscar una escena reciente</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-muted-foreground">Huella del catálogo</span>
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
              {events.map((event) => (
                <option key={event.slug} value={event.slug}>
                  {event.nombre} · Sentinel-1 del {event.s1DateEs}
                </option>
              ))}
            </select>
          </label>
          <p className="text-sm text-muted-foreground">
            La búsqueda pide hasta cinco productos Sentinel-1 GRD, modo IW, de los últimos 120 días
            que corten esta huella. No usa la fecha histórica del evento.
          </p>
          <Button type="button" disabled={!configured || searching} onClick={() => void search()}>
            {searching ? "Buscando en el catálogo…" : "Buscar escenas"}
          </Button>
        </CardContent>
      </Card>

      {scenes.length > 0 && (
        <ul className="flex flex-col gap-2">
          {scenes.map((scene) => (
            <li key={scene.id} className="rounded-xl bg-card px-4 py-3 ring-1 ring-foreground/10">
              <p className="font-medium break-all">{scene.name}</p>
              <p className="mt-1 text-sm text-muted-foreground">{formatStart(scene.start)}</p>
              <Button
                type="button"
                className="mt-3"
                variant="secondary"
                disabled={segmenting !== null}
                onClick={() => void segment(scene)}
              >
                {segmenting === scene.id ? "Descargando y segmentando…" : "Descargar, recortar y segmentar"}
              </Button>
            </li>
          ))}
        </ul>
      )}

      {segmenting && (
        <p className="text-sm text-muted-foreground">
          Una escena GRD pesa cerca de 1 GB. El servicio se queda con un chip de 512×512 alrededor
          del centro de la huella y lo pasa por el mismo segmentador.
        </p>
      )}
      {error && <p className="text-sm text-destructive">{error}</p>}
      {result && (
        <Card>
          <CardHeader>
            <CardTitle>Chip segmentado</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <img
              src={result.preview_png}
              alt="Canal VH de la escena con la máscara de agua encima"
              className="w-full max-w-md rounded-lg"
            />
            <p className="text-sm">
              Agua estimada: <span className="font-medium">{result.area_km2.toFixed(2)} km²</span> en
              el chip de 512×512. Backend: {result.backend}
              {result.device ? ` (${result.device})` : ""}.
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function StatusBanner({ status }: { status: Status | null }) {
  if (!status) {
    return <p className="text-sm text-muted-foreground">Comprobando si hay cuenta de Copernicus…</p>;
  }
  if (status.configured && status.inference) {
    return (
      <p className="text-sm text-muted-foreground">
        La cuenta de Copernicus Data Space está configurada. Las contraseñas no se muestran ni se
        guardan en el repositorio.
      </p>
    );
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle>Sin credenciales de Copernicus</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2 text-sm text-muted-foreground">
        <p>
          {status.message ||
            "Define CDSE_USERNAME y CDSE_PASSWORD en el entorno o en .env.local."}
        </p>
        <p>
          Copia <code>.env.example</code> a <code>.env.local</code>, rellena los dos nombres y
          reinicia el servicio del puerto 43124. El catálogo, el mapa y el visor no dependen de esa
          cuenta.
        </p>
      </CardContent>
    </Card>
  );
}
