import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { EventChips } from "@/components/event-chips";
import { EventMap } from "@/components/event-map";
import { Badge } from "@/components/ui/badge";
import { chipsCollection, events, getEvent, chipsForEvent } from "@/lib/catalog";
import { formatDb, formatInteger } from "@/lib/format";

export function generateStaticParams() {
  return events.map((event) => ({ slug: event.slug }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const event = getEvent(slug);
  return { title: event ? event.nombre : "Evento" };
}

export default async function EventPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const event = getEvent(slug);
  if (!event) notFound();
  const rows = chipsForEvent(slug);
  const samples = rows.filter((chip) => chip.hasFixture);
  const rest = rows.filter((chip) => !chip.hasFixture);

  return (
    <main className="mx-auto flex w-full max-w-7xl flex-1 flex-col gap-6 px-4 py-6 lg:px-6">
      <div>
        <Link href="/" className="text-sm text-muted-foreground hover:text-foreground">
          Catálogo
        </Link>
        <div className="mt-2 flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="text-sm text-primary">{event.iso}</p>
            <h1 className="font-heading text-4xl tracking-tight">{event.nombre}</h1>
            <p className="mt-1 text-muted-foreground">
              Sentinel-1 del {event.s1DateEs}. Sentinel-2 del {event.s2DateEs}.
            </p>
          </div>
          <Badge>{event.orbitEs}</Badge>
        </div>
      </div>

      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          ["Órbita relativa", String(event.relativeOrbit)],
          ["Umbral VH", formatDb(event.vhThreshold)],
          ["Chips manuales", formatInteger(event.handLabeledCount)],
          ["Tiles S2 coincidentes", formatInteger(event.coincidentSize)],
        ].map(([label, value]) => (
          <div key={label} className="rounded-xl bg-card px-4 py-3 ring-1 ring-foreground/10">
            <dt className="text-xs text-muted-foreground">{label}</dt>
            <dd className="mt-1 font-heading text-xl">{value}</dd>
          </div>
        ))}
      </dl>

      <div className="h-[320px] overflow-hidden rounded-xl ring-1 ring-foreground/10 sm:h-[420px]">
        <EventMap
          events={{
            type: "FeatureCollection",
            features: [
              {
                type: "Feature",
                properties: { slug: event.slug, nombre: event.nombre },
                geometry: event.geometry,
              },
            ],
          }}
          chips={chipsCollection(event.slug)}
          focusBounds={event.bounds}
        />
      </div>

      <p className="text-sm text-muted-foreground">
        La metadata del dataset anota {formatInteger(event.trainChipsMeta)} chips de entrenamiento y{" "}
        {formatInteger(event.valChipsMeta)} de validación, cifras del flujo original que mezclan el
        etiquetado débil. Aquí el recuento manual sale del catálogo STAC v1.1.
      </p>

      <EventChips samples={samples} rest={rest} />
    </main>
  );
}
