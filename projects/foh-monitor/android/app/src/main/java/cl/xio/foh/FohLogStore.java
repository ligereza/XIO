package cl.xio.foh;

import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;

import java.util.ArrayList;
import java.util.List;

/** Durable offline FOH evidence. The device that runs the listener owns this DB. */
public final class FohLogStore extends SQLiteOpenHelper {
    private static final String DB_NAME = "xio_foh.db";
    private static final int DB_VERSION = 1;

    public FohLogStore(Context context) {
        super(context.getApplicationContext(), DB_NAME, null, DB_VERSION);
    }

    @Override public void onCreate(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE foh_log (id INTEGER PRIMARY KEY AUTOINCREMENT, at INTEGER NOT NULL, protocol TEXT NOT NULL, detail TEXT NOT NULL, event_key TEXT NOT NULL DEFAULT '')");
        db.execSQL("CREATE INDEX foh_log_at ON foh_log(at)");
        db.execSQL("CREATE INDEX foh_log_event ON foh_log(event_key)");
    }

    @Override public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) { }

    public synchronized long append(long at, String protocol, String detail, String eventKey) {
        ContentValues values = new ContentValues();
        values.put("at", at); values.put("protocol", protocol); values.put("detail", detail);
        values.put("event_key", eventKey == null ? "" : eventKey);
        return getWritableDatabase().insert("foh_log", null, values);
    }

    public synchronized int count() {
        try (Cursor cursor = getReadableDatabase().rawQuery("SELECT COUNT(*) FROM foh_log", null)) {
            return cursor.moveToFirst() ? cursor.getInt(0) : 0;
        }
    }

    public synchronized List<String> recent(int limit) {
        List<String> rows = new ArrayList<>();
        try (Cursor cursor = getReadableDatabase().query("foh_log", new String[]{"at", "protocol", "detail", "event_key"}, null, null, null, null, "at DESC", Integer.toString(Math.max(1, limit)))) {
            while (cursor.moveToNext()) {
                rows.add(cursor.getLong(0) + " · " + cursor.getString(1) + " · " + cursor.getString(2) + (cursor.getString(3).isEmpty() ? "" : " · " + cursor.getString(3)));
            }
        }
        return rows;
    }
}
