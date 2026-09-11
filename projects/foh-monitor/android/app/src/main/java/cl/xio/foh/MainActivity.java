package cl.xio.foh;

import android.Manifest;
import android.app.Activity;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.SharedPreferences;
import android.net.Uri;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import androidx.activity.ComponentActivity;
import androidx.core.content.ContextCompat;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Locale;
import java.util.Map;

/** Native XIO-FOH menu: active local listener plus a bridge to the ISKVW hub. */
public final class MainActivity extends ComponentActivity {
    private static final int BG = 0xff0b1012, SURFACE = 0xff172125, TEAL = 0xff55d6be, VIOLET = 0xffa78bfa, AMBER = 0xfff2c96d, TEXT = 0xffeff7f3, MUTED = 0xff95a9a1;
    private SharedPreferences prefs;
    private EditText hostInput, eventInput;
    private TextView statusView, channelsView, logView;
    private BroadcastReceiver receiver;
    private FohLogStore store;

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        prefs = getSharedPreferences("xio_foh", MODE_PRIVATE);
        store = new FohLogStore(this);
        buildUi();
        receiver = new BroadcastReceiver() { @Override public void onReceive(Context context, Intent intent) { renderStatus(intent); } };
        ContextCompat.registerReceiver(this, receiver, new IntentFilter(FohCaptureService.ACTION_STATUS), ContextCompat.RECEIVER_NOT_EXPORTED);
        refreshLocalStatus();
    }

    private void buildUi() {
        ScrollView scroll = new ScrollView(this); scroll.setBackgroundColor(BG);
        LinearLayout root = column(14); root.setPadding(18, 18, 18, 28); scroll.addView(root); setContentView(scroll);
        TextView eyebrow = text("XIO / FOH", 12, VIOLET); eyebrow.setTypeface(null, 1); root.addView(eyebrow);
        TextView heading = text("Monitor activo de show", 27, TEXT); heading.setTypeface(null, 1); root.addView(heading);
        root.addView(text("El dispositivo escucha señales y guarda el registro offline. El hub ISKVW solo visualiza y opera las herramientas VJ.", 13, MUTED));

        LinearLayout context = card(); context.addView(label("EVENTO FOH / VJ"));
        eventInput = input("eventKey exacto del catálogo VJ", prefs.getString("eventKey", "")); context.addView(eventInput);
        Button apply = button("USAR EVENTO FOH", TEAL, BG); context.addView(apply); apply.setOnClickListener(v -> applyEvent()); root.addView(context);

        LinearLayout host = card(); host.addView(label("HOST XIO / HUB ISKVW"));
        hostInput = input("http://127.0.0.1:5000", prefs.getString("host", "http://127.0.0.1:5000")); host.addView(hostInput);
        LinearLayout hostActions = row(); Button saveHost = button("GUARDAR HOST", AMBER, BG); Button openHub = button("ABRIR HUB ISKVW", VIOLET, BG); hostActions.addView(saveHost, weight()); hostActions.addView(openHub, weight()); host.addView(hostActions); root.addView(host);
        saveHost.setOnClickListener(v -> { saveHost(); Toast.makeText(this, "Host guardado", Toast.LENGTH_SHORT).show(); });
        openHub.setOnClickListener(v -> openUrl(hostUrl() + "/api/plugins/foh_monitor/view"));

        LinearLayout actions = card(); actions.addView(label("MENÚ FOH"));
        LinearLayout signalRow = row(); Button start = button("▶  INICIAR ESCUCHA", TEAL, BG); Button stop = button("■  DETENER", SURFACE, TEXT); signalRow.addView(start, weight()); signalRow.addView(stop, weight()); actions.addView(signalRow);
        start.setOnClickListener(v -> startCapture()); stop.setOnClickListener(v -> stopCapture());
        LinearLayout tools = row(); Button mapping = button("MAPPING LED", SURFACE, TEXT); Button showkit = button("SHOWKIT", SURFACE, TEXT); tools.addView(mapping, weight()); tools.addView(showkit, weight()); actions.addView(tools);
        mapping.setOnClickListener(v -> openUrl(hostUrl() + "/api/plugins/foh_monitor/mapping")); showkit.setOnClickListener(v -> openUrl(hostUrl() + "/api/plugins/foh_monitor/setlist")); root.addView(actions);

        statusView = text("Estado: detenido", 14, TEAL); statusView.setPadding(0, 8, 0, 4); root.addView(statusView);
        channelsView = text("Art-Net :6454 · sACN :5568 · OSC/timecode :7000\nSin paquetes recibidos.", 13, MUTED); root.addView(channelsView);
        LinearLayout logCard = card(); logCard.addView(label("REGISTRO OFFLINE")); logView = text("", 12, MUTED); logCard.addView(logView); Button refresh = button("ACTUALIZAR REGISTRO", SURFACE, TEXT); logCard.addView(refresh); refresh.setOnClickListener(v -> refreshLocalStatus()); root.addView(logCard);
    }

    private void startCapture() {
        saveHost(); prefs.edit().putString("eventKey", eventInput.getText().toString().trim()).apply();
        Intent intent = new Intent(this, FohCaptureService.class).setAction(FohCaptureService.ACTION_START).putExtra(FohCaptureService.EXTRA_EVENT_KEY, eventInput.getText().toString().trim());
        ContextCompat.startForegroundService(this, intent); statusView.setText("Estado: iniciando escucha…");
    }

    private void stopCapture() { startService(new Intent(this, FohCaptureService.class).setAction(FohCaptureService.ACTION_STOP)); statusView.setText("Estado: detenido"); }

    private void applyEvent() {
        String key = eventInput.getText().toString().trim(); if (key.isEmpty()) { Toast.makeText(this, "Escribe un eventKey FOH del catálogo", Toast.LENGTH_LONG).show(); return; }
        prefs.edit().putString("eventKey", key).apply();
        new Thread(() -> postEventContext(key)).start();
    }

    private void postEventContext(String key) {
        try {
            HttpURLConnection connection = (HttpURLConnection) new URL(hostUrl() + "/api/plugins/foh_monitor/context").openConnection();
            connection.setRequestMethod("POST"); connection.setConnectTimeout(1500); connection.setReadTimeout(2500); connection.setDoOutput(true); connection.setRequestProperty("Content-Type", "application/json");
            try (OutputStream out = connection.getOutputStream()) { out.write(("{\"eventKey\":" + JSONObject.quote(key) + "}").getBytes(StandardCharsets.UTF_8)); }
            int code = connection.getResponseCode(); runOnUiThread(() -> Toast.makeText(this, code >= 200 && code < 300 ? "Evento FOH activo" : "El host rechazó ese eventKey", Toast.LENGTH_LONG).show()); connection.disconnect();
        } catch (Exception error) { runOnUiThread(() -> Toast.makeText(this, "No se pudo actualizar el contexto del host; queda guardado localmente", Toast.LENGTH_LONG).show()); }
    }

    private void refreshLocalStatus() {
        logView.setText(String.format(Locale.US, "Registros guardados: %d\n\n%s", store.count(), String.join("\n", store.recent(8))));
        new Thread(() -> {
            try { HttpURLConnection c = (HttpURLConnection) new URL(hostUrl() + "/api/plugins/foh_monitor/status").openConnection(); c.setConnectTimeout(1200); c.setReadTimeout(1800); int code = c.getResponseCode(); runOnUiThread(() -> statusView.setText("Host ISKVW: HTTP " + code + " · escucha local independiente")); c.disconnect(); }
            catch (Exception ignored) { runOnUiThread(() -> statusView.setText("Host ISKVW: sin conexión · escucha local disponible")); }
        }).start();
    }

    private void renderStatus(Intent intent) {
        boolean running = intent.getBooleanExtra("running", false); int count = intent.getIntExtra("logCount", store.count());
        statusView.setText(running ? "Estado: ESCUCHANDO · registro offline activo" : "Estado: detenido");
        logView.setText("Registros guardados: " + count); channelsView.setText("Art-Net :6454 · sACN :5568 · OSC/timecode :7000\nEl servicio FOH está " + (running ? "activo." : "detenido."));
    }

    private String hostUrl() { String value = hostInput == null ? prefs.getString("host", "http://127.0.0.1:5000") : hostInput.getText().toString().trim(); if (value.isEmpty()) value = "http://127.0.0.1:5000"; return value.replaceAll("/+$", ""); }
    private void saveHost() { prefs.edit().putString("host", hostUrl()).apply(); }
    private void openUrl(String url) { try { startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url))); } catch (Exception error) { Toast.makeText(this, "No hay navegador disponible", Toast.LENGTH_SHORT).show(); } }
    private EditText input(String hint, String value) { EditText input = new EditText(this); input.setHint(hint); input.setText(value); input.setTextColor(TEXT); input.setHintTextColor(MUTED); input.setSingleLine(true); input.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI); return input; }
    private TextView label(String value) { TextView view = text(value, 11, AMBER); view.setTypeface(null, 1); view.setPadding(0, 0, 0, 5); return view; }
    private TextView text(String value, int size, int color) { TextView view = new TextView(this); view.setText(value); view.setTextSize(size); view.setTextColor(color); view.setPadding(0, 3, 0, 3); return view; }
    private Button button(String value, int bg, int fg) { Button button = new Button(this); button.setText(value); button.setTextSize(11); button.setTextColor(fg); button.setAllCaps(false); button.setBackgroundColor(bg); return button; }
    private LinearLayout column(int gap) { LinearLayout layout = new LinearLayout(this); layout.setOrientation(LinearLayout.VERTICAL); return layout; }
    private LinearLayout row() { LinearLayout layout = new LinearLayout(this); layout.setOrientation(LinearLayout.HORIZONTAL); layout.setGravity(Gravity.CENTER_VERTICAL); return layout; }
    private LinearLayout card() { LinearLayout layout = column(0); layout.setPadding(12, 12, 12, 12); layout.setBackgroundColor(SURFACE); LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(-1, -2); p.setMargins(0, 12, 0, 0); layout.setLayoutParams(p); return layout; }
    private LinearLayout.LayoutParams weight() { LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(0, 48, 1f); p.setMargins(4, 0, 0, 0); return p; }

    @Override protected void onDestroy() { if (receiver != null) unregisterReceiver(receiver); if (store != null) store.close(); super.onDestroy(); }
}
