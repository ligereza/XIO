package cl.reduciendodano.xiofield.visual;

import android.graphics.Bitmap;
import android.graphics.Color;
import android.graphics.PointF;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.Comparator;
import java.util.List;
import java.util.Locale;

import cl.reduciendodano.xiofield.core.VisualFeatures;

/**
 * Offline visual extractor. It separates the object from its photo background,
 * keeps a second signal for internal relief, and emits a normalized contour
 * for geometric retrieval. It never emits a chemical claim.
 */
public final class VisualFeatureExtractor {
    private static final int ANALYSIS_SIZE = 256;
    private static final int CONTOUR_BINS = 48;
    private static final int RELIEF_GRID = 12;

    private VisualFeatureExtractor() {}

    public static VisualFeatures analyze(Bitmap source) {
        return analyzeDetailed(source).features;
    }

    public static VisualAnalysis analyzeDetailed(Bitmap source) {
        Bitmap bitmap = Bitmap.createScaledBitmap(source, ANALYSIS_SIZE, ANALYSIS_SIZE, true);
        int width = bitmap.getWidth();
        int height = bitmap.getHeight();
        float frameLuminance = averageLuminance(bitmap);
        boolean underexposed = frameLuminance < 28f;
        float[] background = estimateBackground(bitmap);
        float[] separation = new float[width * height];
        for (int y = 0; y < height; y++) {
            for (int x = 0; x < width; x++) {
                separation[y * width + x] = colorDistance(bitmap.getPixel(x, y), background[0], background[1], background[2]);
            }
        }

        float threshold = Math.max(16f, otsuThreshold(separation));
        boolean[] rawMask = new boolean[separation.length];
        for (int i = 0; i < separation.length; i++) rawMask[i] = separation[i] >= threshold;
        boolean[] mask = underexposed ? new boolean[separation.length]
                : bestComponent(close(rawMask, width, height), width, height);
        int objectPixels = count(mask);
        boolean separated = objectPixels >= width * height * .008f && objectPixels <= width * height * .86f;
        boolean fallbackUsed = false;
        if (!separated && !underexposed) {
            // Soft backgrounds and low-light camera frames can defeat the
            // first Otsu threshold. Try progressively more permissive *real
            // connected components*. Never invent a centered ellipse: that
            // would display a silhouette even when the photo contains no
            // separable object.
            for (float relaxed : new float[]{threshold * .80f, threshold * .65f, threshold * .50f, Math.max(8f, threshold * .35f)}) {
                boolean[] relaxedRaw = new boolean[separation.length];
                for (int i = 0; i < separation.length; i++) relaxedRaw[i] = separation[i] >= relaxed;
                boolean[] relaxedMask = bestComponent(close(relaxedRaw, width, height), width, height);
                int relaxedPixels = count(relaxedMask);
                if (relaxedPixels >= width * height * .003f && relaxedPixels <= width * height * .92f) {
                    mask = relaxedMask;
                    objectPixels = relaxedPixels;
                    threshold = relaxed;
                    break;
                }
            }
            fallbackUsed = true;
        }
        boolean contourAvailable = objectPixels >= width * height * .003f
                && objectPixels <= width * height * .92f;

        int minX = width, minY = height, maxX = -1, maxY = -1;
        float sumR = 0f, sumG = 0f, sumB = 0f, sumLuma = 0f, sumLumaSquared = 0f;
        int edgeCount = 0, interiorEdgeCount = 0, interiorForeground = 0;
        float foregroundSeparation = 0f;
        for (int y = 1; y < height - 1; y++) {
            for (int x = 1; x < width - 1; x++) {
                int index = y * width + x;
                if (!mask[index]) continue;
                int pixel = bitmap.getPixel(x, y);
                int r = Color.red(pixel), g = Color.green(pixel), b = Color.blue(pixel);
                float luma = luminance(pixel);
                sumR += r; sumG += g; sumB += b; sumLuma += luma; sumLumaSquared += luma * luma;
                foregroundSeparation += separation[index];
                if (contourAvailable) {
                    minX = Math.min(minX, x); maxX = Math.max(maxX, x);
                    minY = Math.min(minY, y); maxY = Math.max(maxY, y);
                }
                boolean inner = !contourAvailable || (x > width * .20f && x < width * .80f && y > height * .20f && y < height * .80f);
                if (inner) interiorForeground++;
                int right = bitmap.getPixel(x + 1, y);
                int down = bitmap.getPixel(x, y + 1);
                if (Math.abs(luma - luminance(right)) > 18f || Math.abs(luma - luminance(down)) > 18f) {
                    edgeCount++;
                    if (inner) interiorEdgeCount++;
                }
            }
        }

        float pixels = Math.max(1f, contourAvailable ? objectPixels : (width - 2) * (height - 2));
        int meanR = Math.round(sumR / pixels), meanG = Math.round(sumG / pixels), meanB = Math.round(sumB / pixels);
        float[] hsv = new float[3];
        Color.RGBToHSV(meanR, meanG, meanB, hsv);
        float aspect = contourAvailable && maxY > minY ? (float) (maxX - minX + 1) / (float) (maxY - minY + 1) : 0f;
        float foregroundRatio = contourAvailable ? objectPixels / (float) (width * height) : 0f;
        float variance = Math.max(0f, (sumLumaSquared / pixels) - ((sumLuma / pixels) * (sumLuma / pixels)));
        float texture = clamp((float) Math.sqrt(variance) / 80f + (edgeCount / pixels) * .35f);
        String colorLabel = semanticColor(hsv[0], hsv[1], hsv[2]);

        List<PointF> boundary = contourAvailable ? boundary(mask, width, height) : Collections.emptyList();
        float perimeter = contourAvailable ? perimeter(mask, width, height) : 0f;
        float area = contourAvailable ? objectPixels : 0f;
        float circularity = perimeter <= 0f ? 0f : clamp((float) ((4d * Math.PI * area) / (perimeter * perimeter)));
        // A broad, jagged low-contrast region is usually a table/shadow or
        // an underexposed frame, not the sample. Do not publish a misleading
        // silhouette when the contour quality itself contradicts the claim.
        if (contourAvailable && (underexposed || (foregroundRatio > .08f && circularity < .08f))) {
            mask = new boolean[separation.length];
            objectPixels = 0;
            contourAvailable = false;
            minX = width; minY = height; maxX = -1; maxY = -1;
            circularity = 0f;
        }
        float solidity = contourAvailable ? solidity(boundary, area) : 0f;
        float symmetry = contourAvailable ? symmetry(mask, width, height, minX, minY, maxX, maxY) : 0f;
        RadialContour radial = contourAvailable ? radialContour(boundary) : new RadialContour();
        String signature = radial.signature();
        String svg = contourAvailable ? svg(radial.points, minX, minY, maxX, maxY, meanR, meanG, meanB) : "";
        String silhouette = silhouette(aspect, circularity, solidity, contourAvailable);
        float interiorEdgeDensity = interiorEdgeCount / (float) Math.max(1, interiorForeground);
        float markingScore = contourAvailable ? clamp((interiorEdgeDensity - .07f) * 2.6f) : 0f;
        ReliefData relief = contourAvailable ? reliefData(bitmap, mask, width, height, minX, minY, maxX, maxY) : new ReliefData();
        markingScore = Math.max(markingScore, relief.confidence);
        String marking = markingLabel(markingScore, interiorEdgeDensity);
        float meanSeparation = foregroundSeparation / pixels;
        float confidence = contourAvailable ? clamp((meanSeparation / 255f) * .70f + Math.min(1f, boundary.size() / 80f) * .30f) : 0f;
        if (fallbackUsed) confidence *= .45f;
        long hash = averageHash(bitmap);
        Bitmap silhouettePreview = contourAvailable ? silhouettePreview(mask, width, height, meanR, meanG, meanB) : null;
        bitmap.recycle();

        VisualFeatures features = new VisualFeatures(colorLabel, silhouette, aspect, foregroundRatio, hsv[2], hsv[1], texture, meanR, meanG, meanB, hash, marking, markingScore, relief.confidence, relief.signature, confidence, circularity, solidity, symmetry, radial.count(), signature);
        return new VisualAnalysis(features, svg, relief.svg, silhouettePreview, contourAvailable, threshold);
    }

    public static final class VisualAnalysis {
        public final VisualFeatures features;
        public final String silhouetteSvg;
        public final String reliefSvg;
        public final Bitmap silhouettePreview;
        public final boolean separated;
        public final float threshold;

        private VisualAnalysis(VisualFeatures features, String silhouetteSvg, String reliefSvg, Bitmap silhouettePreview, boolean separated, float threshold) {
            this.features = features;
            this.silhouetteSvg = silhouetteSvg;
            this.reliefSvg = reliefSvg;
            this.silhouettePreview = silhouettePreview;
            this.separated = separated;
            this.threshold = threshold;
        }
    }

    private static float[] estimateBackground(Bitmap bitmap) {
        int width = bitmap.getWidth(), height = bitmap.getHeight();
        int border = Math.max(2, width / 14);
        int[] red = new int[width * height], green = new int[width * height], blue = new int[width * height];
        int count = 0;
        for (int y = 0; y < height; y += 2) {
            for (int x = 0; x < width; x += 2) {
                if (x < border || y < border || x >= width - border || y >= height - border) {
                    int pixel = bitmap.getPixel(x, y);
                    red[count] = Color.red(pixel); green[count] = Color.green(pixel); blue[count] = Color.blue(pixel); count++;
                }
            }
        }
        return new float[]{median(red, count), median(green, count), median(blue, count)};
    }

    private static float median(int[] values, int length) {
        if (length <= 0) return 0f;
        Arrays.sort(values, 0, length);
        return values[length / 2];
    }

    private static float otsuThreshold(float[] values) {
        int[] histogram = new int[256];
        for (float value : values) histogram[Math.max(0, Math.min(255, Math.round(value)))]++;
        float total = values.length;
        float sum = 0f;
        for (int i = 0; i < histogram.length; i++) sum += i * histogram[i];
        float sumBackground = 0f, weightBackground = 0f, bestVariance = -1f, best = 16f;
        for (int threshold = 0; threshold < histogram.length; threshold++) {
            weightBackground += histogram[threshold];
            if (weightBackground <= 0f) continue;
            float weightForeground = total - weightBackground;
            if (weightForeground <= 0f) break;
            sumBackground += threshold * histogram[threshold];
            float meanBackground = sumBackground / weightBackground;
            float meanForeground = (sum - sumBackground) / weightForeground;
            float between = weightBackground * weightForeground * (meanBackground - meanForeground) * (meanBackground - meanForeground);
            if (between > bestVariance) { bestVariance = between; best = threshold; }
        }
        return best;
    }

    private static boolean[] close(boolean[] source, int width, int height) {
        boolean[] dilated = new boolean[source.length];
        boolean[] closed = new boolean[source.length];
        for (int y = 1; y < height - 1; y++) {
            for (int x = 1; x < width - 1; x++) {
                boolean any = false;
                for (int dy = -1; dy <= 1 && !any; dy++) for (int dx = -1; dx <= 1; dx++) if (source[(y + dy) * width + (x + dx)]) { any = true; break; }
                dilated[y * width + x] = any;
            }
        }
        for (int y = 1; y < height - 1; y++) {
            for (int x = 1; x < width - 1; x++) {
                boolean all = true;
                for (int dy = -1; dy <= 1 && all; dy++) for (int dx = -1; dx <= 1; dx++) if (!dilated[(y + dy) * width + (x + dx)]) { all = false; break; }
                closed[y * width + x] = all;
            }
        }
        return closed;
    }

    private static boolean[] largestComponent(boolean[] source, int width, int height) {
        boolean[] visited = new boolean[source.length];
        boolean[] best = new boolean[source.length];
        int[] queue = new int[source.length];
        int[] component = new int[source.length];
        int bestCount = 0;
        for (int start = 0; start < source.length; start++) {
            if (!source[start] || visited[start]) continue;
            int head = 0, tail = 0, componentCount = 0;
            queue[tail++] = start; visited[start] = true;
            while (head < tail) {
                int index = queue[head++]; component[componentCount++] = index;
                int x = index % width, y = index / width;
                for (int dy = -1; dy <= 1; dy++) for (int dx = -1; dx <= 1; dx++) {
                    if (dx == 0 && dy == 0) continue;
                    int nx = x + dx, ny = y + dy;
                    if (nx < 0 || ny < 0 || nx >= width || ny >= height) continue;
                    int next = ny * width + nx;
                    if (source[next] && !visited[next]) { visited[next] = true; queue[tail++] = next; }
                }
            }
            if (componentCount > bestCount) {
                Arrays.fill(best, false);
                for (int i = 0; i < componentCount; i++) best[component[i]] = true;
                bestCount = componentCount;
            }
        }
        return best;
    }

    /** Prefer an object fully inside the frame over furniture/table edges. */
    private static boolean[] bestComponent(boolean[] source, int width, int height) {
        boolean[] visited = new boolean[source.length];
        boolean[] best = new boolean[source.length];
        int[] queue = new int[source.length];
        int[] component = new int[source.length];
        int bestInteriorCount = 0;
        float marginX = width * .08f, marginY = height * .08f;
        for (int start = 0; start < source.length; start++) {
            if (!source[start] || visited[start]) continue;
            int head = 0, tail = 0, componentCount = 0;
            int minX = width, minY = height, maxX = -1, maxY = -1;
            queue[tail++] = start; visited[start] = true;
            while (head < tail) {
                int index = queue[head++]; component[componentCount++] = index;
                int x = index % width, y = index / width;
                minX = Math.min(minX, x); minY = Math.min(minY, y);
                maxX = Math.max(maxX, x); maxY = Math.max(maxY, y);
                for (int dy = -1; dy <= 1; dy++) for (int dx = -1; dx <= 1; dx++) {
                    if (dx == 0 && dy == 0) continue;
                    int nx = x + dx, ny = y + dy;
                    if (nx < 0 || ny < 0 || nx >= width || ny >= height) continue;
                    int next = ny * width + nx;
                    if (source[next] && !visited[next]) { visited[next] = true; queue[tail++] = next; }
                }
            }
            // XIO-RD photos are evidence captures, not arbitrary landscapes:
            // the relevant sample is expected away from the frame. This
            // rejects table/laptop edges that morphology can detach by one
            // pixel while retaining a small central tablet/powder sample.
            boolean interior = minX > marginX && minY > marginY
                    && maxX < width - marginX && maxY < height - marginY;
            if (interior && componentCount > bestInteriorCount) {
                Arrays.fill(best, false);
                for (int i = 0; i < componentCount; i++) best[component[i]] = true;
                bestInteriorCount = componentCount;
            }
        }
        return bestInteriorCount > 0 ? best : new boolean[source.length];
    }

    private static int count(boolean[] mask) {
        int count = 0;
        for (boolean value : mask) if (value) count++;
        return count;
    }

    private static List<PointF> boundary(boolean[] mask, int width, int height) {
        List<PointF> points = new ArrayList<>();
        for (int y = 1; y < height - 1; y++) for (int x = 1; x < width - 1; x++) {
            if (!mask[y * width + x]) continue;
            boolean edge = false;
            for (int dy = -1; dy <= 1 && !edge; dy++) for (int dx = -1; dx <= 1; dx++) if (!mask[(y + dy) * width + (x + dx)]) { edge = true; break; }
            if (edge) points.add(new PointF(x, y));
        }
        return points;
    }

    private static float perimeter(boolean[] mask, int width, int height) {
        float total = 0f;
        for (int y = 1; y < height - 1; y++) for (int x = 1; x < width - 1; x++) if (mask[y * width + x]) {
            if (!mask[y * width + x - 1]) total++;
            if (!mask[y * width + x + 1]) total++;
            if (!mask[(y - 1) * width + x]) total++;
            if (!mask[(y + 1) * width + x]) total++;
        }
        return total;
    }

    private static float solidity(List<PointF> boundary, float area) {
        if (boundary.size() < 3 || area <= 0f) return 0f;
        List<PointF> points = new ArrayList<>(boundary);
        points.sort(Comparator.comparingDouble((PointF point) -> point.x).thenComparingDouble(point -> point.y));
        List<PointF> hull = new ArrayList<>();
        for (PointF point : points) {
            while (hull.size() >= 2 && cross(hull.get(hull.size() - 2), hull.get(hull.size() - 1), point) <= 0f) hull.remove(hull.size() - 1);
            hull.add(point);
        }
        int lowerSize = hull.size();
        for (int i = points.size() - 2; i >= 0; i--) {
            PointF point = points.get(i);
            while (hull.size() > lowerSize && cross(hull.get(hull.size() - 2), hull.get(hull.size() - 1), point) <= 0f) hull.remove(hull.size() - 1);
            hull.add(point);
        }
        if (hull.size() > 1) hull.remove(hull.size() - 1);
        float hullArea = Math.abs(polygonArea(hull));
        return hullArea <= 0f ? 0f : clamp(area / hullArea);
    }

    private static float symmetry(boolean[] mask, int width, int height, int minX, int minY, int maxX, int maxY) {
        if (maxX <= minX || maxY <= minY) return 0f;
        int mismatchVertical = 0, mismatchHorizontal = 0, area = 0;
        for (int y = minY; y <= maxY; y++) for (int x = minX; x <= maxX; x++) {
            boolean value = mask[y * width + x];
            if (value) area++;
            if (value != mask[y * width + (minX + maxX - x)]) mismatchVertical++;
            if (value != mask[(minY + maxY - y) * width + x]) mismatchHorizontal++;
        }
        if (area == 0) return 0f;
        return clamp(Math.max(1f - mismatchVertical / (float) area, 1f - mismatchHorizontal / (float) area));
    }

    private static RadialContour radialContour(List<PointF> boundary) {
        RadialContour result = new RadialContour();
        if (boundary.isEmpty()) return result;
        float cx = 0f, cy = 0f;
        for (PointF point : boundary) { cx += point.x; cy += point.y; }
        cx /= boundary.size(); cy /= boundary.size();
        double[] radii = new double[CONTOUR_BINS];
        PointF[] points = new PointF[CONTOUR_BINS];
        for (PointF point : boundary) {
            double angle = Math.atan2(point.y - cy, point.x - cx) + Math.PI;
            int bin = Math.min(CONTOUR_BINS - 1, (int) (angle / (Math.PI * 2d) * CONTOUR_BINS));
            double radius = Math.hypot(point.x - cx, point.y - cy);
            if (radius > radii[bin]) { radii[bin] = radius; points[bin] = point; }
        }
        for (int i = 0; i < CONTOUR_BINS; i++) if (points[i] == null) {
            for (int step = 1; step < CONTOUR_BINS; step++) {
                int left = (i - step + CONTOUR_BINS) % CONTOUR_BINS;
                int right = (i + step) % CONTOUR_BINS;
                if (points[left] != null) { points[i] = points[left]; radii[i] = radii[left]; break; }
                if (points[right] != null) { points[i] = points[right]; radii[i] = radii[right]; break; }
            }
        }
        result.points = points;
        result.radii = radii;
        return result;
    }

    private static String svg(PointF[] points, int minX, int minY, int maxX, int maxY, int red, int green, int blue) {
        if (points == null || points.length < 3 || maxX <= minX || maxY <= minY) return "";
        StringBuilder path = new StringBuilder();
        boolean first = true;
        for (PointF point : points) {
            if (point == null) continue;
            float x = (point.x - minX) / Math.max(1f, maxX - minX) * 1000f;
            float y = (point.y - minY) / Math.max(1f, maxY - minY) * 1000f;
            path.append(first ? "M " : " L ").append(format(x)).append(' ').append(format(y));
            first = false;
        }
        return first ? "" : "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 1000 1000\"><path d=\"" + path + " Z\" fill=\"" + hexColor(red, green, blue) + "\"/></svg>";
    }

    private static Bitmap silhouettePreview(boolean[] mask, int width, int height, int red, int green, int blue) {
        Bitmap preview = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888);
        int[] pixels = new int[mask.length];
        int fill = Color.rgb(red, green, blue);
        for (int i = 0; i < mask.length; i++) pixels[i] = mask[i] ? fill : Color.TRANSPARENT;
        preview.setPixels(pixels, 0, width, 0, 0, width, height);
        return preview;
    }

    /** Builds a small grayscale/high-pass map for internal relief or a logo candidate. */
    private static ReliefData reliefData(Bitmap bitmap, boolean[] mask, int width, int height, int minX, int minY, int maxX, int maxY) {
        ReliefData result = new ReliefData();
        if (maxX <= minX || maxY <= minY) return result;
        float[] grid = new float[RELIEF_GRID * RELIEF_GRID];
        float sum = 0f, max = 0f;
        int occupied = 0;
        for (int gy = 0; gy < RELIEF_GRID; gy++) {
            int fromY = minY + (gy * (maxY - minY + 1)) / RELIEF_GRID;
            int toY = minY + ((gy + 1) * (maxY - minY + 1)) / RELIEF_GRID;
            for (int gx = 0; gx < RELIEF_GRID; gx++) {
                int fromX = minX + (gx * (maxX - minX + 1)) / RELIEF_GRID;
                int toX = minX + ((gx + 1) * (maxX - minX + 1)) / RELIEF_GRID;
                float cellSum = 0f;
                int cellCount = 0;
                for (int y = Math.max(1, fromY); y < Math.min(height - 1, toY); y++) {
                    for (int x = Math.max(1, fromX); x < Math.min(width - 1, toX); x++) {
                        float nx = (x - minX) / (float) Math.max(1, maxX - minX);
                        float ny = (y - minY) / (float) Math.max(1, maxY - minY);
                        if (nx < .12f || nx > .88f || ny < .12f || ny > .88f || !mask[y * width + x]) continue;
                        cellSum += gradientAt(bitmap, x, y);
                        cellCount++;
                    }
                }
                float value = cellCount == 0 ? 0f : cellSum / cellCount;
                grid[gy * RELIEF_GRID + gx] = value;
                if (cellCount > 0) { sum += value; occupied++; }
                max = Math.max(max, value);
            }
        }
        if (occupied == 0 || max <= 0f) return result;
        float mean = sum / occupied;
        float activeThreshold = Math.max(18f, mean * 1.65f);
        int active = 0;
        for (float value : grid) if (value >= activeThreshold) active++;
        float activeRatio = active / (float) grid.length;
        result.confidence = clamp(clamp((mean - 4f) / 30f) * .35f + clamp((max - 18f) / 82f) * .25f + clamp(activeRatio / .16f) * .40f);
        if (result.confidence < .20f) return result;
        StringBuilder signature = new StringBuilder();
        StringBuilder path = new StringBuilder();
        float cell = 1000f / RELIEF_GRID;
        for (int gy = 0; gy < RELIEF_GRID; gy++) {
            for (int gx = 0; gx < RELIEF_GRID; gx++) {
                float normalized = grid[gy * RELIEF_GRID + gx] / max;
                if (signature.length() > 0) signature.append(',');
                signature.append(format(normalized));
                if (grid[gy * RELIEF_GRID + gx] >= activeThreshold) {
                    float x = gx * cell, y = gy * cell;
                    path.append("M ").append(format(x)).append(' ').append(format(y)).append(" h ").append(format(cell)).append(" v ").append(format(cell)).append(" h -").append(format(cell)).append(" Z ");
                }
            }
        }
        result.signature = signature.toString();
        if (path.length() > 0) result.svg = "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 1000 1000\"><path d=\"" + path + "\" fill=\"white\"/></svg>";
        return result;
    }

    private static float gradientAt(Bitmap bitmap, int x, int y) {
        float horizontal = Math.abs(luminance(bitmap.getPixel(x - 1, y)) - luminance(bitmap.getPixel(x + 1, y)));
        float vertical = Math.abs(luminance(bitmap.getPixel(x, y - 1)) - luminance(bitmap.getPixel(x, y + 1)));
        return Math.min(255f, (horizontal + vertical) * .5f);
    }

    private static String silhouette(float aspect, float circularity, float solidity, boolean separated) {
        if (!separated || aspect <= 0f) return "no separada";
        if (aspect > 1.45f || aspect < .69f) return "alargada";
        if (circularity >= .72f && aspect >= .84f && aspect <= 1.18f) return "redonda";
        if (solidity < .84f) return "irregular / recortada";
        if (circularity < .48f) return "angular / compacta";
        return "compacta";
    }

    private static String semanticColor(float hue, float saturation, float value) {
        if (saturation < .10f) return value < .22f ? "muy oscuro" : value > .86f ? "blanco / claro" : "grisáceo";
        if (value < .20f) return "oscuro";
        if (hue < 18 || hue >= 345) return saturation < .28f ? "rosado / beige" : "rojo";
        if (hue < 45) return "amarillo / dorado";
        if (hue < 75) return "verde amarillento";
        if (hue < 165) return "verde";
        if (hue < 205) return "azul verdoso";
        if (hue < 260) return "azul";
        if (hue < 315) return "morado / rosado";
        return "rosado";
    }

    private static String markingLabel(float score, float density) {
        if (density < .05f) return "sin señal clara de marca";
        if (score >= .45f) return "señal fuerte de relieve / logo posible";
        return "señal débil de marca posible";
    }

    private static long averageHash(Bitmap bitmap) {
        long hash = 0L;
        float sum = 0f;
        float[] values = new float[64];
        for (int y = 0; y < 8; y++) for (int x = 0; x < 8; x++) {
            float value = luminance(bitmap.getPixel(x * bitmap.getWidth() / 8, y * bitmap.getHeight() / 8));
            values[y * 8 + x] = value; sum += value;
        }
        float average = sum / 64f;
        for (float value : values) hash = (hash << 1) | (value >= average ? 1L : 0L);
        return hash;
    }

    private static float colorDistance(int pixel, float r, float g, float b) {
        float dr = Color.red(pixel) - r, dg = Color.green(pixel) - g, db = Color.blue(pixel) - b;
        return Math.min(255f, (float) (Math.sqrt(dr * dr + dg * dg + db * db) / 1.732f));
    }

    private static float luminance(int pixel) { return (.2126f * Color.red(pixel)) + (.7152f * Color.green(pixel)) + (.0722f * Color.blue(pixel)); }
    private static float averageLuminance(Bitmap bitmap) {
        long total = 0L;
        int samples = 0;
        for (int y = 0; y < bitmap.getHeight(); y += 4) {
            for (int x = 0; x < bitmap.getWidth(); x += 4) {
                total += Math.round(luminance(bitmap.getPixel(x, y)));
                samples++;
            }
        }
        return total / (float) Math.max(1, samples);
    }
    private static float clamp(float value) { return Math.max(0f, Math.min(1f, value)); }
    private static float cross(PointF a, PointF b, PointF c) { return (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x); }
    private static float polygonArea(List<PointF> points) { float area = 0f; for (int i = 0; i < points.size(); i++) { PointF a = points.get(i), b = points.get((i + 1) % points.size()); area += (a.x * b.y) - (b.x * a.y); } return area / 2f; }
    private static String format(float value) { return String.format(Locale.US, "%.1f", value); }
    private static String hexColor(int red, int green, int blue) { return String.format(Locale.US, "#%02X%02X%02X", red, green, blue); }

    private static final class RadialContour {
        private PointF[] points = new PointF[0];
        private double[] radii = new double[0];
        int count() { int count = 0; for (PointF point : points) if (point != null) count++; return count; }
        String signature() {
            if (radii.length == 0) return "";
            double max = 0d; for (double radius : radii) max = Math.max(max, radius);
            StringBuilder value = new StringBuilder();
            for (double radius : radii) { if (value.length() > 0) value.append(','); value.append(String.format(Locale.US, "%.3f", max == 0d ? 0d : radius / max)); }
            return value.toString();
        }
    }

    private static final class ReliefData {
        private float confidence;
        private String signature = "";
        private String svg = "";
    }
}
