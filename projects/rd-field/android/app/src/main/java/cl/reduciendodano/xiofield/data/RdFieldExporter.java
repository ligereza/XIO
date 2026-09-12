package cl.reduciendodano.xiofield.data;

import android.database.sqlite.SQLiteDatabase;
import android.content.Context;

import java.io.BufferedWriter;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.OutputStreamWriter;
import java.nio.charset.StandardCharsets;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

import cl.reduciendodano.xiofield.core.SampleSession;

/** Exports one auditable sample bundle without flattening away its evidence. */
public final class RdFieldExporter {
    private RdFieldExporter() {}

    public static File export(Context context, SampleSession session) throws IOException {
        File folder = new File(context.getCacheDir(), "rd-exports");
        if (!folder.exists() && !folder.mkdirs()) throw new IOException("No se pudo crear la carpeta de exportación");
        File archive = new File(folder, session.code + "-" + System.currentTimeMillis() + ".zip");
        RdFieldDb database = new RdFieldDb(context);
        RdFieldDb.EventRow event = database.findEvent(session.eventId);
        database.close();
        try (ZipOutputStream zip = new ZipOutputStream(new FileOutputStream(archive))) {
            putText(zip, "evento.json", eventJson(event, session.eventId));
            putText(zip, "registro.json", json(session));
            putText(zip, "capturas.csv", capturesCsv(session));
            putText(zip, "pruebas.csv", testsCsv(session));
            putText(zip, "ejemplos_aprendizaje.csv", trainingCsv(session));
            for (SampleSession.Capture capture : session.captures) {
                File photo = new File(capture.path);
                if (photo.isFile()) putFile(zip, "fotos/" + capture.id + ".jpg", photo);
                File silhouette = new File(capture.silhouettePath);
                if (silhouette.isFile()) putFile(zip, "siluetas/" + capture.id + ".svg", silhouette);
                File silhouettePreview = new File(capture.silhouettePreviewPath);
                if (silhouettePreview.isFile()) putFile(zip, "siluetas/" + capture.id + ".png", silhouettePreview);
                File relief = new File(capture.reliefPath);
                if (relief.isFile()) putFile(zip, "relieves/" + capture.id + ".svg", relief);
            }
        }
        return archive;
    }

    /**
     * Creates a recoverable pre-update backup of the complete RD field store.
     * It intentionally contains only the RD SQLite projection and RD evidence;
     * FOH/ISKVW state lives in its own application and is never copied here.
     */
    public static File exportLocalBackup(Context context) throws IOException {
        File folder = new File(context.getCacheDir(), "rd-exports");
        if (!folder.exists() && !folder.mkdirs()) throw new IOException("No se pudo crear la carpeta de exportación");
        File archive = new File(folder, "xio-rd-backup-" + System.currentTimeMillis() + ".zip");
        RdFieldDb database = new RdFieldDb(context);
        SQLiteDatabase local = database.getWritableDatabase();
        android.database.Cursor checkpoint = local.rawQuery("PRAGMA wal_checkpoint(FULL)", null);
        checkpoint.close();
        database.close();
        File dbFile = context.getDatabasePath("rd_field_local.db");
        File evidenceRoot = new File(context.getFilesDir(), "evidence");
        try (ZipOutputStream zip = new ZipOutputStream(new FileOutputStream(archive))) {
            putText(zip, "backup-manifest.json", "{\n"
                    + "  \"schema\":\"xio-rd-local-backup-v1\",\n"
                    + "  \"createdAt\":" + System.currentTimeMillis() + ",\n"
                    + "  \"domains\":[\"rd\"],\n"
                    + "  \"database\":\"rd_field_local.db\",\n"
                    + "  \"evidenceRoot\":\"evidence/\"\n"
                    + "}\n");
            if (!dbFile.isFile()) throw new IOException("No existe la base local RD");
            putFile(zip, "rd_field_local.db", dbFile);
            addTree(zip, evidenceRoot, evidenceRoot);
        }
        return archive;
    }

    private static void addTree(ZipOutputStream zip, File root, File current) throws IOException {
        if (!current.isDirectory()) return;
        File[] files = current.listFiles();
        if (files == null) return;
        for (File file : files) {
            if (file.isDirectory()) addTree(zip, root, file);
            else if (file.isFile()) {
                String relative = root.toURI().relativize(file.toURI()).getPath();
                if (!relative.isEmpty()) putFile(zip, "evidence/" + relative, file);
            }
        }
    }

    private static String eventJson(RdFieldDb.EventRow event, String fallbackId) {
        if (event == null) return "{\n  \"schema\":\"xio-rd-event-v0.1\",\n  \"eventId\":\"" + escape(fallbackId) + "\"\n}\n";
        StringBuilder out = new StringBuilder();
        out.append("{\n  \"schema\":\"xio-rd-event-v0.1\",\n");
        out.append("  \"eventId\":\"").append(escape(event.id)).append("\",\n");
        out.append("  \"eventName\":\"").append(escape(event.name)).append("\",\n");
        out.append("  \"venue\":\"").append(escape(event.venue)).append("\",\n");
        out.append("  \"producer\":\"").append(escape(event.producer)).append("\",\n");
        out.append("  \"startDate\":\"").append(escape(event.startDate)).append("\",\n");
        out.append("  \"endDate\":\"").append(escape(event.endDate)).append("\",\n");
        out.append("  \"djs\":").append(jsonOrDefault(event.djsJson, "[]")).append(",\n");
        out.append("  \"triangulation\":").append(jsonOrDefault(event.triangulationJson, "{}")).append(",\n");
        out.append("  \"flyerRef\":\"").append(escape(event.flyerRef)).append("\",\n");
        out.append("  \"flyerSha256\":\"").append(escape(event.flyerSha256)).append("\",\n");
        out.append("  \"syncStatus\":\"").append(escape(event.syncStatus)).append("\",\n");
        out.append("  \"reviewStatus\":\"").append(escape(event.reviewStatus)).append("\"\n}\n");
        return out.toString();
    }

    private static String jsonOrDefault(String value, String fallback) {
        if (value == null || value.trim().isEmpty()) return fallback;
        String clean = value.trim();
        return (clean.startsWith("[") && clean.endsWith("]")) || (clean.startsWith("{") && clean.endsWith("}")) ? clean : fallback;
    }

    private static void putText(ZipOutputStream zip, String name, String value) throws IOException {
        zip.putNextEntry(new ZipEntry(name));
        BufferedWriter writer = new BufferedWriter(new OutputStreamWriter(zip, StandardCharsets.UTF_8));
        writer.write(value);
        writer.flush();
        zip.closeEntry();
    }

    private static void putFile(ZipOutputStream zip, String name, File file) throws IOException {
        zip.putNextEntry(new ZipEntry(name));
        try (FileInputStream input = new FileInputStream(file)) {
            byte[] buffer = new byte[8192]; int count;
            while ((count = input.read(buffer)) >= 0) if (count > 0) zip.write(buffer, 0, count);
        }
        zip.closeEntry();
    }

    private static String json(SampleSession sample) {
        StringBuilder out = new StringBuilder();
        out.append("{\n  \"schema\":\"xio-rd-sample-v0.2\",\n");
        out.append("  \"sampleId\":\"").append(escape(sample.id)).append("\",\n");
        out.append("  \"eventId\":\"").append(escape(sample.eventId)).append("\",\n");
        out.append("  \"sampleCode\":\"").append(escape(sample.code)).append("\",\n");
        out.append("  \"createdAt\":").append(sample.createdAt).append(",\n  \"status\":\"").append(escape(sample.status)).append("\",\n");
        out.append("  \"declaredSubstance\":\"").append(escape(sample.declaredSubstance)).append("\",\n");
        out.append("  \"presentation\":\"").append(escape(sample.presentation)).append("\",\n");
        out.append("  \"observedColor\":\"").append(escape(sample.observedColor)).append("\",\n");
        out.append("  \"captures\":[");
        for (int i = 0; i < sample.captures.size(); i++) {
            SampleSession.Capture capture = sample.captures.get(i);
            if (i > 0) out.append(",");
            out.append("{\"id\":\"").append(escape(capture.id)).append("\",\"capturedAt\":").append(capture.capturedAt).append(",\"sha256\":\"").append(escape(capture.sha256)).append("\",\"file\":\"fotos/").append(escape(capture.id)).append(".jpg\",\"silhouetteFile\":\"").append(escape(silhouetteFile(capture))).append("\",\"silhouettePreviewFile\":\"").append(escape(silhouettePreviewFile(capture))).append("\",\"reliefFile\":\"").append(escape(reliefFile(capture))).append("\",\"visual\":\"").append(escape(capture.features.compactDescription())).append("\",\"geometry\":{\"confidence\":").append(capture.features.silhouetteConfidence).append(",\"circularity\":").append(capture.features.circularity).append(",\"solidity\":").append(capture.features.solidity).append(",\"symmetry\":").append(capture.features.symmetry).append(",\"contourPoints\":").append(capture.features.contourPointCount).append(",\"signature\":\"").append(escape(capture.features.geometrySignature)).append("\"},\"relief\":{\"confidence\":").append(capture.features.reliefConfidence).append(",\"signature\":\"").append(escape(capture.features.reliefSignature)).append("\"}}");
        }
        out.append("],\n  \"tests\":[");
        for (int i = 0; i < sample.tests.size(); i++) {
            SampleSession.TestSession test = sample.tests.get(i);
            if (i > 0) out.append(",");
            out.append("{\"ordinal\":").append(test.ordinal).append(",\"method\":\"").append(escape(test.method)).append("\",\"reagent\":\"").append(escape(test.reagent)).append("\",\"startedAt\":").append(test.startedAt).append(",\"endedAt\":").append(test.endedAt).append(",\"elapsedMs\":").append(test.elapsedMs).append(",\"status\":\"").append(escape(test.status)).append("\",\"operatorResult\":\"").append(escape(test.operatorResult)).append("\",\"interpretation\":\"").append(escape(test.interpretation)).append("\"}");
        }
        out.append("],\n  \"corrections\":[");
        for (int i = 0; i < sample.corrections.size(); i++) {
            SampleSession.Correction correction = sample.corrections.get(i);
            if (i > 0) out.append(",");
            out.append("{\"captureId\":\"").append(escape(correction.captureId)).append("\",\"field\":\"").append(escape(correction.field)).append("\",\"proposed\":\"").append(escape(correction.proposedValue)).append("\",\"corrected\":\"").append(escape(correction.correctedValue)).append("\",\"reviewedAt\":").append(correction.reviewedAt).append("}");
        }
        out.append("]\n}\n");
        return out.toString();
    }

    private static String capturesCsv(SampleSession sample) {
        StringBuilder out = new StringBuilder("evento,muestra,captura,fecha_epoch,vista,color,silueta,marca_candidata,proporcion,textura,confianza_silueta,circularidad,solidez,simetria,puntos_contorno,firma_geometrica,confianza_relieve,firma_relieve,archivo,silueta_svg,silueta_preview,relieve_svg\n");
        for (SampleSession.Capture capture : sample.captures) {
            out.append(csv(sample.eventId)).append(',').append(csv(sample.code)).append(',').append(csv(capture.id)).append(',').append(capture.capturedAt).append(',').append(csv(capture.kind)).append(',').append(csv(capture.features.colorLabel)).append(',').append(csv(capture.features.silhouetteLabel)).append(',').append(csv(capture.features.markingCandidate)).append(',').append(capture.features.aspectRatio).append(',').append(capture.features.textureScore).append(',').append(capture.features.silhouetteConfidence).append(',').append(capture.features.circularity).append(',').append(capture.features.solidity).append(',').append(capture.features.symmetry).append(',').append(capture.features.contourPointCount).append(',').append(csv(capture.features.geometrySignature)).append(',').append(capture.features.reliefConfidence).append(',').append(csv(capture.features.reliefSignature)).append(',').append(csv("fotos/" + capture.id + ".jpg")).append(',').append(csv(silhouetteFile(capture))).append(',').append(csv(silhouettePreviewFile(capture))).append(',').append(csv(reliefFile(capture))).append('\n');
        }
        return out.toString();
    }

    private static String testsCsv(SampleSession sample) {
        StringBuilder out = new StringBuilder("evento,muestra,ordinal,metodo,reactivo,inicio_epoch,fin_epoch,tiempo_ms,estado,result_operador,interpretacion\n");
        for (SampleSession.TestSession test : sample.tests) out.append(csv(sample.eventId)).append(',').append(csv(sample.code)).append(',').append(test.ordinal).append(',').append(csv(test.method)).append(',').append(csv(test.reagent)).append(',').append(test.startedAt).append(',').append(test.endedAt).append(',').append(test.elapsedMs).append(',').append(csv(test.status)).append(',').append(csv(test.operatorResult)).append(',').append(csv(test.interpretation)).append('\n');
        return out.toString();
    }

    private static String trainingCsv(SampleSession sample) {
        StringBuilder out = new StringBuilder("evento,muestra,captura,etiqueta,modelo,archivo,silueta_svg,relieve_svg\n");
        for (SampleSession.Correction correction : sample.corrections) out.append(csv(sample.eventId)).append(',').append(csv(sample.code)).append(',').append(csv(correction.captureId)).append(',').append(csv(correction.correctedValue)).append(',').append(csv(correction.modelVersion)).append(',').append(csv("fotos/" + correction.captureId + ".jpg")).append(',').append(csv("siluetas/" + correction.captureId + ".svg")).append(',').append(csv("relieves/" + correction.captureId + ".svg")).append('\n');
        return out.toString();
    }

    private static String silhouetteFile(SampleSession.Capture capture) {
        return capture.silhouettePath != null && new File(capture.silhouettePath).isFile() ? "siluetas/" + capture.id + ".svg" : "";
    }

    private static String reliefFile(SampleSession.Capture capture) {
        return capture.reliefPath != null && new File(capture.reliefPath).isFile() ? "relieves/" + capture.id + ".svg" : "";
    }

    private static String silhouettePreviewFile(SampleSession.Capture capture) {
        return capture.silhouettePreviewPath != null && new File(capture.silhouettePreviewPath).isFile() ? "siluetas/" + capture.id + ".png" : "";
    }

    private static String csv(String value) { if (value == null) return "\"\""; return "\"" + value.replace("\"", "\"\"").replace("\r", " ").replace("\n", " ") + "\""; }

    private static String escape(String value) {
        if (value == null) return "";
        return value.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n").replace("\r", "\\r");
    }
}
