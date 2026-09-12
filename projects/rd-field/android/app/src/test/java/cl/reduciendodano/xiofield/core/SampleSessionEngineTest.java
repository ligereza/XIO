package cl.reduciendodano.xiofield.core;

import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import cl.reduciendodano.xiofield.visual.BatchPatternDetector;
import cl.reduciendodano.xiofield.visual.MoldPatternMatcher;
import cl.reduciendodano.xiofield.visual.VisualMemory;

public final class SampleSessionEngineTest {
    @Test public void sampleKeepsMultipleTestsAndExactElapsedTime() {
        SampleSessionEngine engine = SampleSessionEngine.create("event-1", "XIO-TEST-001");
        SampleSession.TestSession first = engine.addTest("Colorimetría", "Marquis");
        SampleSession.TestSession second = engine.addTest("Tira", "pH");
        first.elapsedMs = 34000L;
        second.elapsedMs = 21000L;
        engine.completeTest(first, "No concluyente", "solo observación");
        engine.completeTest(second, "No aplica", "demo");
        assertEquals(2, engine.snapshot().tests.size());
        assertEquals(34000L, engine.snapshot().tests.get(0).elapsedMs);
        assertEquals("No aplica", engine.snapshot().tests.get(1).operatorResult);
    }

    @Test public void pauseAndResumeAreRecordedWithoutLosingTheSample() {
        SampleSessionEngine engine = SampleSessionEngine.create("event-1", "XIO-TEST-002");
        engine.pause();
        assertTrue(engine.snapshot().paused);
        engine.resume();
        assertFalse(engine.snapshot().paused);
        assertTrue(engine.snapshot().timeline.stream().anyMatch(action -> action.action.equals("session_paused")));
        assertTrue(engine.snapshot().timeline.stream().anyMatch(action -> action.action.equals("session_resumed")));
    }

    @Test public void correctionDoesNotOverwriteVisualProposal() {
        SampleSessionEngine engine = SampleSessionEngine.create("event-1", "XIO-TEST-003");
        VisualFeatures proposal = new VisualFeatures("rosado", "compacta", 1.0f, .5f, .7f, .3f, .2f, 200, 140, 140, 12L);
        SampleSession.Capture capture = new SampleSession.Capture("capture-1", "sample", "evidence/capture-1.jpg", "sha", 1L, proposal);
        engine.addCapture(capture);
        engine.addVisualProposal(capture.id, proposal);
        engine.addCorrection(capture.id, "color", proposal.colorLabel, "beige");
        assertEquals("rosado", engine.snapshot().visualProposals.get(0).features.colorLabel);
        assertEquals("beige", engine.snapshot().corrections.get(0).correctedValue);
    }

    @Test public void repeatedVisualPatternIsScopedToTheSameEvent() {
        VisualFeatures feature = new VisualFeatures("rosado", "compacta", 1.0f, .5f, .7f, .3f, .2f, 200, 140, 140, 12L);
        VisualFeatures distant = new VisualFeatures("azul", "alargada", 2.0f, .3f, .4f, .7f, .8f, 30, 70, 210, 1L);
        BatchPatternDetector detector = new BatchPatternDetector();
        java.util.List<BatchPatternDetector.Observation> observations = java.util.List.of(
                new BatchPatternDetector.Observation("event-now", "XIO-001", 1L, feature),
                new BatchPatternDetector.Observation("event-now", "XIO-002", 2L, feature),
                new BatchPatternDetector.Observation("event-last-year", "XIO-OLD", 3L, distant));
        java.util.List<BatchPatternDetector.Pattern> patterns = detector.detect(observations);
        assertEquals(2, patterns.size());
        assertTrue(patterns.stream().anyMatch(pattern -> pattern.eventId.equals("event-now") && pattern.recurrence() == 2));
    }

    @Test public void recentSameEventMatchRanksAboveOlderHistory() {
        VisualFeatures feature = new VisualFeatures("rosado", "compacta", 1.0f, .5f, .7f, .3f, .2f, 200, 140, 140, 12L);
        VisualMemory memory = new VisualMemory();
        long now = System.currentTimeMillis();
        memory.addReviewed(new VisualMemory.Entry("old", "OLD", "other-event", now - 400L * 86_400_000L, "antecedente", feature));
        memory.addReviewed(new VisualMemory.Entry("recent", "RECENT", "current-event", now - 5L * 60_000L, "recurrencia", feature));
        java.util.List<VisualMemory.Match> matches = memory.findSimilar("current-event", now, feature, 2);
        assertEquals("RECENT", matches.get(0).entry.sampleCode);
        assertTrue(matches.get(0).similarity > matches.get(1).similarity);
    }

    @Test public void normalizedContourAndReliefAreUsedForVisualRetrieval() {
        String contour = "1,.8,.5,.8,1,.8,.5,.8";
        String rotated = ".8,.5,.8,1,.8,.5,.8,1";
        String relief = "0,0,.8,0,0,.8,0,0,0,0,.8,0,0,.8,0,0";
        VisualFeatures first = new VisualFeatures("rosado", "compacta", 1f, .4f, .7f, .3f, .2f, 200, 140, 140, 12L, "marca", .7f, .8f, relief, .9f, .8f, .95f, .9f, 48, contour);
        VisualFeatures sameMould = new VisualFeatures("beige", "compacta", 1.02f, .4f, .7f, .3f, .2f, 190, 135, 130, 12L, "marca", .7f, .8f, relief, .9f, .8f, .95f, .9f, 48, rotated);
        VisualFeatures otherMould = new VisualFeatures("beige", "compacta", 1.02f, .4f, .7f, .3f, .2f, 190, 135, 130, 12L, "marca", .7f, .1f, "0,1,0,1,0,1,0,1,0,1,0,1,0,1,0,1", .9f, .8f, .95f, .9f, 48, "1,1,1,1,1,1,1,1");
        assertTrue(BatchPatternDetector.geometrySimilarity(first, sameMould) > .8f);
        assertTrue(BatchPatternDetector.reliefSimilarity(first, sameMould) > .8f);
        assertTrue(BatchPatternDetector.similarity(first, sameMould) > BatchPatternDetector.similarity(first, otherMould));
    }
    @Test public void ecstasyMouldMatchesUseReviewedDesignLabelsAndIgnoreOtherSubstances() {
        String contour = "1,.8,.5,.8,1,.8,.5,.8";
        String relief = "0,0,.8,0,0,.8,0,0,0,0,.8,0,0,.8,0,0";
        VisualFeatures query = new VisualFeatures("rosado", "compacta", 1f, .4f, .7f, .3f, .2f, 200, 140, 140, 12L, "marca", .7f, .8f, relief, .9f, .8f, .95f, .9f, 48, contour);
        VisualFeatures sameDesign = new VisualFeatures("beige", "compacta", 1.02f, .4f, .7f, .3f, .2f, 190, 135, 130, 12L, "marca", .7f, .8f, relief, .9f, .8f, .95f, .9f, 48, ".8,.5,.8,1,.8,.5,.8,1");
        VisualMemory memory = new VisualMemory();
        memory.addApproved(new VisualMemory.Entry("mold-1", "XIO-EXT-001", "event-1", 1L, "molde: corona", "ÉXTASIS", "mold_design", sameDesign, "ref-corona", 1, true));
        memory.addApproved(new VisualMemory.Entry("other-1", "XIO-MDMA-002", "event-1", 2L, "marca: otra", "COCAÍNA", "mold_design", sameDesign, "ref-other", 1, true));
        java.util.List<VisualMemory.Match> matches = memory.findMoldMatches("ÉXTASIS", "event-1", 3L, query, 5);
        assertEquals(1, matches.size());
        assertEquals("molde: corona", matches.get(0).entry.reviewedLabel);
        assertTrue(matches.get(0).similarity > .75f);
        assertTrue(MoldPatternMatcher.explanation(query, sameDesign).contains("contorno") || MoldPatternMatcher.explanation(query, sameDesign).contains("relieve"));
        assertTrue(MoldPatternMatcher.fingerprint(query).startsWith("MOLD-"));
        java.util.List<VisualFeatures> frontAndBack = java.util.List.of(sameDesign, query);
        java.util.List<VisualMemory.Match> multiView = memory.findMoldMatches("ÉXTASIS", "event-1", 3L, frontAndBack, 5);
        assertEquals(1, multiView.size());
        assertTrue(multiView.get(0).similarity > .75f);
        assertTrue(!MoldPatternMatcher.fingerprint(frontAndBack).equals(MoldPatternMatcher.fingerprint(query)));
    }

    @Test public void pendingMouldCandidateNeverEntersAutomaticMatching() {
        VisualFeatures feature = new VisualFeatures("rosado", "compacta", 1f, .4f, .7f, .3f, .2f, 200, 140, 140, 12L, "marca", .7f, .8f, "0,1,0,1", .9f, .8f, .95f, .9f, 48, "1,.8,1,.8");
        VisualMemory memory = new VisualMemory();
        memory.addReviewed(new VisualMemory.Entry("pending", "XIO-PENDING", "event-1", 1L, "molde: sin aprobar", "ÉXTASIS", "mold_design_candidate", feature));
        assertTrue(memory.findMoldMatches("ÉXTASIS", "event-1", 2L, feature, 3).isEmpty());
    }
}
