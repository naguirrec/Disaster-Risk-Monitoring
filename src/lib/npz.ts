import { unzipSync } from "fflate";

export type NpyArray = {
  dtype: string;
  shape: number[];
  data: Uint8Array;
};

export function parseNpy(buf: Uint8Array): NpyArray {
  if (buf[0] !== 0x93 || buf[1] !== 0x4e || buf[2] !== 0x55) {
    throw new Error("El archivo no es un NPY.");
  }
  const major = buf[6];
  const view = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  const headerLen = major === 1 ? view.getUint16(8, true) : view.getUint32(8, true);
  const offset = (major === 1 ? 10 : 12) + headerLen;
  const header = new TextDecoder().decode(buf.subarray(offset - headerLen, offset));
  const descr = /'descr':\s*'([^']+)'/.exec(header)?.[1];
  if (!descr) throw new Error("NPY sin descr.");
  if (/'fortran_order':\s*True/.test(header)) {
    throw new Error("NPY en orden Fortran no soportado.");
  }
  const shapeRaw = /'shape':\s*\(([^)]*)\)/.exec(header)?.[1] ?? "";
  const shape = shapeRaw
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean)
    .map(Number);
  return { dtype: descr, shape, data: buf.subarray(offset) };
}

export function readNpz(bytes: Uint8Array) {
  const files = unzipSync(bytes);
  const arrays = new Map<string, NpyArray>();
  for (const [name, data] of Object.entries(files)) {
    if (!name.endsWith(".npy")) continue;
    arrays.set(name.replace(/\.npy$/, ""), parseNpy(data));
  }
  return arrays;
}

export function scalarFloat32(array: NpyArray) {
  const view = new DataView(array.data.buffer, array.data.byteOffset, array.data.byteLength);
  return view.getFloat32(0, true);
}

export function dequantize(values: Uint8Array, lo: number, hi: number) {
  const out = new Float32Array(values.length);
  const scale = (hi - lo) / 255;
  for (let i = 0; i < values.length; i++) out[i] = values[i] * scale + lo;
  return out;
}
