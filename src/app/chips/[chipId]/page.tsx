import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ChipViewer } from "@/components/chip-viewer";
import { getChip, sampleChips } from "@/lib/catalog";

export function generateStaticParams() {
  return sampleChips.map((chip) => ({ chipId: chip.chipId }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ chipId: string }>;
}): Promise<Metadata> {
  const { chipId } = await params;
  return { title: chipId };
}

export default async function ChipPage({
  params,
}: {
  params: Promise<{ chipId: string }>;
}) {
  const { chipId } = await params;
  const chip = getChip(chipId);
  if (!chip) notFound();

  return (
    <main className="mx-auto flex w-full max-w-7xl flex-1 flex-col gap-4 px-4 py-6 lg:px-6">
      <div>
        <Link href={`/eventos/${chip.eventSlug}`} className="text-sm text-muted-foreground hover:text-foreground">
          {chip.nombre}
        </Link>
        <h1 className="mt-1 font-heading text-3xl tracking-tight sm:text-4xl">{chip.chipId}</h1>
        <p className="text-muted-foreground">
          Chip Sentinel-1 de 512×512 a 10 m. Huella tomada del catálogo STAC v1.1.
        </p>
      </div>
      <ChipViewer key={chip.chipId} chip={chip} />
    </main>
  );
}
