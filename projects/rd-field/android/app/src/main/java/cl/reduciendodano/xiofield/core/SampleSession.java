package cl.reduciendodano.xiofield.core;

import java.util.ArrayList;
import java.util.List;

/**
 * Aggregate root for one sample. The operator works on this object, not on a
 * flat form. Every relevant change can be persisted as an action and the
 * original visual proposal is never replaced by a human correction.
 */
public final class SampleSession {
    public enum Phase { CAPTURE, OBSERVE, TEST, REVIEW, MEMORY }

    public final String id;
    public String eventId;
    public final String code;
    public final long createdAt;
    public long updatedAt;
    public String declaredSubstance = "";
    public String presentation = "";
    public String observedColor = "";
    public String status = "draft";
    public Phase phase = Phase.CAPTURE;
    public boolean paused;
    public final List<Capture> captures = new ArrayList<>();
    public final List<VisualProposal> visualProposals = new ArrayList<>();
    public final List<TestSession> tests = new ArrayList<>();
    public final List<Correction> corrections = new ArrayList<>();
    public final List<ActionRecord> timeline = new ArrayList<>();

    public SampleSession(String id, String eventId, String code, long createdAt) {
        this.id = id;
        this.eventId = eventId;
        this.code = code;
        this.createdAt = createdAt;
        this.updatedAt = createdAt;
    }

    public static final class Capture {
        public final String id;
        public final String kind;
        public final String path;
        public final String silhouettePath;
        public final String silhouettePreviewPath;
        public final String reliefPath;
        public final String sha256;
        public final long capturedAt;
        public final VisualFeatures features;

        public Capture(String id, String kind, String path, String sha256, long capturedAt, VisualFeatures features) {
            this(id, kind, path, "", "", "", sha256, capturedAt, features);
        }

        public Capture(String id, String kind, String path, String silhouettePath, String sha256, long capturedAt, VisualFeatures features) {
            this(id, kind, path, silhouettePath, "", "", sha256, capturedAt, features);
        }

        public Capture(String id, String kind, String path, String silhouettePath, String reliefPath, String sha256, long capturedAt, VisualFeatures features) {
            this(id, kind, path, silhouettePath, "", reliefPath, sha256, capturedAt, features);
        }

        public Capture(String id, String kind, String path, String silhouettePath, String silhouettePreviewPath, String reliefPath, String sha256, long capturedAt, VisualFeatures features) {
            this.id = id;
            this.kind = kind;
            this.path = path;
            this.silhouettePath = silhouettePath == null ? "" : silhouettePath;
            this.silhouettePreviewPath = silhouettePreviewPath == null ? "" : silhouettePreviewPath;
            this.reliefPath = reliefPath == null ? "" : reliefPath;
            this.sha256 = sha256;
            this.capturedAt = capturedAt;
            this.features = features;
        }
    }

    public static final class VisualProposal {
        public final String captureId;
        public final VisualFeatures features;
        public final String modelVersion;
        public final long createdAt;

        public VisualProposal(String captureId, VisualFeatures features, String modelVersion, long createdAt) {
            this.captureId = captureId;
            this.features = features;
            this.modelVersion = modelVersion;
            this.createdAt = createdAt;
        }
    }

    public static final class TestSession {
        public final String id;
        public final int ordinal;
        public String method;
        public String reagent;
        public long startedAt;
        public long endedAt;
        public long elapsedMs;
        public String operatorResult = "";
        public String interpretation = "";
        public String status = "draft";
        public final List<ReactionObservation> observations = new ArrayList<>();
        public final List<String> evidenceCaptureIds = new ArrayList<>();

        public TestSession(String id, int ordinal, String method, String reagent) {
            this.id = id;
            this.ordinal = ordinal;
            this.method = method;
            this.reagent = reagent;
        }
    }

    public static final class ReactionObservation {
        public final String id;
        public final long observedAt;
        public final String color;
        public final String description;

        public ReactionObservation(String id, long observedAt, String color, String description) {
            this.id = id;
            this.observedAt = observedAt;
            this.color = color;
            this.description = description;
        }
    }

    public static final class Correction {
        public final String id;
        public final String captureId;
        public final String field;
        public final String proposedValue;
        public final String correctedValue;
        public final String modelVersion;
        public final long reviewedAt;

        public Correction(String id, String captureId, String field, String proposedValue, String correctedValue, String modelVersion, long reviewedAt) {
            this.id = id;
            this.captureId = captureId;
            this.field = field;
            this.proposedValue = proposedValue;
            this.correctedValue = correctedValue;
            this.modelVersion = modelVersion;
            this.reviewedAt = reviewedAt;
        }
    }

    public static final class ActionRecord {
        public final long at;
        public final String action;
        public final String payload;

        public ActionRecord(long at, String action, String payload) {
            this.at = at;
            this.action = action;
            this.payload = payload;
        }
    }
}
