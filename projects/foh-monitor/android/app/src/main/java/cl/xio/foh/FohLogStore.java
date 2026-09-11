package cl.xio.foh;

import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;

import java.util.ArrayList;
import java.util.Calendar;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/** Durable offline FOH evidence. The device that runs the listener owns this DB. */
public final class FohLogStore extends SQLiteOpenHelper {
    private static final String DB_NAME = "xio_foh.db";
    private static final int DB_VERSION = 2;

    public FohLogStore(Context context) {
        super(context.getApplicationContext(), DB_NAME, null, DB_VERSION);
    }

    @Override public void onCreate(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE foh_log (id INTEGER PRIMARY KEY AUTOINCREMENT, at INTEGER NOT NULL, protocol TEXT NOT NULL, detail TEXT NOT NULL, event_key TEXT NOT NULL DEFAULT '', tc_value TEXT)");
        db.execSQL("CREATE INDEX foh_log_at ON foh_log(at)");
        db.execSQL("CREATE INDEX foh_log_event ON foh_log(event_key)");
    }

    @Override public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) {
        if (oldVersion < 2) db.execSQL("ALTER TABLE foh_log ADD COLUMN tc_value TEXT");
    }

    public synchronized long append(long at, String protocol, String detail, String eventKey) {
        return append(at, protocol, detail, eventKey, null);
    }

    /** Persists the last usable timecode alongside the wall-clock timestamp.
     * This mirrors the Python JSONL contract: an event is correlated with the
     * TC that was current when it was written, without storing every TC frame.
     */
    public synchronized long append(long at, String protocol, String detail, String eventKey, String tcValue) {
        ContentValues values = new ContentValues();
        values.put("at", at); values.put("protocol", protocol); values.put("detail", detail);
        values.put("event_key", eventKey == null ? "" : eventKey);
        if (tcValue == null || tcValue.isEmpty()) values.putNull("tc_value"); else values.put("tc_value", tcValue);
        return getWritableDatabase().insert("foh_log", null, values);
    }

    public synchronized int count() {
        try (Cursor cursor = getReadableDatabase().rawQuery("SELECT COUNT(*) FROM foh_log", null)) {
            return cursor.moveToFirst() ? cursor.getInt(0) : 0;
        }
    }

    public synchronized List<String> recent(int limit) {
        List<String> rows = new ArrayList<>();
        try (Cursor cursor = getReadableDatabase().query("foh_log", new String[]{"at", "protocol", "detail", "event_key", "tc_value"}, null, null, null, null, "at DESC", Integer.toString(Math.max(1, limit)))) {
            while (cursor.moveToNext()) {
                String tc = cursor.isNull(4) ? "" : " · TC " + cursor.getString(4);
                rows.add(timestamp(cursor.getLong(0)) + " · " + cursor.getString(1) + " · " + cursor.getString(2) + tc + (cursor.getString(3).isEmpty() ? "" : " · " + cursor.getString(3)));
            }
        }
        return rows;
    }

    /** Structured evidence for the native UI and the embedded hotspot host. */
    public synchronized JSONArray eventsJson(int limit) throws JSONException {
        JSONArray rows = new JSONArray();
        try (Cursor cursor = getReadableDatabase().query("foh_log",
                new String[]{"id", "at", "protocol", "detail", "event_key", "tc_value"},
                null, null, null, null, "at DESC", Integer.toString(Math.max(1, Math.min(limit, 200))))) {
            while (cursor.moveToNext()) {
                rows.put(eventObject(cursor.getLong(0), cursor.getLong(1), cursor.getString(2), cursor.getString(3), cursor.getString(4), cursor.isNull(5) ? null : cursor.getString(5)));
            }
        }
        return rows;
    }

    public synchronized JSONObject summaryJson(String eventKey) throws JSONException {
        String selection = eventKey == null || eventKey.trim().isEmpty() ? null : "event_key = ?";
        String[] args = selection == null ? null : new String[]{eventKey.trim()};
        int total = 0;
        JSONObject byProtocol = new JSONObject();
        JSONObject byType = new JSONObject();
        JSONArray dates = new JSONArray();
        java.util.HashSet<String> dateSet = new java.util.HashSet<>();
        long first = 0, last = 0;
        try (Cursor cursor = getReadableDatabase().query("foh_log",
                new String[]{"at", "protocol"}, selection, args, null, null, "at ASC")) {
            while (cursor.moveToNext()) {
                long at = cursor.getLong(0); String protocol = cursor.getString(1);
                total++; if (first == 0) first = at; last = at;
                byProtocol.put(protocol, byProtocol.optInt(protocol, 0) + 1);
                byType.put(protocol, byType.optInt(protocol, 0) + 1);
                dateSet.add(timestamp(at).substring(0, 10));
            }
        }
        java.util.ArrayList<String> sortedDates = new java.util.ArrayList<>(dateSet); java.util.Collections.sort(sortedDates);
        for (String date : sortedDates) dates.put(date);
        JSONObject summary = new JSONObject().put("total", total).put("signalTypes", byType.length())
                .put("byType", byType).put("dates", dates)
                .put("firstTs", first == 0 ? JSONObject.NULL : timestamp(first))
                .put("lastTs", last == 0 ? JSONObject.NULL : timestamp(last));
        return new JSONObject().put("eventKey", eventKey == null ? "" : eventKey.trim())
                .put("total", total).put("byProtocol", byProtocol).put("summary", summary)
                .put("firstAt", first == 0 ? JSONObject.NULL : first)
                .put("lastAt", last == 0 ? JSONObject.NULL : last);
    }

    private static String timestamp(long at) {
        return new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.ROOT).format(new Date(at));
    }

    private static JSONObject eventObject(long id, long at, String protocol, String detail, String eventKey, String tcValue) throws JSONException {
        Object detailValue = detail;
        try { if (detail != null && detail.trim().startsWith("{")) detailValue = new JSONObject(detail); } catch (JSONException ignored) { }
        return new JSONObject().put("id", id).put("at", at).put("ts", timestamp(at))
                .put("protocol", protocol).put("tipo", protocol).put("detail", detail)
                .put("detalle", detailValue).put("eventKey", eventKey).put("fohEventKey", eventKey)
                .put("tc", tcValue == null ? JSONObject.NULL : tcValue).put("domain", "vj_foh");
    }

    /** Exact JSONL shape consumed by the existing FOH Registro HTML. */
    public synchronized String logNdjson(String query) throws JSONException {
        String date = queryDate(query);
        long start;
        try { start = new SimpleDateFormat("yyyyMMdd", Locale.ROOT).parse(date).getTime(); }
        catch (Exception error) { throw new JSONException("date debe ser YYYYMMDD"); }
        Calendar next = Calendar.getInstance(); next.setTimeInMillis(start); next.add(Calendar.DAY_OF_MONTH, 1);
        StringBuilder out = new StringBuilder();
        try (Cursor cursor = getReadableDatabase().query("foh_log",
                new String[]{"id", "at", "protocol", "detail", "event_key", "tc_value"},
                "at >= ? AND at < ?", new String[]{Long.toString(start), Long.toString(next.getTimeInMillis())},
                null, null, "at ASC")) {
            while (cursor.moveToNext()) out.append(eventObject(cursor.getLong(0), cursor.getLong(1), cursor.getString(2), cursor.getString(3), cursor.getString(4), cursor.isNull(5) ? null : cursor.getString(5))).append('\n');
        }
        return out.toString();
    }

    private static String queryDate(String query) {
        String date = new SimpleDateFormat("yyyyMMdd", Locale.ROOT).format(new Date());
        if (query != null) for (String part : query.split("&")) {
            String[] pair = part.split("=", 2);
            if (pair.length == 2 && "date".equals(pair[0])) date = pair[1];
        }
        return date;
    }

    public synchronized JSONObject logsJson() throws JSONException {
        JSONArray files = new JSONArray();
        return new JSONObject().put("dir", "app-private/xio_foh.db").put("files", files)
                .put("storage", "SQLite offline");
    }

    public synchronized JSONObject logJson(String query) throws JSONException {
        String date = "";
        if (query != null) for (String part : query.split("&")) {
            String[] pair = part.split("=", 2);
            if (pair.length == 2 && "date".equals(pair[0])) date = pair[1];
        }
        return new JSONObject().put("ok", true).put("date", date)
                .put("events", eventsJson(200)).put("storage", "SQLite offline");
    }
}
