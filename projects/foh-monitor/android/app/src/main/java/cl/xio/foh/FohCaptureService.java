package cl.xio.foh;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.os.IBinder;
import android.net.wifi.WifiManager;

/** Keeps XIO-FOH listening when the activity is not the foreground screen. */
public final class FohCaptureService extends Service {
    public static final String ACTION_START = "cl.xio.foh.START";
    public static final String ACTION_STOP = "cl.xio.foh.STOP";
    public static final String EXTRA_EVENT_KEY = "eventKey";
    public static final String ACTION_STATUS = "cl.xio.foh.STATUS";
    private FohListener listener;
    private FohLogStore store;
    private FohNativeServer nativeServer;
    private WifiManager.MulticastLock multicastLock;
    private long lastStatusAt;

    @Override public void onCreate() {
        super.onCreate();
        migrateLegacyEmbeddedHost();
        store = new FohLogStore(this);
        WifiManager wifi = (WifiManager) getApplicationContext().getSystemService(WIFI_SERVICE);
        if (wifi != null) {
            multicastLock = wifi.createMulticastLock("xio-foh-sacn");
            multicastLock.setReferenceCounted(false);
            multicastLock.acquire();
        }
        String channelId = "xio_foh_listener";
        NotificationManager manager = getSystemService(NotificationManager.class);
        manager.createNotificationChannel(new NotificationChannel(channelId, getString(cl.xio.foh.R.string.notification_channel), NotificationManager.IMPORTANCE_LOW));
        startForeground(1001, new Notification.Builder(this, channelId)
                .setContentTitle("XIO FOH activo")
                .setContentText("Escuchando Art-Net · sACN · OSC/timecode")
                .setSmallIcon(android.R.drawable.ic_menu_info_details)
                .setOngoing(true).build());
        listener = new FohListener(store, new FohListener.Callback() {
            @Override public void onChanged() { sendStatus(null); }
            @Override public void onError(String message) { sendStatus(message); }
            @Override public void onPacket(String protocol, String detail) { sendPacketToHost(protocol, detail); }
            @Override public void onSetlistIndexChanged(int index) {
                getSharedPreferences("xio_foh", MODE_PRIVATE).edit().putInt("setlistIndex", index).apply();
            }
        });
        // XIO-FOH is self-hosting on the private hotspot. The APK UI is native;
        // this HTTP surface is only for colleagues' browsers and the existing
        // FLUJO-ISKVW visualizer, so no PC or Termux process is required.
        nativeServer = new FohNativeServer(this, store, listener);
        nativeServer.start();
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && ACTION_STOP.equals(intent.getAction())) { stopSelf(); return START_NOT_STICKY; }
        String eventKey = intent == null ? "" : intent.getStringExtra(EXTRA_EVENT_KEY);
        listener.start(eventKey);
        return START_STICKY;
    }

    private void sendStatus(String error) {
        long now = System.currentTimeMillis();
        if (error == null && now - lastStatusAt < 1000) return;
        lastStatusAt = now;
        Intent status = new Intent(ACTION_STATUS);
        status.setPackage(getPackageName());
        status.putExtra("running", listener != null && listener.isRunning());
        status.putExtra("server", nativeServer != null && nativeServer.isRunning());
        status.putExtra("logCount", store == null ? 0 : store.count());
        if (nativeServer != null) status.putExtra("localStatus", nativeServer.localStatusJson().toString());
        if (error != null) status.putExtra("error", error);
        sendBroadcast(status);
    }

    private void sendPacketToHost(String protocol, String detail) {
        String eventKey = getSharedPreferences("xio_foh", MODE_PRIVATE).getString("eventKey", "");
        String host = getSharedPreferences("xio_foh", MODE_PRIVATE).getString("host", "http://127.0.0.1:5100").replaceAll("/+$", "");
        // The native listener already persists every packet locally. Do not
        // POST it back to the same embedded server: that would duplicate the
        // evidence row once for every accepted signal. Forward only when the
        // operator explicitly configured a different XIO/FOH host.
        if (isLocalNativeHost(host)) return;
        new Thread(() -> {
            try {
                java.net.HttpURLConnection connection = (java.net.HttpURLConnection) new java.net.URL(host + "/api/plugins/foh_monitor/ingest").openConnection();
                connection.setRequestMethod("POST"); connection.setConnectTimeout(900); connection.setReadTimeout(1200); connection.setDoOutput(true); connection.setRequestProperty("Content-Type", "application/json");
                String body = "{\"protocol\":" + org.json.JSONObject.quote(protocol) + ",\"detail\":" + org.json.JSONObject.quote(detail) + ",\"eventKey\":" + org.json.JSONObject.quote(eventKey) + "}";
                try (java.io.OutputStream output = connection.getOutputStream()) { output.write(body.getBytes(java.nio.charset.StandardCharsets.UTF_8)); }
                connection.getResponseCode(); connection.disconnect();
            } catch (Exception ignored) { /* Local SQLite remains the source of truth while the host is offline. */ }
        }, "xio-foh-host-sync").start();
    }

    private boolean isLocalNativeHost(String host) {
        return "http://127.0.0.1:5100".equalsIgnoreCase(host)
                || "http://localhost:5100".equalsIgnoreCase(host)
                || "http://[::1]:5100".equalsIgnoreCase(host);
    }

    private void migrateLegacyEmbeddedHost() {
        android.content.SharedPreferences prefs = getSharedPreferences("xio_foh", MODE_PRIVATE);
        if ("http://127.0.0.1:5000".equals(prefs.getString("host", "").trim())) {
            prefs.edit().putString("host", "http://127.0.0.1:5100").apply();
        }
    }

    @Override public void onDestroy() {
        if (listener != null) listener.stop();
        if (nativeServer != null) nativeServer.stop();
        if (multicastLock != null && multicastLock.isHeld()) multicastLock.release();
        if (store != null) store.close();
        super.onDestroy();
    }

    @Override public IBinder onBind(Intent intent) { return null; }
}
