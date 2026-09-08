package com.xio.vision

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper

/**
 * Private, local-first dataset store. Raw observations and human annotations are
 * separate rows so a later correction never erases what the model originally said.
 */
class CaptureDatabase(context: Context) : SQLiteOpenHelper(context, "xio_vision.db", null, 1) {
    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("""
            CREATE TABLE events(
                event_id TEXT PRIMARY KEY,
                started_at_epoch_ms INTEGER NOT NULL,
                title TEXT,
                created_at_epoch_ms INTEGER NOT NULL
            )
        """.trimIndent())
        db.execSQL("""
            CREATE TABLE captures(
                capture_id TEXT PRIMARY KEY,
                event_id TEXT NOT NULL,
                captured_at_epoch_ms INTEGER NOT NULL,
                image_path TEXT NOT NULL,
                image_sha256 TEXT NOT NULL,
                model TEXT NOT NULL,
                dominant_color TEXT NOT NULL,
                average_red INTEGER NOT NULL,
                average_green INTEGER NOT NULL,
                average_blue INTEGER NOT NULL,
                average_brightness REAL NOT NULL,
                average_saturation REAL NOT NULL,
                review_status TEXT NOT NULL DEFAULT 'pending',
                FOREIGN KEY(event_id) REFERENCES events(event_id)
            )
        """.trimIndent())
        db.execSQL("""
            CREATE TABLE model_predictions(
                prediction_id INTEGER PRIMARY KEY AUTOINCREMENT,
                capture_id TEXT NOT NULL,
                rank INTEGER NOT NULL,
                label TEXT NOT NULL,
                score REAL NOT NULL,
                FOREIGN KEY(capture_id) REFERENCES captures(capture_id)
            )
        """.trimIndent())
        db.execSQL("""
            CREATE TABLE human_annotations(
                annotation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                capture_id TEXT NOT NULL,
                substance_label TEXT,
                form_label TEXT,
                color_label TEXT,
                marking_label TEXT,
                notes TEXT,
                annotated_at_epoch_ms INTEGER NOT NULL,
                FOREIGN KEY(capture_id) REFERENCES captures(capture_id)
            )
        """.trimIndent())
        db.execSQL("""
            CREATE TABLE training_examples(
                example_id INTEGER PRIMARY KEY AUTOINCREMENT,
                capture_id TEXT NOT NULL,
                annotation_id INTEGER NOT NULL,
                dataset_status TEXT NOT NULL DEFAULT 'candidate',
                split TEXT NOT NULL DEFAULT 'unassigned',
                created_at_epoch_ms INTEGER NOT NULL,
                UNIQUE(capture_id, annotation_id),
                FOREIGN KEY(capture_id) REFERENCES captures(capture_id),
                FOREIGN KEY(annotation_id) REFERENCES human_annotations(annotation_id)
            )
        """.trimIndent())
        db.execSQL("CREATE INDEX idx_captures_event ON captures(event_id)")
        db.execSQL("CREATE INDEX idx_annotations_capture ON human_annotations(capture_id)")
        db.execSQL("CREATE INDEX idx_training_status ON training_examples(dataset_status)")
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        // Schema migrations will be explicit; no data is silently discarded.
    }

    fun insertCapture(proposal: VisionProposal, imagePath: String, imageSha256: String) {
        val db = writableDatabase
        db.beginTransaction()
        try {
            val now = System.currentTimeMillis()
            val event = ContentValues().apply {
                put("event_id", proposal.eventId)
                put("started_at_epoch_ms", proposal.capturedAtEpochMs)
                put("title", "XIO capture")
                put("created_at_epoch_ms", now)
            }
            db.insertWithOnConflict("events", null, event, SQLiteDatabase.CONFLICT_IGNORE)

            val visual = proposal.visualAttributes
            val capture = ContentValues().apply {
                put("capture_id", proposal.proposalId)
                put("event_id", proposal.eventId)
                put("captured_at_epoch_ms", proposal.capturedAtEpochMs)
                put("image_path", imagePath)
                put("image_sha256", imageSha256)
                put("model", proposal.model)
                put("dominant_color", visual.dominantColor)
                put("average_red", visual.averageRed)
                put("average_green", visual.averageGreen)
                put("average_blue", visual.averageBlue)
                put("average_brightness", visual.averageBrightness)
                put("average_saturation", visual.averageSaturation)
                put("review_status", "pending")
            }
            db.insertOrThrow("captures", null, capture)

            proposal.labels.forEachIndexed { index, label ->
                val prediction = ContentValues().apply {
                    put("capture_id", proposal.proposalId)
                    put("rank", index + 1)
                    put("label", label.label)
                    put("score", label.score)
                }
                db.insertOrThrow("model_predictions", null, prediction)
            }
            db.setTransactionSuccessful()
        } finally {
            db.endTransaction()
        }
    }

    fun addHumanAnnotation(
        captureId: String,
        substance: String?,
        form: String?,
        color: String?,
        marking: String?,
        notes: String?,
    ) {
        val db = writableDatabase
        db.beginTransaction()
        try {
            val annotation = ContentValues().apply {
                put("capture_id", captureId)
                put("substance_label", substance.nullIfBlank())
                put("form_label", form.nullIfBlank())
                put("color_label", color.nullIfBlank())
                put("marking_label", marking.nullIfBlank())
                put("notes", notes.nullIfBlank())
                put("annotated_at_epoch_ms", System.currentTimeMillis())
            }
            val annotationId = db.insertOrThrow("human_annotations", null, annotation)
            val example = ContentValues().apply {
                put("capture_id", captureId)
                put("annotation_id", annotationId)
                put("dataset_status", "candidate")
                put("split", "unassigned")
                put("created_at_epoch_ms", System.currentTimeMillis())
            }
            db.insertOrThrow("training_examples", null, example)
            db.execSQL("UPDATE captures SET review_status = 'annotated' WHERE capture_id = ?", arrayOf(captureId))
            db.setTransactionSuccessful()
        } finally {
            db.endTransaction()
        }
    }

    private fun String?.nullIfBlank(): String? = this?.trim()?.takeIf { it.isNotEmpty() }
}
