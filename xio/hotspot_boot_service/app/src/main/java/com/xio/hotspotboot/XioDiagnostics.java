package com.xio.hotspotboot;

import android.Manifest;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.PackageManager;
import android.net.ConnectivityManager;
import android.net.LinkProperties;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.telephony.CellSignalStrength;
import android.telephony.CellSignalStrengthLte;
import android.telephony.CellSignalStrengthNr;
import android.telephony.SignalStrength;
import android.telephony.TelephonyManager;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.io.Writer;
import java.net.HttpURLConnection;
import java.net.Inet4Address;
import java.net.NetworkInterface;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.Enumeration;
import java.util.List;
import java.util.Locale;
import java.util.TimeZone;

/** Read-only device and XIO host diagnostics used by the control APK. */
public final class XioDiagnostics {
    public static final String RD_HOST = "http://127.0.0.1:5000";
    public static final String FOH_HOST = "http://127.0.0.1:5100";
    private static final int CONNECT_TIMEOUT_MS = 900;
    private static final int READ_TIMEOUT_MS = 1400;
    private static final int MAX_BODY_CHARS = 128 * 1024;
    private static final String SNAPSHOT_FILE = "xio-diagnostics.jsonl";
    private static final Object FILE_LOCK = new Object();

    private XioDiagnostics() { }

    public static JSONObject collect(Context source) {
        Context context = source.getApplicationContext();
        JSONObject result = new JSONObject();
        try {
            result.put("schema", "xio-apk-diagnostics-v1");
            result.put("timestamp", timestamp());
            result.put("hotspot", networkInterfaces());
            result.put("internet", activeNetwork(context));
            result.put("radio", radio(context));
            result.put("battery", battery(context));
            result.put("apps", installedApps(context));

            JSONObject hosts = new JSONObject();
            JSONObject rd = probe(RD_HOST + "/api/plugins");
            JSONObject foh = probe(FOH_HOST + "/api/plugins/foh_monitor/status");
            JSONObject connectivity = probe(RD_HOST + "/api/plugins/connectivity_supervisor/status");
            hosts.put("rd", publicProbe(rd));
            hosts.put("foh", publicProbe(foh));
            hosts.put("connectivity_supervisor", publicProbe(connectivity));
            if (rd.has("payload") && rd.opt("payload") instanceof JSONArray) {
                hosts.put("rd_plugins_loaded", rd.optJSONArray("payload").length());
            }
            result.put("hosts", hosts);
        } catch (Exception error) {
            try { result.put("error", error.getClass().getSimpleName() + ": " + error.getMessage()); }
            catch (Exception ignored) { }
        }
        return result;
    }

    private static JSONObject networkInterfaces() throws Exception {
        JSONObject result = new JSONObject();
        JSONArray interfaces = new JSONArray();
        boolean hotspotUp = false;
        String hotspotName = "";
        String hotspotAddress = "";
        Enumeration<NetworkInterface> all = NetworkInterface.getNetworkInterfaces();
        while (all != null && all.hasMoreElements()) {
            NetworkInterface network = all.nextElement();
            String name = network.getName();
            String address = "";
            Enumeration<java.net.InetAddress> addresses = network.getInetAddresses();
            while (addresses.hasMoreElements()) {
                java.net.InetAddress candidate = addresses.nextElement();
                if (candidate instanceof Inet4Address && !candidate.isLoopbackAddress()) {
                    address = candidate.getHostAddress();
                    break;
                }
            }
            if (address.isEmpty()) continue;
            JSONObject item = new JSONObject().put("name", name)
                    .put("up", network.isUp()).put("ipv4", address);
            interfaces.put(item);
            if (isHotspotInterface(name)) {
                hotspotUp = network.isUp();
                hotspotName = name;
                hotspotAddress = address;
            }
        }
        result.put("hotspot_up", hotspotUp)
                .put("hotspot_iface", hotspotName)
                .put("hotspot_address", hotspotAddress)
                .put("interfaces", interfaces);
        return result;
    }

    private static boolean isHotspotInterface(String name) {
        return "wlan1".equals(name) || name.startsWith("ap_br_") || name.startsWith("softap");
    }

    private static JSONObject activeNetwork(Context context) throws Exception {
        JSONObject result = new JSONObject();
        ConnectivityManager manager = (ConnectivityManager)
                context.getSystemService(Context.CONNECTIVITY_SERVICE);
        if (manager == null) return result.put("available", false);
        Network network = manager.getActiveNetwork();
        NetworkCapabilities capabilities = network == null ? null : manager.getNetworkCapabilities(network);
        LinkProperties links = network == null ? null : manager.getLinkProperties(network);
        boolean validated = capabilities != null
                && capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED);
        result.put("available", network != null)
                .put("validated", validated)
                .put("internet_capability", capabilities != null
                        && capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET))
                .put("cellular", capabilities != null
                        && capabilities.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR))
                .put("wifi", capabilities != null
                        && capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI));
        if (links != null) result.put("iface", links.getInterfaceName());
        return result;
    }

    private static JSONObject radio(Context context) throws Exception {
        JSONObject result = new JSONObject();
        TelephonyManager manager = (TelephonyManager)
                context.getSystemService(Context.TELEPHONY_SERVICE);
        if (manager == null) return result.put("available", false);
        result.put("available", true);
        try {
            int type = manager.getDataNetworkType();
            result.put("network_type", networkTypeName(type));
            result.put("network_type_code", type);
            result.put("data_state", dataStateName(manager.getDataState()));
            result.put("data_state_code", manager.getDataState());
        } catch (SecurityException error) {
            result.put("permission_error", Manifest.permission.READ_PHONE_STATE);
        }

        if (android.os.Build.VERSION.SDK_INT >= 30
                && context.checkSelfPermission(Manifest.permission.READ_PHONE_STATE)
                == PackageManager.PERMISSION_GRANTED) {
            try {
                SignalStrength strength = manager.getSignalStrength();
                if (strength != null) {
                    for (CellSignalStrength cell : strength.getCellSignalStrengths()) {
                        if (cell instanceof CellSignalStrengthLte) {
                            CellSignalStrengthLte lte = (CellSignalStrengthLte) cell;
                            result.put("lte_rssi", lte.getRssi())
                                    .put("lte_rsrp", lte.getRsrp())
                                    .put("lte_rsrq", lte.getRsrq())
                                    .put("lte_rssnr", lte.getRssnr());
                        } else if (cell instanceof CellSignalStrengthNr) {
                            CellSignalStrengthNr nr = (CellSignalStrengthNr) cell;
                            result.put("nr_ss_rsrp", nr.getSsRsrp())
                                    .put("nr_ss_rsrq", nr.getSsRsrq())
                                    .put("nr_ss_sinr", nr.getSsSinr());
                        }
                    }
                }
            } catch (SecurityException error) {
                result.put("signal_permission_error", true);
            } catch (Exception error) {
                result.put("signal_error", error.getClass().getSimpleName());
            }
        } else {
            result.put("signal_permission_error", true);
        }
        return result;
    }

    private static JSONObject battery(Context context) throws Exception {
        JSONObject result = new JSONObject();
        Intent state = context.registerReceiver(null,
                new IntentFilter(Intent.ACTION_BATTERY_CHANGED));
        if (state == null) return result.put("available", false);
        int level = state.getIntExtra("level", -1);
        int scale = state.getIntExtra("scale", -1);
        int temperature = state.getIntExtra("temperature", Integer.MIN_VALUE);
        int status = state.getIntExtra("status", -1);
        result.put("available", true)
                .put("level", level >= 0 && scale > 0 ? Math.round(level * 100f / scale) : JSONObject.NULL)
                .put("temperature_c", temperature == Integer.MIN_VALUE ? JSONObject.NULL : temperature / 10.0)
                .put("charging", status == android.os.BatteryManager.BATTERY_STATUS_CHARGING
                        || status == android.os.BatteryManager.BATTERY_STATUS_FULL)
                .put("status", batteryStatusName(status));
        return result;
    }

    private static String batteryStatusName(int status) {
        switch (status) {
            case android.os.BatteryManager.BATTERY_STATUS_CHARGING: return "CHARGING";
            case android.os.BatteryManager.BATTERY_STATUS_DISCHARGING: return "DISCHARGING";
            case android.os.BatteryManager.BATTERY_STATUS_NOT_CHARGING: return "NOT_CHARGING";
            case android.os.BatteryManager.BATTERY_STATUS_FULL: return "FULL";
            default: return "UNKNOWN";
        }
    }

    private static String dataStateName(int state) {
        switch (state) {
            case TelephonyManager.DATA_CONNECTED: return "CONNECTED";
            case TelephonyManager.DATA_CONNECTING: return "CONNECTING";
            case TelephonyManager.DATA_DISCONNECTED: return "DISCONNECTED";
            case TelephonyManager.DATA_SUSPENDED: return "SUSPENDED";
            default: return Integer.toString(state);
        }
    }

    private static String networkTypeName(int type) {
        switch (type) {
            case TelephonyManager.NETWORK_TYPE_LTE: return "LTE";
            case TelephonyManager.NETWORK_TYPE_NR: return "NR";
            case TelephonyManager.NETWORK_TYPE_HSDPA: return "HSDPA";
            case TelephonyManager.NETWORK_TYPE_HSUPA: return "HSUPA";
            case TelephonyManager.NETWORK_TYPE_UMTS: return "UMTS";
            case TelephonyManager.NETWORK_TYPE_EDGE: return "EDGE";
            case TelephonyManager.NETWORK_TYPE_GPRS: return "GPRS";
            case TelephonyManager.NETWORK_TYPE_GSM: return "GSM";
            default: return Integer.toString(type);
        }
    }

    private static JSONObject installedApps(Context context) throws Exception {
        JSONObject result = new JSONObject();
        for (String packageName : new String[]{"com.termux", "cl.reduciendodano.xiofield", "cl.xio.foh"}) {
            boolean installed;
            try {
                context.getPackageManager().getApplicationInfo(packageName, 0);
                installed = true;
            } catch (PackageManager.NameNotFoundException missing) {
                installed = false;
            }
            result.put(packageName, installed);
        }
        return result;
    }

    private static JSONObject probe(String endpoint) {
        HttpURLConnection connection = null;
        long started = System.currentTimeMillis();
        try {
            connection = (HttpURLConnection) new URL(endpoint).openConnection();
            connection.setConnectTimeout(CONNECT_TIMEOUT_MS);
            connection.setReadTimeout(READ_TIMEOUT_MS);
            connection.setRequestMethod("GET");
            int code = connection.getResponseCode();
            String body = readBody(connection);
            JSONObject result = new JSONObject().put("up", code >= 200 && code < 400)
                    .put("code", code)
                    .put("latency_ms", System.currentTimeMillis() - started);
            try {
                result.put("payload", new JSONObject(body));
            } catch (Exception notObject) {
                try { result.put("payload", new JSONArray(body)); }
                catch (Exception notJson) { result.put("body_preview", body.substring(0, Math.min(180, body.length()))); }
            }
            return result;
        } catch (Exception error) {
            try {
                return new JSONObject().put("up", false)
                        .put("code", 0)
                        .put("latency_ms", System.currentTimeMillis() - started)
                        .put("error", error.getClass().getSimpleName());
            } catch (Exception impossible) {
                return new JSONObject();
            }
        } finally {
            if (connection != null) connection.disconnect();
        }
    }

    private static String readBody(HttpURLConnection connection) throws Exception {
        java.io.InputStream stream = connection.getResponseCode() >= 400
                ? connection.getErrorStream() : connection.getInputStream();
        if (stream == null) return "";
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(stream, StandardCharsets.UTF_8))) {
            StringBuilder body = new StringBuilder();
            String line;
            while ((line = reader.readLine()) != null && body.length() < MAX_BODY_CHARS) {
                body.append(line);
            }
            return body.toString();
        }
    }

    private static JSONObject publicProbe(JSONObject probe) throws Exception {
        JSONObject result = new JSONObject();
        for (String key : new String[]{"up", "code", "latency_ms", "error", "body_preview"}) {
            if (probe.has(key)) result.put(key, probe.get(key));
        }
        if (probe.has("payload")) {
            Object payload = probe.get("payload");
            if (payload instanceof JSONObject) {
                JSONObject source = (JSONObject) payload;
                JSONObject summary = new JSONObject();
                for (String key : new String[]{"server", "listener", "httpPort", "hotspot_up", "hotspot_address", "internet", "radio", "tethering", "clients_present"}) {
                    if (source.has(key)) summary.put(key, source.get(key));
                }
                if (summary.length() > 0) result.put("summary", summary);
            } else if (payload instanceof JSONArray) {
                result.put("items", ((JSONArray) payload).length());
            }
        }
        return result;
    }

    public static String timestamp() {
        SimpleDateFormat format = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssXXX", Locale.ROOT);
        format.setTimeZone(TimeZone.getDefault());
        return format.format(new Date());
    }

    public static void appendSnapshot(Context source, JSONObject snapshot) {
        File file = new File(source.getApplicationContext().getFilesDir(), SNAPSHOT_FILE);
        synchronized (FILE_LOCK) {
            try {
                if (file.exists() && file.length() > 2_000_000L) rotate(file);
                try (Writer writer = new OutputStreamWriter(new FileOutputStream(file, true), StandardCharsets.UTF_8)) {
                    writer.write(snapshot.toString());
                    writer.write("\n");
                }
            } catch (Exception ignored) { }
        }
    }

    private static void rotate(File file) {
        File old = new File(file.getParentFile(), SNAPSHOT_FILE + ".1");
        if (old.exists()) old.delete();
        file.renameTo(old);
    }

    public static JSONObject readLastSnapshot(Context source) {
        File file = new File(source.getApplicationContext().getFilesDir(), SNAPSHOT_FILE);
        if (!file.exists()) return null;
        String last = "";
        synchronized (FILE_LOCK) {
            try (BufferedReader reader = new BufferedReader(new InputStreamReader(
                    new FileInputStream(file), StandardCharsets.UTF_8))) {
                String line;
                while ((line = reader.readLine()) != null) if (!line.trim().isEmpty()) last = line;
            } catch (Exception ignored) { return null; }
        }
        try { return new JSONObject(last); } catch (Exception ignored) { return null; }
    }

    public static List<String> readRecentLines(Context source, int limit) {
        File file = new File(source.getApplicationContext().getFilesDir(), SNAPSHOT_FILE);
        List<String> lines = new ArrayList<>();
        if (!file.exists()) return lines;
        synchronized (FILE_LOCK) {
            try (BufferedReader reader = new BufferedReader(new InputStreamReader(
                    new FileInputStream(file), StandardCharsets.UTF_8))) {
                String line;
                while ((line = reader.readLine()) != null) {
                    if (!line.trim().isEmpty()) {
                        lines.add(line);
                        while (lines.size() > limit) lines.remove(0);
                    }
                }
            } catch (Exception ignored) { }
        }
        return lines;
    }
}
