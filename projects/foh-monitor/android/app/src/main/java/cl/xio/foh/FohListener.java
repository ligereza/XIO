package cl.xio.foh;

import java.io.IOException;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetAddress;
import java.net.MulticastSocket;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.HashMap;
import java.util.Map;

/** Local active FOH listener. It only receives UDP and writes durable evidence. */
public final class FohListener {
    public static final int ARTNET_PORT = 6454;
    public static final int SACN_PORT = 5568;
    public static final int OSC_PORT = 7000;
    private final FohLogStore store;
    private final Callback callback;
    private final Map<String, Channel> channels = new HashMap<>();
    private volatile boolean running;
    private String eventKey = "";
    private Thread worker;

    public FohListener(FohLogStore store, Callback callback) {
        this.store = store; this.callback = callback;
        channels.put("Art-Net", new Channel("Art-Net", ARTNET_PORT));
        channels.put("sACN", new Channel("sACN", SACN_PORT));
        channels.put("OSC / TC", new Channel("OSC / TC", OSC_PORT));
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

    public synchronized Map<String, Snapshot> snapshots() {
        Map<String, Snapshot> result = new HashMap<>();
        for (Map.Entry<String, Channel> entry : channels.entrySet()) result.put(entry.getKey(), entry.getValue().snapshot());
        return result;
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
            Thread o = receiver("OSC / TC", osc, this::parseOsc);
            a.start(); s.start(); o.start();
            while (running) { Thread.sleep(250); callback.onChanged(); }
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
                    if (detail == null) continue;
                    Channel channel = channels.get(name);
                    synchronized (this) { channel.packets++; channel.lastAt = System.currentTimeMillis(); channel.lastDetail = detail; }
                    if (channel.shouldLog()) {
                        store.append(System.currentTimeMillis(), name, detail, eventKey);
                        callback.onPacket(name, detail);
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
        if (length < 10 || !startsWith(data, length, "Art-Net\0")) return null;
        int opcode = (data[8] & 0xff) | ((data[9] & 0xff) << 8);
        return "opcode=0x" + Integer.toHexString(opcode) + " bytes=" + length;
    }

    private String parseSacn(byte[] data, int length) {
        if (length < 126) return null;
        byte[] pid = "ASC-E1.17\0\0\0".getBytes(StandardCharsets.US_ASCII);
        boolean matchingPid = true;
        for (int i = 0; i < pid.length && i + 4 < length; i++) if (data[4 + i] != pid[i]) { matchingPid = false; break; }
        if (!matchingPid) return null;
        int universe = ((data[113] & 0xff) << 8) | (data[114] & 0xff);
        return "universe=" + universe + " bytes=" + length;
    }

    private String parseOsc(byte[] data, int length) {
        if (length >= 16 && startsWith(data, length, "#bundle\0")) {
            int offset = 16; // OSC bundle header + timetag.
            while (offset + 4 <= length) {
                int size = ((data[offset] & 0xff) << 24)
                        | ((data[offset + 1] & 0xff) << 16)
                        | ((data[offset + 2] & 0xff) << 8)
                        | (data[offset + 3] & 0xff);
                offset += 4;
                if (size <= 0 || offset + size > length) return null;
                String nested = parseOsc(Arrays.copyOfRange(data, offset, offset + size), size);
                if (nested != null) return nested;
                offset += size;
            }
            return null;
        }
        int end = 0; while (end < length && data[end] != 0) end++;
        if (end == 0) return null;
        String address = new String(data, 0, end, StandardCharsets.UTF_8);
        if (!address.startsWith("/")) return null;
        return (address.startsWith("/timecode") ? "timecode=" : "address=") + address;
    }

    private static boolean startsWith(byte[] data, int length, String value) {
        byte[] expected = value.getBytes(StandardCharsets.US_ASCII);
        return length >= expected.length && Arrays.equals(Arrays.copyOf(data, expected.length), expected);
    }

    public interface PacketParser { String parse(byte[] data, int length); }
    public interface Callback {
        void onChanged();
        void onError(String message);
        void onPacket(String protocol, String detail);
    }

    private static final class Channel {
        final String name; final int port; long packets; long lastAt; String lastDetail = "sin señal"; long lastLogged;
        Channel(String name, int port) { this.name = name; this.port = port; }
        boolean shouldLog() { if (lastAt - lastLogged < 1000) return false; lastLogged = lastAt; return true; }
        Snapshot snapshot() { return new Snapshot(name, port, packets, lastAt, lastDetail); }
    }

    public static final class Snapshot {
        public final String name; public final int port; public final long packets; public final long lastAt; public final String detail;
        Snapshot(String name, int port, long packets, long lastAt, String detail) { this.name = name; this.port = port; this.packets = packets; this.lastAt = lastAt; this.detail = detail; }
    }
}
