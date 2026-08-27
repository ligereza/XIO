package com.xio.hotspotboot;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.content.Intent;
import android.graphics.Path;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;

import java.util.List;

/**
 * Reenciende el hotspot al boot, SIN root y SIN Shizuku, tocando la UI de tethering.
 *
 * Es el unico mecanismo host-free que sobrevive un reboot: un AccessibilityService
 * habilitado arranca solo al bootear (onServiceConnected), puede abrir Settings y tocar
 * el toggle. Replica la logica validada de hotspot_watch.sh:
 *   - DOBLE COMPUERTA: solo hace click si el switch esta OFF. Nunca apaga uno sano.
 *   - Busca el nodo por texto (multi-idioma); si no, cae a un gesto por coordenada.
 * Corre UNA vez por boot (mDone).
 */
public class HotspotAccessibilityService extends AccessibilityService {

    private static final String TAG = "xioHotspotBoot";

    // Espera a que el sistema asiente tras el boot antes de abrir Settings. Corto: el
    // flujo es event-driven (onAccessibilityEvent reintenta cuando aparece la ventana),
    // asi que un boot lento no lo rompe; solo acelera el reenable.
    private static final long BOOT_SETTLE_MS = 8000L;

    // Textos posibles del switch/fila del hotspot (agregar variantes segun idioma/ROM).
    private static final String[] TOGGLE_HINTS = {
        "portable hotspot", "punto de acceso portatil", "punto de acceso portátil",
        "hotspot", "punto de acceso", "zona wi-fi portatil", "zona wi-fi portátil",
        "compartir internet", "anclaje", "tethering"
    };

    // Fallback por coordenada (UI HyperOS del Mi 11 Lite 5G NE; = tap 540,583 del
    // hotspot_watch.sh). Solo se usa si el nodo por texto no aparece. AJUSTAR on-device.
    private static final int FALLBACK_TAP_X = 540;
    private static final int FALLBACK_TAP_Y = 583;

    private boolean mDone = false;
    private boolean mLaunchedSettings = false;
    private final Handler mHandler = new Handler(Looper.getMainLooper());

    @Override
    protected void onServiceConnected() {
        super.onServiceConnected();
        Log.i(TAG, "service connected -> programando reenable de hotspot en " + BOOT_SETTLE_MS + "ms");
        // Un solo intento por vida del servicio (que en la practica = una vez por boot).
        mHandler.postDelayed(this::openTetherSettings, BOOT_SETTLE_MS);
    }

    private void openTetherSettings() {
        if (mDone) return;
        try {
            Intent i = new Intent("android.settings.TETHER_SETTINGS");
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(i);
            mLaunchedSettings = true;
            Log.i(TAG, "TETHER_SETTINGS abierto; esperando la ventana para tocar el toggle");
        } catch (Exception e) {
            Log.e(TAG, "no pude abrir TETHER_SETTINGS: " + e.getMessage());
        }
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        if (mDone || !mLaunchedSettings) return;
        if (event == null) return;
        if (event.getEventType() != AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED
                && event.getEventType() != AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED) {
            return;
        }
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) return;

        AccessibilityNodeInfo toggle = findToggle(root);
        if (toggle != null) {
            boolean on = toggle.isChecked();
            Log.i(TAG, "toggle encontrado, checked=" + on);
            if (!on) {
                // COMPUERTA: solo si esta OFF.
                boolean clicked = clickNodeOrAncestor(toggle);
                Log.i(TAG, clicked ? "click en el toggle (OFF->ON)" : "click fallo -> fallback gesto");
                if (!clicked) tapFallback();
            } else {
                Log.i(TAG, "hotspot ya ON -> no se toca (compuerta de seguridad)");
            }
            finishOnce();
        }
        // Si no aparecio el toggle todavia, esperamos el proximo evento de ventana.
    }

    /** Busca un Switch/checkable cuyo texto o el de su fila matchee un hint del hotspot. */
    private AccessibilityNodeInfo findToggle(AccessibilityNodeInfo root) {
        for (String hint : TOGGLE_HINTS) {
            List<AccessibilityNodeInfo> hits = root.findAccessibilityNodeInfosByText(hint);
            if (hits == null) continue;
            for (AccessibilityNodeInfo n : hits) {
                AccessibilityNodeInfo sw = firstCheckable(n);
                if (sw != null) return sw;
            }
        }
        // Ultimo recurso: el primer nodo checkable de la pantalla (equivale al "primer
        // android:id/checkbox" que usa hotspot_watch.sh).
        return firstCheckable(root);
    }

    /** Sube al ancestro y baja buscando el primer nodo checkable (el switch). */
    private AccessibilityNodeInfo firstCheckable(AccessibilityNodeInfo node) {
        if (node == null) return null;
        AccessibilityNodeInfo scope = node;
        for (int up = 0; up < 4 && scope.getParent() != null; up++) scope = scope.getParent();
        return searchCheckable(scope);
    }

    private AccessibilityNodeInfo searchCheckable(AccessibilityNodeInfo node) {
        if (node == null) return null;
        if (node.isCheckable()) return node;
        for (int i = 0; i < node.getChildCount(); i++) {
            AccessibilityNodeInfo r = searchCheckable(node.getChild(i));
            if (r != null) return r;
        }
        return null;
    }

    private boolean clickNodeOrAncestor(AccessibilityNodeInfo node) {
        AccessibilityNodeInfo n = node;
        for (int up = 0; up < 5 && n != null; up++) {
            if (n.isClickable() && n.performAction(AccessibilityNodeInfo.ACTION_CLICK)) return true;
            n = n.getParent();
        }
        // Intento directo aunque no se marque clickable.
        return node.performAction(AccessibilityNodeInfo.ACTION_CLICK);
    }

    /** Gesto por coordenada (fallback). Requiere canPerformGestures en el config. */
    private void tapFallback() {
        Path p = new Path();
        p.moveTo(FALLBACK_TAP_X, FALLBACK_TAP_Y);
        GestureDescription.Builder b = new GestureDescription.Builder();
        b.addStroke(new GestureDescription.StrokeDescription(p, 0, 60));
        dispatchGesture(b.build(), null, null);
    }

    private void finishOnce() {
        mDone = true;
        mHandler.postDelayed(() -> performGlobalAction(GLOBAL_ACTION_HOME), 2500);
        Log.i(TAG, "listo -> HOME");
    }

    @Override
    public void onInterrupt() { }
}
