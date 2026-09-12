package cl.reduciendodano.xiofield.visual;

import cl.reduciendodano.xiofield.core.VisualFeatures;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.Collections;
import java.util.List;

/** Local nearest-neighbour memory. Reviewed examples become searchable without pretending to be a chemical classifier. */
public final class VisualMemory {
    public static final class Entry {
        public final String captureId;
        public final String sampleCode;
        public final String eventId;
        public final long capturedAt;
        public final String reviewedLabel;
        public final String declaredSubstance;
        public final String reviewedField;
        public final VisualFeatures features;

        public Entry(String captureId, String sampleCode, String reviewedLabel, VisualFeatures features) {
            this(captureId, sampleCode, "", 0L, reviewedLabel, features);
        }

        public Entry(String captureId, String sampleCode, String eventId, long capturedAt, String reviewedLabel, VisualFeatures features) {
            this(captureId, sampleCode, eventId, capturedAt, reviewedLabel, "", "", features);
        }

        public Entry(String captureId, String sampleCode, String eventId, long capturedAt, String reviewedLabel,
                     String declaredSubstance, String reviewedField, VisualFeatures features) {
            this.captureId = captureId;
            this.sampleCode = sampleCode;
            this.eventId = eventId;
            this.capturedAt = capturedAt;
            this.reviewedLabel = reviewedLabel == null ? "" : reviewedLabel;
            this.declaredSubstance = declaredSubstance == null ? "" : declaredSubstance;
            this.reviewedField = reviewedField == null ? "" : reviewedField;
            this.features = features;
        }
    }

    public static final class Match {
        public final Entry entry;
        public final float similarity;
        public final String explanation;

        public Match(Entry entry, float similarity) { this(entry, similarity, "parecido visual"); }
        public Match(Entry entry, float similarity, String explanation) {
            this.entry = entry; this.similarity = similarity; this.explanation = explanation == null ? "" : explanation;
        }
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

    public List<Match> findMoldMatches(String substance, String eventId, long now, VisualFeatures query, int limit) {
        return findMoldMatches(substance, eventId, now, query == null ? Collections.emptyList() : Collections.singletonList(query), limit);
    }

    public List<Match> findMoldMatches(String substance, String eventId, long now, List<VisualFeatures> queryViews, int limit) {
        List<Match> matches = new ArrayList<>();
        if (!isEcstasy(substance) || queryViews == null || queryViews.isEmpty()) return matches;
        for (Entry entry : entries) {
            if (!isMoldEntry(entry) || (!entry.declaredSubstance.isEmpty() && !isEcstasy(entry.declaredSubstance))) continue;
            float score = 0f;
            String explanation = "parecido visual";
            for (VisualFeatures query : queryViews) {
                float candidate = MoldPatternMatcher.similarity(query, entry.features);
                if (candidate > score) { score = candidate; explanation = MoldPatternMatcher.explanation(query, entry.features); }
            }
            long ageDays = entry.capturedAt <= 0L ? 0L : Math.max(0L, (now - entry.capturedAt) / 86_400_000L);
            float recency = ageDays <= 365 ? 1f : Math.max(.88f, 1f - (Math.min(ageDays, 3650L) / 3650f) * .12f);
            float sameEvent = !eventId.isEmpty() && eventId.equals(entry.eventId) ? 1.04f : 1f;
            matches.add(new Match(entry, Math.min(1f, score * recency * sameEvent), explanation));
        }
        matches.sort(Comparator.comparingDouble((Match match) -> match.similarity).reversed());
        return matches.subList(0, Math.min(limit, matches.size()));
    }

    private static boolean isMoldEntry(Entry entry) {
        return "mold_design".equalsIgnoreCase(entry.reviewedField)
                || entry.reviewedLabel.toLowerCase().startsWith("molde:");
    }

    private static boolean isEcstasy(String value) {
        if (value == null) return false;
        String clean = value.toLowerCase().replace("é", "e");
        return clean.contains("extasis") || clean.contains("mdma");
    }

    private static float similarity(VisualFeatures a, VisualFeatures b) { return BatchPatternDetector.similarity(a, b); }
}
