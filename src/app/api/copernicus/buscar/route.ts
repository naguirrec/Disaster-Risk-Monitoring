const inferenceUrl = process.env.INFERENCE_URL ?? "http://127.0.0.1:43124";

export async function POST(request: Request) {
  const payload = await request.json().catch(() => null);
  if (!payload || !Array.isArray(payload.bounds)) {
    return Response.json({ error: "Falta la huella del evento." }, { status: 400 });
  }
  try {
    const response = await fetch(`${inferenceUrl}/cdse/search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bounds: payload.bounds }),
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
