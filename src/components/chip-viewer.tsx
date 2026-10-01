"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { Chip } from "@/lib/catalog";
import { formatDb, formatInteger, formatKm2, formatPercent, formatScore, gcsChipUrl } from "@/lib/format";
import { cn } from "cn";

type Segmentation = {
  chipId: string;
  modelName: string;
  modelVersion: string;
  backend: string;
  backendLabel: string;
  vhThreshold: number;
  waterPixels: number;
  validPixels: number;
  areaKm2: number;
  referenceWaterPixels: number;
  referenceAreaKm2: number;
  iou: number;
  maskPng: string;
};

export function ChipViewer({ chip }: { chip: Chip }) {
  const [attempt, setAttempt] = useState(0);
  const [status, setStatus] = useState<"empty" | "loading" | "ready" | "error">(
    chip.hasFixture ? "loading" : "empty",
  );
  const [result, setResult] = useState<Segmentation | null>(null);
  const [message, setMessage] = useState("");
  const [showMask, setShowMask] = useState(true);
  const [opacity, setOpacity] = useState(0.72);

  useEffect(() => {
    if (!chip.hasFixture) return;
    const controller = new AbortController();
    fetch("/api/segmentar", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ chipId: chip.chipId }),
      signal: controller.signal,
    })
      .then(async (response) => {
        const body = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(body.error || "La segmentación no devolvió máscara.");
        }
        return body as Segmentation;
      })
      .then((body) => {
        setResult(body);
        setStatus("ready");
      })
      .catch((error: Error) => {
        if (error.name === "AbortError") return;
        setMessage(error.message);
        setStatus("error");
      });
    return () => controller.abort();
  }, [attempt, chip.chipId, chip.hasFixture]);

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
      <Card className="overflow-hidden">
        <div className="relative bg-[#1c2430]">
          {chip.hasFixture ? (
            <>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={`/previews/${chip.chipId}.jpg`}
                alt={`Sentinel-1 VH del chip ${chip.chipId}, estirado al percentil 2-98`}
                className="aspect-square w-full object-contain"
              />
              {status === "ready" && result && showMask ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={result.maskPng}
                  alt="Máscara de agua superpuesta"
                  className="absolute inset-0 h-full w-full object-contain"
                  style={{ opacity }}
                />
              ) : null}
              {status === "loading" ? (
                <div className="absolute inset-x-0 bottom-0 bg-[#1c2430]/80 px-4 py-3 text-sm text-white">
                  Segmentando con flood_segmentation_model…
                </div>
              ) : null}
            </>
          ) : (
            <div className="flex aspect-square flex-col items-start justify-end gap-3 p-6 text-white">
              <p className="font-heading text-2xl">Sin ráster en la muestra local</p>
              <p className="max-w-md text-sm leading-relaxed text-white/80">
                {chip.chipId} está en el catálogo STAC de chips etiquetados a mano, con su
                huella y el área de la etiqueta. El GeoTIFF Sentinel-1 no se descargó: la
                muestra local guarda dos chips por evento, no los 446.
              </p>
            </div>
          )}
        </div>
        {chip.hasFixture ? (
          <CardContent className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={showMask}
                onChange={(event) => setShowMask(event.target.checked)}
                disabled={status !== "ready"}
              />
              Mostrar máscara de agua
            </label>
            <label className="flex items-center gap-3 text-sm">
              Opacidad
              <input
                type="range"
                min={0.2}
                max={1}
                step={0.02}
                value={opacity}
                onChange={(event) => setOpacity(Number(event.target.value))}
                disabled={status !== "ready"}
                className="w-36"
              />
            </label>
          </CardContent>
        ) : null}
      </Card>

      <div className="flex flex-col gap-4">
        <Card>
          <CardHeader>
            <CardTitle>Área inundada</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            {status === "loading" ? (
              <>
                <Skeleton className="h-8 w-36" />
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-4/5" />
                <p className="text-sm text-muted-foreground">
                  La etiqueta manual ya está en el catálogo: {formatKm2(chip.referenceAreaKm2)} de
                  agua en píxeles válidos. La estimación del modelo llega al terminar la inferencia.
                </p>
              </>
            ) : null}
            {status === "ready" && result ? (
              <>
                <p className="font-heading text-3xl tracking-tight">{formatKm2(result.areaKm2)}</p>
                <p className="text-sm text-muted-foreground">
                  {formatInteger(result.waterPixels)} píxeles de agua sobre{" "}
                  {formatInteger(result.validPixels)} válidos (
                  {formatPercent(result.waterPixels / Math.max(result.validPixels, 1))}). Cada
                  píxel mide 10 m × 10 m.
                </p>
                <dl className="grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <dt className="text-muted-foreground">Referencia manual</dt>
                    <dd>{formatKm2(result.referenceAreaKm2)}</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">Coincidencia</dt>
                    <dd>{formatScore(result.iou)} IoU</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">Umbral VH</dt>
                    <dd>{formatDb(result.vhThreshold)}</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">Modelo</dt>
                    <dd>{result.modelName}</dd>
                  </div>
                </dl>
                <Badge variant="secondary">{result.backendLabel}</Badge>
              </>
            ) : null}
            {status === "error" ? (
              <div className="flex flex-col gap-3">
                <p className="font-medium text-destructive">No hay máscara</p>
                <p className="text-sm text-muted-foreground">
                  {message || "El servicio de inferencia no respondió."} Comprueba que el proceso
                  Python sigue en el puerto 43124 y vuelve a intentarlo.
                </p>
                <Button
                  type="button"
                  onClick={() => {
                    setStatus("loading");
                    setResult(null);
                    setAttempt((value) => value + 1);
                  }}
                >
                  Reintentar segmentación
                </Button>
              </div>
            ) : null}
            {status === "empty" ? (
              <div className="flex flex-col gap-3 text-sm">
                <p>
                  Referencia manual en este chip:{" "}
                  <strong>{formatKm2(chip.referenceAreaKm2)}</strong> (
                  {formatPercent(chip.waterFraction)} de los píxeles válidos).
                </p>
                <p className="text-muted-foreground">
                  Para segmentarlo, descarga el par Sentinel-1 y la etiqueta, regenera las fixtures
                  y vuelve a abrir el visor.
                </p>
                <a className="text-primary underline-offset-4 hover:underline" href={gcsChipUrl(chip.chipId, "S1Hand")}>
                  GeoTIFF Sentinel-1
                </a>
                <a className="text-primary underline-offset-4 hover:underline" href={gcsChipUrl(chip.chipId, "LabelHand")}>
                  Etiqueta manual
                </a>
              </div>
            ) : null}
          </CardContent>
        </Card>
        <Card size="sm">
          <CardHeader>
            <CardTitle>Ficha</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2 text-sm">
            <p>
              {chip.nombre} · Sentinel-1 {chip.s1DateEs}
            </p>
            <p>
              Órbita {chip.orbitEs.toLowerCase()}, relativa {chip.relativeOrbit}
            </p>
            <p className="text-muted-foreground">
              {chip.role === "held_out"
                ? "Este chip se apartó del entrenamiento breve."
                : chip.role === "train"
                  ? "Este chip entró en el entrenamiento breve de la muestra."
                  : "Este chip no forma parte de la muestra descargada."}
            </p>
            <Link href={`/eventos/${chip.eventSlug}`} className={cn(buttonVariants({ variant: "outline" }))}>
              Volver al evento
            </Link>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
