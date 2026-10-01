# flood_segmentation_model

Triton espera el motor en `1/model.plan`. Ese archivo no está en el repositorio: hay que exportarlo con TensorRT en la GPU de destino, a partir del `.etlt` de TAO, y colocarlo aquí antes de arrancar el perfil `nvidia`.

El servicio portable de este proyecto imita el contrato (nombre del modelo, imagen VV/VH de entrada, máscara de salida) sin cargar ese plan.
