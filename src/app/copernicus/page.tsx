import type { Metadata } from "next";
import { CopernicusPanel } from "@/components/copernicus-panel";
import { events } from "@/lib/catalog";

export const metadata: Metadata = { title: "Copernicus" };

export default function CopernicusPage() {
  const options = events.map((event) => ({
    slug: event.slug,
    nombre: event.nombre,
    s1DateEs: event.s1DateEs,
    bounds: event.bounds,
    centroid: event.centroid,
    vhThreshold: event.vhThreshold,
  }));

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-4 py-8">
      <div>
        <p className="text-sm font-medium tracking-wide text-primary uppercase">
          Copernicus Data Space
        </p>
        <h1 className="mt-2 font-heading text-4xl tracking-tight">Una escena nueva sobre una huella conocida</h1>
        <p className="mt-3 text-muted-foreground">
          El catálogo de Sen1Floods11 se queda en 2016–2019. Desde aquí se puede pedir una escena
          Sentinel-1 GRD IW reciente que corte una de esas huellas, recortar un chip de 512×512 y
          pasarlo por el mismo segmentador. Si no hay cuenta, esta página lo dice y el resto de la
          aplicación sigue igual.
        </p>
      </div>
      <CopernicusPanel events={options} />
    </main>
  );
}
