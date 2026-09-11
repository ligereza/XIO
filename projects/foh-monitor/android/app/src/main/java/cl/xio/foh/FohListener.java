package cl.xio.foh;

import java.io.IOException;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetAddress;
import java.net.MulticastSocket;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/** Native counterpart of the existing passive foh_monitor listener.
 *
 * It receives only. It never sends to the lighting/visual rig. The protocol
 * rules, channel split and timecode semantics mirror the Python plugin.
 */
public final class FohListener {
    public static final int ARTNET_PORT = 6454;
    public static final int SACN_PORT = 5568;
    public static final int OSC_PORT = 7000;
    private static final long ACTIVE_WINDOW_MS = 5000L;
    private static final long TC_FREEZE_MS = 2000L;
    private final FohLogStore store;
    private final Callback callback;
    private final Map<String, Channel> channels = new HashMap<>();
    private final Object stateLock = new Object();
    private volatile boolean running;
    private String eventKey = "";
    private Thread worker;
    private String tcValue;
    private long tcLastSeen;
    private long tcLastChange;
    private long tcPackets;
    private final Map<Long, Integer> tcBuckets = new HashMap<>();
    private final Map<String, Boolean> previousChannelActive = new HashMap<>();
    private String previousTcState;
    private volatile long lastTcForwardAt;
    private final List<String> setlistSongs = new ArrayList<>();
    private final List<Double> setlistDurations = new ArrayList<>();
    private int setlistIndex = -1;
    private int tcSongIndex = -1;

    public FohListener(FohLogStore store, Callback callback) {
        this.store = store;
        this.callback = callback;
        channels.put("Art-Net", new Channel("Art-Net", ARTNET_PORT));
        channels.put("sACN", new Channel("sACN", SACN_PORT));
        channels.put("OSC / visual", new Channel("OSC / visual", OSC_PORT));
    }

    public synchronized void start(String eventKey) {
        if (running) return;
        this.eventKey = eventKey == null ? "" : eventKey.trim();
        running = true;
        worker = new Thread(this::run, "xio-foh-udp");
        worker.start();
    }

    public synchronized void stop() {
        running = false;
        if (worker != null) worker.interrupt();
        worker = null;
    }

    public boolean isRunning() { return running; }

    public synchronized void setEventKey(String value) { eventKey = value == null ? "" : value.trim(); }

    /** Called by the host whenever the persisted setlist changes. */
    public void setSetlist(JSONArray songs, JSONArray durations, int index) {
        synchronized (stateLock) {
            setlistSongs.clear();
            setlistDurations.clear();
            if (songs != null) for (int i = 0; i < songs.length(); i++) {
                String value = songs.optString(i, "").trim();
                if (!value.isEmpty()) setlistSongs.add(value);
            }
            if (durations != null) for (int i = 0; i < durations.length(); i++) {
                if (durations.isNull(i)) setlistDurations.add(null);
                else {
                    double value = durations.optDouble(i, 0);
                    setlistDurations.add(value > 0 ? value : null);
                }
            }
            while (setlistDurations.size() < setlistSongs.size()) setlistDurations.add(null);
            setlistIndex = setlistSongs.isEmpty() ? -1 : Math.max(0, Math.min(index, setlistSongs.size() - 1));
            tcSongIndex = -1;
        }
    }

    public int currentSetlistIndex() {
        synchronized (stateLock) { return setlistIndex; }
    }

    public synchronized Map<String, Snapshot> snapshots() {
        Map<String, Snapshot> result = new HashMap<>();
        synchronized (stateLock) {
            for (Map.Entry<String, Channel> entry : channels.entrySet()) result.put(entry.getKey(), entry.getValue().snapshot());
        }
        return result;
    }

    public JSONObject timecodeSnapshot() throws JSONException {
        synchronized (stateLock) {
            long now = System.currentTimeMillis();
            Long age = tcLastSeen == 0 ? null : Math.max(0L, now - tcLastSeen) / 1000L;
            String state;
            if (tcLastSeen == 0) state = "sin_senal";
            else if (now - tcLastSeen > ACTIVE_WINDOW_MS) state = "caido";
            else if (tcValue != null && now - tcLastChange > TC_FREEZE_MS) state = "congelado";
            else state = "corriendo";
            return new JSONObject().put("value", tcValue == null ? JSONObject.NULL : tcValue)
                    .put("display", formatTimecode(tcValue)).put("fps", 30).put("state", state)
                    .put("age", age == null ? JSONObject.NULL : age).put("pps", tcPps(now))
                    .put("packets_total", tcPackets).put("address", "/timecode");
        }
    }

    private void run() {
        try (DatagramSocket artnet = new DatagramSocket(ARTNET_PORT);
             MulticastSocket sacn = new MulticastSocket(SACN_PORT);
             DatagramSocket osc = new DatagramSocket(OSC_PORT)) {
            artnet.setSoTimeout(250); sacn.setSoTimeout(250); osc.setSoTimeout(250);
            for (int universe = 1; universe <= 16; universe++) {
                try { sacn.joinGroup(InetAddress.getByName("239.255.0." + universe)); } catch (IOException ignored) { }
            }
            Thread a = receiver("Art-Net", artnet, this::parseArtNet);
            Thread s = receiver("sACN", sacn, this::parseSacn);
            Thread o = receiver("OSC", osc, this::parseOsc);
            a.start(); s.start(); o.start();
            while (running) { Thread.sleep(250); recordTransitions(); callback.onChanged(); }
            a.interrupt(); s.interrupt(); o.interrupt();
        } catch (Exception error) {
            callback.onError(error.getMessage() == null ? error.getClass().getSimpleName() : error.getMessage());
        } finally { running = false; callback.onChanged(); }
    }

    private Thread receiver(String name, DatagramSocket socket, PacketParser parser) {
        return new Thread(() -> {
            byte[] data = new byte[8192];
            while (running) {
                try {
                    DatagramPacket packet = new DatagramPacket(data, data.length);
                    socket.receive(packet);
                    String detail = parser.parse(packet.getData(), packet.getLength());
                    if (detail == null || detail.isEmpty()) continue;
                    Channel channel = channels.get(name);
                    if ("OSC".equals(name)) channel = detail.startsWith("timecode=") ? null : channels.get("OSC / visual");
                    if (channel != null) {
                        synchronized (stateLock) { channel.hit(System.currentTimeMillis(), detail); }
                        if (channel.shouldLog()) {
                            appendLog(channel.name, detail);
                            callback.onPacket("OSC".equals(name) ? "OSC / TC" : name, detail);
                        }
                    }
                    if ("OSC".equals(name) && detail.startsWith("timecode=") && System.currentTimeMillis() - lastTcForwardAt >= 1000L) {
                        lastTcForwardAt = System.currentTimeMillis();
                        callback.onPacket("OSC / TC", detail);
                    }
                    callback.onChanged();
                } catch (java.net.SocketTimeoutException ignored) {
                } catch (IOException error) {
                    if (running) callback.onError(name + ": " + error.getMessage());
                    break;
                }
            }
        }, "xio-foh-" + name.replace(' ', '-'));
    }

    private String parseArtNet(byte[] data, int length) {
        if (length < 12 || !startsWith(data, length, "Art-Net\0")) return null;
        int opcode = (data[8] & 0xff) | ((data[9] & 0xff) << 8);
        if (opcode == 0x5000) {
            if (length < 18) return null;
            int payloadLength = ((data[16] & 0xff) << 8) | (data[17] & 0xff);
            if (payloadLength > 512 || length < 18 + payloadLength) return null;
            int universe = (data[14] & 0xff) | ((data[15] & 0xff) << 8);
            return "OpDmx uni " + universe;
        }
        return "op 0x" + String.format(java.util.Locale.US, "%04x", opcode);
    }

    private String parseSacn(byte[] data, int length) {
        byte[] pid = "ASC-E1.17\0\0\0".getBytes(StandardCharsets.US_ASCII);
        if (length < 126 || !startsWithAt(data, length, 4, pid)) return null;
        int universe = ((data[113] & 0xff) << 8) | (data[114] & 0xff);
        return "E1.31 uni " + universe;
    }

    private String parseOsc(byte[] data, int length) {
        List<byte[]> messages = oscMessages(Arrays.copyOf(data, length), 0);
        if (messages.isEmpty()) return null;
        String visual = null;
        for (byte[] message : messages) {
            String address = oscAddress(message);
            if (address == null) continue;
            String arg = oscFirstArg(message);
            if (address.startsWith("/timecode")) hitTimecode(arg);
            else if (visual == null) visual = "address=" + address;
        }
        if (visual != null) return visual;
        return tcValue == null ? null : "timecode=" + tcValue;
    }

    private void hitTimecode(String raw) {
        if (raw == null || raw.isEmpty()) return;
        synchronized (stateLock) {
            long now = System.currentTimeMillis(); tcPackets++; tcLastSeen = now;
            if (!raw.equals(tcValue)) { tcValue = raw; tcLastChange = now; autoSetlistByTimecode(raw); }
            long second = now / 1000L;
            tcBuckets.put(second, tcBuckets.containsKey(second) ? tcBuckets.get(second) + 1 : 1);
            for (Long key : new ArrayList<>(tcBuckets.keySet())) if (key < second - 10) tcBuckets.remove(key);
        }
    }

    private void autoSetlistByTimecode(String raw) {
        if (setlistSongs.isEmpty()) return;
        Double now = parseTimecode(raw);
        if (now == null) return;
        int selected = -1;
        for (int i = 0; i < setlistSongs.size(); i++) {
            String[] parts = setlistSongs.get(i).split("\\s+", 2);
            Double start = parts.length > 0 ? parseTimecode(parts[0]) : null;
            if (start == null) return;
            if (start <= now) selected = i; else break;
        }
        if (selected < 0 || selected == tcSongIndex) return;
        tcSongIndex = selected; setlistIndex = selected;
        callback.onSetlistIndexChanged(selected);
        try { appendLog("setlist_next", new JSONObject().put("accion", "auto-tc").put("actual", setlistSongs.get(selected)).put("n", selected + 1).put("de", setlistSongs.size()).toString()); }
        catch (Exception ignored) { }
    }

    /** Mirrors the Python plugin's transition log: timestamps transitions,
     * not every high-rate packet, while preserving the current TC for later
     * event/cue correlation. */
    private void recordTransitions() {
        List<String[]> pending = new ArrayList<>();
        synchronized (stateLock) {
            long now = System.currentTimeMillis();
            for (Channel channel : channels.values()) {
                boolean active = channel.lastAt != 0 && now - channel.lastAt <= ACTIVE_WINDOW_MS;
                Boolean was = previousChannelActive.get(channel.name);
                if (was == null) previousChannelActive.put(channel.name, active);
                else if (active != was) {
                    String detail;
                    try { detail = new JSONObject().put("canal", channelKey(channel.name)).put("info", channel.lastDetail).put("pps", channel.pps + channel.windowPackets).toString(); }
                    catch (JSONException ignored) { detail = channel.lastDetail; }
                    pending.add(new String[]{active ? "senal_on" : "senal_off", detail});
                    previousChannelActive.put(channel.name, active);
                }
            }
            String state = timecodeStateLocked(now);
            if (!"sin_senal".equals(state)) {
                if (previousTcState == null) previousTcState = state;
                else if (!state.equals(previousTcState)) {
                    try {
                        if (("congelado".equals(state) || "caido".equals(state)) && "corriendo".equals(previousTcState))
                            pending.add(new String[]{"tc_freeze", new JSONObject().put("estado", state).put("valor", tcValue).put("pps", tcPps(now)).toString()});
                        else if ("corriendo".equals(state) && ("congelado".equals(previousTcState) || "caido".equals(previousTcState)))
                            pending.add(new String[]{"tc_resume", new JSONObject().put("valor", tcValue).toString()});
                        else if ("caido".equals(state) && "congelado".equals(previousTcState))
                            pending.add(new String[]{"tc_freeze", new JSONObject().put("estado", "caido").put("valor", tcValue).put("pps", 0).toString()});
                    } catch (JSONException ignored) { }
                    previousTcState = state;
                }
            }
        }
        for (String[] row : pending) appendLog(row[0], row[1]);
    }

    private void appendLog(String type, String detail) {
        store.append(System.currentTimeMillis(), type, detail == null ? "" : detail, eventKey, currentTimecodeValue());
    }

    private String currentTimecodeValue() {
        synchronized (stateLock) {
            long age = tcLastSeen == 0 ? Long.MAX_VALUE : System.currentTimeMillis() - tcLastSeen;
            return tcValue != null && age <= ACTIVE_WINDOW_MS ? tcValue : null;
        }
    }

    private String timecodeStateLocked(long now) {
        if (tcLastSeen == 0) return "sin_senal";
        if (now - tcLastSeen > ACTIVE_WINDOW_MS) return "caido";
        return tcValue != null && now - tcLastChange > TC_FREEZE_MS ? "congelado" : "corriendo";
    }

    private static String channelKey(String value) {
        if ("Art-Net".equals(value)) return "artnet";
        if ("sACN".equals(value)) return "sacn";
        return "osc";
    }

    private static Double parseTimecode(String value) {
        if (value == null) return null;
        String s = value.trim();
        try {
            if (!s.contains(":")) return Double.parseDouble(s);
            String[] p = s.split(":");
            if (p.length < 3) return null;
            int h = Integer.parseInt(p[0]), m = Integer.parseInt(p[1]), sec = Integer.parseInt(p[2]);
            int frame = p.length > 3 ? Integer.parseInt(p[3]) : 0;
            return h * 3600.0 + m * 60.0 + sec + frame / 30.0;
        } catch (NumberFormatException ignored) { return null; }
    }

    private static String formatTimecode(String value) {
        if (value == null) return null;
        if (value.contains(":")) return value;
        try {
            double total = Math.max(0, Double.parseDouble(value));
            int h = (int) (total / 3600), m = (int) ((total % 3600) / 60), s = (int) (total % 60);
            int frame = (int) Math.round((total - Math.floor(total)) * 30); if (frame >= 30) frame = 29;
            return String.format(java.util.Locale.US, "%02d:%02d:%02d:%02d", h, m, s, frame);
        } catch (NumberFormatException ignored) { return value; }
    }

    private long tcPps(long now) {
        long second = now / 1000L; int sum = 0;
        for (int i = 1; i <= 3; i++) sum += tcBuckets.containsKey(second - i) ? tcBuckets.get(second - i) : 0;
        return Math.round(sum / 3.0);
    }

    private static String oscAddress(byte[] data) {
        if (data == null || data.length == 0 || data[0] != '/') return null;
        int end = 0; while (end < data.length && data[end] != 0) end++;
        if (end == 0) return null;
        return new String(data, 0, end, StandardCharsets.UTF_8);
    }

    private static String oscFirstArg(byte[] data) {
        try {
            int addressEnd = indexOfZero(data, 0); if (addressEnd <= 0) return null;
            int tagsStart = align4(addressEnd + 1); if (tagsStart >= data.length || data[tagsStart] != ',') return null;
            int tagsEnd = indexOfZero(data, tagsStart); if (tagsEnd < 0 || tagsEnd + 1 >= data.length) return null;
            int valueStart = align4(tagsEnd + 1); char tag = (char) data[tagsStart + 1];
            if (tag == 's') { int end = indexOfZero(data, valueStart); return end < 0 ? null : new String(data, valueStart, end - valueStart, StandardCharsets.UTF_8); }
            ByteBuffer b = ByteBuffer.wrap(data).order(ByteOrder.BIG_ENDIAN);
            if (tag == 'f' && valueStart + 4 <= data.length) return String.valueOf(round(b.getFloat(valueStart)));
            if (tag == 'd' && valueStart + 8 <= data.length) return String.valueOf(round(b.getDouble(valueStart)));
            if (tag == 'i' && valueStart + 4 <= data.length) return String.valueOf(b.getInt(valueStart));
            if (tag == 'h' && valueStart + 8 <= data.length) return String.valueOf(b.getLong(valueStart));
        } catch (Exception ignored) { }
        return null;
    }

    private static double round(double value) { return Math.round(value * 1000.0) / 1000.0; }
    private static int indexOfZero(byte[] data, int from) { for (int i = from; i < data.length; i++) if (data[i] == 0) return i; return -1; }
    private static int align4(int value) { return (value + 3) & ~3; }

    private static List<byte[]> oscMessages(byte[] data, int depth) {
        List<byte[]> result = new ArrayList<>(); if (data == null || depth > 4) return result;
        if (!startsWith(data, data.length, "#bundle\0")) { if (oscAddress(data) != null) result.add(data); return result; }
        if (data.length < 16) return result;
        int pos = 16;
        while (pos + 4 <= data.length) {
            int size = ByteBuffer.wrap(data, pos, 4).order(ByteOrder.BIG_ENDIAN).getInt(); pos += 4;
            if (size <= 0 || pos + size > data.length) return new ArrayList<>();
            result.addAll(oscMessages(Arrays.copyOfRange(data, pos, pos + size), depth + 1)); pos += size;
        }
        return pos == data.length ? result : new ArrayList<>();
    }

    private static boolean startsWith(byte[] data, int length, String value) {
        return startsWithAt(data, length, 0, value.getBytes(StandardCharsets.US_ASCII));
    }

    private static boolean startsWithAt(byte[] data, int length, int offset, byte[] expected) {
        if (offset < 0 || offset + expected.length > length) return false;
        for (int i = 0; i < expected.length; i++) if (data[offset + i] != expected[i]) return false;
        return true;
    }

    public interface PacketParser { String parse(byte[] data, int length); }
    public interface Callback {
        void onChanged();
        void onError(String message);
        void onPacket(String protocol, String detail);
        default void onSetlistIndexChanged(int index) { }
    }

    private static final class Channel {
        final String name; final int port; long packets; long lastAt; String lastDetail = ""; long lastLogged;
        long windowStarted; long windowPackets; long pps;
        Channel(String name, int port) { this.name = name; this.port = port; }
        boolean shouldLog() { if (lastAt - lastLogged < 1000) return false; lastLogged = lastAt; return true; }
        void hit(long now, String detail) {
            if (windowStarted == 0) windowStarted = now;
            if (now - windowStarted >= 1000) { pps = windowPackets; windowPackets = 0; windowStarted = now; }
            windowPackets++; packets++; lastAt = now; lastDetail = detail;
        }
        Snapshot snapshot() {
            long now = System.currentTimeMillis(); long age = lastAt == 0 ? Long.MAX_VALUE : now - lastAt;
            return new Snapshot(name, port, packets, lastAt, lastDetail, pps + (now - windowStarted < 1000 ? windowPackets : 0), age <= ACTIVE_WINDOW_MS);
        }
    }

    public static final class Snapshot {
        public final String name; public final int port; public final long packets; public final long lastAt;
        public final String detail; public final long pps; public final boolean active;
        Snapshot(String name, int port, long packets, long lastAt, String detail, long pps, boolean active) {
            this.name = name; this.port = port; this.packets = packets; this.lastAt = lastAt; this.detail = detail; this.pps = pps; this.active = active;
        }
    }
}
