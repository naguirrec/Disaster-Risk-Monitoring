export type Watch = {
  slug: string;
  nombre: string;
  lugar: string;
  resumen: string;
  lon: number;
  lat: number;
  vhThreshold: number;
  desde?: string;
  hasta?: string;
};

// Paiporta, not the centroid of the 2019 Sen1Floods11 polygon. That centroid
// falls in the Mediterranean. These watches ask for a scene that covers the town.
export const watches: Watch[] = [
  {
    slug: "dana-valencia",
    nombre: "DANA de Valencia",
    lugar: "Paiporta",
    resumen:
      "El 29 de octubre de 2024 la rambla del Poyo desbordó Paiporta. La búsqueda pide una escena Sentinel-1 de esos días que cubra el pueblo, y el recorte se centra ahí.",
    lon: -0.4164,
    lat: 39.4306,
    vhThreshold: -22.5,
    desde: "2024-10-26",
    hasta: "2024-11-08",
  },
  {
    slug: "valencia-ahora",
    nombre: "La misma calle, ahora",
    lugar: "Paiporta",
    resumen:
      "La última pasada de los últimos 120 días sobre el mismo punto. Sirve para comparar el radar de la crecida con el de una fecha reciente.",
    lon: -0.4164,
    lat: 39.4306,
    vhThreshold: -22.5,
  },
];
