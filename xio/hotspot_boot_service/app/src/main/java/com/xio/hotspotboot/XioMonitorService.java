package com.xio.hotspotboot;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.os.IBinder;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

/** Optional persistent read-only monitor for network and XIO host health. */
public final class XioMonitorService extends Service {
    public static final String ACTION_START = "com.xio.hotspotboot.MONITOR_START";
    public static final String ACTION_STOP = "com.xio.hotspotboot.MONITOR_STOP";
    private static final String CHANNEL_ID = "xio_diagnostics";
    private ScheduledExecutorService executor;
    private volatile boolean stopping;
    private JSONObject previous;

    @Override public void onCreate() {
        super.onCreate();
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (manager != null) {
            manager.createNotificationChannel(new NotificationChannel(
                    CHANNEL_ID, "XIO diagnóstico", NotificationManager.IMPORTANCE_LOW));
        }
        startForeground(2001, new Notification.Builder(this, CHANNEL_ID)
                .setContentTitle("XIO monitor activo")
                .setContentText("Registrando hotspot, radio y servidores")
                .setSmallIcon(android.R.drawable.ic_menu_info_details)
                .setOngoing(true).build());
        getSharedPreferences("xio_monitor", MODE_PRIVATE).edit().putBoolean("active", true).apply();
        executor = Executors.newSingleThreadScheduledExecutor(runnable -> {
            Thread thread = new Thread(runnable, "xio-diagnostics");
            thread.setDaemon(true);
            return thread;
        });
        executor.scheduleWithFixedDelay(this::sample, 0L, 20L, TimeUnit.SECONDS);
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && ACTION_STOP.equals(intent.getAction())) {
            stopping = true;
            stopSelf();
            return START_NOT_STICKY;
        }
        return START_NOT_STICKY;
    }

    private void sample() {
        if (stopping) return;
        JSONObject snapshot = XioDiagnostics.collect(this);
        JSONArray transitions = transitions(previous, snapshot);
        try { if (transitions.length() > 0) snapshot.put("transitions", transitions); }
        catch (Exception ignored) { }
        XioDiagnostics.appendSnapshot(this, snapshot);
        previous = snapshot;
    }

    private JSONArray transitions(JSONObject oldValue, JSONObject newValue) {
        JSONArray result = new JSONArray();
        if (oldValue == null || newValue == null) return result;
        compare(oldValue, newValue, result, "hotspot", "hotspot", "hotspot_up");
        compare(oldValue, newValue, result, "internet", "internet", "validated");
        compare(oldValue, newValue, result, "radio", "radio", "network_type");
        compare(oldValue, newValue, result, "data", "radio", "data_state");
        compare(oldValue, newValue, result, "RD host", "hosts", "rd", "up");
        compare(oldValue, newValue, result, "FOH host", "hosts", "foh", "up");
        compare(oldValue, newValue, result, "tethering", "hosts", "connectivity_supervisor",
                "summary", "tethering", "active");
        return result;
    }

    private void compare(JSONObject oldValue, JSONObject newValue, JSONArray result,
                         String label, String... path) {
        Object oldItem = atPath(oldValue, path);
        Object newItem = atPath(newValue, path);
        if (oldItem == null || newItem == null || oldItem == JSONObject.NULL || newItem == JSONObject.NULL) return;
        if (!String.valueOf(oldItem).equals(String.valueOf(newItem))) {
            result.put(label + ": " + oldItem + " -> " + newItem);
        }
    }

    private Object atPath(JSONObject object, String... path) {
        Object current = object;
        for (String key : path) {
            if (!(current instanceof JSONObject)) return null;
            current = ((JSONObject) current).opt(key);
        }
        return current;
    }

    @Override public void onDestroy() {
        stopping = true;
        if (executor != null) executor.shutdownNow();
        getSharedPreferences("xio_monitor", MODE_PRIVATE).edit().putBoolean("active", false).apply();
        super.onDestroy();
    }

    @Override public IBinder onBind(Intent intent) { return null; }
}
