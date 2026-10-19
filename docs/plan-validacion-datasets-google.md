# Plan · Punto 3: validar y ampliar el modelo con los datasets abiertos de Google

> Brief para ejecutar con Cursor. Datos verificados el 19/10/2026. Lo marcado **por confirmar** no se ha comprobado.

## 1. Contexto

El repo segmenta agua en Sentinel-1 (VV/VH en dB) con una U-Net pequeña (`services/inference/`, umbral 0,5; IoU macro 0,61 en 11 chips apartados frente a 0,55 del umbral VH). El catálogo usa Sen1Floods11: 12 eventos de 2016 a 2019 y 22 chips locales en `data/fixtures/`. `/vigia` ya descarga escenas de Copernicus Data Space (`services/inference/cdse.py`), por ejemplo Paiporta en la DANA del 29/10/2024. Esa cifra **no está validada** contra ninguna referencia.

## 2. Objetivo

Usar datasets abiertos de Google, que no requieren aprobación de API, para:

1. **Encontrar inundaciones españolas** fuera de Sen1Floods11, sobre todo recientes (DANA de Valencia 2024), con **Groundsource**.
2. **Comparar las máscaras de la U-Net** con una referencia independiente: **Inundation History**.
3. (Opcional) Dar contexto hidrológico con **GRRR**.

## 3. Fuentes de datos

| Dataset | Dónde | Formato | Licencia |
| --- | --- | --- | --- |
| Groundsource (inundaciones extraídas de noticias, 2.646.302 registros, de 2000 a hoy) | https://zenodo.org/records/18647054 · DOI `10.5281/zenodo.18647054` · espejo: https://huggingface.co/datasets/stefan-it/Groundsource | Un único `groundsource_2026.parquet` (667,1 MB, md5 `cd1b5de6508f7aad8e1d1d0dd4cecea6`). Columnas: `uuid`, `area_km2`, `geometry` (WKB), `start_date`, `end_date`. **No trae columna de país**: el filtro por España tiene que ser espacial. | CC BY 4.0 |
| Inundation History (frecuencia con que cada píxel de 128 m estuvo mojado entre 1999 y 2020, derivada de GLAD) | Bucket público `gs://flood-forecasting/inundation_history/` (consola: https://console.cloud.google.com/storage/browser/flood-forecasting/inundation_history). Por HTTP: `https://storage.googleapis.com/flood-forecasting/inundation_history/data/<fichero>` | GeoJSON por celda (~83k km²). Nombre: `inundation_history_{min_lat}_{min_lng}_{max_lat}_{max_lng}.geojson`. Tres capas MultiPolygon: `High_risk` (≥5 % del tiempo), `Medium_risk` (≥1 %), `Low_risk` (≥0,5 %). Las masas de agua permanentes están quitadas. Cobertura: lat −39 a 43 y lng −125 a 170. **El norte de España por encima de 43° N queda fuera.** Celda de Valencia: `inundation_history_37.272_-2.460_39.981_0.000.geojson` | CC BY 4.0 (`LICENSE_CC-BY-4.0.txt` en el bucket) |
| GRRR (reanálisis de caudal 1980–2023 y reforecast 2016–2023) | `gs://flood-forecasting/hydrologic_predictions/model_id_8583a5c2_v0/` con `reanalysis/`, `reforecast/`, `return_periods.zarr/` y `hybas_outlet_locations_UNOFFICIAL.zarr/` | Zarr (estructura interna **por confirmar**) | CC BY 4.0 |

Más contexto: https://sites.research.google/gr/floodforecasting/resources/ · código: https://github.com/google-research/flood-forecasting

**Atribución obligatoria (CC BY 4.0)**, en la UI y en el README:
- Mayo, R. et al. (2026). *Groundsource: A Dataset of Flood Events from News*. Zenodo. https://doi.org/10.5281/zenodo.18647054
- Google Flood Forecasting, *Inundation History dataset*, CC BY 4.0, basado en GLAD.
- Google, *Google Runoff Reanalysis & Reforecast (GRRR)*, CC BY 4.0 (si se usa).

Aviso: Inundation History es una **climatología** de 1999 a 2020, no el mapa de un evento. No sirve como "verdad" para la DANA de 2024. Mide si la U-Net marca agua en zonas que se inundan a menudo y si da falsos positivos fuera de ellas. Para un IoU por evento hace falta una referencia del evento, como CEMS Rapid Mapping EMSR773 o GFM (ver preguntas abiertas).

## 4. Tareas

### T1. Ingesta de Groundsource
- `scripts/google_datasets/fetch_groundsource.py`: descarga el parquet desde Zenodo a `data/google/raw/` (no se versiona; añadir a `.gitignore`), comprueba el md5 y no vuelve a descargar si ya existe.
- Dependencias de script: `pyarrow`, `geopandas`, `shapely`. Mejor en `scripts/requirements.txt` que en `services/inference/requirements.txt`.

### T2. Filtrar eventos de España
- `scripts/google_datasets/filter_spain.py`: decodifica el WKB, interseca con el polígono de España peninsular y Baleares (fuente del límite **por confirmar**, por ejemplo Natural Earth admin-0) y se queda con eventos desde 2014-10 (inicio de Sentinel-1).
- Agrupa los registros contiguos en espacio y tiempo en "eventos". Prioriza por `area_km2` y número de registros.
- Salida versionada y pequeña: `data/metadata/groundsource_spain.geojson` (uuid, fechas, área, centroide en tierra).
- Comprobación: tiene que salir un evento en el entorno de Valencia entre el 29/10 y el 5/11/2024.

### T3. Emparejar con escenas de Sentinel-1
- Reutilizar `services/inference/cdse.py`: búsqueda OData de GRD IW cuyo footprint cubra el centroide, en la ventana `start_date − 3 d … end_date + 12 d`. También una escena "seca" de referencia del mismo track unos 30 días antes.
- Salida: `data/metadata/groundsource_spain_scenes.json` (evento → producto(s), órbita, fecha). Las escenas siguen yendo a `data/copernicus/`, sin versionar.

### T4. Segmentar
- `scripts/google_datasets/run_segmentation.py`: mismo mosaico 2×2 de 512 px que el vigía, llamando a `POST /v2/models/flood_segmentation_model/infer` (puerto 43124). Guarda la máscara georreferenciada (GeoTIFF o polígonos) en `data/google/masks/`, sin versionar.

### T5. Métricas frente a la referencia
- `scripts/google_datasets/evaluate.py`: rasteriza `High_risk` / `Medium_risk` de Inundation History a la rejilla de la máscara.
- Métricas por evento y por nivel de riesgo: IoU, precisión, recall y F1. Hacer lo mismo con el **baseline de umbral VH** para comparar como en `model_card.json`. Excluir agua permanente; la máscara JRC GSW queda **por confirmar** como fuente.
- Salida versionada: `data/metadata/google_validation.json` y un resumen en `services/inference/model_card.json` bajo una clave nueva `external_validation`, sin tocar las cifras existentes.

### T6. Interfaz
- Nueva sección en `/metodo` ("Validación con datos de Google"): tabla de métricas, nota de que es una climatología y no un mapa del evento, y atribuciones.
- Opcional: ruta `/eventos/es/[uuid]` o filtro en `/` para los eventos de Groundsource, con el mapa (`event-map.tsx`) mostrando la máscara U-Net sobre las capas de Inundation History.
- Datos para el front: `src/data/google_events.json`, generado por el script.

### Nota de diseño (obligatoria)
Cualquier UI nueva usa la escala tintada de la marca: de casi blanco a casi negro, con el tono de la marca, para fondos, superficies, bordes y texto. **Nunca grises puros.** Usar los tokens de `src/app/globals.css` (`--background` `oklch(0.965 0.012 95)`, `--card`, `--border`, `--foreground` `oklch(0.25 0.03 210)`, `--muted-foreground`…). No usar los `--chart-*`, `--sidebar-*` ni el tema `.dark` actual, que tienen croma 0 (grises puros): si hacen falta, retintarlos antes.

## 5. Criterios de aceptación
- [ ] `fetch_groundsource.py` descarga y verifica el md5. Una segunda ejecución no vuelve a descargar.
- [ ] `groundsource_spain.geojson` existe, pesa menos de 2 MB e incluye la DANA de Valencia 2024.
- [ ] Al menos 5 eventos españoles con escena Sentinel-1 emparejada, Paiporta 2024 incluido.
- [ ] `google_validation.json` con IoU, precisión y recall de U-Net y de umbral VH por evento.
- [ ] La sección de `/metodo` se ve en `http://127.0.0.1:43123/metodo` con atribución CC BY 4.0 y aviso de limitaciones.
- [ ] No se versionan datos crudos (parquet, GeoJSON de Inundation History, SAFE, máscaras).
- [ ] UI solo con tokens tintados; `npm run lint` pasa.

## 6. Preguntas abiertas
1. ¿Hace falta una referencia por evento para tener un IoU real? Candidatos: CEMS Rapid Mapping (activación de la DANA, código **por confirmar**) y GFM (`https://api.gfm.eodc.eu/v2/`, requiere registro).
2. Precisión espacial de Groundsource: el área media ronda 142 km². ¿Sirve como AOI o solo como fecha y centroide?
3. El norte peninsular (>43° N) queda fuera de Inundation History. ¿Se excluye o se busca otra referencia?
4. ¿Se usa GRRR? (Formato Zarr y variables **por confirmar**.)
5. ¿Los eventos nuevos sirven también para **reentrenar** o solo para validar? Si sirven para reentrenar, apartar los de validación para no filtrar datos.

## 7. Siguiente fase (cuando haya acceso a la API de Flood Forecasting)
- Acceso: lista de espera en https://developers.google.com/flood-forecasting. Después, clave de API y habilitar la API en un proyecto de Google Cloud. Uso principalmente no comercial. CC BY 4.0.
- Base `https://floodforecasting.googleapis.com/v1`. Endpoints previstos (nombres exactos y parámetros **por confirmar** en la doc de la API):
  - `gauges:searchGaugesByArea`: gauges dentro de un AOI de España.
  - `gauges:queryGaugeForecasts`: previsión de hasta 7 días por gauge.
  - `floodStatus:searchLatestFloodStatusByArea`: estado de alerta actual por zona.
  - `flashFloods:search`: avisos de crecida súbita urbana (24 h).
- Integración: un job (`services/inference/flood_watch.py`, **propuesto**) consulta el estado por AOI. Si hay alerta, crea una vigilancia en `src/lib/watches.ts` y dispara la búsqueda de la siguiente pasada Sentinel-1 en `/vigia` (`/api/copernicus/buscar` y luego `/segmentar`). La clave va en `.env.local` (`GOOGLE_FLOOD_API_KEY`), nunca en git.
