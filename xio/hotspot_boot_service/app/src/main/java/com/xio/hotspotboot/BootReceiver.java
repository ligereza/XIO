package com.xio.hotspotboot;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.util.Log;

/**
 * Respaldo de arranque. El AccessibilityService ya auto-arranca al boot (onServiceConnected);
 * este receiver solo declara RECEIVE_BOOT_COMPLETED y deja rastro en el log. No lanza el
 * flujo por si mismo para no duplicar el reenable (el servicio es la unica fuente de verdad).
 */
public class BootReceiver extends BroadcastReceiver {
    private static final String TAG = "xioHotspotBoot";

    @Override
    public void onReceive(Context context, Intent intent) {
        if (intent == null || intent.getAction() == null) return;
        Log.i(TAG, "BOOT_COMPLETED recibido (" + intent.getAction() + "); el servicio se encarga");
    }
}
