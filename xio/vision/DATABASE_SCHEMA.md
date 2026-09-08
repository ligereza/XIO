# Dataset local de XIO Vision

La captura es la unidad de trabajo. No se sobrescribe la predicción original cuando
la persona corrige el registro.

```text
events
  └── captures
        ├── model_predictions
        ├── human_annotations
        └── training_examples
```

## Flujo

1. La cámara devuelve un archivo JPEG de resolución útil; no se usa una miniatura como
   fuente de entrenamiento.
2. XIO crea `event_id`, `capture_id` y timestamp.
3. Guarda la imagen en el almacenamiento privado de la app y calcula SHA-256.
4. Ejecuta EfficientNet-Lite0 y guarda todas sus predicciones con ranking.
5. Calcula color dominante, RGB promedio, brillo y saturación.
6. La persona completa sustancia, forma/molde, color, marca/estampado y notas.
7. La anotación se guarda como una fila separada.
8. Esa relación crea un `training_example` con estado `candidate`.

## Tablas

- `events`: contexto temporal o evento de terreno.
- `captures`: imagen, hash, timestamp y medidas visuales.
- `model_predictions`: salida original del modelo, sin editar.
- `human_annotations`: ground truth introducido explícitamente por la persona.
- `training_examples`: cola de ejemplos candidatos para revisión y futura exportación.

## Decisiones de seguridad

- La imagen y SQLite quedan en el almacenamiento privado de la app.
- No hay sincronización de red ni entrenamiento automático.
- Una corrección humana no convierte la predicción en verdad química; sólo la etiqueta
  como dato anotado para revisión.
- Antes de entrenar se debe depurar duplicados, definir taxonomía, separar train/validation/test
  y aprobar una política de retención con RD.
