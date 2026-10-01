import type { Metadata } from "next";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export const metadata: Metadata = { title: "Método" };

const steps = [
  {
    title: "Preproceso",
    course: "NVIDIA DALI en GPU: decode, recorte y normalización de los tiles.",
    here: "En esta máquina el chip ya viene a 512×512. La fixture guarda VV y VH cuantizados a 8 bits, y el servicio los devuelve a decibelios antes de segmentar.",
  },
  {
    title: "Entrenamiento",
    course: "TAO Toolkit, tarea unet, backbone ResNet-18, salida portable .etlt.",
    here: "Se entrena un U-Net pequeño en PyTorch, solo CPU, con un puñado de chips públicos. Si no mejora el umbral VH de la metadata, ese umbral es el que responde.",
  },
  {
    title: "Despliegue",
    course: "TensorRT genera un .plan de la GPU y Triton lo sirve como flood_segmentation_model.",
    here: "Un proceso FastAPI expone el mismo nombre de modelo y el mismo contrato HTTP de Triton (imagen de entrada, máscara de salida). No hay motor TensorRT cargado.",
  },
];

export default function MethodPage() {
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-4 py-8">
      <div>
        <p className="text-sm font-medium tracking-wide text-primary uppercase">Curso y réplica</p>
        <h1 className="mt-2 font-heading text-4xl tracking-tight">El mismo flujo, sin fingir la GPU</h1>
        <p className="mt-3 text-muted-foreground">
          El curso es Disaster Risk Monitoring Using Satellite Imagery, de NVIDIA Deep Learning
          Institute con UNOSAT. El identificador que usan los alumnos es course-v1:DLI+S-ES-01+V1.
          El caso es uno: inundación, segmentación píxel a píxel sobre Sentinel-1. Los notebooks del
          laboratorio no están en este repositorio.
        </p>
      </div>
      <ol className="flex flex-col gap-3">
        {steps.map((step, index) => (
          <li key={step.title}>
            <Card>
              <CardHeader>
                <CardTitle>
                  0{index + 1} {step.title}
                </CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-2 text-sm">
                <p>
                  <span className="font-medium">En el curso. </span>
                  {step.course}
                </p>
                <p>
                  <span className="font-medium">Aquí. </span>
                  {step.here}
                </p>
              </CardContent>
            </Card>
          </li>
        ))}
      </ol>
      <p className="text-sm text-muted-foreground">
        El perfil Docker <code>nvidia</code> deja escrito el camino DALI, TAO, TensorRT y Triton
        para cuando haya una GPU NVIDIA y sesión en NGC. El perfil <code>cpu</code> levanta esta
        web y el servicio portable. El detalle de arranque está en el README.
      </p>
    </main>
  );
}
