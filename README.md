# Monitor de inundaciones

Una mesa de trabajo para ver agua en radar Sentinel-1. El objetivo es poder señalar un lugar, pedir la escena que lo cubre y estimar cuánta superficie está en agua, con el mismo tipo de decisión que enseña el curso **Disaster Risk Monitoring Using Satellite Imagery** (NVIDIA Deep Learning Institute con UNOSAT, `course-v1:DLI+S-ES-01+V1`): cada píxel es agua o no lo es.

No es un sistema de alerta ni mide la altura de la lámina de agua. Sentinel-1 no es un altímetro. Mide el rebote del radar. Esta web convierte ese rebote en una máscara y en kilómetros cuadrados, y la pone encima del mapa.

Hay dos usos.

El **catálogo** recorre inundaciones ya etiquetadas, entre 2016 y 2019, del conjunto [Sen1Floods11](https://github.com/cloudtostreet/Sen1Floods11). Sirve para ver de qué aprendió el modelo y cuánto se parece su máscara a la etiqueta hecha a mano.

El **vigía** (`/vigia`) sale de ese archivo. Pide una escena posterior a Copernicus Data Space, la calibra, la coloca en el sitio real y mide el agua. El caso que trae es Paiporta en la DANA del 29 de octubre de 2024, y el mismo punto en una pasada de los últimos 120 días. El recuadro del radar se puede hacer transparente para ver las calles debajo.

## Qué mide

Sentinel-1 es un radar de banda C. Una escena GRD en modo IW trae dos imágenes de la misma pasada:

- **VV**: la señal se envió y se recibió en polarización vertical.
- **VH**: se envió en vertical y se recibió en horizontal.

El número que guarda el GeoTIFF no está en decibelios. Es una cuenta digital. El producto incluye una tabla de calibración `sigmaNought`. Con ella se pasa a coeficiente de retrodispersión:

```text
sigma0 = DN² / Aσ²
dB     = 10 · log10(sigma0)
```

`Aσ` es el valor de esa tabla en el píxel. El agua lisa desvía el pulso lejos del satélite, así que devuelve poco y sale oscura, sobre todo en VH. El suelo rugoso, el cultivo y la ciudad devuelven más. Esa diferencia es lo que se usa. No hay una cota de agua en metros.

La decisión de cada píxel es binaria. El modelo devuelve una probabilidad. A partir de 0,5 el píxel cuenta como agua. Cada píxel de estas escenas mide 10 m × 10 m, así que el área es el número de píxeles de agua por 0,0001 km². Al lado se calcula la misma área con la regla simple del curso: agua donde VH, ya en dB, queda por debajo del umbral del lugar. Las dos cifras se enseñan juntas para no confundir el modelo con esa regla.

## De dónde salen los datos

**Sen1Floods11**, para aprender y para el catálogo. Son crecidas observadas entre 2016 y 2019. En el repositorio está la metadata de 12 eventos y la huella de 446 chips etiquetados a mano. La muestra que el visor puede segmentar sin descargar nada son 22 chips (dos por evento con etiqueta manual), en `data/fixtures/`. El bucket público es `https://storage.googleapis.com/sen1floods11/v1.1/`. No se versiona el resto del dataset, de unos 14 GB.

**Copernicus Data Space**, para cualquier fecha posterior, incluida la DANA de 2024. Con `CDSE_USERNAME` y `CDSE_PASSWORD` el servicio pide un token a `identity.dataspace.copernicus.eu` (cliente público `cdse-public`), busca en el OData de `catalogue.dataspace.copernicus.eu` y descarga el producto desde `zipper.dataspace.copernicus.eu`. La búsqueda del vigía no usa el polígono histórico: pide escenas GRD IW cuyo footprint cubra el pueblo. En Paiporta, la ventana de la crecida es del 26 de octubre al 8 de noviembre de 2024. La otra opción son los últimos 120 días sobre el mismo punto. Las escenas descargadas quedan en `data/copernicus/` y no se suben a git. Una escena pesa cerca de 1,7 GB; de ella se guardan las mediciones VV y VH y sus XML de calibración.

Las contraseñas no se escriben en el repositorio. El proceso las lee del entorno y, si ahí no están, de `.env` o `.env.local`.

## Cómo se procesa una escena nueva

1. Se elige un punto en tierra. El centroide del polígono de España en Sen1Floods11 cae en el Mediterráneo; por eso el vigía no lo usa.
2. El catálogo OData devuelve las pasadas que cortan ese punto.
3. Se descarga el SAFE y se leen los GeoTIFF de VV y VH. Esos TIFF no traen una transformación geográfica útil: la posición va en unos 200 puntos de control (GCP). Con los seis más cercanos se estima la fila y la columna del pueblo. Si el punto cae fuera de la escena, se dice y no se recorta una esquina al azar.
4. Se toma un mosaico de 2×2 chips de 512×512, unos 10,2 km de lado, centrado en el pueblo.
5. Cada canal se calibra a dB con su tabla `sigmaNought`.
6. El U-Net clasifica cada chip. La máscara es la probabilidad ≥ 0,5.
7. Las cuatro esquinas del mosaico se vuelven a pasar a longitud y latitud con los mismos GCP. El radar no mira al norte, así que el recuadro sale girado sobre el mapa.
8. Se pintan dos capas: un falso color (rojo VV, verde VH, azul el cociente VV/VH, con ventanas fijas en dB para que dos fechas se puedan comparar) y la máscara de agua, en cian y con el resto transparente.

El falso color no es una foto. El verde domina porque VH ocupa el canal verde. En la esquina del mapa hay dos controles. **Radar** baja la opacidad del falso color hasta dejar ver las calles. **Máscara** baja solo el velo de agua. Son capas propias del vigía: no tocan el mar que ya dibuja el mapa base.

## Qué hace cada página

| Ruta | Para qué |
| --- | --- |
| `/` | Los 12 eventos del catálogo y el mapa de huellas. El ámbar marca los chips que sí están en la muestra local. |
| `/eventos/[slug]` | Un evento: fecha de Sentinel-1, órbita, umbral VH y sus chips. |
| `/chips` y `/chips/[chipId]` | El visor. Sobre el VH estirado superpone la máscara, estima el área y, si hay etiqueta, el IoU contra esa etiqueta. La opacidad de la máscara se puede bajar. |
| `/vigia` | El caso operativo. Busca la pasada, mide, coloca el radar girado sobre el pueblo y deja regular por separado la opacidad del radar y la de la máscara. |
| `/copernicus` | La búsqueda anterior, sobre una huella del catálogo de 2016–2019, con un solo chip. |
| `/metodo` | En qué se parece esto al laboratorio del curso y en qué no. |

## El modelo

El servicio se llama `flood_segmentation_model`, igual que en el curso, y habla el contrato HTTP de Triton: entra `float32` `[1, 2, 512, 512]` (VV y VH en dB) y sale `float32` `[1, 1, 512, 512]`, la probabilidad de agua. Lo implementa un proceso FastAPI. No hay un motor TensorRT ni un servidor Triton cargado.

La red es una U-Net pequeña, sin el ResNet-18 del curso. Los pesos que responde son los entrenados con 22 chips (`services/inference/weights/flood_unet.pt`). En 11 chips apartados, el IoU macro es **0,61**. Un reentrenamiento con 122 chips, 8 épocas y recortes de 256 llegó a **0,59**. Otro, en la GPU, con 354 chips a 512, pérdida BCE+Dice y las crecidas de España y Ghana enteras apartadas, sube esas crecidas (España de 0,35 a 0,49, Ghana de 0,37 a 0,58) pero en los 11 chips baja a **0,57**, así que tampoco sustituye al de 22 chips. Los dos superan el umbral VH en esos 11 chips (**0,55**). Las cifras están en `services/inference/model_card.json`. El modelo aprendió con inundaciones de 2016–2019. Aplicarlo a 2024 es una transferencia: la cifra de Paiporta es una estimación, no una validación contra un mapa oficial de la DANA.

La normalización que ve la red es fija: VV de −25 a 0 dB y VH de −35 a −5 dB. El umbral VH del evento solo lo usa el backend de reserva, el que clasifica por umbral si no hay pesos.

## Cómo se corresponde con el curso

| Paso del curso | En el laboratorio | Aquí |
| --- | --- | --- |
| Preproceso | NVIDIA DALI en GPU | Calibración a dB y la normalización de arriba, en CPU. El perfil `nvidia` deja el pipeline DALI en `deploy/dali/preprocess.py`. |
| Entrenamiento | TAO Toolkit, `unet`, ResNet-18, salida `.etlt` | U-Net pequeño en PyTorch. Usa la GPU NVIDIA si `torch.cuda` la ve, y si no la CPU. Plantilla TAO en `deploy/tao/unet_resnet18.yaml`. |
| Despliegue | TensorRT, `model.plan`, Triton | El mismo nombre de modelo y el mismo contrato HTTP. No hay `model.plan`. |

Los notebooks del laboratorio no están en el repositorio y no se redistribuyen. El perfil Docker `nvidia` documenta el camino DALI → TAO → TensorRT → Triton para cuando haya GPU NVIDIA, sesión en NGC y un `model.plan` compilado en esa misma GPU.

## Arranque en local

Hacen falta Node 22 y Python 3.12.

```bash
cp .env.example .env.local
npm install
python3 -m pip install -r services/inference/requirements.txt
python3 -m uvicorn server:app --app-dir services/inference --host 0.0.0.0 --port 43124
npm run dev
```

En `.env.local` van el usuario y la contraseña de Copernicus Data Space. Sin ellos el catálogo y el visor siguen funcionando; el vigía dice que le falta la cuenta.

La web queda en [http://127.0.0.1:43123](http://127.0.0.1:43123). El visor llama a `POST /api/segmentar`. El vigía llama a `POST /api/copernicus/buscar` y `POST /api/copernicus/segmentar`. Esas rutas reenvían al proceso del puerto 43124.

Contrato del servicio:

- `GET /v2/health/ready`
- `GET /v2/models/flood_segmentation_model`
- `POST /v2/models/flood_segmentation_model/infer`

El cuerpo de la inferencia usa la extensión binaria de Triton (`Inference-Header-Content-Length`). El umbral del evento viaja en la entrada opcional `vh_threshold`.

El mapa base no lleva clave: CARTO Positron y, si ese estilo no carga, OpenFreeMap Positron. El worker de MapLibre se sirve desde `public/maplibre-gl-worker.mjs`. En desarrollo, `allowedDevOrigins` incluye `127.0.0.1`, `localhost` y los hosts de preview; si el host no está permitido, Next no entrega los bundles y el mapa se queda en blanco.

## Docker

```bash
docker compose --profile cpu up --build
```

Eso construye la web (puerto 43123) y el servicio portable (puerto 43124).

```bash
docker compose --profile nvidia up
```

Ese perfil no arranca solo. Pide GPU NVIDIA, `docker login nvcr.io` y un `model.plan` en `deploy/triton/model_repository/flood_segmentation_model/1/`.

## Qué hay del dataset en el repositorio

- `data/metadata/Sen1Floods11_Metadata.geojson` — 12 polígonos de evento: país, fechas, órbita y umbral VH. Colombia está en la metadata y no tiene chips en la colección manual.
- `data/metadata/chips.geojson` — huellas de los 446 chips etiquetados a mano.
- `data/fixtures/*.npz` — los 22 chips de la muestra: VV y VH en 8 bits, y la etiqueta.
- `public/previews/*.jpg` — el canal VH para el visor.

En la fixture, VV va de −30 a 0 dB y VH de −40 a −5 dB, lineales en `uint8`. El umbral de cada evento queda dentro de esa ventana VH. El paso de cuantización es de unos 0,14 dB.

`CNN_Chips_FTC.geojson` no está en el bucket v1.1 (esas URL responden 404). Las huellas equivalentes están en `data/metadata/chips.geojson`. Los GeoTIFF de los 446 chips, si se descargan para reentrenar, van a `data/raw/` y tampoco se versionan.

La lista de la muestra local está en `data/fixtures/manifest.json`. `scripts/prepare_catalog.py` regenera el catálogo si el caché de descarga está en `/tmp/sen1`.

## Cita

Bonafilia, D., Tellman, B., Anderson, T., Issenberg, E. 2020. Sen1Floods11: a georeferenced dataset to train and test deep learning flood algorithms for Sentinel-1. CVPR Workshops, 2020.
