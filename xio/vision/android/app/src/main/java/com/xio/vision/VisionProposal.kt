package com.xio.vision

/**
 * Resultado de observación visual. No representa una decisión ni dispara acciones.
 */
data class VisionProposal(
    val proposalId: String,
    val eventId: String,
    val capturedAtEpochMs: Long,
    val labels: List<LabelScore>,
    val model: String,
    val visualAttributes: VisualAttributes,
    val requiresHumanReview: Boolean = true,
)

data class LabelScore(
    val label: String,
    val score: Float,
)

data class VisualAttributes(
    val dominantColor: String,
    val averageRed: Int,
    val averageGreen: Int,
    val averageBlue: Int,
    val averageBrightness: Float,
    val averageSaturation: Float,
)
