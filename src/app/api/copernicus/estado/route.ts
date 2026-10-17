const inferenceUrl = process.env.INFERENCE_URL ?? "http://127.0.0.1:43124";

export async function GET() {
  try {
    const response = await fetch(`${inferenceUrl}/cdse/status`, { cache: "no-store" });
    if (!response.ok) {
      return Response.json(
        {
          configured: false,
          inference: false,
          message: "El servicio de inferencia no confirma el estado de Copernicus.",
        },
        { status: 200 },
      );
    }
    const body = await response.json();
    return Response.json({ ...body, inference: true });
  } catch {
    return Response.json({
      configured: false,
      inference: false,
      message: "El servicio de inferencia no responde en el puerto 43124. El catálogo sigue disponible.",
    });
  }
}
