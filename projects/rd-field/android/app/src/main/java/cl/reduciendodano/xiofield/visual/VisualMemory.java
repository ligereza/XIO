package cl.reduciendodano.xiofield.visual;

import cl.reduciendodano.xiofield.core.VisualFeatures;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

/** Local nearest-neighbour memory. Reviewed examples become searchable without pretending to be a chemical classifier. */
public final class VisualMemory {
    public static final class Entry {
        public final String captureId;
        public final String sampleCode;
        public final String eventId;
        public final long capturedAt;
        public final String reviewedLabel;
        public final VisualFeatures features;

        public Entry(String captureId, String sampleCode, String reviewedLabel, VisualFeatures features) {
            this(captureId, sampleCode, "", 0L, reviewedLabel, features);
        }

        public Entry(String captureId, String sampleCode, String eventId, long capturedAt, String reviewedLabel, VisualFeatures features) {
            this.captureId = captureId;
            this.sampleCode = sampleCode;
            this.eventId = eventId;
            this.capturedAt = capturedAt;
            this.reviewedLabel = reviewedLabel;
            this.features = features;
        }
    }

    public static final class Match {
        public final Entry entry;
        public final float similarity;

        public Match(Entry entry, float similarity) { this.entry = entry; this.similarity = similarity; }
    }

    private final List<Entry> entries = new ArrayList<>();

    public void addReviewed(Entry entry) { entries.removeIf(item -> item.captureId.equals(entry.captureId)); entries.add(entry); }

    public List<Match> findSimilar(VisualFeatures query, int limit) {
        List<Match> matches = new ArrayList<>();
        for (Entry entry : entries) matches.add(new Match(entry, similarity(query, entry.features)));
        matches.sort(Comparator.comparingDouble((Match match) -> match.similarity).reversed());
        return matches.subList(0, Math.min(limit, matches.size()));
    }

    public List<Match> findSimilar(String eventId, long now, VisualFeatures query, int limit) {
        List<Match> matches = new ArrayList<>();
        for (Entry entry : entries) {
            float visual = BatchPatternDetector.similarity(query, entry.features);
            float sameEventBoost = !eventId.isEmpty() && eventId.equals(entry.eventId) ? 1.12f : 1f;
            long ageDays = entry.capturedAt <= 0L ? 0L : Math.max(0L, (now - entry.capturedAt) / 86_400_000L);
            float recency = ageDays <= 30 ? 1f : Math.max(.82f, 1f - (Math.min(ageDays, 3650L) / 3650f) * .18f);
            matches.add(new Match(entry, Math.min(1f, visual * sameEventBoost * recency)));
        }
        matches.sort(Comparator.comparingDouble((Match match) -> match.similarity).reversed());
        return matches.subList(0, Math.min(limit, matches.size()));
    }

    public int reviewedCount() { return entries.size(); }

    private static float similarity(VisualFeatures a, VisualFeatures b) { return BatchPatternDetector.similarity(a, b); }
}
