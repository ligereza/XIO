package cl.reduciendodano.xiofield.data;

import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;

import cl.reduciendodano.xiofield.core.SampleSession;
import cl.reduciendodano.xiofield.core.VisualFeatures;
import cl.reduciendodano.xiofield.visual.BatchPatternDetector;
import cl.reduciendodano.xiofield.visual.VisualMemory;

import java.util.ArrayList;
import java.util.List;

/** Local append-friendly projection for the sample workflow. It never writes to RD's imported databases. */
public final class RdFieldDb extends SQLiteOpenHelper {
    private static final String DB_NAME = "rd_field_local.db";
    private static final int DB_VERSION = 8;

    public RdFieldDb(Context context) { super(context.getApplicationContext(), DB_NAME, null, DB_VERSION); }

    @Override public void onCreate(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE events (id TEXT PRIMARY KEY, code TEXT NOT NULL, name TEXT NOT NULL, venue TEXT, scheduled_at INTEGER, started_at INTEGER, status TEXT NOT NULL, synthetic INTEGER NOT NULL DEFAULT 0, start_date TEXT, end_date TEXT, producer TEXT, djs_json TEXT NOT NULL DEFAULT '[]', triangulation_json TEXT NOT NULL DEFAULT '{}', flyer_ref TEXT, flyer_sha256 TEXT, sync_status TEXT NOT NULL DEFAULT 'pending', review_status TEXT NOT NULL DEFAULT 'pendiente_revision_humana')");
        db.execSQL("CREATE TABLE samples (id TEXT PRIMARY KEY, event_id TEXT NOT NULL, code TEXT NOT NULL UNIQUE, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, declared_substance TEXT, presentation TEXT, observed_color TEXT, status TEXT NOT NULL, phase TEXT NOT NULL, paused INTEGER NOT NULL DEFAULT 0, sync_status TEXT NOT NULL DEFAULT 'pending', sync_error TEXT, sync_at INTEGER, sync_receipts_json TEXT NOT NULL DEFAULT '[]', FOREIGN KEY(event_id) REFERENCES events(id))");
        db.execSQL("CREATE TABLE captures (id TEXT PRIMARY KEY, sample_id TEXT NOT NULL, kind TEXT NOT NULL, path TEXT NOT NULL, silhouette_svg_path TEXT, silhouette_preview_path TEXT, relief_svg_path TEXT, geometry_signature TEXT, relief_signature TEXT, silhouette_confidence REAL, relief_confidence REAL, circularity REAL, solidity REAL, symmetry REAL, contour_point_count INTEGER, sha256 TEXT, captured_at INTEGER NOT NULL, width INTEGER, height INTEGER, silhouette TEXT, aspect_ratio REAL, foreground_ratio REAL, color_label TEXT, brightness REAL, saturation REAL, texture_score REAL, mean_red INTEGER, mean_green INTEGER, mean_blue INTEGER, perceptual_hash INTEGER, marking_candidate TEXT, marking_score REAL, model_version TEXT, FOREIGN KEY(sample_id) REFERENCES samples(id))");
        db.execSQL("CREATE TABLE tests (id TEXT PRIMARY KEY, sample_id TEXT NOT NULL, ordinal INTEGER NOT NULL, method TEXT, reagent TEXT, started_at INTEGER, ended_at INTEGER, elapsed_ms INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, operator_result TEXT, interpretation TEXT, FOREIGN KEY(sample_id) REFERENCES samples(id))");
        db.execSQL("CREATE TABLE test_observations (id TEXT PRIMARY KEY, test_id TEXT NOT NULL, observed_at INTEGER NOT NULL, color_text TEXT, description TEXT, capture_id TEXT, FOREIGN KEY(test_id) REFERENCES tests(id))");
        db.execSQL("CREATE TABLE corrections (id TEXT PRIMARY KEY, sample_id TEXT NOT NULL, capture_id TEXT, field TEXT NOT NULL, proposed_value TEXT, corrected_value TEXT, model_version TEXT, reviewed_at INTEGER NOT NULL, FOREIGN KEY(sample_id) REFERENCES samples(id))");
        db.execSQL("CREATE TABLE action_log (id INTEGER PRIMARY KEY AUTOINCREMENT, sample_id TEXT NOT NULL, at INTEGER NOT NULL, action TEXT NOT NULL, payload TEXT, FOREIGN KEY(sample_id) REFERENCES samples(id))");
        db.execSQL("CREATE TABLE training_examples (id TEXT PRIMARY KEY, sample_id TEXT NOT NULL, capture_id TEXT NOT NULL, label TEXT, review_status TEXT NOT NULL, model_version TEXT, split TEXT, FOREIGN KEY(sample_id) REFERENCES samples(id), FOREIGN KEY(capture_id) REFERENCES captures(id))");
        db.execSQL("CREATE INDEX idx_samples_event ON samples(event_id)");
        db.execSQL("CREATE INDEX idx_captures_sample ON captures(sample_id)");
        db.execSQL("CREATE INDEX idx_tests_sample ON tests(sample_id)");
        db.execSQL("CREATE INDEX idx_actions_sample ON action_log(sample_id, at)");
    }

    @Override public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) {
        if (oldVersion < 2) {
            db.execSQL("ALTER TABLE captures ADD COLUMN marking_candidate TEXT");
            db.execSQL("ALTER TABLE captures ADD COLUMN marking_score REAL NOT NULL DEFAULT 0");
        }
        if (oldVersion < 3) {
            db.execSQL("ALTER TABLE captures ADD COLUMN silhouette_svg_path TEXT");
            db.execSQL("ALTER TABLE captures ADD COLUMN geometry_signature TEXT");
            db.execSQL("ALTER TABLE captures ADD COLUMN silhouette_confidence REAL NOT NULL DEFAULT 0");
            db.execSQL("ALTER TABLE captures ADD COLUMN circularity REAL NOT NULL DEFAULT 0");
            db.execSQL("ALTER TABLE captures ADD COLUMN solidity REAL NOT NULL DEFAULT 0");
            db.execSQL("ALTER TABLE captures ADD COLUMN symmetry REAL NOT NULL DEFAULT 0");
            db.execSQL("ALTER TABLE captures ADD COLUMN contour_point_count INTEGER NOT NULL DEFAULT 0");
        }
        if (oldVersion < 4) {
            db.execSQL("ALTER TABLE captures ADD COLUMN relief_svg_path TEXT");
            db.execSQL("ALTER TABLE captures ADD COLUMN relief_signature TEXT");
            db.execSQL("ALTER TABLE captures ADD COLUMN relief_confidence REAL NOT NULL DEFAULT 0");
        }
        if (oldVersion < 5) db.execSQL("ALTER TABLE samples ADD COLUMN observed_color TEXT");
        if (oldVersion < 6) db.execSQL("ALTER TABLE captures ADD COLUMN silhouette_preview_path TEXT");
        if (oldVersion < 7) {
            db.execSQL("ALTER TABLE events ADD COLUMN start_date TEXT");
            db.execSQL("ALTER TABLE events ADD COLUMN end_date TEXT");
            db.execSQL("ALTER TABLE events ADD COLUMN producer TEXT");
            db.execSQL("ALTER TABLE events ADD COLUMN djs_json TEXT NOT NULL DEFAULT '[]'");
            db.execSQL("ALTER TABLE events ADD COLUMN triangulation_json TEXT NOT NULL DEFAULT '{}'");
            db.execSQL("ALTER TABLE events ADD COLUMN flyer_ref TEXT");
            db.execSQL("ALTER TABLE events ADD COLUMN flyer_sha256 TEXT");
            db.execSQL("ALTER TABLE events ADD COLUMN sync_status TEXT NOT NULL DEFAULT 'pending'");
            db.execSQL("ALTER TABLE events ADD COLUMN review_status TEXT NOT NULL DEFAULT 'pendiente_revision_humana'");
        }
        if (oldVersion < 8) {
            db.execSQL("ALTER TABLE samples ADD COLUMN sync_status TEXT NOT NULL DEFAULT 'pending'");
            db.execSQL("ALTER TABLE samples ADD COLUMN sync_error TEXT");
            db.execSQL("ALTER TABLE samples ADD COLUMN sync_at INTEGER");
            db.execSQL("ALTER TABLE samples ADD COLUMN sync_receipts_json TEXT NOT NULL DEFAULT '[]'");
        }
    }

    /** Creates only an empty field draft when an installation has no local data. */
    public void ensureFieldDraft() {
        SQLiteDatabase db = getWritableDatabase();
        if (countFieldSamples(db) > 0) return;
        long now = System.currentTimeMillis();
        ContentValues event = new ContentValues();
        event.put("id", "pending-event"); event.put("code", "PENDING-EVENT"); event.put("name", "Evento no seleccionado"); event.put("venue", ""); event.put("scheduled_at", now); event.put("status", "draft"); event.put("synthetic", 0); db.insertOrThrow("events", null, event);
        ContentValues sample = new ContentValues();
        sample.put("id", "draft-sample-" + now); sample.put("event_id", "pending-event"); sample.put("code", "XIO-DRAFT-" + now); sample.put("created_at", now); sample.put("updated_at", now); sample.put("declared_substance", ""); sample.put("presentation", ""); sample.put("status", "draft"); sample.put("phase", "OBSERVE"); sample.put("paused", 0); db.insertOrThrow("samples", null, sample);
    }

    public SampleRow latestSample() {
        Cursor cursor = getReadableDatabase().query("samples", null,
                "id<>? AND event_id<>? AND code NOT LIKE ?",
                new String[]{"demo-sample", "demo-event", "XIO-DEMO-%"}, null, null,
                "updated_at DESC", "1");
        try {
            if (!cursor.moveToFirst()) return null;
            return sampleRow(cursor);
        } finally { cursor.close(); }
    }

    public List<SampleRow> recentSamples() {
        List<SampleRow> result = new ArrayList<>();
        Cursor cursor = getReadableDatabase().query("samples", null,
                "id<>? AND event_id<>? AND code NOT LIKE ?",
                new String[]{"demo-sample", "demo-event", "XIO-DEMO-%"}, null, null,
                "created_at DESC", "40");
        try { while (cursor.moveToNext()) result.add(sampleRow(cursor)); } finally { cursor.close(); }
        return result;
    }

    public List<SampleSession.Capture> loadCaptures(String sampleId) {
        List<SampleSession.Capture> result = new ArrayList<>();
        Cursor cursor = getReadableDatabase().query("captures", null, "sample_id=?", new String[]{sampleId}, null, null, "captured_at ASC");
        try {
            while (cursor.moveToNext()) {
                VisualFeatures features = featuresFrom(cursor);
                result.add(new SampleSession.Capture(cursor.getString(cursor.getColumnIndexOrThrow("id")), cursor.getString(cursor.getColumnIndexOrThrow("kind")), cursor.getString(cursor.getColumnIndexOrThrow("path")), cursor.getString(cursor.getColumnIndexOrThrow("silhouette_svg_path")), cursor.getString(cursor.getColumnIndexOrThrow("silhouette_preview_path")), cursor.getString(cursor.getColumnIndexOrThrow("relief_svg_path")), cursor.getString(cursor.getColumnIndexOrThrow("sha256")), cursor.getLong(cursor.getColumnIndexOrThrow("captured_at")), features));
            }
        } finally { cursor.close(); }
        return result;
    }

    public List<SampleSession.TestSession> loadTests(String sampleId) {
        List<SampleSession.TestSession> result = new ArrayList<>();
        SQLiteDatabase db = getReadableDatabase();
        Cursor cursor = db.query("tests", null, "sample_id=?", new String[]{sampleId}, null, null, "ordinal ASC");
        try {
            while (cursor.moveToNext()) {
                SampleSession.TestSession test = new SampleSession.TestSession(cursor.getString(cursor.getColumnIndexOrThrow("id")), cursor.getInt(cursor.getColumnIndexOrThrow("ordinal")), cursor.getString(cursor.getColumnIndexOrThrow("method")), cursor.getString(cursor.getColumnIndexOrThrow("reagent")));
                test.startedAt = cursor.isNull(cursor.getColumnIndexOrThrow("started_at")) ? 0L : cursor.getLong(cursor.getColumnIndexOrThrow("started_at"));
                test.endedAt = cursor.isNull(cursor.getColumnIndexOrThrow("ended_at")) ? 0L : cursor.getLong(cursor.getColumnIndexOrThrow("ended_at"));
                test.elapsedMs = cursor.getLong(cursor.getColumnIndexOrThrow("elapsed_ms"));
                test.status = cursor.getString(cursor.getColumnIndexOrThrow("status"));
                test.operatorResult = cursor.getString(cursor.getColumnIndexOrThrow("operator_result"));
                test.interpretation = cursor.getString(cursor.getColumnIndexOrThrow("interpretation"));
                Cursor observations = db.query("test_observations", null, "test_id=?", new String[]{test.id}, null, null, "observed_at ASC");
                try {
                    while (observations.moveToNext()) test.observations.add(new SampleSession.ReactionObservation(observations.getString(observations.getColumnIndexOrThrow("id")), observations.getLong(observations.getColumnIndexOrThrow("observed_at")), observations.getString(observations.getColumnIndexOrThrow("color_text")), observations.getString(observations.getColumnIndexOrThrow("description"))));
                } finally { observations.close(); }
                result.add(test);
            }
        } finally { cursor.close(); }
        return result;
    }

    public List<SampleSession.Correction> loadCorrections(String sampleId) {
        List<SampleSession.Correction> result = new ArrayList<>();
        Cursor cursor = getReadableDatabase().query("corrections", null, "sample_id=?", new String[]{sampleId}, null, null, "reviewed_at ASC");
        try {
            while (cursor.moveToNext()) result.add(new SampleSession.Correction(cursor.getString(cursor.getColumnIndexOrThrow("id")), cursor.getString(cursor.getColumnIndexOrThrow("capture_id")), cursor.getString(cursor.getColumnIndexOrThrow("field")), cursor.getString(cursor.getColumnIndexOrThrow("proposed_value")), cursor.getString(cursor.getColumnIndexOrThrow("corrected_value")), cursor.getString(cursor.getColumnIndexOrThrow("model_version")), cursor.getLong(cursor.getColumnIndexOrThrow("reviewed_at"))));
        } finally { cursor.close(); }
        return result;
    }

    public List<SampleSession.ActionRecord> loadActions(String sampleId) {
        List<SampleSession.ActionRecord> result = new ArrayList<>();
        Cursor cursor = getReadableDatabase().query("action_log", null, "sample_id=?", new String[]{sampleId}, null, null, "at ASC, id ASC");
        try {
            while (cursor.moveToNext()) result.add(new SampleSession.ActionRecord(cursor.getLong(cursor.getColumnIndexOrThrow("at")), cursor.getString(cursor.getColumnIndexOrThrow("action")), cursor.getString(cursor.getColumnIndexOrThrow("payload"))));
        } finally { cursor.close(); }
        return result;
    }

    public void saveSession(SampleSession session) {
        SQLiteDatabase db = getWritableDatabase();
        ContentValues values = new ContentValues();
        values.put("id", session.id); values.put("event_id", session.eventId); values.put("code", session.code); values.put("created_at", session.createdAt); values.put("updated_at", session.updatedAt); values.put("declared_substance", session.declaredSubstance); values.put("presentation", session.presentation); values.put("observed_color", session.observedColor); values.put("status", session.status); values.put("phase", session.phase.name()); values.put("paused", session.paused ? 1 : 0);
        // Any local mutation invalidates the previous host receipt. Evidence
        // remains intact, but the sample must be sent again.
        values.put("sync_status", "pending"); values.put("sync_error", ""); values.putNull("sync_at"); values.put("sync_receipts_json", "[]");
        if (db.update("samples", values, "id=?", new String[]{session.id}) == 0) db.insertOrThrow("samples", null, values);
        db.delete("test_observations", "test_id IN (SELECT id FROM tests WHERE sample_id=?)", new String[]{session.id});
        db.delete("tests", "sample_id=?", new String[]{session.id});
        for (SampleSession.TestSession test : session.tests) {
            ContentValues testValues = new ContentValues();
            testValues.put("id", test.id); testValues.put("sample_id", session.id); testValues.put("ordinal", test.ordinal); testValues.put("method", test.method); testValues.put("reagent", test.reagent);
            if (test.startedAt == 0) testValues.putNull("started_at"); else testValues.put("started_at", test.startedAt);
            if (test.endedAt == 0) testValues.putNull("ended_at"); else testValues.put("ended_at", test.endedAt);
            testValues.put("elapsed_ms", test.elapsedMs); testValues.put("status", test.status); testValues.put("operator_result", test.operatorResult); testValues.put("interpretation", test.interpretation); db.insertOrThrow("tests", null, testValues);
            for (SampleSession.ReactionObservation observation : test.observations) { ContentValues observationValues = new ContentValues(); observationValues.put("id", observation.id); observationValues.put("test_id", test.id); observationValues.put("observed_at", observation.observedAt); observationValues.put("color_text", observation.color); observationValues.put("description", observation.description); db.insertOrThrow("test_observations", null, observationValues); }
        }
        db.delete("action_log", "sample_id=?", new String[]{session.id});
        for (SampleSession.ActionRecord action : session.timeline) { ContentValues actionValues = new ContentValues(); actionValues.put("sample_id", session.id); actionValues.put("at", action.at); actionValues.put("action", action.action); actionValues.put("payload", action.payload); db.insert("action_log", null, actionValues); }
    }

    public void upsertEvent(String id, String name, String venue, String producer,
                            String startDate, String endDate, String djsJson,
                            String triangulationJson, String flyerRef, String flyerSha256,
                            String syncStatus) {
        SQLiteDatabase db = getWritableDatabase();
        ContentValues values = new ContentValues();
        values.put("id", id);
        values.put("code", id);
        values.put("name", name);
        values.put("venue", venue);
        values.put("scheduled_at", System.currentTimeMillis());
        values.put("status", "draft");
        values.put("synthetic", 0);
        values.put("start_date", startDate);
        values.put("end_date", endDate);
        values.put("producer", producer);
        values.put("djs_json", djsJson);
        values.put("triangulation_json", triangulationJson);
        values.put("flyer_ref", flyerRef);
        values.put("flyer_sha256", flyerSha256);
        values.put("sync_status", syncStatus == null || syncStatus.trim().isEmpty() ? "pending" : syncStatus);
        values.put("review_status", "pendiente_revision_humana");
        if (db.update("events", values, "id=?", new String[]{id}) == 0) db.insertOrThrow("events", null, values);
    }

    public void markEventSynced(String id, String reviewStatus) {
        ContentValues values = new ContentValues();
        values.put("sync_status", "synced");
        values.put("review_status", reviewStatus == null || reviewStatus.trim().isEmpty() ? "pendiente_revision_humana" : reviewStatus);
        getWritableDatabase().update("events", values, "id=?", new String[]{id});
    }

    /** Records the durable local state of the sample-to-host projection. */
    public void recordSampleSync(String sampleId, String status, String error, String receiptsJson) {
        ContentValues values = new ContentValues();
        values.put("sync_status", status == null || status.trim().isEmpty() ? "pending" : status);
        values.put("sync_error", error == null ? "" : error);
        values.put("sync_at", System.currentTimeMillis());
        values.put("sync_receipts_json", receiptsJson == null || receiptsJson.trim().isEmpty() ? "[]" : receiptsJson);
        getWritableDatabase().update("samples", values, "id=?", new String[]{sampleId});
    }

    /** A process killed while uploading must become retryable on next launch. */
    public void recoverInterruptedSampleSyncs() {
        ContentValues values = new ContentValues();
        values.put("sync_status", "pending");
        values.put("sync_error", "envío interrumpido; listo para reintentar");
        getWritableDatabase().update("samples", values, "sync_status=?", new String[]{"sending"});
    }

    /** Keeps evidence recovery in the same append-friendly audit stream as operator actions. */
    public void appendAction(String sampleId, String action, String payload) {
        ContentValues values = new ContentValues();
        values.put("sample_id", sampleId);
        values.put("at", System.currentTimeMillis());
        values.put("action", action == null ? "evidence_recovery" : action);
        values.put("payload", payload == null ? "" : payload);
        getWritableDatabase().insert("action_log", null, values);
    }

    public List<EventRow> recentEvents() {
        List<EventRow> result = new ArrayList<>();
        Cursor cursor = getReadableDatabase().query("events", null, "id<>? AND synthetic=0", new String[]{"pending-event"}, null, null, "scheduled_at DESC", "60");
        try { while (cursor.moveToNext()) result.add(eventRow(cursor)); } finally { cursor.close(); }
        return result;
    }

    public EventRow findEvent(String id) {
        Cursor cursor = getReadableDatabase().query("events", null, "id=?", new String[]{id}, null, null, null, "1");
        try { return cursor.moveToFirst() ? eventRow(cursor) : null; } finally { cursor.close(); }
    }

    public void insertCapture(String sampleId, SampleSession.Capture capture) {
        SQLiteDatabase db = getWritableDatabase();
        VisualFeatures f = capture.features;
        ContentValues values = new ContentValues();
        values.put("id", capture.id); values.put("sample_id", sampleId); values.put("kind", capture.kind); values.put("path", capture.path); values.put("silhouette_svg_path", capture.silhouettePath); values.put("silhouette_preview_path", capture.silhouettePreviewPath); values.put("relief_svg_path", capture.reliefPath); values.put("geometry_signature", f.geometrySignature); values.put("relief_signature", f.reliefSignature); values.put("silhouette_confidence", f.silhouetteConfidence); values.put("relief_confidence", f.reliefConfidence); values.put("circularity", f.circularity); values.put("solidity", f.solidity); values.put("symmetry", f.symmetry); values.put("contour_point_count", f.contourPointCount); values.put("sha256", capture.sha256); values.put("captured_at", capture.capturedAt); values.put("silhouette", f.silhouetteLabel); values.put("aspect_ratio", f.aspectRatio); values.put("foreground_ratio", f.foregroundRatio); values.put("color_label", f.colorLabel); values.put("brightness", f.brightness); values.put("saturation", f.saturation); values.put("texture_score", f.textureScore); values.put("mean_red", f.meanRed); values.put("mean_green", f.meanGreen); values.put("mean_blue", f.meanBlue); values.put("perceptual_hash", f.perceptualHash); values.put("marking_candidate", f.markingCandidate); values.put("marking_score", f.markingScore); values.put("model_version", SampleSessionEngineVersion.VALUE); db.insertWithOnConflict("captures", null, values, SQLiteDatabase.CONFLICT_REPLACE);
    }

    public String captureModelVersion(String sampleId, String captureId) {
        Cursor cursor = getReadableDatabase().query("captures", new String[]{"model_version"},
                "sample_id=? AND id=?", new String[]{sampleId, captureId}, null, null, null, "1");
        try { return cursor.moveToFirst() ? cursor.getString(cursor.getColumnIndexOrThrow("model_version")) : ""; }
        finally { cursor.close(); }
    }

    public void deleteCapture(String sampleId, String captureId) {
        getWritableDatabase().delete("captures", "sample_id=? AND id=?", new String[]{sampleId, captureId});
    }

    public void saveCorrectionAndTrainingExample(String sampleId, SampleSession.Correction correction, String label) {
        saveCorrectionAndTrainingExample(sampleId, correction, label, "reviewed");
    }

    public void saveCorrectionAndTrainingExample(String sampleId, SampleSession.Correction correction,
                                                  String label, String reviewStatus) {
        SQLiteDatabase db = getWritableDatabase();
        ContentValues correctionValues = new ContentValues();
        correctionValues.put("id", correction.id); correctionValues.put("sample_id", sampleId); correctionValues.put("capture_id", correction.captureId); correctionValues.put("field", correction.field); correctionValues.put("proposed_value", correction.proposedValue); correctionValues.put("corrected_value", correction.correctedValue); correctionValues.put("model_version", correction.modelVersion); correctionValues.put("reviewed_at", correction.reviewedAt); db.insertOrThrow("corrections", null, correctionValues);
        ContentValues example = new ContentValues();
        example.put("id", "training-" + correction.captureId + "-" + correction.field); example.put("sample_id", sampleId); example.put("capture_id", correction.captureId); example.put("label", label); example.put("review_status", reviewStatus == null || reviewStatus.trim().isEmpty() ? "pending_review" : reviewStatus); example.put("model_version", correction.modelVersion); example.put("split", "local-review"); db.insertWithOnConflict("training_examples", null, example, SQLiteDatabase.CONFLICT_REPLACE);
    }

    public List<VisualMemory.Entry> reviewedMemory() {
        List<VisualMemory.Entry> result = new ArrayList<>();
        String sql = "SELECT t.capture_id, s.code, s.event_id, s.declared_substance, c.captured_at, t.label, "
                + "COALESCE((SELECT cr.field FROM corrections cr WHERE cr.sample_id=t.sample_id AND cr.capture_id=t.capture_id "
                + "ORDER BY cr.reviewed_at DESC LIMIT 1), '') AS review_field, c.* "
                + "FROM training_examples t JOIN samples s ON s.id=t.sample_id JOIN captures c ON c.id=t.capture_id "
                + "WHERE t.review_status='reviewed' AND s.event_id<>? AND s.code NOT LIKE ? ORDER BY c.captured_at DESC";
        Cursor cursor = getReadableDatabase().rawQuery(sql, new String[]{"demo-event", "XIO-DEMO-%"});
        try { while (cursor.moveToNext()) result.add(new VisualMemory.Entry(cursor.getString(cursor.getColumnIndexOrThrow("capture_id")), cursor.getString(cursor.getColumnIndexOrThrow("code")), cursor.getString(cursor.getColumnIndexOrThrow("event_id")), cursor.getLong(cursor.getColumnIndexOrThrow("captured_at")), cursor.getString(cursor.getColumnIndexOrThrow("label")), cursor.getString(cursor.getColumnIndexOrThrow("declared_substance")), cursor.getString(cursor.getColumnIndexOrThrow("review_field")), featuresFrom(cursor))); } finally { cursor.close(); }
        return result;
    }

    public List<BatchPatternDetector.Observation> sampleVisualObservations(String eventId) {
        List<BatchPatternDetector.Observation> result = new ArrayList<>();
        String sql = "SELECT s.event_id, s.code, c.captured_at, c.* FROM samples s JOIN captures c ON c.sample_id=s.id WHERE s.event_id=? AND s.event_id<>? AND s.code NOT LIKE ? ORDER BY c.captured_at ASC";
        Cursor cursor = getReadableDatabase().rawQuery(sql, new String[]{eventId, "demo-event", "XIO-DEMO-%"});
        try { while (cursor.moveToNext()) result.add(new BatchPatternDetector.Observation(cursor.getString(cursor.getColumnIndexOrThrow("event_id")), cursor.getString(cursor.getColumnIndexOrThrow("code")), cursor.getLong(cursor.getColumnIndexOrThrow("captured_at")), featuresFrom(cursor))); } finally { cursor.close(); }
        return result;
    }

    public List<SampleRow> reviewedSamples() {
        List<SampleRow> result = new ArrayList<>();
        Cursor cursor = getReadableDatabase().query("samples", null,
                "status=? AND event_id<>? AND code NOT LIKE ?",
                new String[]{"reviewed", "demo-event", "XIO-DEMO-%"}, null, null, "updated_at DESC");
        try { while (cursor.moveToNext()) result.add(sampleRow(cursor)); } finally { cursor.close(); }
        return result;
    }

    private static SampleRow sampleRow(Cursor cursor) {
        return new SampleRow(cursor.getString(cursor.getColumnIndexOrThrow("id")), cursor.getString(cursor.getColumnIndexOrThrow("event_id")), cursor.getString(cursor.getColumnIndexOrThrow("code")), cursor.getLong(cursor.getColumnIndexOrThrow("created_at")), cursor.getString(cursor.getColumnIndexOrThrow("declared_substance")), cursor.getString(cursor.getColumnIndexOrThrow("presentation")), cursor.getString(cursor.getColumnIndexOrThrow("observed_color")), cursor.getString(cursor.getColumnIndexOrThrow("status")), cursor.getString(cursor.getColumnIndexOrThrow("phase")), cursor.getInt(cursor.getColumnIndexOrThrow("paused")) == 1, cursor.getString(cursor.getColumnIndexOrThrow("sync_status")), cursor.getString(cursor.getColumnIndexOrThrow("sync_error")), cursor.isNull(cursor.getColumnIndexOrThrow("sync_at")) ? 0L : cursor.getLong(cursor.getColumnIndexOrThrow("sync_at")), cursor.getString(cursor.getColumnIndexOrThrow("sync_receipts_json")));
    }

    private static EventRow eventRow(Cursor cursor) {
        return new EventRow(
                cursor.getString(cursor.getColumnIndexOrThrow("id")),
                cursor.getString(cursor.getColumnIndexOrThrow("name")),
                cursor.getString(cursor.getColumnIndexOrThrow("venue")),
                cursor.getString(cursor.getColumnIndexOrThrow("producer")),
                cursor.getString(cursor.getColumnIndexOrThrow("start_date")),
                cursor.getString(cursor.getColumnIndexOrThrow("end_date")),
                cursor.getString(cursor.getColumnIndexOrThrow("djs_json")),
                cursor.getString(cursor.getColumnIndexOrThrow("triangulation_json")),
                cursor.getString(cursor.getColumnIndexOrThrow("flyer_ref")),
                cursor.getString(cursor.getColumnIndexOrThrow("flyer_sha256")),
                cursor.getString(cursor.getColumnIndexOrThrow("sync_status")),
                cursor.getString(cursor.getColumnIndexOrThrow("review_status")));
    }

    private static VisualFeatures featuresFrom(Cursor cursor) {
        String marking = cursor.getString(cursor.getColumnIndexOrThrow("marking_candidate"));
        return new VisualFeatures(cursor.getString(cursor.getColumnIndexOrThrow("color_label")), cursor.getString(cursor.getColumnIndexOrThrow("silhouette")), cursor.getFloat(cursor.getColumnIndexOrThrow("aspect_ratio")), cursor.getFloat(cursor.getColumnIndexOrThrow("foreground_ratio")), cursor.getFloat(cursor.getColumnIndexOrThrow("brightness")), cursor.getFloat(cursor.getColumnIndexOrThrow("saturation")), cursor.getFloat(cursor.getColumnIndexOrThrow("texture_score")), cursor.getInt(cursor.getColumnIndexOrThrow("mean_red")), cursor.getInt(cursor.getColumnIndexOrThrow("mean_green")), cursor.getInt(cursor.getColumnIndexOrThrow("mean_blue")), cursor.getLong(cursor.getColumnIndexOrThrow("perceptual_hash")), marking == null ? "sin señal clara de marca" : marking, cursor.getFloat(cursor.getColumnIndexOrThrow("marking_score")), cursor.getFloat(cursor.getColumnIndexOrThrow("relief_confidence")), cursor.getString(cursor.getColumnIndexOrThrow("relief_signature")), cursor.getFloat(cursor.getColumnIndexOrThrow("silhouette_confidence")), cursor.getFloat(cursor.getColumnIndexOrThrow("circularity")), cursor.getFloat(cursor.getColumnIndexOrThrow("solidity")), cursor.getFloat(cursor.getColumnIndexOrThrow("symmetry")), cursor.getInt(cursor.getColumnIndexOrThrow("contour_point_count")), cursor.getString(cursor.getColumnIndexOrThrow("geometry_signature")));
    }

    private static int countFieldSamples(SQLiteDatabase db) {
        Cursor cursor = db.rawQuery("SELECT COUNT(*) FROM samples WHERE id<>? AND event_id<>? AND code NOT LIKE ?", new String[]{"demo-sample", "demo-event", "XIO-DEMO-%"});
        try { cursor.moveToFirst(); return cursor.getInt(0); } finally { cursor.close(); }
    }

    public static final class SampleRow {
        public final String id, eventId, code, declaredSubstance, presentation, observedColor, status, phase, syncStatus, syncError, syncReceiptsJson;
        public final long createdAt;
        public final long syncAt;
        public final boolean paused;
        public SampleRow(String id, String eventId, String code, long createdAt, String declaredSubstance, String presentation, String observedColor, String status, String phase, boolean paused, String syncStatus, String syncError, long syncAt, String syncReceiptsJson) { this.id = id; this.eventId = eventId; this.code = code; this.createdAt = createdAt; this.declaredSubstance = declaredSubstance; this.presentation = presentation; this.observedColor = observedColor; this.status = status; this.phase = phase; this.paused = paused; this.syncStatus = syncStatus; this.syncError = syncError; this.syncAt = syncAt; this.syncReceiptsJson = syncReceiptsJson; }
    }

    public static final class EventRow {
        public final String id, name, venue, producer, startDate, endDate, djsJson,
                triangulationJson, flyerRef, flyerSha256, syncStatus, reviewStatus;

        public EventRow(String id, String name, String venue, String producer,
                        String startDate, String endDate, String djsJson,
                        String triangulationJson, String flyerRef, String flyerSha256,
                        String syncStatus, String reviewStatus) {
            this.id = id; this.name = name; this.venue = venue; this.producer = producer;
            this.startDate = startDate; this.endDate = endDate; this.djsJson = djsJson;
            this.triangulationJson = triangulationJson; this.flyerRef = flyerRef;
            this.flyerSha256 = flyerSha256; this.syncStatus = syncStatus;
            this.reviewStatus = reviewStatus;
        }
    }

    private static final class SampleSessionEngineVersion { private static final String VALUE = "visual-contour-v0.4"; }
}
