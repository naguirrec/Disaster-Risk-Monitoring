"use client";

import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { Chip } from "@/lib/catalog";
import { formatKm2, formatPercent } from "@/lib/format";

export function EventChips({ samples, rest }: { samples: Chip[]; rest: Chip[] }) {
  if (samples.length === 0 && rest.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-border bg-card px-5 py-8">
        <p className="font-heading text-xl">Sin chips etiquetados a mano</p>
        <p className="mt-2 max-w-xl text-sm text-muted-foreground">
          Colombia aparece en Sen1Floods11_Metadata.geojson, pero la colección STAC de chips
          manuales (446) no incluye ese evento. No hay ráster local que abrir en el visor.
        </p>
      </div>
    );
  }

  return (
    <Tabs defaultValue="muestra">
      <TabsList>
        <TabsTrigger value="muestra">Muestra local ({samples.length})</TabsTrigger>
        <TabsTrigger value="catalogo">Resto del catálogo ({rest.length})</TabsTrigger>
      </TabsList>
      <TabsContent value="muestra" className="pt-3">
        <div className="grid gap-3 sm:grid-cols-2">
          {samples.map((chip) => (
            <Link
              key={chip.chipId}
              href={`/chips/${chip.chipId}`}
              className="overflow-hidden rounded-xl bg-card ring-1 ring-foreground/10"
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={`/previews/${chip.chipId}.jpg`}
                alt={`Vista previa SAR de ${chip.chipId}`}
                className="aspect-[16/10] w-full object-cover"
              />
              <div className="flex items-start justify-between gap-3 p-3">
                <div>
                  <p className="font-medium">{chip.chipId}</p>
                  <p className="text-sm text-muted-foreground">
                    Referencia {formatKm2(chip.referenceAreaKm2)} · {formatPercent(chip.waterFraction)}
                  </p>
                </div>
                <Badge variant="outline">
                  {chip.role === "held_out" ? "Apartado" : "Entrenamiento"}
                </Badge>
              </div>
            </Link>
          ))}
        </div>
      </TabsContent>
      <TabsContent value="catalogo" className="pt-3">
        <p className="mb-3 text-sm text-muted-foreground">
          Estos chips tienen huella y etiqueta resumida. Abrir uno muestra el estado vacío: no hay
          GeoTIFF en la muestra.
        </p>
        <ul className="grid max-h-80 gap-2 overflow-auto sm:grid-cols-2">
          {rest.map((chip) => (
            <li key={chip.chipId}>
              <Link
                href={`/chips/${chip.chipId}`}
                className="flex items-center justify-between rounded-lg bg-card px-3 py-2 text-sm ring-1 ring-foreground/10 hover:bg-muted"
              >
                <span>{chip.chipId}</span>
                <span className="text-muted-foreground">{formatKm2(chip.referenceAreaKm2)}</span>
              </Link>
            </li>
          ))}
        </ul>
      </TabsContent>
    </Tabs>
  );
}
