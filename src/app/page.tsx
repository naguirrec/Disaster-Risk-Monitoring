import Link from "next/link";
import { EventMap } from "@/components/event-map";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { chipsCollection, events, eventsCollection, handLabeledEvents, sampleChips } from "@/lib/catalog";
import { formatDb } from "@/lib/format";
import { cn } from "cn";

export default function HomePage() {
  return (
    <main className="mx-auto flex w-full max-w-7xl flex-1 flex-col gap-6 px-4 py-6 lg:px-6">
      <section className="grid gap-6 lg:grid-cols-[1.2fr_0.8fr] lg:items-end">
        <div>
          <p className="text-sm font-medium tracking-wide text-primary uppercase">
            Radar Sentinel-1 · 10 m · agua o no agua
          </p>
          <h1 className="mt-2 max-w-2xl font-heading text-4xl leading-tight tracking-tight sm:text-5xl">
            Once inundaciones etiquetadas, y el mapa para recorrerlas
          </h1>
          <p className="mt-3 max-w-2xl text-base leading-relaxed text-muted-foreground">
            Sen1Floods11 reúne crecidas observadas entre 2016 y 2019. Esta mesa de trabajo lista
            cada evento con país, fecha de adquisición y órbita, dibuja la huella en el mapa y abre
            un chip de 512×512 para estimar el área de agua.
          </p>
        </div>
        <div className="grid grid-cols-3 gap-2">
          <Card size="sm">
            <CardContent>
              <p className="font-heading text-2xl">{handLabeledEvents.length}</p>
              <p className="text-xs text-muted-foreground">eventos con etiqueta manual</p>
            </CardContent>
          </Card>
          <Card size="sm">
            <CardContent>
              <p className="font-heading text-2xl">446</p>
              <p className="text-xs text-muted-foreground">chips de 512×512</p>
            </CardContent>
          </Card>
          <Card size="sm">
            <CardContent>
              <p className="font-heading text-2xl">{sampleChips.length}</p>
              <p className="text-xs text-muted-foreground">chips en la muestra local</p>
            </CardContent>
          </Card>
        </div>
      </section>

      <div className="grid items-start gap-4 lg:grid-cols-[340px_minmax(0,1fr)]">
        <div className="order-2 flex max-h-[70vh] flex-col gap-2 overflow-auto lg:order-1 lg:max-h-[calc(100vh-13rem)]">
          {events.map((event) => (
            <Link
              key={event.slug}
              href={`/eventos/${event.slug}`}
              className="rounded-xl bg-card px-4 py-3 ring-1 ring-foreground/10 hover:bg-accent"
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="font-heading text-lg leading-tight">{event.nombre}</p>
                  <p className="text-sm text-muted-foreground">{event.s1DateEs}</p>
                </div>
                <Badge variant={event.hasHandLabels ? "secondary" : "outline"}>
                  {event.orbitEs}
                </Badge>
              </div>
              <p className="mt-2 text-sm text-muted-foreground">
                {event.hasHandLabels
                  ? `${event.handLabeledCount} chips manuales · umbral VH ${formatDb(event.vhThreshold)}`
                  : "En la metadata, sin chips del conjunto manual"}
              </p>
            </Link>
          ))}
        </div>
        <div className="order-1 h-[360px] overflow-hidden rounded-xl ring-1 ring-foreground/10 lg:order-2 lg:sticky lg:top-20 lg:h-[calc(100vh-8rem)]">
          <EventMap events={eventsCollection()} chips={chipsCollection()} />
        </div>
      </div>

      <section className="flex flex-col gap-3 border-t border-border pt-5 sm:flex-row sm:items-center sm:justify-between">
        <p className="max-w-3xl text-sm text-muted-foreground">
          La metadata v1.1 trae 12 polígonos. Once coinciden con los chips etiquetados a mano;
          Colombia queda en el archivo y no tiene chips en esa colección. En el mapa, el ámbar marca
          la muestra que sí se puede segmentar.
        </p>
        <Link href="/chips/Spain_3285448" className={cn(buttonVariants())}>
          Abrir un chip de España
        </Link>
      </section>
    </main>
  );
}
