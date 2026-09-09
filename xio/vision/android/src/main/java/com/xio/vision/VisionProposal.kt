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
    val requiresHumanReview: Boolean = true,
)

data class LabelScore(
    val label: String,
    val score: Float,
)
