package cl.reduciendodano.xiofield.visual;

import cl.reduciendodano.xiofield.core.VisualFeatures;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

/**
 * Groups visually similar captures and gives context to recurrence. A group
 * is a visual pattern, never a substance identity or a batch-confirmation.
 */
public final class BatchPatternDetector {
    private static final float GROUP_THRESHOLD = .78f;

    public static final class Observation {
        public final String eventId;
        public final String sampleCode;
        public final long capturedAt;
        public final VisualFeatures features;

        public Observation(String eventId, String sampleCode, long capturedAt, VisualFeatures features) {
            this.eventId = eventId; this.sampleCode = sampleCode; this.capturedAt = capturedAt; this.features = features;
        }
    }

    public static final class Pattern {
        public final String representativeSampleCode;
        public final String eventId;
        public final List<String> sampleCodes = new ArrayList<>();
        public long firstSeen;
        public long lastSeen;
        public float confidence;
        private final VisualFeatures representativeFeatures;

        private Pattern(Observation first) {
            representativeSampleCode = first.sampleCode; eventId = first.eventId; representativeFeatures = first.features; firstSeen = first.capturedAt; lastSeen = first.capturedAt; confidence = 1f; sampleCodes.add(first.sampleCode);
        }

        public int recurrence() { return sampleCodes.size(); }
        public boolean repeatedInEvent() { return recurrence() > 1; }
    }

    public List<Pattern> detect(List<Observation> observations) {
        List<Pattern> patterns = new ArrayList<>();
        List<Observation> sorted = new ArrayList<>(observations);
        sorted.sort(Comparator.comparingLong(item -> item.capturedAt));
        for (Observation observation : sorted) {
            Pattern best = null; float bestSimilarity = 0f;
            for (Pattern pattern : patterns) {
                if (!pattern.eventId.equals(observation.eventId)) continue;
                float similarity = similarity(observation.features, pattern.representativeFeatures);
                if (similarity > bestSimilarity) { bestSimilarity = similarity; best = pattern; }
            }
            if (best != null && bestSimilarity >= GROUP_THRESHOLD) {
                best.sampleCodes.add(observation.sampleCode); best.lastSeen = Math.max(best.lastSeen, observation.capturedAt); best.confidence = Math.min(1f, (best.confidence + bestSimilarity) / 2f);
            } else {
                patterns.add(new Pattern(observation));
            }
        }
        patterns.sort(Comparator.comparingInt(Pattern::recurrence).reversed().thenComparingLong(pattern -> -pattern.lastSeen));
        return patterns;
    }

    public static float similarity(VisualFeatures a, VisualFeatures b) {
        float color = 1f - Math.min(1f, (Math.abs(a.meanRed - b.meanRed) + Math.abs(a.meanGreen - b.meanGreen) + Math.abs(a.meanBlue - b.meanBlue)) / 765f);
        float shape = 1f - Math.min(1f, Math.abs(a.aspectRatio - b.aspectRatio));
        float geometry = geometrySimilarity(a, b);
        float relief = reliefSimilarity(a, b);
        float texture = 1f - Math.min(1f, Math.abs(a.textureScore - b.textureScore));
        float hash = 1f - (Long.bitCount(a.perceptualHash ^ b.perceptualHash) / 64f);
        float marking = 1f - Math.min(1f, Math.abs(a.markingScore - b.markingScore));
        // The contour is the strongest visual identity available in the field:
        // colour and lighting drift, while the mould outline remains useful.
        return (color * .18f) + (geometry * .30f) + (relief * .14f) + (shape * .14f) + (texture * .10f) + (hash * .10f) + (marking * .04f);
    }

    /**
     * Compares normalized radial contours with cyclic alignment so that the
     * same mould can be found after the operator rotates the tablet. The
     * scalar geometry measurements keep the score useful when an old capture
     * has no SVG/signature yet.
     */
    public static float geometrySimilarity(VisualFeatures a, VisualFeatures b) {
        float contour = contourSimilarity(a.geometrySignature, b.geometrySignature);
        float metrics = 0f;
        int metricCount = 0;
        if (a.circularity > 0f && b.circularity > 0f) {
            metrics += 1f - Math.min(1f, Math.abs(a.circularity - b.circularity));
            metricCount++;
        }
        if (a.solidity > 0f && b.solidity > 0f) {
            metrics += 1f - Math.min(1f, Math.abs(a.solidity - b.solidity));
            metricCount++;
        }
        if (a.symmetry > 0f && b.symmetry > 0f) {
            metrics += 1f - Math.min(1f, Math.abs(a.symmetry - b.symmetry));
            metricCount++;
        }
        if (a.contourPointCount > 0 && b.contourPointCount > 0) {
            metrics += 1f - Math.min(1f, Math.abs(a.contourPointCount - b.contourPointCount) / 96f);
            metricCount++;
        }
        float metricScore = metricCount == 0 ? 0.5f : metrics / metricCount;
        if (a.geometrySignature.isEmpty() || b.geometrySignature.isEmpty()) {
            return metricCount == 0 ? (1f - Math.min(1f, Math.abs(a.aspectRatio - b.aspectRatio))) : metricScore;
        }
        return contour * .72f + metricScore * .28f;
    }

    /** Compares the normalized interior grayscale/relief map, rotation tolerant for field photos. */
    public static float reliefSimilarity(VisualFeatures a, VisualFeatures b) {
        float[] left = parseSignature(a.reliefSignature);
        float[] right = parseSignature(b.reliefSignature);
        if (left.length < 4 || right.length < 4) {
            return a.reliefConfidence > 0f && b.reliefConfidence > 0f
                    ? 1f - Math.min(1f, Math.abs(a.reliefConfidence - b.reliefConfidence))
                    : 0.5f;
        }
        int side = Math.max(1, Math.round((float) Math.sqrt(left.length)));
        int rightSide = Math.max(1, Math.round((float) Math.sqrt(right.length)));
        if (side * side != left.length || rightSide * rightSide != right.length) return vectorSimilarity(left, right);
        float best = 0f;
        for (int rotation = 0; rotation < 4; rotation++) {
            float error = 0f;
            for (int y = 0; y < side; y++) for (int x = 0; x < side; x++) {
                int targetX = rotation == 1 ? side - 1 - y : rotation == 2 ? side - 1 - x : rotation == 3 ? y : x;
                int targetY = rotation == 1 ? x : rotation == 2 ? side - 1 - y : rotation == 3 ? side - 1 - x : y;
                int leftIndex = y * side + x;
                int rightIndex = Math.min(right.length - 1, targetY * rightSide + Math.min(rightSide - 1, targetX * rightSide / side));
                error += Math.abs(left[leftIndex] - right[rightIndex]);
            }
            best = Math.max(best, 1f - Math.min(1f, error / left.length));
        }
        return best;
    }

    private static float contourSimilarity(String left, String right) {
        float[] a = parseSignature(left);
        float[] b = parseSignature(right);
        if (a.length < 3 || b.length < 3) return 0.5f;
        int length = Math.min(a.length, b.length);
        float best = 0f;
        for (int shift = 0; shift < length; shift++) {
            float error = 0f;
            for (int i = 0; i < length; i++) {
                float av = a[i * a.length / length];
                float bv = b[((i + shift) % length) * b.length / length];
                error += Math.abs(av - bv);
            }
            best = Math.max(best, 1f - Math.min(1f, error / length));
        }
        return best;
    }

    private static float[] parseSignature(String value) {
        if (value == null || value.trim().isEmpty()) return new float[0];
        String[] tokens = value.split(",");
        float[] parsed = new float[tokens.length];
        int count = 0;
        for (String token : tokens) {
            try {
                float number = Float.parseFloat(token.trim());
                if (Float.isNaN(number) || Float.isInfinite(number)) continue;
                parsed[count++] = Math.max(0f, Math.min(1f, number));
            } catch (NumberFormatException ignored) {
                // A malformed signature must not prevent the rest of the
                // sample from being searchable by its other observations.
            }
        }
        if (count == parsed.length) return parsed;
        float[] result = new float[count];
        System.arraycopy(parsed, 0, result, 0, count);
        return result;
    }

    private static float vectorSimilarity(float[] a, float[] b) {
        int length = Math.min(a.length, b.length);
        if (length == 0) return 0.5f;
        float error = 0f;
        for (int i = 0; i < length; i++) error += Math.abs(a[i * a.length / length] - b[i * b.length / length]);
        return 1f - Math.min(1f, error / length);
    }
}
