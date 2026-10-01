import type { Metadata } from "next";
import Link from "next/link";
import { buttonVariants } from "@/components/ui/button";
import { sampleChips } from "@/lib/catalog";
import { cn } from "cn";

export const metadata: Metadata = { title: "Visor de chips" };

export default function ChipsIndexPage() {
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col justify-center gap-4 px-4 py-16">
      <p className="text-sm font-medium tracking-wide text-primary uppercase">Visor</p>
      <h1 className="font-heading text-4xl tracking-tight">Ningún chip seleccionado</h1>
      <p className="text-muted-foreground">
        Elige un evento del catálogo y abre una de las muestras Sentinel-1. El visor enseña el radar,
        pide la máscara a flood_segmentation_model y calcula el área inundada a 10 m. Si el servicio
        no responde, la ficha pasa a error; si el chip no está descargado, queda el estado vacío.
      </p>
      <div className="flex flex-wrap gap-2">
        <Link href="/eventos/bolivia" className={cn(buttonVariants())}>
          Ver Bolivia
        </Link>
        <Link href={`/chips/${sampleChips[0]?.chipId ?? ""}`} className={cn(buttonVariants({ variant: "outline" }))}>
          Abrir {sampleChips[0]?.chipId}
        </Link>
      </div>
    </main>
  );
}
