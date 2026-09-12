package cl.reduciendodano.xiofield.data;

import android.content.Context;
import android.util.Base64;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

import cl.reduciendodano.xiofield.core.SampleSession;
import cl.reduciendodano.xiofield.core.VisualFeatures;
import cl.reduciendodano.xiofield.visual.MoldPatternMatcher;

/**
 * Small LAN client for the XIO RD host. The mobile app remains usable
 * offline; synchronization is an explicit projection of the local session.
 */
public final class FlujoGateway {
    public static final String XIO_BASE_ENDPOINT = "http://127.0.0.1:5000";
    public static final String DEFAULT_ENDPOINT = XIO_BASE_ENDPOINT + "/api/plugins/rd_field";
    private static final String USB_TUNNEL_ENDPOINT = XIO_BASE_ENDPOINT;
    private static final int CONNECT_TIMEOUT_MS = 4500;
    private static final int READ_TIMEOUT_MS = 12000;
    private static final int MAX_PHOTO_BYTES = 5 * 1024 * 1024;
    // Base64 expands the bytes; keep the raw-photo budget below XIO's 8 MB
    // request cap after JSON encoding and metadata are added.
    private static final int MAX_PAYLOAD_BYTES = 4 * 1024 * 1024;
    private final Context context;
    private final ExecutorService executor = Executors.newSingleThreadExecutor();

    public FlujoGateway(Context context) {
        this.context = context.getApplicationContext();
    }

    public void syncSample(SampleSession sample, String endpoint, String token, Callback callback) {
        executor.execute(() -> {
            try {
                JSONObject payload = buildPayload(sample);
                JSONObject response = requestWithUsbFallback("POST", endpoint + "/sync", payload, token);
                deliver(callback, Result.success(response));
            } catch (Exception error) {
                deliver(callback, Result.failure(error));
            }
        });
    }

    public void syncEvent(JSONObject event, String endpoint, String token, Callback callback) {
        executor.execute(() -> {
            try {
                JSONObject response = requestWithUsbFallback("POST", endpoint + "/events/sync", event, token);
                deliver(callback, Result.success(response));
            } catch (Exception error) {
                deliver(callback, Result.failure(error));
            }
        });
    }

    public void loadBootstrap(String endpoint, String token, Callback callback) {
        executor.execute(() -> {
            try {
                JSONObject response = requestWithUsbFallback("GET", endpoint + "/bootstrap", null, token);
                deliver(callback, Result.success(response));
            } catch (Exception error) {
                deliver(callback, Result.failure(error));
            }
        });
    }

    public void loadSamples(String endpoint, String eventRef, String sampleCode, Callback callback) {
        executor.execute(() -> {
            try {
                String encodedEvent = URLEncoder.encode(eventRef == null ? "" : eventRef, "UTF-8");
                String target = endpoint + "/samples?eventRef=" + encodedEvent;
                if (sampleCode != null && !sampleCode.trim().isEmpty()) {
                    target += "&sampleCode=" + URLEncoder.encode(sampleCode.trim(), "UTF-8");
                }
                JSONObject response = requestWithUsbFallback("GET", target, null, "");
                deliver(callback, Result.success(response));
            } catch (Exception error) {
                deliver(callback, Result.failure(error));
            }
        });
    }

    public void shutdown() {
        executor.shutdownNow();
    }

    JSONObject buildPayload(SampleSession sample) throws IOException, JSONException {
        JSONObject payload = new JSONObject();
        payload.put("schema", "xio-flujo-rd-v1");
        payload.put("date", new SimpleDateFormat("yyyy-MM-dd", Locale.US).format(new Date(sample.createdAt)));
        payload.put("eventRef", sample.eventId);
        payload.put("eventOrigin", "xio_app");
        payload.put("sampleCode", sample.code);
        payload.put("substanceDeclared", safe(sample.declaredSubstance, "sin declarar"));
        payload.put("sampleType", safe(sample.presentation, "sin clasificar"));

        SampleSession.Capture latest = latestCapture(sample);
        VisualFeatures features = latest == null ? null : latest.features;
        payload.put("color", sample.observedColor == null || sample.observedColor.isEmpty() ? (features == null ? "" : features.colorLabel) : sample.observedColor);
        payload.put("texture", textureText(features));
        payload.put("logoOrMark", reviewedMark(sample, features));
        payload.put("moldDesign", reviewedMoldDesign(sample));
        payload.put("moldFingerprint", MoldPatternMatcher.fingerprint(designViews(sample)));
        payload.put("mesa", new JSONObject().put("label", "XIO / mesa móvil").put("number", 1));
        payload.put("notes", notes(sample, features));

        JSONArray captures = new JSONArray();
        int encodedBytes = 0;
        for (SampleSession.Capture capture : sample.captures) {
            JSONObject item = new JSONObject();
            item.put("id", capture.id);
            item.put("kind", capture.kind);
            item.put("capturedAt", capture.capturedAt);
            item.put("sha256", safe(capture.sha256, ""));
            item.put("photoRef", "sha256:" + safe(capture.sha256, capture.id));
            item.put("silhouetteRef", capture.silhouettePath == null || capture.silhouettePath.isEmpty() ? "" : "svg:" + capture.id);
            item.put("silhouettePreviewRef", capture.silhouettePreviewPath == null || capture.silhouettePreviewPath.isEmpty() ? "" : "png:" + capture.id);
            item.put("reliefRef", capture.reliefPath == null || capture.reliefPath.isEmpty() ? "" : "svg:" + capture.id + ".relief");
            item.put("geometrySignature", safe(capture.features.geometrySignature, ""));
            item.put("reliefSignature", safe(capture.features.reliefSignature, ""));
            item.put("silhouetteConfidence", capture.features.silhouetteConfidence);
            item.put("reliefConfidence", capture.features.reliefConfidence);
            item.put("circularity", capture.features.circularity);
            item.put("solidity", capture.features.solidity);
            item.put("symmetry", capture.features.symmetry);
            item.put("contourPointCount", capture.features.contourPointCount);
            File file = new File(capture.path);
            long fileLength = file.isFile() ? file.length() : 0L;
            if (fileLength > 0 && fileLength <= MAX_PHOTO_BYTES && encodedBytes + fileLength <= MAX_PAYLOAD_BYTES) {
                byte[] bytes = readBytes(file, MAX_PHOTO_BYTES);
                if (bytes.length <= MAX_PHOTO_BYTES && encodedBytes + bytes.length <= MAX_PAYLOAD_BYTES) {
                    item.put("photoBase64", Base64.encodeToString(bytes, Base64.NO_WRAP));
                    encodedBytes += bytes.length;
                }
            }
            captures.put(item);
        }
        payload.put("captures", captures);

        JSONArray tests = new JSONArray();
        for (SampleSession.TestSession test : sample.tests) {
            JSONObject item = new JSONObject();
            item.put("reagent", safe(test.reagent, "sin reactivo"));
            item.put("order", test.ordinal);
            item.put("resultColor", latestObservation(test));
            item.put("family", "");
            item.put("matchesDeclared", JSONObject.NULL);
            item.put("suspectedAdulterant", "");
            tests.put(item);
        }
        payload.put("tests", tests);
        return payload;
    }

    private JSONObject request(String method, String target, JSONObject body, String token) throws IOException, JSONException {
        HttpURLConnection connection = (HttpURLConnection) new URL(target).openConnection();
        connection.setRequestMethod(method);
        connection.setConnectTimeout(CONNECT_TIMEOUT_MS);
        connection.setReadTimeout(READ_TIMEOUT_MS);
        connection.setRequestProperty("Accept", "application/json");
        if (token != null && !token.trim().isEmpty()) connection.setRequestProperty("X-XIO-Token", token.trim());
        if (body != null) {
            byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
            connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            connection.setFixedLengthStreamingMode(bytes.length);
            connection.getOutputStream().write(bytes);
        }
        int status = connection.getResponseCode();
        java.io.InputStream input = status >= 400 ? connection.getErrorStream() : connection.getInputStream();
        String responseText = input == null ? "{}" : new String(readAll(input), StandardCharsets.UTF_8);
        connection.disconnect();
        if (status < 200 || status >= 300) throw new IOException("XIO-RD HTTP " + status + ": " + responseText);
        return new JSONObject(responseText);
    }

    private JSONObject requestWithUsbFallback(String method, String target, JSONObject body, String token) throws IOException, JSONException {
        try {
            return request(method, target, body, token);
        } catch (IOException first) {
            if (target.startsWith(USB_TUNNEL_ENDPOINT)) throw first;
            // Development/field handoff: when USB reverse is active, keep the
            // same client usable even if the MAK firewall blocks the LAN port.
            return request(method, USB_TUNNEL_ENDPOINT + target.substring(target.indexOf('/', 8)), body, token);
        }
    }

    private static byte[] readBytes(File file, int maxBytes) throws IOException {
        try (FileInputStream input = new FileInputStream(file); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[8192];
            int total = 0;
            int count;
            while ((count = input.read(buffer)) != -1) {
                total += count;
                if (total > maxBytes) throw new IOException("foto demasiado grande");
                output.write(buffer, 0, count);
            }
            return output.toByteArray();
        }
    }

    private static byte[] readAll(java.io.InputStream input) throws IOException {
        try (java.io.InputStream source = input; ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[8192];
            int count;
            while ((count = source.read(buffer)) != -1) output.write(buffer, 0, count);
            return output.toByteArray();
        }
    }

    private static SampleSession.Capture latestCapture(SampleSession sample) {
        return sample.captures.isEmpty() ? null : sample.captures.get(sample.captures.size() - 1);
    }

    private static String textureText(VisualFeatures features) {
        if (features == null) return "";
        return String.format(Locale.US, "propuesta XIO · textura %.0f%%", features.textureScore * 100f);
    }

    private static String reviewedMark(SampleSession sample, VisualFeatures features) {
        String fallback = features == null ? "" : features.markingCandidate;
        for (int i = sample.corrections.size() - 1; i >= 0; i--) {
            SampleSession.Correction correction = sample.corrections.get(i);
            if (!"marking_label".equals(correction.field)) continue;
            String value = correction.correctedValue == null ? "" : correction.correctedValue.trim();
            int marker = value.lastIndexOf("operador:");
            return marker >= 0 ? value.substring(marker + "operador:".length()).trim() : value;
        }
        return fallback;
    }

    private static String reviewedMoldDesign(SampleSession sample) {
        for (int i = sample.corrections.size() - 1; i >= 0; i--) {
            SampleSession.Correction correction = sample.corrections.get(i);
            if (!"mold_design".equals(correction.field)) continue;
            String value = correction.correctedValue == null ? "" : correction.correctedValue.trim();
            if (value.toLowerCase(Locale.ROOT).startsWith("molde:")) return value.substring("molde:".length()).trim();
            return value;
        }
        return "";
    }

    private static String notes(SampleSession sample, VisualFeatures features) {
        String visual = features == null ? "" : features.compactDescription();
        SampleSession.Capture latest = latestCapture(sample);
        StringBuilder notes = new StringBuilder("xio_visual_source=proposal; model=visual-contour-v0.3; ");
        notes.append(visual).append("; phase=").append(sample.phase.name());
        String mold = reviewedMoldDesign(sample);
        if (!mold.isEmpty()) notes.append("; xio_mold_design=").append(mold);
        if (features != null) notes.append("; xio_mold_fingerprint=").append(MoldPatternMatcher.fingerprint(designViews(sample)));
        if (features != null) {
            notes.append(String.format(Locale.US, "; geometry_confidence=%.3f; circularity=%.3f; solidity=%.3f; symmetry=%.3f; contour_points=%d; geometry_signature=%s; relief_confidence=%.3f; relief_signature=%s", features.silhouetteConfidence, features.circularity, features.solidity, features.symmetry, features.contourPointCount, features.geometrySignature, features.reliefConfidence, features.reliefSignature));
        }
        if (latest != null && latest.silhouettePath != null && !latest.silhouettePath.isEmpty()) notes.append("; xio_silhouette_ref=svg:").append(latest.id);
        if (latest != null && latest.reliefPath != null && !latest.reliefPath.isEmpty()) notes.append("; xio_relief_ref=svg:").append(latest.id);
        return notes.toString();
    }

    private static String latestObservation(SampleSession.TestSession test) {
        if (!test.observations.isEmpty()) return safe(test.observations.get(test.observations.size() - 1).color, "");
        return safe(test.operatorResult, "");
    }

    private static List<VisualFeatures> designViews(SampleSession sample) {
        List<VisualFeatures> result = new ArrayList<>();
        for (SampleSession.Capture capture : sample.captures) if (capture.features != null) result.add(capture.features);
        return result;
    }

    private static String safe(String value, String fallback) {
        return value == null || value.trim().isEmpty() ? fallback : value.trim();
    }

    private void deliver(Callback callback, Result result) {
        new android.os.Handler(android.os.Looper.getMainLooper()).post(() -> callback.onComplete(result));
    }

    public interface Callback {
        void onComplete(Result result);
    }

    public static final class Result {
        public final JSONObject response;
        public final Exception error;

        private Result(JSONObject response, Exception error) {
            this.response = response;
            this.error = error;
        }

        static Result success(JSONObject response) { return new Result(response, null); }
        static Result failure(Exception error) { return new Result(null, error); }
        public boolean isSuccess() { return error == null; }
    }
}
