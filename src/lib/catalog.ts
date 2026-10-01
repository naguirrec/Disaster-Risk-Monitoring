import chipsJson from "@/data/chips.json";
import eventsJson from "@/data/events.json";

export type Polygon = {
  type: "Polygon";
  coordinates: number[][][];
};

export type FloodEvent = {
  id: number;
  slug: string;
  location: string;
  nombre: string;
  iso: string;
  prefix: string | null;
  s1Date: string;
  s2Date: string;
  s1DateEs: string;
  s2DateEs: string;
  orbit: string;
  orbitEs: string;
  relativeOrbit: number;
  vhThreshold: number;
  trainChipsMeta: number;
  valChipsMeta: number;
  coincidentSize: number;
  handLabeledCount: number;
  sampleCount: number;
  centroid: number[];
  bounds: number[];
  geometry: Polygon;
  hasHandLabels: boolean;
};

export type Chip = {
  chipId: string;
  eventSlug: string;
  nombre: string;
  location: string;
  prefix: string;
  s1DateEs: string;
  orbitEs: string;
  relativeOrbit: number;
  vhThreshold: number;
  bbox: number[];
  geometry: Polygon;
  waterPixels: number;
  validPixels: number;
  nodataPixels: number;
  waterFraction: number;
  referenceAreaKm2: number;
  hasFixture: boolean;
  role: "held_out" | "train" | null;
};

export const events = eventsJson as FloodEvent[];
export const chips = chipsJson as Chip[];

export const handLabeledEvents = events.filter((event) => event.hasHandLabels);
export const sampleChips = chips.filter((chip) => chip.hasFixture);

export function getEvent(slug: string) {
  return events.find((event) => event.slug === slug);
}

export function getChip(chipId: string) {
  return chips.find((chip) => chip.chipId === chipId);
}

export function chipsForEvent(slug: string) {
  return chips.filter((chip) => chip.eventSlug === slug);
}

export function eventsCollection() {
  return {
    type: "FeatureCollection" as const,
    features: events.map((event) => ({
      type: "Feature" as const,
      properties: {
        slug: event.slug,
        nombre: event.nombre,
        orbitEs: event.orbitEs,
        handLabeledCount: event.handLabeledCount,
      },
      geometry: event.geometry,
    })),
  };
}

export function chipsCollection(slug?: string) {
  const rows = slug ? chipsForEvent(slug) : sampleChips;
  return {
    type: "FeatureCollection" as const,
    features: rows.map((chip) => ({
      type: "Feature" as const,
      properties: {
        chipId: chip.chipId,
        eventSlug: chip.eventSlug,
        nombre: chip.nombre,
        hasFixture: chip.hasFixture ? 1 : 0,
      },
      geometry: chip.geometry,
    })),
  };
}

export const PIXEL_KM2 = 0.0001;
