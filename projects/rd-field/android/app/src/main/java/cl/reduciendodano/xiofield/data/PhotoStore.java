package cl.reduciendodano.xiofield.data;

import android.content.Context;
import android.graphics.Bitmap;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;

/** Stores evidence inside app-private storage and returns a stable hash for exports. */
public final class PhotoStore {
    private final Context context;

    public PhotoStore(Context context) { this.context = context.getApplicationContext(); }

    public File prepareFile(String sampleId, String captureId) throws IOException {
        File directory = new File(context.getFilesDir(), "evidence" + File.separator + sampleId);
        if (!directory.exists() && !directory.mkdirs()) throw new IOException("cannot create evidence directory");
        return new File(directory, captureId + ".jpg");
    }

    public StoredPhoto store(String sampleId, String captureId, Bitmap bitmap) throws IOException {
        File file = prepareFile(sampleId, captureId);
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        if (!bitmap.compress(Bitmap.CompressFormat.JPEG, 94, bytes)) throw new IOException("cannot encode image");
        byte[] payload = bytes.toByteArray();
        try (FileOutputStream output = new FileOutputStream(file)) { output.write(payload); }
        return new StoredPhoto(file, sha256(payload), bitmap.getWidth(), bitmap.getHeight());
    }

    public File storeSilhouette(String sampleId, String captureId, String svg) throws IOException {
        File file = new File(prepareFile(sampleId, captureId).getParentFile(), captureId + ".svg");
        try (FileOutputStream output = new FileOutputStream(file)) {
            output.write(svg.getBytes(StandardCharsets.UTF_8));
        }
        return file;
    }

    public File storeRelief(String sampleId, String captureId, String svg) throws IOException {
        File file = new File(prepareFile(sampleId, captureId).getParentFile(), captureId + ".relief.svg");
        try (FileOutputStream output = new FileOutputStream(file)) {
            output.write(svg.getBytes(StandardCharsets.UTF_8));
        }
        return file;
    }

    public File storeSilhouettePreview(String sampleId, String captureId, Bitmap bitmap) throws IOException {
        File file = new File(prepareFile(sampleId, captureId).getParentFile(), captureId + ".silhouette.png");
        try (FileOutputStream output = new FileOutputStream(file)) {
            if (!bitmap.compress(Bitmap.CompressFormat.PNG, 100, output)) throw new IOException("cannot encode silhouette preview");
        }
        return file;
    }

    public static final class StoredPhoto {
        public final File file;
        public final String sha256;
        public final int width;
        public final int height;

        public StoredPhoto(File file, String sha256, int width, int height) { this.file = file; this.sha256 = sha256; this.width = width; this.height = height; }
    }

    private static String sha256(byte[] data) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(data);
            StringBuilder builder = new StringBuilder();
            for (byte item : digest) builder.append(String.format("%02x", item));
            return builder.toString();
        } catch (NoSuchAlgorithmException error) { return "hash-unavailable"; }
    }
}
