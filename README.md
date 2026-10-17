# Monitor de inundaciones

Mesa de trabajo para los eventos de [Sen1Floods11](https://github.com/cloudtostreet/Sen1Floods11) (Cloud to Street, CVPR 2020). El catálogo muestra país, fecha de Sentinel-1 y órbita. El visor abre un chip SAR de 512×512 a 10 m, superpone la máscara de agua y estima el área inundada.

El caso es el del curso **Disaster Risk Monitoring Using Satellite Imagery** (NVIDIA Deep Learning Institute con UNOSAT, `course-v1:DLI+S-ES-01+V1`): segmentación píxel a píxel, agua o no agua, sobre radar Sentinel-1. Los notebooks del laboratorio no están aquí.

## Cómo se corresponde con el curso

| Paso del curso | En el laboratorio | En este repositorio |
| --- | --- | --- |
| Preproceso | NVIDIA DALI en GPU | Normalización en CPU. El perfil `nvidia` deja el pipeline DALI en `deploy/dali/preprocess.py` |
| Entrenamiento | TAO Toolkit, `unet`, ResNet-18, salida `.etlt` | U-Net pequeño en PyTorch, solo CPU. Plantilla TAO en `deploy/tao/unet_resnet18.yaml` |
| Despliegue | TensorRT → `model.plan` → Triton `flood_segmentation_model` | FastAPI con el mismo nombre de modelo y el contrato HTTP de Triton (imagen VV/VH en dB, máscara de probabilidad). No hay plan TensorRT |

El backend que responde de verdad está en `services/inference/model_card.json`. El servicio sigue cargando el U-Net de 22 chips (`services/inference/weights/flood_unet.pt`): en los mismos 11 chips apartados su IoU macro es 0,61, por delante del umbral VH (0,55). No es un modelo TAO ni un motor Triton.

## Qué cambió

El mapa ya no depende de abrir la página en `127.0.0.1`. Next, en desarrollo, bloquea los bundles de `/_next` si el host del navegador no está permitido, y sin esos bundles MapLibre no arranca. `allowedDevOrigins` incluye `127.0.0.1`, `localhost`, el nombre de esta máquina (`cursor`) y los hosts de preview de Cursor (`*.cursor.sh`, `*.cursor.com` y los equivalentes con `**`). El mapa base no lleva clave: CARTO Positron, y OpenFreeMap Positron si el estilo de CARTO no llega a cargar.

Se descargó solo el conjunto etiquetado a mano de Sen1Floods11: 446 chips, `S1Hand` y `LabelHand`, desde `https://storage.googleapis.com/sen1floods11/v1.1/data/flood_events/HandLabeled/`. No se bajó Sentinel-2, ni el conjunto débil, ni el bucket de unos 14 GB. Los GeoTIFF quedan en `data/raw/` y están en `.gitignore`.

Entrenar los 446 en CPU alarga demasiado el pase, así que el reentrenamiento usa un subconjunto estratificado de 122 chips (`data/metadata/train_split.json`). Hay chips de los 11 eventos con etiqueta manual, y se apartan los mismos 11 que el modelo anterior. Partiendo de esos pesos, 8 épocas y recortes de 256, el mejor IoU macro del fine-tune fue **0,591**. No supera el **0,610** del checkpoint de 22 chips y sí supera el umbral VH (**0,552**), así que el servicio que escucha en el puerto 43124 sigue sirviendo el modelo de 22 chips con el mismo contrato HTTP de Triton (`flood_segmentation_model`).

Copernicus Data Space queda listo y apagado hasta que existan credenciales. El proceso de inferencia lee `CDSE_USERNAME` y `CDSE_PASSWORD` del entorno y, si no están, de `.env` o `.env.local`. No se escriben en el repositorio. Con cuenta, la página `/copernicus` busca una escena Sentinel-1 GRD IW reciente sobre una huella del catálogo y, al descargarla, recorta un chip de 512×512 y lo pasa por el segmentador. Sin esas variables la página muestra ese vacío y el catálogo, el mapa y el visor siguen funcionando. En este entorno no había credenciales, así que no se descargó ninguna escena.

El zip del curso y los notebooks del laboratorio siguen fuera del repositorio.

## Cuenta de Copernicus en local

```bash
cp .env.example .env.local
```

Edita `.env.local` y deja los dos valores reales:

```text
CDSE_USERNAME=
CDSE_PASSWORD=
```

Reinicia el servicio de inferencia para que los lea. El cliente público es `cdse-public`, el token sale de `identity.dataspace.copernicus.eu` y el catálogo es el OData de `catalogue.dataspace.copernicus.eu`.

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

La demo no necesita el bucket entero. Los 446 GeoTIFF manuales usados para el reentrenamiento están en `data/raw/` y no se versionan. Tampoco se versionan las escenas que baje Copernicus (`data/copernicus/`).

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
