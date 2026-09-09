package cl.reduciendodano.xiofield.core;

/** Visual measurements extracted from a capture. They are observations, not chemical claims. */
public final class VisualFeatures {
    public final String colorLabel;
    public final String silhouetteLabel;
    public final float aspectRatio;
    public final float foregroundRatio;
    public final float brightness;
    public final float saturation;
    public final float textureScore;
    public final int meanRed;
    public final int meanGreen;
    public final int meanBlue;
    public final long perceptualHash;
    public final String markingCandidate;
    public final float markingScore;
    public final float reliefConfidence;
    public final String reliefSignature;
    public final float silhouetteConfidence;
    public final float circularity;
    public final float solidity;
    public final float symmetry;
    public final int contourPointCount;
    public final String geometrySignature;

    public VisualFeatures(String colorLabel, String silhouetteLabel, float aspectRatio, float foregroundRatio, float brightness, float saturation, float textureScore, int meanRed, int meanGreen, int meanBlue, long perceptualHash) {
        this(colorLabel, silhouetteLabel, aspectRatio, foregroundRatio, brightness, saturation, textureScore, meanRed, meanGreen, meanBlue, perceptualHash, "sin señal clara", 0f);
    }

    public VisualFeatures(String colorLabel, String silhouetteLabel, float aspectRatio, float foregroundRatio, float brightness, float saturation, float textureScore, int meanRed, int meanGreen, int meanBlue, long perceptualHash, String markingCandidate, float markingScore) {
        this(colorLabel, silhouetteLabel, aspectRatio, foregroundRatio, brightness, saturation, textureScore, meanRed, meanGreen, meanBlue, perceptualHash, markingCandidate, markingScore, 0f, "", 0f, 0f, 0f, 0f, 0, "");
    }

    public VisualFeatures(String colorLabel, String silhouetteLabel, float aspectRatio, float foregroundRatio, float brightness, float saturation, float textureScore, int meanRed, int meanGreen, int meanBlue, long perceptualHash, String markingCandidate, float markingScore, float silhouetteConfidence, float circularity, float solidity, float symmetry, int contourPointCount, String geometrySignature) {
        this(colorLabel, silhouetteLabel, aspectRatio, foregroundRatio, brightness, saturation, textureScore, meanRed, meanGreen, meanBlue, perceptualHash, markingCandidate, markingScore, 0f, "", silhouetteConfidence, circularity, solidity, symmetry, contourPointCount, geometrySignature);
    }

    public VisualFeatures(String colorLabel, String silhouetteLabel, float aspectRatio, float foregroundRatio, float brightness, float saturation, float textureScore, int meanRed, int meanGreen, int meanBlue, long perceptualHash, String markingCandidate, float markingScore, float reliefConfidence, String reliefSignature, float silhouetteConfidence, float circularity, float solidity, float symmetry, int contourPointCount, String geometrySignature) {
        this.colorLabel = colorLabel;
        this.silhouetteLabel = silhouetteLabel;
        this.aspectRatio = aspectRatio;
        this.foregroundRatio = foregroundRatio;
        this.brightness = brightness;
        this.saturation = saturation;
        this.textureScore = textureScore;
        this.meanRed = meanRed;
        this.meanGreen = meanGreen;
        this.meanBlue = meanBlue;
        this.perceptualHash = perceptualHash;
        this.markingCandidate = markingCandidate;
        this.markingScore = markingScore;
        this.reliefConfidence = reliefConfidence;
        this.reliefSignature = reliefSignature == null ? "" : reliefSignature;
        this.silhouetteConfidence = silhouetteConfidence;
        this.circularity = circularity;
        this.solidity = solidity;
        this.symmetry = symmetry;
        this.contourPointCount = contourPointCount;
        this.geometrySignature = geometrySignature == null ? "" : geometrySignature;
    }

    public String compactDescription() {
        return colorLabel + " · " + silhouetteLabel + " · proporción " + String.format(java.util.Locale.US, "%.2f", aspectRatio) + " · " + markingCandidate;
    }
}
