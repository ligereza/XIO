package cl.reduciendodano.xiofield.visual;

import cl.reduciendodano.xiofield.core.VisualFeatures;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.Collections;
import java.util.HashMap;
import java.util.Map;
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
        public final String referenceId;
        public final int catalogRevision;
        public final boolean approved;

        public Entry(String captureId, String sampleCode, String reviewedLabel, VisualFeatures features) {
            this(captureId, sampleCode, "", 0L, reviewedLabel, features);
        }

        public Entry(String captureId, String sampleCode, String eventId, long capturedAt, String reviewedLabel, VisualFeatures features) {
            this(captureId, sampleCode, eventId, capturedAt, reviewedLabel, "", "", features);
        }

        public Entry(String captureId, String sampleCode, String eventId, long capturedAt, String reviewedLabel,
                     String declaredSubstance, String reviewedField, VisualFeatures features) {
            this(captureId, sampleCode, eventId, capturedAt, reviewedLabel, declaredSubstance,
                    reviewedField, features, "", 0, false);
        }

        public Entry(String captureId, String sampleCode, String eventId, long capturedAt, String reviewedLabel,
                     String declaredSubstance, String reviewedField, VisualFeatures features,
                     String referenceId, int catalogRevision, boolean approved) {
            this.captureId = captureId;
            this.sampleCode = sampleCode;
            this.eventId = eventId;
            this.capturedAt = capturedAt;
            this.reviewedLabel = reviewedLabel == null ? "" : reviewedLabel;
            this.declaredSubstance = declaredSubstance == null ? "" : declaredSubstance;
            this.reviewedField = reviewedField == null ? "" : reviewedField;
            this.features = features;
            this.referenceId = referenceId == null ? "" : referenceId;
            this.catalogRevision = catalogRevision;
            this.approved = approved;
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

    public void addApproved(Entry entry) {
        entries.removeIf(item -> !entry.referenceId.isEmpty()
                && entry.referenceId.equals(item.referenceId)
                && entry.captureId.equals(item.captureId));
        entries.add(entry);
    }

    public void clearApproved() { entries.removeIf(item -> item.approved); }

    public int approvedCount() {
        int count = 0;
        for (Entry entry : entries) if (entry.approved) count++;
        return count;
    }

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
        Map<String, List<Entry>> references = new HashMap<>();
        for (Entry entry : entries) {
            if (!entry.approved || !isMoldEntry(entry)
                    || (!entry.declaredSubstance.isEmpty() && !isEcstasy(entry.declaredSubstance))) continue;
            if (entry.features == null || entry.features.reliefConfidence < .45f) continue;
            String reference = entry.referenceId.isEmpty() ? entry.captureId : entry.referenceId;
            references.computeIfAbsent(reference, ignored -> new ArrayList<>()).add(entry);
        }
        boolean multiView = queryViews.size() >= 2;
        float threshold = multiView ? .82f : .90f;
        int requiredSupport = multiView ? 2 : 1;
        for (Map.Entry<String, List<Entry>> reference : references.entrySet()) {
            float scoreTotal = 0f;
            int support = 0;
            String explanation = "parecido visual";
            for (VisualFeatures query : queryViews) {
                if (query == null || query.reliefConfidence < .45f || query.silhouetteConfidence < .55f) continue;
                float best = 0f;
                Entry bestEntry = null;
                for (Entry candidateEntry : reference.getValue()) {
                    float candidate = MoldPatternMatcher.similarity(query, candidateEntry.features);
                    if (candidate > best) { best = candidate; bestEntry = candidateEntry; }
                }
                if (best >= threshold) {
                    support++;
                    scoreTotal += best;
                    if (bestEntry != null) explanation = MoldPatternMatcher.explanation(query, bestEntry.features);
                }
            }
            if (support < requiredSupport) continue;
            float score = scoreTotal / Math.max(1, support);
            Entry representative = reference.getValue().get(0);
            long ageDays = representative.capturedAt <= 0L ? 0L : Math.max(0L, (now - representative.capturedAt) / 86_400_000L);
            float recency = ageDays <= 365 ? 1f : Math.max(.88f, 1f - (Math.min(ageDays, 3650L) / 3650f) * .12f);
            float sameEvent = !eventId.isEmpty() && eventId.equals(representative.eventId) ? 1.04f : 1f;
            matches.add(new Match(representative, Math.min(1f, score * recency * sameEvent), explanation));
        }
        matches.sort(Comparator.comparingDouble((Match match) -> match.similarity).reversed());
        if (matches.size() > 1 && matches.get(0).similarity - matches.get(1).similarity < .12f) return Collections.emptyList();
        return matches.subList(0, Math.min(limit, matches.size()));
    }

    private static boolean isMoldEntry(Entry entry) {
        return entry.reviewedField.toLowerCase().startsWith("mold_design")
                || entry.reviewedLabel.toLowerCase().startsWith("molde:");
    }

    private static boolean isEcstasy(String value) {
        if (value == null) return false;
        String clean = value.toLowerCase().replace("é", "e");
        return clean.contains("extasis") || clean.contains("mdma");
    }

    private static float similarity(VisualFeatures a, VisualFeatures b) { return BatchPatternDetector.similarity(a, b); }
}
