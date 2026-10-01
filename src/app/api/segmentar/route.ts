import { readFile } from "node:fs/promises";
import path from "node:path";
import { PNG } from "pngjs";
import { getChip, PIXEL_KM2 } from "@/lib/catalog";
import { dequantize, readNpz, scalarFloat32 } from "@/lib/npz";

export const runtime = "nodejs";

const MODEL = "flood_segmentation_model";

function backendLabel(backend: string) {
  if (backend === "pytorch_unet") return "U-Net PyTorch (CPU)";
  return "Umbral VH de la metadata";
}

export async function POST(request: Request) {
  const body = await request.json().catch(() => null);
  const chipId = body?.chipId;
  if (typeof chipId !== "string" || !/^[A-Za-z0-9_-]+$/.test(chipId)) {
    return Response.json({ error: "Identificador de chip no válido." }, { status: 400 });
  }

  const fixturesDir = path.join(process.cwd(), "data", "fixtures");
  const filePath = path.join(fixturesDir, `${chipId}.npz`);
  if (path.dirname(filePath) !== fixturesDir) {
    return Response.json({ error: "Ruta de chip rechazada." }, { status: 400 });
  }

  let bytes: Buffer;
  try {
    bytes = await readFile(filePath);
  } catch {
    return Response.json(
      {
        error: `${chipId} no está en la muestra local. Descarga el GeoTIFF público y regenera las fixtures.`,
      },
      { status: 404 },
    );
  }

  const npz = readNpz(bytes);
  const vv = npz.get("vv");
  const vh = npz.get("vh");
  const label = npz.get("label");
  const vvLo = npz.get("vv_lo");
  const vvHi = npz.get("vv_hi");
  const vhLo = npz.get("vh_lo");
  const vhHi = npz.get("vh_hi");
  if (!vv || !vh || !label || !vvLo || !vvHi || !vhLo || !vhHi) {
    return Response.json({ error: "La fixture del chip está incompleta." }, { status: 500 });
  }

  const vvDb = dequantize(vv.data, scalarFloat32(vvLo), scalarFloat32(vvHi));
  const vhDb = dequantize(vh.data, scalarFloat32(vhLo), scalarFloat32(vhHi));
  const labels = new Int8Array(label.data);
  const pixels = vvDb.length;
  const tensor = Buffer.alloc(pixels * 2 * 4);
  const view = new DataView(tensor.buffer);
  for (let i = 0; i < pixels; i++) view.setFloat32(i * 4, vvDb[i], true);
  for (let i = 0; i < pixels; i++) view.setFloat32((pixels + i) * 4, vhDb[i], true);

  const chip = getChip(chipId);
  const vhThreshold = chip?.vhThreshold ?? -21.69;
  const threshold = Buffer.alloc(4);
  new DataView(threshold.buffer).setFloat32(0, vhThreshold, true);

  const header = {
    inputs: [
      {
        name: "input",
        shape: [1, 2, 512, 512],
        datatype: "FP32",
        parameters: { binary_data_size: tensor.length },
      },
      {
        name: "vh_threshold",
        shape: [1],
        datatype: "FP32",
        parameters: { binary_data_size: 4 },
      },
    ],
    outputs: [{ name: "output", parameters: { binary_data: true } }],
  };
  const headerBytes = Buffer.from(JSON.stringify(header));
  const inferenceUrl = process.env.INFERENCE_URL ?? "http://127.0.0.1:43124";

  let upstream: Response;
  try {
    upstream = await fetch(`${inferenceUrl}/v2/models/${MODEL}/infer`, {
      method: "POST",
      headers: {
        "inference-header-content-length": String(headerBytes.length),
        "content-type": "application/octet-stream",
      },
      body: Buffer.concat([headerBytes, tensor, threshold]),
      signal: AbortSignal.timeout(60_000),
    });
  } catch {
    return Response.json(
      {
        error: `El servicio de inferencia no responde en ${inferenceUrl}.`,
      },
      { status: 503 },
    );
  }

  if (!upstream.ok) {
    const detail = await upstream.text();
    return Response.json(
      { error: detail || "La inferencia rechazó el chip." },
      { status: 502 },
    );
  }

  const responseBytes = Buffer.from(await upstream.arrayBuffer());
  const responseHeaderLen = Number(upstream.headers.get("inference-header-content-length"));
  if (!responseHeaderLen) {
    return Response.json({ error: "La respuesta de inferencia no trae cabecera Triton." }, { status: 502 });
  }
  const meta = JSON.parse(responseBytes.subarray(0, responseHeaderLen).toString()) as {
    model_name: string;
    model_version: string;
    parameters?: { backend?: string; vh_threshold?: number };
  };
  const rawMask = responseBytes.subarray(responseHeaderLen);
  const aligned = new Uint8Array(rawMask.byteLength);
  aligned.set(rawMask);
  const probability = new Float32Array(aligned.buffer);

  let waterPixels = 0;
  let validPixels = 0;
  let referenceWaterPixels = 0;
  let tp = 0;
  let fp = 0;
  let fn = 0;
  const png = new PNG({ width: 512, height: 512 });
  for (let i = 0; i < probability.length; i++) {
    const nodata = labels[i] === -1;
    const truth = labels[i] === 1;
    const predicted = probability[i] >= 0.5;
    const offset = i * 4;
    if (!nodata) {
      validPixels += 1;
      if (truth) referenceWaterPixels += 1;
      if (predicted) waterPixels += 1;
      if (predicted && truth) tp += 1;
      else if (predicted && !truth) fp += 1;
      else if (!predicted && truth) fn += 1;
    }
    if (predicted && !nodata) {
      png.data[offset] = 20;
      png.data[offset + 1] = 168;
      png.data[offset + 2] = 176;
      png.data[offset + 3] = 210;
    }
  }
  const denom = tp + fp + fn;
  const backend = meta.parameters?.backend ?? "vh_threshold";

  return Response.json({
    chipId,
    modelName: meta.model_name,
    modelVersion: meta.model_version,
    backend,
    backendLabel: backendLabel(backend),
    vhThreshold: Number((meta.parameters?.vh_threshold ?? vhThreshold).toFixed(2)),
    waterPixels,
    validPixels,
    areaKm2: waterPixels * PIXEL_KM2,
    referenceWaterPixels,
    referenceAreaKm2: referenceWaterPixels * PIXEL_KM2,
    iou: denom === 0 ? 1 : tp / denom,
    maskPng: `data:image/png;base64,${PNG.sync.write(png).toString("base64")}`,
  });
}
