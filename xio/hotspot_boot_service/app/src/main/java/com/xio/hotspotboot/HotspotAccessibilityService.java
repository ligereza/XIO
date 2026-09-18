package com.xio.hotspotboot;

import android.accessibilityservice.AccessibilityService;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Rect;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.util.Log;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;

import java.net.Inet4Address;
import java.net.NetworkInterface;
import java.text.Normalizer;
import java.util.ArrayList;
import java.util.Enumeration;
import java.util.List;
import java.util.Locale;

/**
 * Boot-triggered hotspot recovery without root or Shizuku.
 *
 * Safety contract:
 * - boot is the only automatic trigger;
 * - if wlan1 (or another known SoftAP interface) already has an IPv4 address,
 *   Settings is never opened;
 * - the service acts at most once per Android boot;
 * - only a semantically labelled, checkable Settings node may be clicked;
 * - there is no first-checkbox fallback and no fixed-coordinate tap;
 * - after a click, the network interface must confirm recovery, otherwise the
 *   service aborts without retrying blindly.
 */
public class HotspotAccessibilityService extends AccessibilityService {

    private static final String TAG = "xioHotspotBoot";
    private static final String PREFS = "recovery_state";
    private static final String LAST_BOOT = "last_boot_count";
    private static final long BOOT_SETTLE_MS = 8000L;
    private static final long FIND_TIMEOUT_MS = 20000L;
    private static final long VERIFY_INTERVAL_MS = 3000L;
    private static final int VERIFY_ATTEMPTS = 8;

    private static final String[] TOGGLE_HINTS = {
        "portable hotspot", "punto de acceso portatil", "hotspot",
        "punto de acceso", "zona wi-fi portatil", "compartir internet",
        "anclaje", "tethering"
    };

    private boolean mDone = false;
    private boolean mLaunchedSettings = false;
    private boolean mActionInFlight = false;
    private int mVerifyAttempts = 0;
    private final Handler mHandler = new Handler(Looper.getMainLooper());

    private static final class ToggleCandidate {
        final AccessibilityNodeInfo node;
        final int subtreeSize;

        ToggleCandidate(AccessibilityNodeInfo node, int subtreeSize) {
            this.node = node;
            this.subtreeSize = subtreeSize;
        }
    }

    @Override
    protected void onServiceConnected() {
        super.onServiceConnected();
        if (hasHotspotIpv4()) {
            mDone = true;
            Log.i(TAG, "hotspot already UP; no Settings launch and no tap");
            return;
        }
        if (!claimBootAttempt()) {
            mDone = true;
            Log.i(TAG, "recovery already evaluated for this boot; staying passive");
            return;
        }
        Log.i(TAG, "hotspot DOWN at service start; scheduling guarded boot recovery");
        mHandler.postDelayed(this::openTetherSettings, BOOT_SETTLE_MS);
        mHandler.postDelayed(() -> abort("Settings did not expose a confirmed switch"),
                BOOT_SETTLE_MS + FIND_TIMEOUT_MS);
    }

    private boolean claimBootAttempt() {
        int bootCount = Settings.Global.getInt(getContentResolver(), Settings.Global.BOOT_COUNT, -1);
        String marker = bootCount >= 0 ? Integer.toString(bootCount) : "unknown";
        SharedPreferences prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        String previous = prefs.getString(LAST_BOOT, "");
        if (marker.equals(previous) && !"unknown".equals(marker)) return false;
        prefs.edit().putString(LAST_BOOT, marker).apply();
        return true;
    }

    private void openTetherSettings() {
        if (mDone || hasHotspotIpv4()) {
            if (!mDone) {
                mDone = true;
                Log.i(TAG, "hotspot came UP before UI; no tap");
            }
            return;
        }
        try {
            Intent intent = new Intent("android.settings.TETHER_SETTINGS");
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(intent);
            mLaunchedSettings = true;
            Log.i(TAG, "TETHER_SETTINGS opened; waiting for semantic switch");
        } catch (Exception e) {
            abort("could not open TETHER_SETTINGS: " + e.getMessage());
        }
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        if (mDone || !mLaunchedSettings || mActionInFlight || event == null) return;
        if (event.getEventType() != AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED
                && event.getEventType() != AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED) {
            return;
        }
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null || !isSettingsWindow(root)) return;

        AccessibilityNodeInfo toggle = findToggle(root);
        if (toggle == null) return;

        Log.i(TAG, "semantic hotspot switch found, checked=" + toggle.isChecked());
        if (toggle.isChecked()) {
            abort("semantic switch is already ON; no tap");
            return;
        }
        if (!toggle.isEnabled()) {
            abort("semantic switch is disabled; no tap");
            return;
        }
        if (!clickNodeOrAncestor(toggle)) {
            abort("semantic switch click failed; no coordinate fallback");
            return;
        }
        mActionInFlight = true;
        mVerifyAttempts = 0;
        Log.i(TAG, "semantic switch clicked once; verifying wlan interface");
        mHandler.postDelayed(this::verifyHotspotAfterClick, VERIFY_INTERVAL_MS);
    }

    private boolean isSettingsWindow(AccessibilityNodeInfo root) {
        CharSequence packageName = root.getPackageName();
        return packageName != null && "com.android.settings".contentEquals(packageName);
    }

    private AccessibilityNodeInfo findToggle(AccessibilityNodeInfo root) {
        List<ToggleCandidate> candidates = new ArrayList<>();
        collectToggleCandidates(root, candidates);
        if (candidates.isEmpty()) return null;

        int smallest = Integer.MAX_VALUE;
        for (ToggleCandidate candidate : candidates) {
            smallest = Math.min(smallest, candidate.subtreeSize);
        }
        AccessibilityNodeInfo selected = null;
        int selectedCount = 0;
        for (ToggleCandidate candidate : candidates) {
            if (candidate.subtreeSize != smallest) continue;
            if (selected != null && sameBounds(selected, candidate.node)) continue;
            selected = candidate.node;
            selectedCount++;
        }
        // Deliberately no root-wide checkbox fallback: ambiguity means abort.
        return selectedCount == 1 ? selected : null;
    }

    private void collectToggleCandidates(AccessibilityNodeInfo node,
                                         List<ToggleCandidate> candidates) {
        if (node == null) return;
        if (containsAnyHint(node)) {
            List<AccessibilityNodeInfo> checkables = new ArrayList<>();
            collectCheckableNodes(node, checkables);
            if (checkables.size() == 1 && !containsSameBounds(candidates, checkables.get(0))) {
                candidates.add(new ToggleCandidate(checkables.get(0), subtreeSize(node)));
            }
        }
        for (int i = 0; i < node.getChildCount(); i++) {
            collectToggleCandidates(node.getChild(i), candidates);
        }
    }

    private boolean containsAnyHint(AccessibilityNodeInfo node) {
        String text = nodeText(node);
        for (String hint : TOGGLE_HINTS) {
            if (text.contains(normalize(hint))) return true;
        }
        for (int i = 0; i < node.getChildCount(); i++) {
            if (containsAnyHint(node.getChild(i))) return true;
        }
        return false;
    }

    private void collectCheckableNodes(AccessibilityNodeInfo node,
                                       List<AccessibilityNodeInfo> result) {
        if (node == null) return;
        if (node.isCheckable() && node.isEnabled()) result.add(node);
        for (int i = 0; i < node.getChildCount(); i++) {
            collectCheckableNodes(node.getChild(i), result);
        }
    }

    private int subtreeSize(AccessibilityNodeInfo node) {
        if (node == null) return 0;
        int size = 1;
        for (int i = 0; i < node.getChildCount(); i++) {
            size += subtreeSize(node.getChild(i));
        }
        return size;
    }

    private boolean containsSameBounds(List<ToggleCandidate> candidates,
                                       AccessibilityNodeInfo node) {
        for (ToggleCandidate candidate : candidates) {
            if (sameBounds(candidate.node, node)) return true;
        }
        return false;
    }

    private boolean sameBounds(AccessibilityNodeInfo first, AccessibilityNodeInfo second) {
        Rect a = new Rect();
        Rect b = new Rect();
        first.getBoundsInScreen(a);
        second.getBoundsInScreen(b);
        return a.equals(b);
    }

    private String nodeText(AccessibilityNodeInfo node) {
        String text = node.getText() == null ? "" : node.getText().toString();
        String description = node.getContentDescription() == null
                ? "" : node.getContentDescription().toString();
        String resource = node.getViewIdResourceName() == null
                ? "" : node.getViewIdResourceName();
        return normalize(text + " " + description + " " + resource);
    }

    private String normalize(String value) {
        String folded = Normalizer.normalize(value == null ? "" : value, Normalizer.Form.NFKD);
        folded = folded.replaceAll("\\p{M}", "");
        return folded.toLowerCase(Locale.ROOT).replace('-', ' ').replace('_', ' ').trim();
    }

    private boolean clickNodeOrAncestor(AccessibilityNodeInfo node) {
        AccessibilityNodeInfo current = node;
        for (int depth = 0; depth < 5 && current != null; depth++) {
            if (current.isClickable() && current.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
                return true;
            }
            current = current.getParent();
        }
        return node.performAction(AccessibilityNodeInfo.ACTION_CLICK);
    }

    private void verifyHotspotAfterClick() {
        if (mDone || !mActionInFlight) return;
        if (hasHotspotIpv4()) {
            mActionInFlight = false;
            finishOnce("hotspot interface confirmed UP");
            return;
        }
        if (mVerifyAttempts++ < VERIFY_ATTEMPTS) {
            mHandler.postDelayed(this::verifyHotspotAfterClick, VERIFY_INTERVAL_MS);
            return;
        }
        abort("switch click did not produce a hotspot IPv4");
    }

    private boolean hasHotspotIpv4() {
        try {
            Enumeration<NetworkInterface> interfaces = NetworkInterface.getNetworkInterfaces();
            while (interfaces != null && interfaces.hasMoreElements()) {
                NetworkInterface network = interfaces.nextElement();
                String name = network.getName();
                if (!isHotspotInterface(name) || !network.isUp()) continue;
                Enumeration<java.net.InetAddress> addresses = network.getInetAddresses();
                while (addresses.hasMoreElements()) {
                    java.net.InetAddress address = addresses.nextElement();
                    if (address instanceof Inet4Address
                            && !address.isLoopbackAddress()
                            && !address.isLinkLocalAddress()) {
                        return true;
                    }
                }
            }
        } catch (Exception e) {
            Log.w(TAG, "could not inspect hotspot interfaces: " + e.getMessage());
        }
        return false;
    }

    private boolean isHotspotInterface(String name) {
        return "wlan1".equals(name)
                || name.startsWith("ap_br_")
                || name.startsWith("softap");
    }

    private void abort(String reason) {
        if (mDone) return;
        mActionInFlight = false;
        mDone = true;
        mHandler.removeCallbacksAndMessages(null);
        Log.w(TAG, "recovery aborted: " + reason);
        mHandler.postDelayed(() -> performGlobalAction(GLOBAL_ACTION_HOME), 500L);
    }

    private void finishOnce(String reason) {
        if (mDone) return;
        mDone = true;
        mHandler.removeCallbacksAndMessages(null);
        Log.i(TAG, "recovery finished: " + reason);
        mHandler.postDelayed(() -> performGlobalAction(GLOBAL_ACTION_HOME), 500L);
    }

    @Override
    public void onInterrupt() {
        mHandler.removeCallbacksAndMessages(null);
    }
}
