package cl.reduciendodano.xiofield.core;

import java.util.UUID;

/** Domain actions for the field workflow. UI code calls actions; it does not mutate rows directly. */
public final class SampleSessionEngine {
    public static final String VISUAL_MODEL_VERSION = "visual-contour-v0.4";
    private final SampleSession session;

    public SampleSessionEngine(SampleSession session) {
        this.session = session;
    }

    public static SampleSessionEngine create(String eventId, String code) {
        long now = System.currentTimeMillis();
        SampleSession session = new SampleSession(UUID.randomUUID().toString(), eventId, code, now);
        SampleSessionEngine engine = new SampleSessionEngine(session);
        engine.record("sample_created", "code=" + code);
        return engine;
    }

    /** Rehydrates an existing sample without inventing a new identity or timeline event. */
    public static SampleSessionEngine createExisting(String id, String eventId, String code, long createdAt, String phase, boolean paused) {
        SampleSession session = new SampleSession(id, eventId, code, createdAt);
        try {
            session.phase = SampleSession.Phase.valueOf(phase == null ? "CAPTURE" : phase);
        } catch (IllegalArgumentException ignored) {
            session.phase = SampleSession.Phase.CAPTURE;
        }
        session.paused = paused;
        return new SampleSessionEngine(session);
    }

    public SampleSession snapshot() { return session; }

    public void restoreCapture(SampleSession.Capture capture) { session.captures.add(capture); }

    public void restoreVisualProposal(String captureId, VisualFeatures features, String modelVersion, long createdAt) {
        session.visualProposals.add(new SampleSession.VisualProposal(captureId, features, modelVersion, createdAt));
    }

    public void restoreTest(SampleSession.TestSession test) { session.tests.add(test); }

    public void restoreCorrection(SampleSession.Correction correction) { session.corrections.add(correction); }

    public void restoreAction(SampleSession.ActionRecord action) { session.timeline.add(action); }

    public void setDeclaredSubstance(String value) {
        session.declaredSubstance = value == null ? "" : value.trim();
        touch("declaration_changed", session.declaredSubstance);
    }

    public void setPresentation(String value) {
        session.presentation = value == null ? "" : value.trim();
        touch("presentation_changed", session.presentation);
    }

    public void setObservedColor(String value) {
        session.observedColor = value == null ? "" : value.trim();
        touch("observed_color_changed", session.observedColor);
    }

    public void setEventId(String value) {
        String next = value == null ? "" : value.trim();
        if (next.isEmpty() || next.equals(session.eventId)) return;
        session.eventId = next;
        touch("event_context_changed", next);
    }

    public void transitionTo(SampleSession.Phase phase) {
        session.phase = phase;
        touch("phase_changed", phase.name());
    }

    public void pause() {
        session.paused = true;
        touch("session_paused", "");
    }

    public void resume() {
        session.paused = false;
        touch("session_resumed", "");
    }

    public void addCapture(SampleSession.Capture capture) {
        session.captures.add(capture);
        touch("capture_added", capture.id);
    }

    public void addVisualProposal(String captureId, VisualFeatures features) {
        session.visualProposals.add(new SampleSession.VisualProposal(captureId, features, VISUAL_MODEL_VERSION, System.currentTimeMillis()));
        touch("visual_proposal_created", captureId);
    }

    public void addCorrection(String captureId, String field, String proposedValue, String correctedValue) {
        SampleSession.Correction correction = new SampleSession.Correction(UUID.randomUUID().toString(), captureId, field, proposedValue, correctedValue, VISUAL_MODEL_VERSION, System.currentTimeMillis());
        session.corrections.add(correction);
        touch("human_correction_added", field + "=" + correctedValue);
    }

    public SampleSession.TestSession addTest(String method, String reagent) {
        SampleSession.TestSession test = new SampleSession.TestSession(UUID.randomUUID().toString(), session.tests.size() + 1, method, reagent);
        session.tests.add(test);
        touch("test_added", test.id);
        return test;
    }

    public void startTest(SampleSession.TestSession test) {
        if (test.startedAt == 0L) test.startedAt = System.currentTimeMillis();
        test.status = "running";
        touch("test_started", test.id);
    }

    public void stopTest(SampleSession.TestSession test) {
        if (test.startedAt == 0L) return;
        long now = System.currentTimeMillis();
        test.elapsedMs += Math.max(0L, now - test.startedAt);
        test.endedAt = now;
        test.status = "draft";
        touch("test_stopped", test.id + " elapsedMs=" + test.elapsedMs);
    }

    public void addObservation(SampleSession.TestSession test, String color, String description) {
        test.observations.add(new SampleSession.ReactionObservation(UUID.randomUUID().toString(), System.currentTimeMillis(), color, description));
        touch("reaction_observation_added", test.id);
    }

    public void completeTest(SampleSession.TestSession test, String operatorResult, String interpretation) {
        test.operatorResult = operatorResult == null ? "" : operatorResult.trim();
        test.interpretation = interpretation == null ? "" : interpretation.trim();
        test.status = "done";
        touch("test_completed", test.id);
    }

    private void touch(String action, String payload) {
        session.updatedAt = System.currentTimeMillis();
        record(action, payload);
    }

    private void record(String action, String payload) {
        session.timeline.add(new SampleSession.ActionRecord(System.currentTimeMillis(), action, payload == null ? "" : payload));
    }
}
