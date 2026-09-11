package cl.xio.foh;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;

import androidx.activity.ComponentActivity;
import androidx.core.content.ContextCompat;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/** Native XIO-FOH surface. The screen is a port of the existing FOH product,
 * not a WebView and not a second invented monitoring model. */
public final class MainActivity extends ComponentActivity {
    private static final int BG = 0xff07090d, SURFACE = 0xff12151d, LINE = 0xff293247;
    private static final int TEXT = 0xffe8eaed, MUTED = 0xff8a92a6, BLUE = 0xff60a5fa;
    private static final int GREEN = 0xff4ade80, RED = 0xfff87171, AMBER = 0xfffbbf24;
    private SharedPreferences prefs;
    private FohLogStore store;
    private LinearLayout pageHost;
    private EditText hostInput, eventInput, setlistInput;
    private Spinner eventSpinner;
    private JSONArray catalogEvents = new JSONArray();
    private TextView contextBanner, statusView, timecodeView, timecodeState, currentSong, nextSong, progressLabel, feedView;
    private TextView lightsState, lightsMeta, visualState, visualMeta, audioState, audioMeta, batteryView;
    private ProgressBar songProgress;
    private long localStatusAt;
    private String activePage = "FOH";
    private BroadcastReceiver receiver;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Runnable refresh = new Runnable() { @Override public void run() { refreshStatus(); handler.postDelayed(this, 1000); } };

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        prefs = getSharedPreferences("xio_foh", MODE_PRIVATE);
        store = new FohLogStore(this);
        buildShell();
        receiver = new BroadcastReceiver() {
            @Override public void onReceive(Context c, Intent i) {
                String local = i.getStringExtra("localStatus");
                try { if (local != null) { localStatusAt = System.currentTimeMillis(); renderStatus(new JSONObject(local)); } else refreshStatus(); }
                catch (Exception ignored) { refreshStatus(); }
            }
        };
        ContextCompat.registerReceiver(this, receiver, new IntentFilter(FohCaptureService.ACTION_STATUS), ContextCompat.RECEIVER_NOT_EXPORTED);
        startCapture();
        showPage("FOH");
        handler.post(refresh);
    }

    private void buildShell() {
        ScrollView scroll = new ScrollView(this); scroll.setBackgroundColor(BG);
        LinearLayout shell = column(); shell.setPadding(dp(14), dp(12), dp(14), dp(24)); scroll.addView(shell);
        TextView eyebrow = text("FOH / ISKVW", 12, 0xffa78bfa); eyebrow.setTypeface(null, 1); shell.addView(eyebrow);
        TextView heading = text("Monitor de señales y contexto del show", 21, TEXT); heading.setTypeface(null, 1); shell.addView(heading);
        shell.addView(text("XIO-FOH escucha en el dispositivo y conserva la evidencia offline.", 12, MUTED));
        LinearLayout nav = row(); nav.setPadding(0, dp(10), 0, dp(4));
        for (String page : new String[]{"FOH", "EVENTO", "SHOWKIT", "REGISTRO", "TOOLS"}) {
            Button b = button(page, page.equals("FOH") ? BLUE : SURFACE, page.equals("FOH") ? BG : TEXT);
            nav.addView(b, weight(1, 44, 2)); b.setOnClickListener(v -> { activePage = ((Button) v).getText().toString(); showPage(activePage); });
        }
        shell.addView(nav); pageHost = column(); shell.addView(pageHost); setContentView(scroll);
    }

    private void showPage(String requested) {
        activePage = requested.toUpperCase(Locale.ROOT); pageHost.removeAllViews();
        if ("EVENTO".equals(activePage)) buildEventPage();
        else if ("SHOWKIT".equals(activePage)) buildSetlistPage();
        else if ("REGISTRO".equals(activePage)) buildRegistryPage();
        else if ("TOOLS".equals(activePage)) buildToolsPage();
        else buildMonitorPage();
    }

    private void buildMonitorPage() {
        LinearLayout context = card(); contextBanner = text("FOH / ISKVW · contexto sin seleccionar", 13, TEXT); context.addView(contextBanner);
        Button choose = button("SELECCIONAR EVENTO", SURFACE, BLUE); context.addView(choose); choose.setOnClickListener(v -> showPage("EVENTO")); pageHost.addView(context);

        LinearLayout tiles = row();
        LinearLayout light = signalTile("LUCES"); lightsState = tileState(light); lightsMeta = tileMeta(light); tiles.addView(light, weight(1, -2, 3));
        LinearLayout visual = signalTile("VISUAL"); visualState = tileState(visual); visualMeta = tileMeta(visual); tiles.addView(visual, weight(1, -2, 3));
        LinearLayout audio = signalTile("AUDIO"); audioState = tileState(audio); audioMeta = tileMeta(audio); tiles.addView(audio, weight(1, -2, 3));
        pageHost.addView(tiles);

        LinearLayout now = card(); timecodeView = text("--:--:--:--", 34, TEXT); timecodeView.setGravity(Gravity.CENTER); now.addView(timecodeView);
        timecodeState = text("TIMECODE · sin señal", 11, MUTED); timecodeState.setGravity(Gravity.CENTER); now.addView(timecodeState);
        currentSong = text("--", 20, TEXT); currentSong.setGravity(Gravity.CENTER); currentSong.setTypeface(null, 1); now.addView(currentSong);
        songProgress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal); songProgress.setMax(100); songProgress.setProgress(0); songProgress.setVisibility(View.GONE);
        now.addView(songProgress, new LinearLayout.LayoutParams(-1, dp(16)));
        progressLabel = text("", 10, MUTED); progressLabel.setGravity(Gravity.CENTER); progressLabel.setVisibility(View.GONE); now.addView(progressLabel);
        nextSong = text("", 12, MUTED); nextSong.setGravity(Gravity.CENTER); now.addView(nextSong); pageHost.addView(now);

        LinearLayout links = row();
        addLink(links, "MAPPING", "/api/plugins/foh_monitor/mapping", BLUE);
        addLink(links, "RESUMEN", "/api/plugins/foh_monitor/resumen", BLUE);
        addLink(links, "REGISTRO", "/api/plugins/foh_monitor/registro", BLUE);
        addLink(links, "RAIDER", "/raider?domain=foh", AMBER); pageHost.addView(links);

        LinearLayout controls = card(); controls.addView(text("CAPTURA FOH ACTIVA", 11, AMBER));
        LinearLayout actions = row(); Button stop = button("DETENER", SURFACE, TEXT); Button start = button("INICIAR ESCUCHA", 0xff1d4ed8, TEXT);
        actions.addView(start, weight(1, 46, 2)); actions.addView(stop, weight(1, 46, 2)); controls.addView(actions); pageHost.addView(controls);
        start.setOnClickListener(v -> startCapture()); stop.setOnClickListener(v -> stopCapture());

        statusView = text("Estado: consultando…", 12, GREEN); pageHost.addView(statusView);
        batteryView = text("", 12, MUTED); pageHost.addView(batteryView);
        LinearLayout feed = card(); feed.addView(text("FEED DE EVENTOS", 11, AMBER)); feedView = text("sin eventos", 12, MUTED); feed.addView(feedView); pageHost.addView(feed);
        refreshStatus();
    }

    private LinearLayout signalTile(String name) {
        LinearLayout tile = card(); tile.setPadding(dp(8), dp(8), dp(8), dp(8));
        TextView title = text(name, 10, MUTED); title.setTypeface(null, 1); tile.addView(title);
        tile.addView(text("N/D", 16, MUTED)); tile.addView(text("sin señal aun", 10, MUTED)); return tile;
    }
    private TextView tileState(LinearLayout tile) { return (TextView) tile.getChildAt(1); }
    private TextView tileMeta(LinearLayout tile) { return (TextView) tile.getChildAt(2); }

    private void addLink(LinearLayout row, String label, String path, int color) {
        Button link = button(label, SURFACE, color); row.addView(link, weight(1, 42, 2)); link.setOnClickListener(v -> openUrl(hostUrl() + path));
    }

    private void buildEventPage() {
        LinearLayout box = card(); box.addView(text("EVENTO EXACTO DEL CATALOGO VJ", 11, AMBER));
        box.addView(text("Se selecciona una identidad existente; no se crea un evento por nombre.", 12, MUTED));
        eventSpinner = new Spinner(this); box.addView(eventSpinner); eventInput = input("fohEventKey", prefs.getString("eventKey", "")); box.addView(eventInput);
        LinearLayout actions = row(); Button use = button("USAR EVENTO", 0xff1d4ed8, TEXT); Button clear = button("QUITAR", SURFACE, TEXT);
        actions.addView(use, weight(1, 46, 2)); actions.addView(clear, weight(1, 46, 2)); box.addView(actions); pageHost.addView(box); loadCatalog();
        use.setOnClickListener(v -> applyEvent()); clear.setOnClickListener(v -> postJson("/api/plugins/foh_monitor/context", "{\"clear\":true}", "Contexto eliminado"));
    }

    private void buildSetlistPage() {
        LinearLayout box = card(); box.addView(text("SHOW KIT / SETLIST", 11, AMBER));
        box.addView(text("Tema actual y siguiente provienen del setlist; el timecode puede avanzar automáticamente.", 12, MUTED));
        setlistInput = new EditText(this); setlistInput.setTextColor(TEXT); setlistInput.setHintTextColor(MUTED); setlistInput.setHint("Una línea por tema"); setlistInput.setMinLines(7); setlistInput.setGravity(Gravity.TOP); setlistInput.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE); box.addView(setlistInput);
        LinearLayout actions = row(); Button save = button("GUARDAR SETLIST", 0xff1d4ed8, TEXT); Button prev = button("PREV", SURFACE, TEXT); Button next = button("NEXT", SURFACE, TEXT);
        actions.addView(save, weight(1, 46, 2)); actions.addView(prev, weight(1, 46, 1)); actions.addView(next, weight(1, 46, 1)); box.addView(actions); pageHost.addView(box);
        save.setOnClickListener(v -> saveSetlist()); prev.setOnClickListener(v -> postSimple("/api/plugins/foh_monitor/prev")); next.setOnClickListener(v -> postSimple("/api/plugins/foh_monitor/next")); loadSetlist();
    }

    private void buildRegistryPage() {
        LinearLayout box = card(); box.addView(text("REGISTRO / RESUMEN", 11, AMBER));
        feedView = text("cargando evidencia local…", 12, MUTED); box.addView(feedView);
        Button refreshButton = button("ACTUALIZAR", SURFACE, TEXT); box.addView(refreshButton); refreshButton.setOnClickListener(v -> refreshStatus());
        Button summary = button("ABRIR RESUMEN DEL EVENTO", 0xff7c3aed, TEXT); box.addView(summary); summary.setOnClickListener(v -> openUrl(hostUrl() + "/api/plugins/foh_monitor/resumen?eventKey=" + Uri.encode(prefs.getString("eventKey", "")))); pageHost.addView(box); refreshStatus();
    }

    private void buildToolsPage() {
        LinearLayout box = card(); box.addView(text("HERRAMIENTAS FOH / ISKVW", 11, AMBER));
        box.addView(text("Estas acciones abren las herramientas existentes del host; no se reemplazan por pantallas falsas.", 12, MUTED));
        addTool(box, "HUB ISKVW", "/api/plugins/foh_monitor/view"); addTool(box, "PANEL FOH", "/api/plugins/foh_monitor/panel"); addTool(box, "MAPPING LED", "/api/plugins/foh_monitor/mapping"); addTool(box, "RAIDER", "/raider?domain=foh"); addTool(box, "REGISTRO", "/api/plugins/foh_monitor/registro");
        box.addView(text("Escucha: Art-Net :6454 · sACN :5568 · OSC/timecode :7000 · host HTTP :5000", 11, MUTED)); pageHost.addView(box);
    }
    private void addTool(LinearLayout box, String label, String path) { Button b = button(label, SURFACE, TEXT); box.addView(b); b.setOnClickListener(v -> openUrl(hostUrl() + path)); }

    private void refreshStatus() {
        new Thread(() -> {
            JSONObject status = getJson("/api/plugins/foh_monitor/status");
            JSONArray events = getJsonArray("/api/plugins/foh_monitor/events?limit=10");
            runOnUiThread(() -> { if (status != null && System.currentTimeMillis() - localStatusAt > 2500) renderStatus(status); if (events != null) renderFeed(events); else if (feedView != null && "REGISTRO".equals(activePage)) renderLocalFeed(); });
        }, "xio-foh-ui-refresh").start();
    }

    private void renderStatus(JSONObject s) {
        if (statusView != null) {
            boolean listening = s.optBoolean("listener");
            boolean server = s.optBoolean("server");
            statusView.setText("Estado: " + (listening ? "ESCUCHANDO" : "escucha detenida") + " · APK nativa" + (server ? " · host :5000" : " · visualizador externo"));
        }
        JSONObject c = s.optJSONObject("channels");
        renderTile(lightsState, lightsMeta, combined(c, "artnet", "sacn"), "Art-Net/sACN");
        renderTile(visualState, visualMeta, c == null ? null : c.optJSONObject("osc"), "OSC visual");
        JSONObject audio = s.optJSONObject("audio");
        if (audio == null || !audio.optBoolean("available")) { setTile(audioState, audioMeta, "N/D", audio == null ? "sin datos" : audio.optString("reason", "no disponible"), MUTED); }
        else setTile(audioState, audioMeta, audio.optBoolean("active") ? "ON" : "OFF", audio.optString("level_db", "") + " dBFS", audio.optBoolean("active") ? GREEN : RED);
        JSONObject tc = s.optJSONObject("timecode");
        JSONObject sl = s.optJSONObject("setlist");
        if (tc != null) {
            String display = tc.isNull("display") ? "--:--:--:--" : tc.optString("display", "--:--:--:--");
            String state = tc.optString("state", "sin_senal");
            timecodeView.setText(display);
            timecodeState.setText("TIMECODE " + state.replace('_', ' ').toUpperCase(Locale.ROOT) + (tc.has("age") && !tc.isNull("age") ? " · hace " + tc.optString("age") + "s" : ""));
            timecodeState.setTextColor("corriendo".equals(state) ? GREEN : "sin_senal".equals(state) ? MUTED : RED);
        }
        if (sl != null) {
            currentSong.setText(sl.isNull("current_name") ? "(sin setlist)" : sl.optString("current_name", "(sin setlist)"));
            String following = sl.isNull("next_name") ? "" : sl.optString("next_name", "");
            nextSong.setText(following.isEmpty() ? "" : "sigue: " + following);
            updateSongProgress(tc, sl);
        } else {
            updateSongProgress(tc, null);
        }
        JSONObject cx = s.optJSONObject("context"); if (contextBanner != null) contextBanner.setText(cx == null || cx.length() == 0 ? "FOH / ISKVW · contexto sin seleccionar" : "FOH / ISKVW · " + cx.optString("name", cx.optString("eventKey", "evento")) + " · " + cx.optString("dateIso", "fecha por confirmar") + " · " + cx.optString("venueName", "venue por confirmar"));
        JSONObject b = s.optJSONObject("battery"); if (batteryView != null && b != null) batteryView.setText("BAT " + (b.isNull("level") ? "N/D" : b.optString("level")) + "%" + (b.optBoolean("charging") ? " cargando" : "") + " · " + (b.isNull("temperature") ? "N/D" : b.optString("temperature")) + " C");
    }

    private void updateSongProgress(JSONObject tc, JSONObject sl) {
        if (songProgress == null || progressLabel == null || tc == null || sl == null || tc.isNull("value") || sl.isNull("start_sec") || sl.isNull("dur")) {
            hideSongProgress(); return;
        }
        String state = tc.optString("state", "sin_senal");
        double tcSeconds = timecodeSeconds(tc.opt("value"));
        double start = sl.optDouble("start_sec", Double.NaN);
        double duration = sl.optDouble("dur", Double.NaN);
        if (!(tcSeconds >= 0) || !(start >= 0) || !(duration > 0) || !("corriendo".equals(state) || "congelado".equals(state))) {
            hideSongProgress(); return;
        }
        double fraction = Math.max(0, Math.min(1, (tcSeconds - start) / duration));
        songProgress.setProgress((int) Math.round(fraction * 100));
        progressLabel.setText(Math.round(fraction * 100) + "% · " + formatSeconds(Math.max(0, tcSeconds - start)) + " / " + formatSeconds(duration));
        songProgress.setVisibility(View.VISIBLE); progressLabel.setVisibility(View.VISIBLE);
    }

    private void hideSongProgress() { if (songProgress != null) songProgress.setVisibility(View.GONE); if (progressLabel != null) progressLabel.setVisibility(View.GONE); }
    private double timecodeSeconds(Object value) {
        if (value == null || value == JSONObject.NULL) return Double.NaN;
        String raw = String.valueOf(value);
        if (raw.contains(":")) {
            String[] p = raw.split(":");
            if (p.length != 4) return Double.NaN;
            try { return Integer.parseInt(p[0]) * 3600d + Integer.parseInt(p[1]) * 60d + Integer.parseInt(p[2]) + Integer.parseInt(p[3]) / 30d; }
            catch (NumberFormatException ignored) { return Double.NaN; }
        }
        try { return Double.parseDouble(raw); } catch (NumberFormatException ignored) { return Double.NaN; }
    }
    private String formatSeconds(double value) { int total = (int) Math.round(value); return String.format(Locale.ROOT, "%02d:%02d", total / 60, total % 60); }

    private JSONObject combined(JSONObject channels, String first, String second) { if (channels == null) return null; JSONObject a = channels.optJSONObject(first), b = channels.optJSONObject(second); if (a == null && b == null) return null; JSONObject r = new JSONObject(); try { boolean active = (a != null && a.optBoolean("active")) || (b != null && b.optBoolean("active")); r.put("active", active).put("pps", (a == null ? 0 : a.optLong("pps")) + (b == null ? 0 : b.optLong("pps"))).put("age", active ? 0 : JSONObject.NULL); } catch (Exception ignored) { } return r; }
    private void renderTile(TextView state, TextView meta, JSONObject value, String label) { if (value == null || value.isNull("age")) setTile(state, meta, "N/D", "sin señal aun", MUTED); else setTile(state, meta, value.optBoolean("active") ? "ON" : "OFF", (value.optLong("pps") + " pps") + " · " + label, value.optBoolean("active") ? GREEN : RED); }
    private void setTile(TextView state, TextView meta, String title, String detail, int color) { if (state != null) { state.setText(title); state.setTextColor(color); } if (meta != null) meta.setText(detail); }
    private void renderFeed(JSONArray events) {
        if (feedView == null) return;
        StringBuilder out = new StringBuilder();
        for (int i = events.length() - 1; i >= 0; i--) {
            JSONObject e = events.optJSONObject(i); if (e == null) continue;
            if (out.length() > 0) out.append('\n');
            out.append(e.optString("ts", "")).append(" · ").append(e.optString("tipo", e.optString("protocol", "evento"))).append(" · ").append(e.optString("detalle", e.optString("detail", "")));
        }
        List<String> local = store == null ? new ArrayList<>() : store.recent(6);
        if (!local.isEmpty()) {
            if (out.length() > 0) out.append("\n\n");
            out.append("APK local (SQLite offline)\n").append(String.join("\n", local));
        }
        feedView.setText(out.length() == 0 ? "sin eventos" : out.toString());
    }
    private void renderLocalFeed() { if (feedView != null) feedView.setText("Registros guardados: " + store.count() + "\n\n" + String.join("\n", store.recent(10))); }

    private void loadCatalog() { new Thread(() -> { try (InputStream input = getAssets().open("foh_vj_context.json")) { String body = read(input); catalogEvents = new JSONObject(body).optJSONArray("events"); if (catalogEvents == null) catalogEvents = new JSONArray(); List<String> labels = new ArrayList<>(); for (int i = 0; i < catalogEvents.length(); i++) { JSONObject e = catalogEvents.optJSONObject(i); labels.add(e == null ? "evento" : e.optString("name", "evento") + " · " + e.optString("dateIso", "sin fecha")); } runOnUiThread(() -> { eventSpinner.setAdapter(new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, labels)); }); } catch (Exception ignored) { } }, "xio-foh-catalog").start(); }
    private void applyEvent() { String key = eventInput.getText().toString().trim(); if (key.isEmpty()) return; postJson("/api/plugins/foh_monitor/context", "{\"eventKey\":" + JSONObject.quote(key) + "}", "Evento FOH activo"); }
    private void loadSetlist() { new Thread(() -> { JSONObject r = getJson("/api/plugins/foh_monitor/setlist"); if (r == null) return; runOnUiThread(() -> { JSONArray songs = r.optJSONArray("songs"); if (songs != null) { StringBuilder b = new StringBuilder(); for (int i = 0; i < songs.length(); i++) { if (i > 0) b.append('\n'); b.append(songs.optString(i)); } setlistInput.setText(b.toString()); } }); }, "xio-foh-setlist").start(); }
    private void saveSetlist() { String text = setlistInput.getText().toString().trim(); if (!text.isEmpty()) postJson("/api/plugins/foh_monitor/setlist", "{\"text\":" + JSONObject.quote(text) + "}", "Setlist guardada"); }
    private void postSimple(String path) { new Thread(() -> { post(path, "{}"); refreshStatus(); }, "xio-foh-action").start(); }
    private void postJson(String path, String body, String success) { new Thread(() -> { JSONObject r = post(path, body); runOnUiThread(() -> android.widget.Toast.makeText(this, r == null ? "Host FOH no disponible" : success, android.widget.Toast.LENGTH_SHORT).show()); refreshStatus(); }, "xio-foh-post").start(); }
    private JSONObject getJson(String path) { try { HttpURLConnection c = (HttpURLConnection) new URL(hostUrl() + path).openConnection(); c.setConnectTimeout(1200); c.setReadTimeout(1800); return new JSONObject(read(c)); } catch (Exception ignored) { return null; } }
    private JSONArray getJsonArray(String path) { try { HttpURLConnection c = (HttpURLConnection) new URL(hostUrl() + path).openConnection(); c.setConnectTimeout(1200); c.setReadTimeout(1800); return new JSONArray(read(c)); } catch (Exception ignored) { return null; } }
    private JSONObject post(String path, String body) { try { HttpURLConnection c = (HttpURLConnection) new URL(hostUrl() + path).openConnection(); c.setRequestMethod("POST"); c.setConnectTimeout(1200); c.setReadTimeout(1800); c.setDoOutput(true); c.setRequestProperty("Content-Type", "application/json"); try (OutputStream out = c.getOutputStream()) { out.write(body.getBytes(StandardCharsets.UTF_8)); } return new JSONObject(read(c)); } catch (Exception ignored) { return null; } }
    private String read(HttpURLConnection c) throws Exception { try (InputStream input = c.getResponseCode() < 400 ? c.getInputStream() : c.getErrorStream()) { return read(input); } finally { c.disconnect(); } }
    private static String read(InputStream input) throws Exception { BufferedReader r = new BufferedReader(new InputStreamReader(input, StandardCharsets.UTF_8)); StringBuilder b = new StringBuilder(); String line; while ((line = r.readLine()) != null) b.append(line); return b.toString(); }

    private void startCapture() { String key = prefs.getString("eventKey", ""); Intent i = new Intent(this, FohCaptureService.class).setAction(FohCaptureService.ACTION_START).putExtra(FohCaptureService.EXTRA_EVENT_KEY, key); ContextCompat.startForegroundService(this, i); }
    private void stopCapture() { startService(new Intent(this, FohCaptureService.class).setAction(FohCaptureService.ACTION_STOP)); }
    private String hostUrl() { String value = prefs.getString("host", "http://127.0.0.1:5000").trim(); return (value.isEmpty() ? "http://127.0.0.1:5000" : value).replaceAll("/+$", ""); }
    private void openUrl(String value) { try { startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(value))); } catch (Exception ignored) { } }
    private EditText input(String hint, String value) { EditText e = new EditText(this); e.setHint(hint); e.setText(value); e.setTextColor(TEXT); e.setHintTextColor(MUTED); e.setSingleLine(true); return e; }
    private TextView text(String value, int size, int color) { TextView t = new TextView(this); t.setText(value); t.setTextSize(size); t.setTextColor(color); t.setPadding(0, dp(3), 0, dp(3)); return t; }
    private Button button(String value, int bg, int fg) { Button b = new Button(this); b.setText(value); b.setTextSize(10); b.setTextColor(fg); b.setAllCaps(false); b.setGravity(Gravity.CENTER); b.setMinHeight(0); b.setMinWidth(0); b.setPadding(0, 0, 0, 0); b.setIncludeFontPadding(false); GradientDrawable d = new GradientDrawable(); d.setColor(bg); d.setCornerRadius(dp(10)); d.setStroke(dp(1), LINE); b.setBackground(d); return b; }
    private LinearLayout card() { LinearLayout l = column(); l.setPadding(dp(12), dp(10), dp(12), dp(10)); GradientDrawable d = new GradientDrawable(); d.setColor(SURFACE); d.setCornerRadius(dp(12)); d.setStroke(dp(1), LINE); l.setBackground(d); LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(-1, -2); p.setMargins(0, dp(7), 0, 0); l.setLayoutParams(p); return l; }
    private LinearLayout column() { LinearLayout l = new LinearLayout(this); l.setOrientation(LinearLayout.VERTICAL); return l; }
    private LinearLayout row() { LinearLayout l = new LinearLayout(this); l.setOrientation(LinearLayout.HORIZONTAL); l.setGravity(Gravity.CENTER_VERTICAL); return l; }
    private LinearLayout.LayoutParams weight(float w, int h, int margin) { LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(0, h, w); p.setMargins(dp(margin), 0, 0, 0); return p; }
    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }
    @Override protected void onDestroy() { handler.removeCallbacks(refresh); if (receiver != null) unregisterReceiver(receiver); if (store != null) store.close(); super.onDestroy(); }
}
