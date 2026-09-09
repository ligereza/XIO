package com.xio.vision

import android.graphics.Bitmap
import android.graphics.Color
import kotlin.math.max

/**
 * Deterministic visual measurements used as observations and dataset features.
 * These features describe pixels; they do not identify a substance.
 */
object ColorFeatureExtractor {
    fun extract(bitmap: Bitmap): VisualAttributes {
        require(bitmap.width > 0 && bitmap.height > 0) { "bitmap must not be empty" }

        val stride = max(1, max(bitmap.width, bitmap.height) / 96)
        var count = 0
        var red = 0L
        var green = 0L
        var blue = 0L
        var brightness = 0.0
        var saturation = 0.0
        val hueBuckets = DoubleArray(8)
        var neutral = 0.0

        for (y in 0 until bitmap.height step stride) {
            for (x in 0 until bitmap.width step stride) {
                val pixel = bitmap.getPixel(x, y)
                val hsv = FloatArray(3)
                Color.colorToHSV(pixel, hsv)
                val r = Color.red(pixel)
                val g = Color.green(pixel)
                val b = Color.blue(pixel)
                red += r
                green += g
                blue += b
                brightness += hsv[2].toDouble()
                saturation += hsv[1].toDouble()
                if (hsv[1] < 0.14f) {
                    neutral += 1.0
                } else {
                    hueBuckets[((hsv[0] / 360f) * 8f).toInt().coerceIn(0, 7)] += 1.0
                }
                count++
            }
        }

        val dominantIndex = hueBuckets.indices.maxByOrNull { hueBuckets[it] } ?: 0
        val neutralRatio = neutral / count
        val dominantColor = when {
            brightness / count < 0.12 -> "negro"
            neutralRatio > 0.65 && brightness / count > 0.86 -> "blanco"
            neutralRatio > 0.65 -> "gris"
            else -> listOf("rojo", "naranjo", "amarillo", "verde", "cian", "azul", "morado", "rosado")[dominantIndex]
        }

        return VisualAttributes(
            dominantColor = dominantColor,
            averageRed = (red / count).toInt(),
            averageGreen = (green / count).toInt(),
            averageBlue = (blue / count).toInt(),
            averageBrightness = (brightness / count).toFloat(),
            averageSaturation = (saturation / count).toFloat(),
        )
    }
}
