const inferenceUrl = process.env.INFERENCE_URL ?? "http://127.0.0.1:43124";

export const maxDuration = 300;

export async function POST(request: Request) {
  const payload = await request.json().catch(() => null);
  if (!payload?.product_id || payload.lon == null || payload.lat == null) {
    return Response.json({ error: "Faltan la escena y el centro del evento." }, { status: 400 });
  }
  try {
    const response = await fetch(`${inferenceUrl}/cdse/segment`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        product_id: payload.product_id,
        lon: payload.lon,
        lat: payload.lat,
        vh_threshold: payload.vh_threshold,
        tiles: payload.tiles,
      }),
      cache: "no-store",
    });
    const body = await response.json();
    return Response.json(body, { status: response.status });
  } catch {
    return Response.json(
      { error: "No se pudo hablar con el servicio de inferencia." },
      { status: 503 },
    );
  }
}
