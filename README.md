# Monitor de inundaciones

Mesa de trabajo para los eventos de [Sen1Floods11](https://github.com/cloudtostreet/Sen1Floods11) (Cloud to Street, CVPR 2020). El catálogo muestra país, fecha de Sentinel-1 y órbita. El visor abre un chip SAR de 512×512 a 10 m, superpone la máscara de agua y estima el área inundada.

El caso es el del curso **Disaster Risk Monitoring Using Satellite Imagery** (NVIDIA Deep Learning Institute con UNOSAT, `course-v1:DLI+S-ES-01+V1`): segmentación píxel a píxel, agua o no agua, sobre radar Sentinel-1. Los notebooks del laboratorio no están aquí.

## Cómo se corresponde con el curso

| Paso del curso | En el laboratorio | En este repositorio |
| --- | --- | --- |
| Preproceso | NVIDIA DALI en GPU | Normalización en CPU. El perfil `nvidia` deja el pipeline DALI en `deploy/dali/preprocess.py` |
| Entrenamiento | TAO Toolkit, `unet`, ResNet-18, salida `.etlt` | U-Net pequeño en PyTorch, solo CPU, sobre un puñado de chips públicos. Plantilla TAO en `deploy/tao/unet_resnet18.yaml` |
| Despliegue | TensorRT → `model.plan` → Triton `flood_segmentation_model` | FastAPI con el mismo nombre de modelo y el contrato HTTP de Triton (imagen VV/VH en dB, máscara de probabilidad). No hay plan TensorRT |

El backend que responde de verdad está en `services/inference/model_card.json`. En esta muestra el U-Net pequeño queda por delante del umbral VH (IoU macro 0,61 frente a 0,55 en 11 chips apartados), así que el servicio carga `services/inference/weights/flood_unet.pt`. Si en otro entrenamiento no supera el umbral, el mismo proceso pasa a devolver `VH < VH_thresh` del evento. No es un modelo TAO ni un motor Triton.

## Datos

Bucket público: `gs://sen1floods11/v1.1/` (HTTPS `https://storage.googleapis.com/sen1floods11/v1.1/`).

En el repositorio:

- `data/metadata/Sen1Floods11_Metadata.geojson` — los 12 polígonos de evento (país, fechas, órbita, umbral VH).
- `data/metadata/chips.geojson` — huellas de los 446 chips etiquetados a mano, reconstruidas desde el catálogo STAC v1.1.
- `data/fixtures/*.npz` — 22 chips (dos por evento manual): VV, VH en 8 bits y la etiqueta.
- `public/previews/*.jpg` — vista del canal VH.

La metadata v1.1 lista también Colombia. Ese evento no tiene chips en la colección manual; la ficha lo dice.

Escala de la fixture: VV de −30 a 0 dB y VH de −40 a −5 dB, lineales en `uint8`. El umbral de cada evento (entre unos −25 y −19 dB) cae dentro de la ventana VH, así que la decisión del umbral se conserva salvo en el paso de cuantización (~0,14 dB).

### Qué no se descargó

- **`CNN_Chips_FTC.geojson` no está en el bucket v1.1.** Estas URLs responden 404:

  - `https://storage.googleapis.com/sen1floods11/v1.1/CNN_Chips_FTC.geojson`
  - `https://storage.googleapis.com/sen1floods11/CNN_Chips_FTC.geojson`
  - `https://storage.googleapis.com/cnn_chips/CNN_Chips_FTC.geojson`

  Las huellas equivalentes están en `data/metadata/chips.geojson`.

- El resto del dataset (~14 GB): Sentinel-2, etiquetas débiles, agua permanente de JRC y los checkpoints. Para clonar el bucket hace falta `gsutil` y espacio:

  ```bash
  gsutil -m rsync -r gs://sen1floods11/v1.1 /ruta/local
  ```

La demo no necesita esa descarga. Los GeoTIFF crudos usados para entrenar están en `data/raw/` y no se versionan.

Para ampliar la muestra, los chips siguen este patrón (ejemplo Bolivia):

```text
https://storage.googleapis.com/sen1floods11/v1.1/data/flood_events/HandLabeled/S1Hand/Bolivia_242570_S1Hand.tif
https://storage.googleapis.com/sen1floods11/v1.1/data/flood_events/HandLabeled/LabelHand/Bolivia_242570_LabelHand.tif
```

La lista de la muestra local está en `data/fixtures/manifest.json`. `scripts/prepare_catalog.py` regenera el catálogo si el caché de descarga está en `/tmp/sen1`.

## Arranque en local

Hacen falta Node 22 y Python 3.12.

```bash
npm install
python3 -m pip install -r services/inference/requirements.txt
python3 -m uvicorn server:app --app-dir services/inference --host 0.0.0.0 --port 43124
npm run dev
```

La web queda en [http://127.0.0.1:43123](http://127.0.0.1:43123). El visor llama a `POST /api/segmentar`, que reenvía el chip al contrato Triton del puerto 43124.

Contrato del servicio:

- `GET /v2/health/ready`
- `GET /v2/models/flood_segmentation_model`
- `POST /v2/models/flood_segmentation_model/infer`

La entrada `input` es `FP32` con forma `[1, 2, 512, 512]` (VV, VH en dB). La salida `output` es `FP32` `[1, 1, 512, 512]`, probabilidad de agua. El cuerpo usa la extensión binaria de Triton (`Inference-Header-Content-Length`). El umbral del evento viaja en la entrada opcional `vh_threshold`; solo la usa el backend de umbral.

## Docker

```bash
docker compose --profile cpu up --build
```

Eso construye la web (puerto 43123) y el servicio portable (puerto 43124).

El perfil de GPU no se levanta solo y no va a arrancar sin NVIDIA, sin `docker login nvcr.io` y sin un `model.plan` montado en `deploy/triton/model_repository/flood_segmentation_model/1/`:

```bash
docker compose --profile nvidia up
```

Ese perfil documenta DALI → TAO U-Net ResNet-18 → TensorRT → Triton. No incluye los notebooks ni los pesos del curso.

## Cita del dataset

Bonafilia, D., Tellman, B., Anderson, T., Issenberg, E. 2020. Sen1Floods11: a georeferenced dataset to train and test deep learning flood algorithms for Sentinel-1. CVPR Workshops, 2020.
