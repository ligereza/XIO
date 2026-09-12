package cl.reduciendodano.xiofield.visual;

import cl.reduciendodano.xiofield.core.VisualFeatures;

/** Visual-only comparison for tablet mould/design recurrence. */
public final class MoldPatternMatcher {
    private MoldPatternMatcher() {}

    public static float similarity(VisualFeatures query, VisualFeatures reference) {
        if (query == null || reference == null) return 0f;
        float geometry = BatchPatternDetector.geometrySimilarity(query, reference);
        float relief = BatchPatternDetector.reliefSimilarity(query, reference);
        float hash = 1f - (Long.bitCount(query.perceptualHash ^ reference.perceptualHash) / 64f);
        float shape = 1f - Math.min(1f, Math.abs(query.aspectRatio - reference.aspectRatio));
        float marking = 1f - Math.min(1f, Math.abs(query.markingScore - reference.markingScore));
        // Design is carried mainly by contour and relief; colour is omitted so
        // the same press can be found under different lighting or dyes.
        float score = geometry * .48f + relief * .30f + hash * .12f + shape * .07f + marking * .03f;
        if (query.silhouetteConfidence < .20f || reference.silhouetteConfidence < .20f) score *= .72f;
        return Math.max(0f, Math.min(1f, score));
    }

    public static String explanation(VisualFeatures query, VisualFeatures reference) {
        if (query == null || reference == null) return "sin evidencia visual comparable";
        float geometry = BatchPatternDetector.geometrySimilarity(query, reference);
        float relief = BatchPatternDetector.reliefSimilarity(query, reference);
        if (geometry >= relief + .12f) return "contorno/proporción coinciden más";
        if (relief >= geometry + .12f) return "relieve o marca interior coinciden más";
        return "contorno y relieve coinciden";
    }
}
