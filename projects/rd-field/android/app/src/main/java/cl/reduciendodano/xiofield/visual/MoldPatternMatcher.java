package cl.reduciendodano.xiofield.visual;

import cl.reduciendodano.xiofield.core.VisualFeatures;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;

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

    /** Stable evidence key for recurrence when no human name exists yet. */
    public static String fingerprint(VisualFeatures features) {
        if (features == null) return "MOLD-UNKNOWN";
        String material = features.geometrySignature + "|" + features.reliefSignature + "|"
                + String.format(java.util.Locale.US, "%.3f|%.3f|%.3f", features.aspectRatio, features.circularity, features.solidity);
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(material.getBytes(StandardCharsets.UTF_8));
            StringBuilder value = new StringBuilder("MOLD-");
            for (int i = 0; i < 6; i++) value.append(String.format(java.util.Locale.US, "%02X", digest[i]));
            return value.toString();
        } catch (NoSuchAlgorithmException error) {
            return "MOLD-" + Integer.toHexString(material.hashCode()).toUpperCase(java.util.Locale.ROOT);
        }
    }
}
