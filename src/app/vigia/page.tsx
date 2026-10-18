import type { Metadata } from "next";
import { VigiaDesk } from "@/components/vigia-desk";
import { watches } from "@/lib/watches";

export const metadata: Metadata = {
  title: "Vigía",
  description:
    "Escenas Sentinel-1 recientes o de la DANA de Valencia, calibradas y colocadas sobre el mapa.",
};

export default function VigiaPage() {
  return <VigiaDesk watches={watches} />;
}
