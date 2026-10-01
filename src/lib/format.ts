const number = new Intl.NumberFormat("es-ES", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const integer = new Intl.NumberFormat("es-ES");

export function formatKm2(value: number) {
  return `${number.format(value)} km²`;
}

export function formatInteger(value: number) {
  return integer.format(value);
}

export function formatPercent(value: number) {
  return new Intl.NumberFormat("es-ES", {
    style: "percent",
    maximumFractionDigits: 1,
  }).format(value);
}

export function formatDb(value: number) {
  return `${number.format(value)} dB`;
}

export function formatScore(value: number) {
  return number.format(value);
}

export function gcsChipUrl(chipId: string, layer: "S1Hand" | "LabelHand") {
  return `https://storage.googleapis.com/sen1floods11/v1.1/data/flood_events/HandLabeled/${layer}/${chipId}_${layer}.tif`;
}
