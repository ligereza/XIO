package cl.xio.foh;

import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.SharedPreferences;
import android.os.BatteryManager;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;

/**
 * Small dependency-free HTTP host for XIO-FOH.
 *
 * The native APK owns the active listener and this server owns the same local
 * evidence surface that the previous Python/Termux host exposed. Other phones
 * on the private hotspot can therefore keep using the existing HTML hub while
 * the Xiaomi itself uses the native APK UI. This is deliberately not a
 * WebView: the APK UI never depends on this server to measure signals.
 */
public final class FohNativeServer {
    /** Native FOH surface; XIO-RD/FLUJO keeps the shared host port 5000. */
    public static final int PORT = 5100;
    private final Context context;
    private final FohLogStore store;
    private final FohListener listener;
    private final SharedPreferences prefs;
    private final Object lifecycle = new Object();
    private volatile boolean running;
    private ServerSocket serverSocket;
    private Thread acceptThread;
    private JSONObject catalog;

    public FohNativeServer(Context context, FohLogStore store, FohListener listener) {
        this.context = context.getApplicationContext();
        this.store = store;
        this.listener = listener;
        this.prefs = this.context.getSharedPreferences("xio_foh", Context.MODE_PRIVATE);
        syncListenerSetlist();
    }

    public void start() {
        synchronized (lifecycle) {
            if (running) return;
            try {
                serverSocket = new ServerSocket(PORT, 32, InetAddress.getByName("0.0.0.0"));
                running = true;
                acceptThread = new Thread(this::acceptLoop, "xio-foh-http");
                acceptThread.start();
            } catch (IOException error) {
                running = false;
            }
        }
    }

    public boolean isRunning() { return running; }

    /** Snapshot for the native Activity and remote FOH browser clients. */
    public JSONObject localStatusJson() {
        try { return statusJson(); }
        catch (JSONException error) { return errorJson("estado local no disponible"); }
    }

    public void stop() {
        synchronized (lifecycle) {
            running = false;
            if (serverSocket != null) {
                try { serverSocket.close(); } catch (IOException ignored) { }
                serverSocket = null;
            }
            if (acceptThread != null) acceptThread.interrupt();
            acceptThread = null;
        }
    }

    private void acceptLoop() {
        while (running) {
            try {
                Socket client = serverSocket.accept();
                Thread worker = new Thread(() -> handle(client), "xio-foh-http-client");
                worker.start();
            } catch (IOException error) {
                if (running) continue;
            }
        }
    }

    private void handle(Socket socket) {
        try (Socket client = socket;
             InputStream input = client.getInputStream();
             OutputStream output = client.getOutputStream()) {
            BufferedReader reader = new BufferedReader(new InputStreamReader(input, StandardCharsets.ISO_8859_1));
            String requestLine = reader.readLine();
            if (requestLine == null || requestLine.isEmpty()) return;
            String[] parts = requestLine.split(" ", 3);
            if (parts.length < 2) { respond(output, 400, "text/plain; charset=utf-8", "solicitud invalida"); return; }
            String method = parts[0].toUpperCase();
            String target = parts[1];
            int contentLength = 0;
            String header;
            while ((header = reader.readLine()) != null && !header.isEmpty()) {
                int colon = header.indexOf(':');
                if (colon > 0 && "content-length".equalsIgnoreCase(header.substring(0, colon).trim())) {
                    try { contentLength = Integer.parseInt(header.substring(colon + 1).trim()); } catch (NumberFormatException ignored) { }
                }
            }
            char[] bodyChars = new char[Math.max(0, contentLength)];
            int offset = 0;
            while (offset < bodyChars.length) {
                int read = reader.read(bodyChars, offset, bodyChars.length - offset);
                if (read < 0) break;
                offset += read;
            }
            String body = new String(bodyChars, 0, offset);
            Response response = route(method, target, body);
            respond(output, response.status, response.type, response.body);
        } catch (Exception ignored) { }
    }

    private Response route(String method, String target, String body) {
        String path = target;
        String query = "";
        int q = target.indexOf('?');
        if (q >= 0) { path = target.substring(0, q); query = target.substring(q + 1); }
        if (path.startsWith("/api/plugins/foh_monitor")) {
            path = path.substring("/api/plugins/foh_monitor".length());
        }
        if (path.isEmpty() || "/".equals(path)) path = "/view";
        try {
            if ("GET".equals(method) && "/status".equals(path)) return json(statusJson());
            if ("GET".equals(method) && "/events".equals(path)) return json(eventsJson(query));
            if ("GET".equals(method) && "/context/data".equals(path)) return json(contextJson());
            if ("GET".equals(method) && "/context".equals(path)) return asset("context.html", "text/html; charset=utf-8");
            if ("POST".equals(method) && "/context".equals(path)) return postContext(body);
            if ("GET".equals(method) && "/setlist".equals(path)) return json(setlistJson());
            if ("POST".equals(method) && "/setlist".equals(path)) return postSetlist(body);
            if ("POST".equals(method) && "/next".equals(path)) return moveSetlist(1);
            if ("POST".equals(method) && "/prev".equals(path)) return moveSetlist(-1);
            if ("POST".equals(method) && "/ingest".equals(path)) return ingest(body);
            if ("GET".equals(method) && "/resumen".equals(path)) return summary(query);
            if ("GET".equals(method) && "/registro".equals(path)) return asset("registro.html", "text/html; charset=utf-8");
            if ("GET".equals(method) && "/mapping".equals(path)) return asset("mapping.html", "text/html; charset=utf-8");
            if ("GET".equals(method) && "/view".equals(path)) return asset("hub.html", "text/html; charset=utf-8");
            if ("GET".equals(method) && "/panel".equals(path)) return asset("panel.html", "text/html; charset=utf-8");
            if ("GET".equals(method) && "/manifest.webmanifest".equals(path)) return manifest();
            if ("GET".equals(method) && "/log".equals(path)) {
                String ndjson = store.logNdjson(query);
                return ndjson.isEmpty() ? new Response(404, "application/json; charset=utf-8", errorJson("no hay registro para esa fecha").toString())
                        : new Response(200, "application/x-ndjson; charset=utf-8", ndjson);
            }
            if ("GET".equals(method) && "/logs".equals(path)) return json(store.logsJson());
            if ("GET".equals(method) && "/raider".equals(path)) return asset("raider.html", "text/html; charset=utf-8");
            return new Response(404, "text/plain; charset=utf-8", "ruta FOH no disponible");
        } catch (Exception error) {
            return json(500, errorJson(error.getMessage() == null ? "error interno" : error.getMessage()));
        }
    }

    private Response ingest(String body) throws JSONException {
        JSONObject data = new JSONObject(body.isEmpty() ? "{}" : body);
        if (data.has("eventRef") || data.has("rdEventRef") || data.has("rd_event_ref")) {
            return json(422, errorJson("FOH usa eventKey; no acepta identidad RD eventRef"));
        }
        String protocol = data.optString("protocol", "").trim();
        String detail = data.optString("detail", "").trim();
        String eventKey = data.optString("eventKey", "").trim();
        if (protocol.isEmpty() || detail.isEmpty()) return json(400, errorJson("protocol y detail son obligatorios"));
        if (!eventKey.isEmpty() && findEvent(eventKey) == null) return json(409, errorJson("eventKey no existe en catalogo VJ/FOH"));
        store.append(System.currentTimeMillis(), protocol, detail, eventKey);
        return json(new JSONObject().put("ok", true).put("domain", "vj_foh").put("source", "xio_foh_apk"));
    }

    private Response postContext(String body) throws JSONException {
        JSONObject data = new JSONObject(body.isEmpty() ? "{}" : body);
        if (data.optBoolean("clear", false)) {
            prefs.edit().remove("eventKey").apply();
            listener.setEventKey("");
            return json(contextJson());
        }
        String key = data.optString("eventKey", "").trim();
        JSONObject event = findEvent(key);
        if (event == null) return json(409, errorJson("eventKey no existe en catalogo VJ/FOH"));
        prefs.edit().putString("eventKey", key).apply();
        listener.setEventKey(key);
        store.append(System.currentTimeMillis(), "contexto", "evento FOH seleccionado: " + key, key);
        JSONObject response = contextJson();
        response.put("setlistBinding", bindUnownedSetlist(event, key));
        return json(response);
    }

    /**
     * Associate a legacy setlist only when it has no owner and the selected
     * catalog event declares a show-kit setlist. This does not reset songs,
     * durations, index, or timestamps; an existing different owner wins.
     */
    private JSONObject bindUnownedSetlist(JSONObject event, String key) throws JSONException {
        String owner = prefs.getString("setlistEventKey", "").trim();
        JSONArray songs = setlistSongs();
        if (songs.length() == 0) return new JSONObject().put("status", "not_loaded").put("fohEventKey", owner.isEmpty() ? JSONObject.NULL : owner);
        if (!owner.isEmpty()) return new JSONObject().put("status", owner.equals(key) ? "already" : "conflict").put("fohEventKey", owner);
        JSONObject kit = event == null ? null : event.optJSONObject("showKit");
        String setlistRef = kit == null ? "" : kit.optString("setlist", "").trim();
        if (setlistRef.isEmpty()) return new JSONObject().put("status", "no_kit").put("fohEventKey", JSONObject.NULL);
        prefs.edit().putString("setlistEventKey", key).apply();
        store.append(System.currentTimeMillis(), "setlist_context_bound", "setlist=" + setlistRef, key);
        return new JSONObject().put("status", "bound").put("fohEventKey", key).put("setlist", setlistRef);
    }

    private Response postSetlist(String body) throws JSONException {
        JSONObject data = new JSONObject(body.isEmpty() ? "{}" : body);
        JSONArray songs = data.optJSONArray("songs");
        if (songs == null) {
            String text = data.optString("text", "");
            songs = new JSONArray();
            for (String line : text.split("\\R")) if (!line.trim().isEmpty()) songs.put(line.trim());
        }
        if (songs.length() == 0) return json(400, errorJson("setlist vacia"));
        JSONArray durations = data.optJSONArray("durations");
        if (durations == null) durations = durationsFromAssetOrNull();
        prefs.edit().putString("setlist", songs.toString()).putString("setlistEventKey", currentEventKey()).putInt("setlistIndex", 0).apply();
        listener.setSetlist(songs, durations, 0);
        store.append(System.currentTimeMillis(), "setlist", "cargada: " + songs.length() + " temas", currentEventKey());
        return json(setlistJson());
    }

    private Response moveSetlist(int delta) throws JSONException {
        JSONArray songs = setlistSongs();
        if (songs.length() == 0) return json(400, errorJson("sin setlist cargada"));
        int index = Math.max(0, Math.min(songs.length() - 1, prefs.getInt("setlistIndex", 0) + delta));
        prefs.edit().putInt("setlistIndex", index).apply();
        listener.setSetlist(songs, durationsFromAssetOrNull(), index);
        store.append(System.currentTimeMillis(), "setlist", "actual: " + songs.optString(index), currentEventKey());
        return json(setlistJson());
    }

    private Response summary(String query) throws JSONException {
        String key = queryValue(query, "eventKey");
        if (key.isEmpty()) return asset("resumen.html", "text/html; charset=utf-8");
        if (findEvent(key) == null) return json(409, errorJson("eventKey no existe en catalogo VJ/FOH"));
        JSONObject result = store.summaryJson(key);
        result.put("rows", store.eventsJson(key, 200));
        result.put("ok", true).put("domain", "vj_foh").put("readOnly", true);
        return json(result);
    }

    private JSONObject statusJson() throws JSONException {
        JSONObject channels = new JSONObject();
        for (Map.Entry<String, FohListener.Snapshot> entry : listener.snapshots().entrySet()) {
            FohListener.Snapshot s = entry.getValue();
            JSONObject channel = new JSONObject().put("active", s.active).put("packets_total", s.packets)
                    .put("pps", s.pps).put("port", s.port).put("detail", s.detail);
            channel.put("age", s.lastAt == 0 ? JSONObject.NULL : Math.max(0, (System.currentTimeMillis() - s.lastAt) / 1000));
            String key = "Art-Net".equals(entry.getKey()) ? "artnet" : "sACN".equals(entry.getKey()) ? "sacn" : "osc";
            channel.put("last_seen", s.lastAt == 0 ? JSONObject.NULL : s.lastAt);
            channel.put("invalid_packets", 0).put("error", JSONObject.NULL);
            channels.put(key, channel);
        }
        JSONObject audio = new JSONObject().put("available", false).put("active", false)
                .put("level_db", JSONObject.NULL).put("age", JSONObject.NULL)
                .put("reason", "audio nativo aun no habilitado; el panel conserva N/D honesto");
        return new JSONObject().put("ok", true).put("domain", "vj_foh").put("listener_mode", "native_apk")
                .put("server", running).put("httpPort", PORT).put("rdHostPort", 5000)
                .put("listener", listener.isRunning()).put("channels", channels).put("timecode", listener.timecodeSnapshot())
                .put("audio", audio).put("battery", batteryJson()).put("eventKey", currentEventKey())
                .put("context", currentContext()).put("setlist", setlistJson())
                .put("active_window", 5).put("log_file", "app-private/xio_foh.db")
                .put("storage", "xio_foh.db");
    }

    private JSONArray eventsJson(String query) throws JSONException {
        int limit = 20;
        try { limit = Integer.parseInt(queryValue(query, "limit")); } catch (NumberFormatException ignored) { }
        return store.eventsJson(queryValue(query, "eventKey"), limit);
    }

    private JSONObject contextJson() throws JSONException {
        JSONObject cat = catalog();
        String key = currentEventKey();
        JSONArray events = cat.optJSONArray("events");
        JSONObject current = findEvent(key);
        return new JSONObject().put("ok", true).put("domain", "vj_foh")
                .put("catalogAvailable", events != null && events.length() > 0)
                .put("current", current == null ? JSONObject.NULL : current)
                .put("events", events == null ? new JSONArray() : events)
                .put("setlistBinding", setlistBindingJson())
                .put("event_policy", "fohEventKey_must_exist_in_vj_catalog")
                .put("rd_is_separate", true);
    }

    private JSONObject setlistBindingJson() throws JSONException {
        String owner = prefs.getString("setlistEventKey", "").trim();
        String current = currentEventKey();
        JSONArray songs = setlistSongs();
        String status = songs.length() == 0 ? "not_loaded" : owner.isEmpty() ? "unbound"
                : owner.equals(current) ? "bound" : "conflict";
        return new JSONObject().put("status", status).put("fohEventKey", owner.isEmpty() ? JSONObject.NULL : owner)
                .put("contextMatch", !owner.isEmpty() && owner.equals(current)).put("songs", songs.length());
    }

    private JSONObject setlistJson() throws JSONException {
        JSONArray songs = setlistSongs();
        int storedIndex = listener.currentSetlistIndex() >= 0 ? listener.currentSetlistIndex() : prefs.getInt("setlistIndex", 0);
        int index = songs.length() == 0 ? -1 : Math.max(0, Math.min(songs.length() - 1, storedIndex));
        JSONArray durations = durationsFromAssetOrNull();
        String current = index >= 0 ? songs.optString(index) : "";
        String next = index >= 0 && index + 1 < songs.length() ? songs.optString(index + 1) : "";
        JSONObject result = new JSONObject().put("songs", songs).put("index", index).put("total", songs.length())
                .put("fohEventKey", prefs.getString("setlistEventKey", "")).put("current", current.isEmpty() ? JSONObject.NULL : current)
                .put("current_name", songName(current)).put("next", next.isEmpty() ? JSONObject.NULL : next)
                .put("next_name", songName(next)).put("start_sec", timecodeStart(current))
                .put("dur", index >= 0 && index < durations.length() && !durations.isNull(index) ? durations.optDouble(index) : JSONObject.NULL)
                .put("context_match", !prefs.getString("setlistEventKey", "").isEmpty()
                        && prefs.getString("setlistEventKey", "").equals(currentEventKey()))
                .put("loaded_at", JSONObject.NULL).put("advanced_at", JSONObject.NULL);
        return result;
    }

    private JSONArray setlistSongs() {
        try {
            String stored = prefs.getString("setlist", "");
            if (!stored.trim().isEmpty()) return new JSONArray(stored);
        } catch (JSONException ignored) { }
        return defaultSetlist();
    }

    private void syncListenerSetlist() {
        JSONArray songs = setlistSongs();
        listener.setSetlist(songs, durationsFromAssetOrNull(), prefs.getInt("setlistIndex", 0));
    }

    private JSONArray defaultSetlist() {
        JSONArray songs = new JSONArray();
        try (InputStream input = context.getAssets().open("setlist_festival_sentir.txt")) {
            BufferedReader reader = new BufferedReader(new InputStreamReader(input, StandardCharsets.UTF_8));
            String line;
            while ((line = reader.readLine()) != null) if (!line.trim().isEmpty()) songs.put(line.trim());
        } catch (Exception ignored) { }
        return songs;
    }

    private JSONArray durationsFromAssetOrNull() {
        try (InputStream input = context.getAssets().open("setlist_durations_dref.json")) {
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            byte[] buffer = new byte[4096]; int read;
            while ((read = input.read(buffer)) >= 0) bytes.write(buffer, 0, read);
            JSONArray values = new JSONObject(bytes.toString(StandardCharsets.UTF_8.name())).optJSONArray("durations");
            return values == null ? new JSONArray() : values;
        } catch (Exception ignored) { return new JSONArray(); }
    }

    private static String songName(String value) {
        if (value == null || value.isEmpty()) return null;
        String[] parts = value.split("\\s+", 2);
        return parts.length == 2 && parts[0].contains(":") ? parts[1] : value;
    }

    private static Object timecodeStart(String value) {
        if (value == null || value.isEmpty()) return JSONObject.NULL;
        String[] parts = value.split("\\s+", 2);
        if (parts.length == 0 || !parts[0].contains(":")) return JSONObject.NULL;
        try {
            String[] tc = parts[0].split(":");
            int h = Integer.parseInt(tc[0]), m = Integer.parseInt(tc[1]), s = Integer.parseInt(tc[2]);
            int f = tc.length > 3 ? Integer.parseInt(tc[3]) : 0;
            return h * 3600.0 + m * 60.0 + s + f / 30.0;
        } catch (Exception ignored) { return JSONObject.NULL; }
    }

    private Object currentContext() {
        JSONObject event = findEvent(currentEventKey());
        return event == null ? JSONObject.NULL : event;
    }

    private JSONObject batteryJson() throws JSONException {
        Intent battery = context.registerReceiver(null, new IntentFilter(Intent.ACTION_BATTERY_CHANGED));
        if (battery == null) return new JSONObject().put("level", JSONObject.NULL).put("charging", false).put("temperature", JSONObject.NULL);
        int level = battery.getIntExtra(BatteryManager.EXTRA_LEVEL, -1);
        int scale = battery.getIntExtra(BatteryManager.EXTRA_SCALE, 100);
        int rawTemp = battery.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, Integer.MIN_VALUE);
        int status = battery.getIntExtra(BatteryManager.EXTRA_STATUS, -1);
        return new JSONObject().put("level", level < 0 ? JSONObject.NULL : Math.round(level * 100f / Math.max(scale, 1)))
                .put("charging", status == BatteryManager.BATTERY_STATUS_CHARGING || status == BatteryManager.BATTERY_STATUS_FULL)
                .put("temperature", rawTemp == Integer.MIN_VALUE ? JSONObject.NULL : rawTemp / 10.0);
    }

    private JSONObject catalog() {
        if (catalog != null) return catalog;
        try (InputStream input = context.getAssets().open("foh_vj_context.json")) {
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            byte[] buffer = new byte[4096]; int read;
            while ((read = input.read(buffer)) >= 0) bytes.write(buffer, 0, read);
            catalog = new JSONObject(bytes.toString(StandardCharsets.UTF_8.name()));
        } catch (Exception ignored) { catalog = new JSONObject(); }
        return catalog;
    }

    private JSONObject findEvent(String key) {
        if (key == null || key.isEmpty()) return null;
        JSONArray events = catalog().optJSONArray("events");
        if (events == null) return null;
        for (int i = 0; i < events.length(); i++) {
            JSONObject event = events.optJSONObject(i);
            if (event != null && key.equals(event.optString("eventKey"))) return event;
        }
        return null;
    }

    private String currentEventKey() { return prefs.getString("eventKey", "").trim(); }

    private Response nativePanel() throws JSONException {
        JSONObject s = statusJson();
        JSONObject channels = s.optJSONObject("channels");
        StringBuilder html = new StringBuilder("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>FOH Monitor</title><style>body{font:16px system-ui;background:#07090d;color:#e8eaed;padding:16px}article{border:1px solid #293247;border-radius:14px;padding:14px;margin:10px 0}b{font-size:20px}a{color:#60a5fa;margin-right:12px}</style><h1>FOH / ISKVW</h1>");
        html.append("<p>evento: ").append(escapeHtml(currentEventKey().isEmpty() ? "sin seleccionar" : currentEventKey())).append("</p>");
        String[][] channelLabels = {{"Art-Net", "artnet"}, {"sACN", "sacn"}, {"OSC / visual", "osc"}};
        for (String[] channel : channelLabels) {
            String name = channel[0];
            JSONObject c = channels == null ? null : channels.optJSONObject(channel[1]);
            String state = c == null || c.isNull("age") ? "N/D" : c.optBoolean("active") ? "ACTIVO" : "OFF";
            html.append("<article><b>").append(name).append("</b><br>").append(state);
            if (c != null) html.append(" · ").append(c.optInt("pps", 0)).append(" paquetes/s · ").append(escapeHtml(c.optString("detail", "")));
            html.append("</article>");
        }
        html.append("<p><a href='context'>EVENTO</a><a href='mapping'>MAPPING</a><a href='resumen'>RESUMEN</a><a href='registro'>REGISTRO</a></p>");
        return new Response(200, "text/html; charset=utf-8", html.toString());
    }

    private Response manifest() throws JSONException {
        return new Response(200, "application/manifest+json", new JSONObject().put("name", "FOH XIO").put("short_name", "FOH").put("display", "fullscreen").put("start_url", "panel").toString());
    }

    private Response asset(String name, String type) {
        try (InputStream input = context.getAssets().open(name)) {
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            byte[] buffer = new byte[8192]; int read;
            while ((read = input.read(buffer)) >= 0) bytes.write(buffer, 0, read);
            return new Response(200, type, bytes.toString(StandardCharsets.UTF_8.name()));
        } catch (IOException error) { return new Response(404, "text/plain; charset=utf-8", "asset no disponible: " + name); }
    }

    private static String queryValue(String query, String wanted) {
        for (String item : query.split("&")) {
            String[] pair = item.split("=", 2);
            if (pair.length == 2 && wanted.equals(URLDecoder.decode(pair[0], StandardCharsets.UTF_8))) return URLDecoder.decode(pair[1], StandardCharsets.UTF_8);
        }
        return "";
    }

    private static JSONObject errorJson(String message) {
        JSONObject result = new JSONObject();
        try { result.put("ok", false).put("error", message); } catch (JSONException ignored) { }
        return result;
    }
    private static Response json(JSONObject body) { return json(200, body); }
    private static Response json(JSONArray body) { return new Response(200, "application/json; charset=utf-8", body.toString()); }
    private static Response json(int status, JSONObject body) { return new Response(status, "application/json; charset=utf-8", body.toString()); }
    private static String escapeHtml(String value) { return value == null ? "" : value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\"", "&quot;"); }

    private static void respond(OutputStream output, int status, String type, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        String reason = status == 200 ? "OK" : status == 400 ? "Bad Request" : status == 404 ? "Not Found" : status == 409 ? "Conflict" : "Error";
        output.write(("HTTP/1.1 " + status + " " + reason + "\r\nContent-Type: " + type + "\r\nContent-Length: " + bytes.length + "\r\nConnection: close\r\nAccess-Control-Allow-Origin: *\r\n\r\n").getBytes(StandardCharsets.ISO_8859_1));
        output.write(bytes); output.flush();
    }

    private static final class Response {
        final int status; final String type; final String body;
        Response(int status, String type, String body) { this.status = status; this.type = type; this.body = body; }
    }
}
