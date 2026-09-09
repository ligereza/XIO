package com.xio.vision

import android.content.Context
import android.graphics.Bitmap
import com.google.mediapipe.framework.image.BitmapImageBuilder
import com.google.mediapipe.tasks.core.BaseOptions
import com.google.mediapipe.tasks.vision.imageclassifier.ImageClassifier
import java.util.UUID

/**
 * Adaptador offline para XIO. La app debe copiar el modelo a assets y entregar un eventId.
 * La salida es una propuesta auditable; esta clase no confirma muestras ni ejecuta acciones.
 */
class OfflineImageClassifier(
    context: Context,
    modelAssetName: String = "efficientnet_lite0.tflite",
    private val maxResults: Int = 5,
) : AutoCloseable {

    private val classifier: ImageClassifier

    init {
        val baseOptions = BaseOptions.builder()
            .setModelAssetPath(modelAssetName)
            .build()

        val options = ImageClassifier.ImageClassifierOptions.builder()
            .setBaseOptions(baseOptions)
            .setMaxResults(maxResults)
            .build()

        classifier = ImageClassifier.createFromOptions(context, options)
    }

    fun classify(eventId: String, bitmap: Bitmap, capturedAtEpochMs: Long = System.currentTimeMillis()): VisionProposal {
        require(eventId.isNotBlank()) { "eventId must not be blank" }

        val image = BitmapImageBuilder(bitmap).build()
        val result = classifier.classify(image)
        val categories = result.classificationResult()
            .classifications()
            .firstOrNull()
            ?.categories()
            .orEmpty()

        return VisionProposal(
            proposalId = UUID.randomUUID().toString(),
            eventId = eventId,
            capturedAtEpochMs = capturedAtEpochMs,
            labels = categories.map { category ->
                LabelScore(
                    label = category.categoryName() ?: category.displayName() ?: "unknown",
                    score = category.score(),
                )
            },
            model = "efficientnet_lite0.tflite",
            visualAttributes = ColorFeatureExtractor.extract(bitmap),
        )
    }

    override fun close() {
        classifier.close()
    }
}
