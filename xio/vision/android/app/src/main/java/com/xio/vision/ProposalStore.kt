package com.xio.vision

import android.content.Context
import java.io.File

/** Append-only local record. It stores proposals, never an automatic decision. */
class ProposalStore(private val context: Context) {
    private val fileName = "vision_proposals.jsonl"

    fun append(proposal: VisionProposal) {
        val labels = proposal.labels.joinToString(",") { label ->
            "{\"label\":\"${escape(label.label)}\",\"score\":${label.score}}"
        }
        val json = "{" +
            "\"proposalId\":\"${escape(proposal.proposalId)}\"," +
            "\"eventId\":\"${escape(proposal.eventId)}\"," +
            "\"capturedAtEpochMs\":${proposal.capturedAtEpochMs}," +
            "\"model\":\"${escape(proposal.model)}\"," +
            "\"requiresHumanReview\":${proposal.requiresHumanReview}," +
            "\"visualAttributes\":{" +
                "\"dominantColor\":\"${escape(proposal.visualAttributes.dominantColor)}\"," +
                "\"averageRed\":${proposal.visualAttributes.averageRed}," +
                "\"averageGreen\":${proposal.visualAttributes.averageGreen}," +
                "\"averageBlue\":${proposal.visualAttributes.averageBlue}," +
                "\"averageBrightness\":${proposal.visualAttributes.averageBrightness}," +
                "\"averageSaturation\":${proposal.visualAttributes.averageSaturation}" +
            "}," +
            "\"labels\":[${labels}]" +
            "}\n"
        context.openFileOutput(fileName, Context.MODE_APPEND).use { it.write(json.toByteArray()) }
    }

    fun appendAnnotation(
        captureId: String,
        substance: String?,
        form: String?,
        color: String?,
        marking: String?,
        notes: String?,
    ) {
        val json = "{" +
            "\"type\":\"human_annotation\"," +
            "\"captureId\":\"${escape(captureId)}\"," +
            "\"substance\":${jsonString(substance)}," +
            "\"form\":${jsonString(form)}," +
            "\"color\":${jsonString(color)}," +
            "\"marking\":${jsonString(marking)}," +
            "\"notes\":${jsonString(notes)}," +
            "\"annotatedAtEpochMs\":${System.currentTimeMillis()}" +
            "}\n"
        context.openFileOutput(fileName, Context.MODE_APPEND).use { it.write(json.toByteArray()) }
    }

    fun file(): File = File(context.filesDir, fileName)

    private fun escape(value: String): String = value.replace("\\", "\\\\").replace("\"", "\\\"")
    private fun jsonString(value: String?): String = value?.let { "\"${escape(it.trim())}\"" } ?: "null"
}
