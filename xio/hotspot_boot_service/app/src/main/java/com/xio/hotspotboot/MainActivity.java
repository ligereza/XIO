package com.xio.hotspotboot;

import android.Manifest;
import android.app.Activity;
import android.content.ComponentName;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * XIO infrastructure control plane. RD and FOH remain independent products;
 * this APK observes their hosts and manages only the shared phone runtime.
 */
public final class MainActivity extends Activity {
    private static final String TERMUX_PACKAGE = "com.termux";
    private static final String TERMUX_RUN_COMMAND = "com.termux.RUN_COMMAND";
    private static final String RUN_COMMAND_PATH = "com.termux.RUN_COMMAND_PATH";
    private static final String RUN_COMMAND_ARGUMENTS = "com.termux.RUN_COMMAND_ARGUMENTS";
    private static final String RUN_COMMAND_WORKDIR = "com.termux.RUN_COMMAND_WORKDIR";
    private static final String RUN_COMMAND_BACKGROUND = "com.termux.RUN_COMMAND_BACKGROUND";
    private static final String RUN_COMMAND_SESSION_ACTION = "com.termux.RUN_COMMAND_SESSION_ACTION";
    private static final String TERMUX_SHELL = "/data/data/com.termux/files/usr/bin/sh";
    private static final String TERMUX_HOME = "/data/data/com.termux/files/home";
    private static final String TERMUX_SERVER_SCRIPT = "/sdcard/xio_termux/run_server.sh";
    private static final String RECOVERY_MARKER = "/sdcard/xio_termux/hotspot_runtime_recovery.enabled";
    private static final int REQUEST_PERMISSIONS = 41;

    private static final int BG = Color.rgb(7, 9, 13);
    private static final int SURFACE = Color.rgb(18, 21, 29);
    private static final int TEXT = Color.rgb(232, 234, 237);
    private static final int MUTED = Color.rgb(138, 146, 166);
    private static final int BLUE = Color.rgb(96, 165, 250);

    private final android.os.Handler handler = new android.os.Handler(android.os.Looper.getMainLooper());
    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private TextView actionMessage;
    private TextView status;
    private TextView history;
    private TextView monitorState;
    private final Runnable refresh = new Runnable() {
        @Override public void run() {
            refreshStatus();
            handler.postDelayed(this, 5000L);
        }
    };

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        setContentView(buildView());
        requestRuntimePermissions();
    }

    @Override protected void onResume() {
        super.onResume();
        refreshStatus();
        handler.postDelayed(refresh, 1000L);
    }

    @Override protected void onPause() {
        handler.removeCallbacks(refresh);
        super.onPause();
    }

    @Override protected void onDestroy() {
        handler.removeCallbacksAndMessages(null);
        executor.shutdownNow();
        super.onDestroy();
    }

    private View buildView() {
        ScrollView scroll = new ScrollView(this);
        scroll.setBackgroundColor(BG);
        LinearLayout page = column();
        page.setPadding(dp(16), dp(18), dp(16), dp(24));
        page.addView(text("XIO", 28, TEXT));
        page.addView(text("Infraestructura del Xiaomi", 15, MUTED));
        page.addView(text("RD y FOH conservan sus propios roles. XIO observa y mantiene "
                + "la red, el host, los plugins y la recuperación.", 13, MUTED));

        Button host = button("INICIAR / REINICIAR HOST XIO", BLUE);
        page.addView(host, fullHeight(54, 14));
        host.setOnClickListener(v -> startTermuxServer());

        LinearLayout monitorRow = new LinearLayout(this);
        monitorRow.setOrientation(LinearLayout.HORIZONTAL);
        Button monitor = button("MONITOR ON/OFF", SURFACE);
        Button sample = button("DIAGNÓSTICO AHORA", SURFACE);
        monitorRow.addView(monitor, weightedHeight(48, 1f, 0));
        monitorRow.addView(sample, weightedHeight(48, 1f, 6));
        page.addView(monitorRow, fullHeight(48, 10));
        monitor.setOnClickListener(v -> toggleMonitor());
        sample.setOnClickListener(v -> forceSample());

        Button hub = button("ABRIR HUB XIO / PLUGINS", SURFACE);
        page.addView(hub, fullHeight(48, 10));
        hub.setOnClickListener(v -> openHub());

        LinearLayout recoveryRow = new LinearLayout(this);
        recoveryRow.setOrientation(LinearLayout.HORIZONTAL);
        Button arm = button("ARMAR RECUPERACIÓN", SURFACE);
        Button disarm = button("DESARMAR", SURFACE);
        recoveryRow.addView(arm, weightedHeight(48, 1f, 0));
        recoveryRow.addView(disarm, weightedHeight(48, 1f, 6));
        page.addView(recoveryRow, fullHeight(48, 10));
        arm.setOnClickListener(v -> setRecoveryArmed(true));
        disarm.setOnClickListener(v -> setRecoveryArmed(false));

        Button hotspot = button("ABRIR AJUSTES DEL HOTSPOT", SURFACE);
        page.addView(hotspot, fullHeight(48, 10));
        hotspot.setOnClickListener(v -> openHotspotSettings());

        actionMessage = text("Listo. XIO no inicia ni controla las interfaces RD/FOH.", 12, MUTED);
        page.addView(actionMessage, fullHeight(-2, 12));
        monitorState = text("Monitor: comprobando…", 12, MUTED);
        page.addView(monitorState, fullHeight(-2, 4));
        status = text("Comprobando estado…", 13, TEXT);
        status.setPadding(dp(12), dp(14), dp(12), dp(14));
        status.setBackgroundColor(SURFACE);
        page.addView(status, fullHeight(-2, 8));
        page.addView(text("Historial local de muestras y transiciones", 12, MUTED), fullHeight(-2, 14));
        history = text("sin muestras todavía", 11, MUTED);
        page.addView(history, fullHeight(-2, 4));
        scroll.addView(page);
        return scroll;
    }

    private void startTermuxServer() {
        runTermuxCommand(new String[]{TERMUX_SERVER_SCRIPT},
                "Termux recibió la orden de iniciar/reiniciar el host XIO.");
    }

    private void setRecoveryArmed(boolean armed) {
        String shell = armed ? "touch " + RECOVERY_MARKER : "rm -f " + RECOVERY_MARKER;
        runTermuxCommand(new String[]{"-c", shell}, armed
                ? "Recuperación de hotspot armada explícitamente."
                : "Recuperación de hotspot desarmada.");
    }

    private void runTermuxCommand(String[] arguments, String successMessage) {
        try {
            Intent command = new Intent(TERMUX_RUN_COMMAND);
            command.setComponent(new ComponentName(TERMUX_PACKAGE,
                    "com.termux.app.RunCommandService"));
            command.putExtra(RUN_COMMAND_PATH, TERMUX_SHELL);
            command.putExtra(RUN_COMMAND_ARGUMENTS, arguments);
            command.putExtra(RUN_COMMAND_WORKDIR, TERMUX_HOME);
            command.putExtra(RUN_COMMAND_BACKGROUND, true);
            command.putExtra(RUN_COMMAND_SESSION_ACTION, 0);
            startService(command);
            setMessage(successMessage);
        } catch (Exception error) {
            setMessage("No se pudo ejecutar Termux: " + message(error)
                    + ". Revisa allow-external-apps=true.");
        }
    }

    private void toggleMonitor() {
        if (monitorActive()) {
            startService(new Intent(this, XioMonitorService.class).setAction(XioMonitorService.ACTION_STOP));
            setMessage("Monitor detenido; el historial local se conserva.");
        } else {
            startMonitor();
        }
    }

    private void startMonitor() {
        try {
            Intent start = new Intent(this, XioMonitorService.class).setAction(XioMonitorService.ACTION_START);
            if (Build.VERSION.SDK_INT >= 26) startForegroundService(start); else startService(start);
            setMessage("Monitor solicitado: muestreo cada 20 segundos.");
        } catch (Exception error) {
            setMessage("No se pudo iniciar el monitor: " + message(error));
        }
    }

    private boolean monitorActive() {
        return getSharedPreferences("xio_monitor", MODE_PRIVATE).getBoolean("active", false);
    }

    private void forceSample() {
        executor.execute(() -> {
            JSONObject snapshot = XioDiagnostics.collect(this);
            XioDiagnostics.appendSnapshot(this, snapshot);
            render(snapshot);
            setMessage("Diagnóstico guardado en el historial local.");
        });
    }

    private void refreshStatus() {
        executor.execute(() -> {
            JSONObject snapshot = monitorActive() ? XioDiagnostics.readLastSnapshot(this) : null;
            if (snapshot == null) snapshot = XioDiagnostics.collect(this);
            render(snapshot);
        });
    }

    private void render(JSONObject snapshot) {
        if (snapshot == null) return;
        StringBuilder value = new StringBuilder();
        JSONObject hotspot = snapshot.optJSONObject("hotspot");
        JSONObject internet = snapshot.optJSONObject("internet");
        JSONObject radio = snapshot.optJSONObject("radio");
        JSONObject battery = snapshot.optJSONObject("battery");
        JSONObject apps = snapshot.optJSONObject("apps");
        JSONObject hosts = snapshot.optJSONObject("hosts");
        JSONObject rd = hosts == null ? null : hosts.optJSONObject("rd");
        JSONObject foh = hosts == null ? null : hosts.optJSONObject("foh");
        JSONObject runtime = hosts == null ? null : hosts.optJSONObject("xio_runtime");
        JSONObject connsup = hosts == null ? null : hosts.optJSONObject("connectivity_supervisor");

        value.append("Muestra: ").append(snapshot.optString("timestamp", "N/D")).append('\n');
        value.append("Hotspot: ").append(hotspotState(hotspot)).append(" · ")
                .append(hotspot == null ? "" : hotspot.optString("hotspot_address", ""));
        value.append('\n').append("Internet: ").append(internetState(internet));
        value.append('\n').append("Radio: ").append(radio == null ? "N/D" : radio.optString("network_type", "N/D"))
                .append(" · data ").append(radio == null ? "N/D" : radio.optString("data_state", "N/D"));
        if (radio != null && radio.has("lte_rsrp")) value.append(" · RSRP ").append(radio.optInt("lte_rsrp"));
        if (battery != null) value.append('\n').append("Batería: ")
                .append(!battery.isNull("level") ? battery.optInt("level") + "%" : "N/D")
                .append(" · ").append(battery.optString("temperature_c", "N/D")).append(" °C")
                .append(battery.optBoolean("charging", false) ? " · cargando" : "");
        value.append('\n').append("Runtime XIO :5000: ").append(probeState(runtime));
        JSONObject runtimeSummary = runtime == null ? null : runtime.optJSONObject("summary");
        if (runtimeSummary != null && runtimeSummary.has("connected")) value.append(" · ADB backend ")
                .append(runtimeSummary.optBoolean("connected", false) ? "conectado" : "desconectado");
        value.append('\n').append("Host XIO/plugins :5000: ").append(probeState(rd));
        if (hosts != null && hosts.has("rd_plugins_loaded")) value.append(" · ").append(hosts.optInt("rd_plugins_loaded")).append(" plugins");
        value.append('\n').append("Host FOH :5100: ").append(probeState(foh));
        if (apps != null) value.append('\n').append("Apps detectadas: Termux=")
                .append(apps.optBoolean("com.termux", false) ? "sí" : "no")
                .append(" · RD=").append(apps.optBoolean("cl.reduciendodano.xiofield", false) ? "sí" : "no")
                .append(" · FOH=").append(apps.optBoolean("cl.xio.foh", false) ? "sí" : "no");
        if (connsup != null && connsup.has("summary")) {
            JSONObject summary = connsup.optJSONObject("summary");
            if (summary != null && summary.has("tethering")) {
                JSONObject tethering = summary.optJSONObject("tethering");
                if (tethering != null) value.append('\n').append("Tethering plugin: ")
                        .append(tethering.optBoolean("active", false) ? "activo" : "inactivo")
                        .append(" · conntrack errors ").append(tethering.optInt("conntrack_error_count", 0));
            }
            JSONObject watchdogs = summary == null ? null : summary.optJSONObject("watchdogs");
            if (watchdogs != null) value.append('\n').append("Watchdogs: Shizuku=")
                    .append(watchdogs.optInt("shizuku", 0) > 0 ? "UP" : "DOWN")
                    .append(" · server=").append(watchdogs.optInt("server", 0) > 0 ? "UP" : "DOWN")
                    .append(" · hotspot=").append(watchdogs.optInt("hotspot", 0) > 0 ? "UP" : "DOWN");
        }

        List<String> recent = XioDiagnostics.readRecentLines(this, 8);
        StringBuilder recentText = new StringBuilder();
        for (int i = recent.size() - 1; i >= 0; i--) {
            try {
                if (recentText.length() > 0) recentText.append('\n');
                recentText.append(shortLine(new JSONObject(recent.get(i))));
            } catch (Exception ignored) { }
        }
        String rendered = value.toString();
        String renderedHistory = recentText.length() == 0 ? "sin muestras todavía" : recentText.toString();
        runOnUiThread(() -> {
            if (status != null) status.setText(rendered);
            if (history != null) history.setText(renderedHistory);
            if (monitorState != null) monitorState.setText("Monitor: " + (monitorActive() ? "ACTIVO · 20 s" : "detenido"));
        });
    }

    private String shortLine(JSONObject snapshot) {
        JSONObject hotspot = snapshot.optJSONObject("hotspot");
        JSONObject radio = snapshot.optJSONObject("radio");
        JSONObject hosts = snapshot.optJSONObject("hosts");
        String line = snapshot.optString("timestamp", "N/D")
                + " · hotspot=" + (hotspot != null && hotspot.optBoolean("hotspot_up", false) ? "UP" : "DOWN")
                + " · radio=" + (radio == null ? "N/D" : radio.optString("network_type", "N/D"))
                + " · XIO=" + probeState(hosts == null ? null : hosts.optJSONObject("rd"))
                + " · FOH=" + probeState(hosts == null ? null : hosts.optJSONObject("foh"));
        if (snapshot.optJSONArray("transitions") != null) line += " · CAMBIO: " + snapshot.optJSONArray("transitions");
        return line;
    }

    private String hotspotState(JSONObject value) {
        if (value == null || !value.has("hotspot_up")) return "N/D";
        return value.optBoolean("hotspot_up") ? "UP" : "DOWN";
    }

    private String internetState(JSONObject value) {
        if (value == null || !value.optBoolean("available", false)) return "DOWN";
        String transport = value.optBoolean("cellular", false) ? "celular"
                : value.optBoolean("wifi", false) ? "Wi‑Fi" : "red";
        return transport + (value.optBoolean("validated", false) ? " validada" : " sin validar")
                + (value.has("iface") ? " · " + value.optString("iface") : "");
    }

    private String probeState(JSONObject value) {
        if (value == null) return "N/D";
        if (!value.optBoolean("up", false)) {
            int code = value.optInt("code", 0);
            return code == 0 ? "DOWN" : "HTTP " + code;
        }
        return "UP " + value.optInt("code", 200) + " (" + value.optLong("latency_ms", 0) + " ms)";
    }

    private void openHub() {
        try {
            Intent intent = new Intent(this, HubActivity.class);
            startActivity(intent);
        } catch (Exception error) {
            setMessage("No se pudo abrir el hub: " + message(error));
        }
    }

    private void openHotspotSettings() {
        try {
            startActivity(new Intent("android.settings.TETHER_SETTINGS"));
            setMessage("Ajustes del hotspot abiertos; XIO no pulsa el switch.");
        } catch (Exception error) {
            setMessage("No se pudieron abrir los ajustes: " + message(error));
        }
    }

    private void requestRuntimePermissions() {
        List<String> missing = new ArrayList<>();
        if (Build.VERSION.SDK_INT >= 23
                && checkSelfPermission(Manifest.permission.READ_PHONE_STATE) != PackageManager.PERMISSION_GRANTED) {
            missing.add(Manifest.permission.READ_PHONE_STATE);
        }
        if (Build.VERSION.SDK_INT >= 23
                && checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
            missing.add(Manifest.permission.ACCESS_FINE_LOCATION);
        }
        if (Build.VERSION.SDK_INT >= 33
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            missing.add(Manifest.permission.POST_NOTIFICATIONS);
        }
        if (!missing.isEmpty()) requestPermissions(missing.toArray(new String[0]), REQUEST_PERMISSIONS);
    }

    private void setMessage(String value) {
        runOnUiThread(() -> { if (actionMessage != null) actionMessage.setText(value); });
    }

    private String message(Exception error) {
        String value = error.getMessage();
        return value == null || value.isEmpty() ? error.getClass().getSimpleName() : value;
    }

    private LinearLayout column() {
        LinearLayout value = new LinearLayout(this);
        value.setOrientation(LinearLayout.VERTICAL);
        return value;
    }

    private TextView text(String value, int size, int color) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextSize(size);
        view.setTextColor(color);
        view.setGravity(Gravity.START);
        view.setPadding(0, dp(4), 0, dp(4));
        return view;
    }

    private Button button(String value, int background) {
        Button view = new Button(this);
        view.setText(value);
        view.setTextSize(11);
        view.setTextColor(TEXT);
        view.setAllCaps(false);
        view.setMinHeight(0);
        view.setMinWidth(0);
        view.setPadding(dp(4), 0, dp(4), 0);
        view.setBackgroundColor(background);
        return view;
    }

    private LinearLayout.LayoutParams fullHeight(int height, int topMargin) {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, height < 0 ? -2 : dp(height));
        params.setMargins(0, dp(topMargin), 0, 0);
        return params;
    }

    private LinearLayout.LayoutParams weightedHeight(int height, float weight, int leftMargin) {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(0, dp(height), weight);
        params.setMargins(dp(leftMargin), 0, 0, 0);
        return params;
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }
}
