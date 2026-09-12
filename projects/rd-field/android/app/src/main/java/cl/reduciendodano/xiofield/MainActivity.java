package cl.reduciendodano.xiofield;

import android.Manifest;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.LinearGradient;
import android.graphics.Paint;
import android.graphics.PorterDuff;
import android.graphics.PorterDuffColorFilter;
import android.graphics.Typeface;
import android.graphics.Shader;
import android.net.Uri;
import android.os.Bundle;
import android.provider.MediaStore;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Space;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import androidx.annotation.Nullable;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;
import androidx.core.content.FileProvider;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.List;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Locale;
import java.util.UUID;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;

import cl.reduciendodano.xiofield.core.SampleSession;
import cl.reduciendodano.xiofield.core.SampleSessionEngine;
import cl.reduciendodano.xiofield.core.VisualFeatures;
import cl.reduciendodano.xiofield.data.PhotoStore;
import cl.reduciendodano.xiofield.data.FlujoGateway;
import cl.reduciendodano.xiofield.data.RdFieldDb;
import cl.reduciendodano.xiofield.data.RdFieldExporter;
import cl.reduciendodano.xiofield.visual.BatchPatternDetector;
import cl.reduciendodano.xiofield.visual.VisualFeatureExtractor;
import cl.reduciendodano.xiofield.visual.VisualMemory;

/** Phase-driven field surface. The operator sees one useful action at a time. */
public final class MainActivity extends AppCompatActivity {
    private static final int REQUEST_CAMERA = 44;
    private static final int REQUEST_PERMISSION = 45;
    private static final int BG = Color.rgb(13, 18, 21);
    private static final int SURFACE = Color.rgb(22, 29, 32);
    private static final int SURFACE_RAISED = Color.rgb(30, 40, 42);
    private static final int TEXT = Color.rgb(237, 241, 234);
    private static final int MUTED = Color.rgb(146, 160, 153);
    private static final int TEAL = Color.rgb(63, 171, 151);
    private static final int CORAL = Color.rgb(225, 103, 79);
    private static final int AMBER = Color.rgb(230, 201, 107);
    private static final int LINE = Color.rgb(54, 68, 69);
    private RdFieldDb database;
    private PhotoStore photoStore;
    private SampleSessionEngine engine;
    private VisualMemory memory;
    private FlujoGateway flujo;
    private File pendingCameraFile;
    private LinearLayout content;
    private TextView title;
    private TextView status;
    private String eventLabel = "";
    private String eventProducer = "";
    private boolean eventContextPending;
    private int activeTab;
    private int activeTestIndex;
    private SampleSession.Capture pendingCapture;
    private final Map<String, String> testColors = new HashMap<>();
    private String manualReagent = "";
    private static final String[] SUBSTANCE_OPTIONS = {"MDMA", "ÉXTASIS", "COCAÍNA", "LSD", "KETAMINA", "CANNABIS", "OPIOIDE", "BENZODIACEPINA", "ANFETAMINA", "OTRA"};
    private static final String[] COLOR_OPTIONS = {"blanco", "amarillo", "verde", "azul", "morado", "rosado", "rojo", "transparente", "otro"};
    private static final int[] COLOR_VALUES = {0xfff1eee0, 0xffe6c96b, 0xff65ad68, 0xff5c88c6, 0xff9875bd, 0xffd68aa0, 0xffcf635d, 0xffb9d0ca, 0xff7d8885};
    private static final String[] REAGENT_LIBRARY = {"Marquis", "Mecke", "Mandelin", "Froehde", "Simon's", "Liebermann", "Morris", "Ehrlich", "Hofmann", "Zimmermann", "Robadope", "CBD:THC"};

    @Override protected void onCreate(@Nullable Bundle state) {
        super.onCreate(state);
        database = new RdFieldDb(this);
        database.ensureDemo();
        photoStore = new PhotoStore(this);
        flujo = new FlujoGateway(this);
        memory = new VisualMemory();
        RdFieldDb.SampleRow row = database.latestSample();
        engine = SampleSessionEngine.createExisting(row.id, row.eventId, row.code, row.createdAt, row.phase, row.paused);
        engine.snapshot().status = row.status == null ? "draft" : row.status;
        engine.snapshot().declaredSubstance = row.declaredSubstance == null ? "" : row.declaredSubstance;
        engine.snapshot().presentation = row.presentation == null ? "" : row.presentation;
        engine.snapshot().observedColor = row.observedColor == null ? "" : row.observedColor;
        android.content.SharedPreferences contextStore = getSharedPreferences("xio_event_context", MODE_PRIVATE);
        if (row.eventId.equals(contextStore.getString("event_id", ""))) {
            eventLabel = contextStore.getString("event_label", "");
            eventProducer = contextStore.getString("event_producer", "");
            eventContextPending = contextStore.getBoolean("pending", true);
        }
        for (SampleSession.Capture capture : database.loadCaptures(row.id)) {
            engine.restoreCapture(capture);
            engine.restoreVisualProposal(capture.id, capture.features, SampleSessionEngine.VISUAL_MODEL_VERSION, capture.capturedAt);
        }
        recoverOrphanCaptureFiles(row.id);
        for (SampleSession.TestSession test : database.loadTests(row.id)) engine.restoreTest(test);
        for (SampleSession.Correction correction : database.loadCorrections(row.id)) engine.restoreCorrection(correction);
        for (SampleSession.ActionRecord action : database.loadActions(row.id)) engine.restoreAction(action);
        for (VisualMemory.Entry entry : database.reviewedMemory()) memory.addReviewed(entry);
        buildShell();
        render();
        // The host RD catalog is the source of truth for prior events. Load it
        // on startup so the field screen does not look like an empty/demo DB.
        loadBootstrapAndMaybeChoose(false, false);
    }

    private void buildShell() {
        FrameLayout frame = new FrameLayout(this);
        frame.setBackgroundColor(BG);
        ScrollView scroll = new ScrollView(this);
        content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(dp(12), dp(10), dp(12), dp(18));
        scroll.addView(content);
        frame.addView(scroll, new FrameLayout.LayoutParams(-1, -1));
        setContentView(frame);
    }

    private void render() {
        content.removeAllViews();
        SampleSession sample = engine.snapshot();
        title = text("XIO / RD", 11, AMBER);
        title.setTypeface(null, Typeface.BOLD);
        content.addView(title);
        TextView event = text("● " + eventContextText(sample) + "  ·  " + (sample.paused ? "Ⅱ" : "●"), 10, sample.paused ? AMBER : TEAL);
        event.setContentDescription("Cambiar evento XIO-RD");
        event.setOnClickListener(view -> loadBootstrapAndMaybeChoose(true, false));
        event.setPadding(0, dp(5), 0, 0); content.addView(event);
        TextView sampleCode = text(sample.code, 28, TEXT);
        sampleCode.setTypeface(null, Typeface.BOLD); content.addView(sampleCode);
        LinearLayout topActions = new LinearLayout(this); topActions.setGravity(Gravity.END);
        Button host = iconButton("⌂", "Configurar host XIO-RD", SURFACE, AMBER);
        topActions.addView(host, new LinearLayout.LayoutParams(dp(44), dp(38)));
        Button sync = iconButton("⇧", "Sincronizar con XIO-RD", SURFACE, TEAL);
        LinearLayout.LayoutParams syncParams = new LinearLayout.LayoutParams(dp(44), dp(38)); syncParams.setMargins(dp(5), 0, 0, 0); topActions.addView(sync, syncParams);
        Button raider = iconButton("▦", "Abrir RAIDER", SURFACE, AMBER);
        LinearLayout.LayoutParams raiderParams = new LinearLayout.LayoutParams(dp(44), dp(38)); raiderParams.setMargins(dp(5), 0, 0, 0); topActions.addView(raider, raiderParams);
        Button nextSample = iconButton("⊕", "Nueva muestra del mismo evento", SURFACE, TEAL);
        LinearLayout.LayoutParams nextParams = new LinearLayout.LayoutParams(dp(44), dp(38)); nextParams.setMargins(dp(5), 0, 0, 0); topActions.addView(nextSample, nextParams);
        content.addView(topActions, new LinearLayout.LayoutParams(-1, dp(38)));
        sync.setOnClickListener(view -> syncCurrentSample());
        host.setOnClickListener(view -> showHostDialog());
        raider.setOnClickListener(view -> openRaider());
        nextSample.setOnClickListener(view -> startNextSample());
        status = text(statusLine(sample), 11, MUTED);
        status.setPadding(0, dp(2), 0, dp(9)); content.addView(status);
        content.addView(tabBar());
        content.addView(divider());
        if (activeTab == 0) renderCaptureTab(sample);
        else if (activeTab == 1) renderColorimetryTab(sample);
        else renderEntriesTab();
        Space bottom = new Space(this); content.addView(bottom, new LinearLayout.LayoutParams(1, dp(16)));
    }

    private String statusLine(SampleSession sample) {
        return "◉ " + sample.captures.size() + "   ⏱ " + applicableTests(sample).size() + "   " + (sample.paused ? "Ⅱ" : "●") + " guardado";
    }

    private LinearLayout phaseBar(SampleSession.Phase active) {
        LinearLayout bar = new LinearLayout(this); bar.setOrientation(LinearLayout.HORIZONTAL); bar.setGravity(Gravity.CENTER_VERTICAL);
        SampleSession.Phase[] phases = {SampleSession.Phase.OBSERVE, SampleSession.Phase.TEST, SampleSession.Phase.REVIEW, SampleSession.Phase.MEMORY};
        String[] labels = {"◉", "⏱", "✓", "⌕"};
        String[] descriptions = {"Observar", "Probar", "Corregir", "Memoria"};
        for (int i = 0; i < phases.length; i++) {
            Button button = actionButton(labels[i], phases[i] == active ? TEAL : SURFACE, phases[i] == active ? BG : MUTED);
            button.setContentDescription(descriptions[i]); button.setTextSize(17);
            SampleSession.Phase phase = phases[i];
            button.setOnClickListener(view -> { engine.transitionTo(phase); persist(); render(); });
            LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(0, dp(38), 1f); params.setMargins(i == 0 ? 0 : dp(4), 0, 0, 0); bar.addView(button, params);
        }
        return bar;
    }

    private LinearLayout tabBar() {
        LinearLayout bar = new LinearLayout(this);
        bar.setOrientation(LinearLayout.HORIZONTAL);
        bar.setGravity(Gravity.CENTER_VERTICAL);
        String[] icons = {"▣", "◌", "☷"};
        String[] descriptions = {"Captura y datos", "Resultados colorimétricos", "Ingresos guardados"};
        for (int i = 0; i < icons.length; i++) {
            int tab = i;
            Button button = actionButton(icons[i], tab == activeTab ? TEAL : SURFACE, tab == activeTab ? BG : MUTED);
            button.setTextSize(18);
            button.setContentDescription(descriptions[i]);
            button.setOnClickListener(view -> { activeTab = tab; if (tab == 0) engine.transitionTo(SampleSession.Phase.OBSERVE); else if (tab == 1) engine.transitionTo(SampleSession.Phase.TEST); else engine.transitionTo(SampleSession.Phase.MEMORY); persist(); render(); });
            LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(0, dp(42), 1f);
            params.setMargins(i == 0 ? 0 : dp(5), 0, 0, 0);
            bar.addView(button, params);
        }
        return bar;
    }

    private void renderCaptureTab(SampleSession sample) {
        content.addView(sectionLabel("1  ·  INGRESO"));
        content.addView(heading(pendingCapture == null ? "Nueva muestra" : "Revisar captura"));
        if (pendingCapture != null) {
            addEvidencePair(pendingCapture.path, pendingCapture.silhouettePreviewPath, sample.presentation, sample.observedColor, pendingCapture.features);
            content.addView(body("foto  +  visión"));
        } else if (!sample.captures.isEmpty()) {
            SampleSession.Capture latest = sample.captures.get(sample.captures.size() - 1);
            addEvidencePair(latest.path, latest.silhouettePreviewPath, sample.presentation, sample.observedColor, latest.features);
            content.addView(body("último ingreso guardado"));
        } else {
            Button capture = actionButton("▣  FOTO", CORAL, TEXT);
            content.addView(capture, new LinearLayout.LayoutParams(-1, dp(50)));
            capture.setOnClickListener(view -> openCamera());
        }

        content.addView(sectionLabel("DECLARACIÓN"));
        addOptionStrip("sustancia", SUBSTANCE_OPTIONS, sample.declaredSubstance, value -> {
            engine.setDeclaredSubstance(value);
            if (!containsIgnoreCase(formatsFor(value), sample.presentation)) engine.setPresentation("");
            render();
        });
        if (!sample.declaredSubstance.isEmpty()) {
            addOptionStrip("formato", formatsFor(sample.declaredSubstance), sample.presentation, value -> { engine.setPresentation(value); render(); });
        }
        // The observed colour belongs to the capture context, not only to a
        // completed declaration. Keep the ramp visible while a photo is
        // reviewed/repeated and persist each choice so camera Activity
        // recreation cannot erase it.
        addColorRampControl(content, "COLOR", sample.observedColor, "Rampa cromática del color observado",
                value -> engine.setObservedColor(value), this::persist);

        if (pendingCapture != null) {
            LinearLayout actions = new LinearLayout(this);
            actions.setOrientation(LinearLayout.HORIZONTAL);
            Button discard = actionButton("🗑", SURFACE, CORAL);
            discard.setContentDescription("Descartar foto");
            Button save = actionButton("✓  GUARDAR", TEAL, BG);
            save.setContentDescription("Guardar ingreso");
            actions.addView(discard, new LinearLayout.LayoutParams(0, dp(50), .28f));
            LinearLayout.LayoutParams saveParams = new LinearLayout.LayoutParams(0, dp(50), .72f); saveParams.setMargins(dp(6), 0, 0, 0); actions.addView(save, saveParams);
            content.addView(actions, new LinearLayout.LayoutParams(-1, dp(50)));
            discard.setOnClickListener(view -> discardPendingCapture(true));
            save.setOnClickListener(view -> saveCurrentEntry());
        } else {
            Button save = actionButton("✓  GUARDAR", TEAL, BG);
            save.setContentDescription("Guardar ingreso sin foto");
            content.addView(save, new LinearLayout.LayoutParams(-1, dp(50)));
            save.setOnClickListener(view -> saveCurrentEntry());
        }
        if (pendingCapture != null) {
            Button retry = actionButton("⊙  REPETIR FOTO", SURFACE, TEAL);
            content.addView(retry, new LinearLayout.LayoutParams(-1, dp(40)));
            retry.setOnClickListener(view -> { discardPendingCapture(false); openCamera(); });
        }
    }

    private void renderColorimetryTab(SampleSession sample) {
        content.addView(sectionLabel("2  ·  COLORIMETRÍA"));
        List<SampleSession.TestSession> tests = ensureColorimetryTests(sample);
        if (tests.isEmpty()) {
            if ("OTRA".equalsIgnoreCase(sample.declaredSubstance)) {
                content.addView(heading("Elige el reactivo"));
                content.addView(body("El operador define el primer test cuando la sustancia no tiene un panel automático."));
                addOptionStrip("reactivo", REAGENT_LIBRARY, manualReagent, value -> { manualReagent = value; render(); });
                Button add = actionButton("⊕  AÑADIR TEST", TEAL, BG);
                content.addView(add, new LinearLayout.LayoutParams(-1, dp(50)));
                add.setOnClickListener(view -> {
                    if (manualReagent.isEmpty()) { Toast.makeText(this, "elige un reactivo", Toast.LENGTH_SHORT).show(); return; }
                    engine.addTest("Colorimetría", manualReagent);
                    activeTestIndex = 0;
                    persist();
                    render();
                });
                return;
            }
            content.addView(heading("Selecciona la sustancia"));
            content.addView(body("El panel se arma con los reactivos que corresponden; no se muestran pruebas que no aplican."));
            Button go = actionButton("▣  IR A INGRESO", TEAL, BG);
            content.addView(go, new LinearLayout.LayoutParams(-1, dp(50)));
            go.setOnClickListener(view -> { activeTab = 0; render(); });
            return;
        }
        content.addView(heading("Test " + (activeTestIndex + 1) + " de " + tests.size()));
        addTestSelector(tests);
        SampleSession.TestSession current = tests.get(activeTestIndex);
        content.addView(body("reactivo correspondiente  ·  " + current.reagent));
        addColorimetryInput(current, activeTestIndex);
        Button save = actionButton(activeTestIndex + 1 < tests.size() ? "✓  GUARDAR Y SEGUIR" : "✓  GUARDAR TEST", TEAL, BG);
        content.addView(save, new LinearLayout.LayoutParams(-1, dp(50)));
        save.setOnClickListener(view -> saveCurrentColorimetryTest(tests));
    }

    private void renderEntriesTab() {
        content.addView(sectionLabel("3  ·  REGISTRO"));
        content.addView(heading("Eventos locales"));
        List<RdFieldDb.EventRow> eventRows = database.recentEvents();
        for (RdFieldDb.EventRow row : eventRows) {
            String label = row.name == null || row.name.trim().isEmpty() ? row.id : row.name;
            String detail = row.venue == null || row.venue.trim().isEmpty() ? "" : "  ·  " + row.venue;
            String sync = "synced".equalsIgnoreCase(row.syncStatus) ? "  ·  ✓" : "  ·  pendiente";
            content.addView(body("●  " + label + detail + sync));
        }
        Button changeEvent = actionButton("＋  CREAR / CAMBIAR EVENTO", SURFACE_RAISED, AMBER);
        content.addView(changeEvent, new LinearLayout.LayoutParams(-1, dp(46)));
        changeEvent.setOnClickListener(view -> loadBootstrapAndMaybeChoose(true, false));
        content.addView(heading("Ingresos"));
        List<RdFieldDb.SampleRow> rows = database.recentSamples();
        if (rows.isEmpty()) { content.addView(body("sin ingresos")); return; }
        for (RdFieldDb.SampleRow row : rows) {
            List<SampleSession.Capture> captures = database.loadCaptures(row.id);
            SampleSession.Capture latest = captures.isEmpty() ? null : captures.get(captures.size() - 1);
            addEntryRow(row, latest);
        }
    }

    private void addEvidencePair(String photoPath, String silhouettePath, String format, String declaredColor, VisualFeatures features) {
        LinearLayout pair = new LinearLayout(this);
        pair.setOrientation(LinearLayout.HORIZONTAL);
        pair.setGravity(Gravity.CENTER_VERTICAL);
        pair.setPadding(0, dp(8), 0, dp(3));
        pair.addView(thumbnail(photoPath, "⊘", MUTED), new LinearLayout.LayoutParams(0, dp(154), 1f));
        LinearLayout.LayoutParams visualParams = new LinearLayout.LayoutParams(0, dp(154), 1f); visualParams.setMargins(dp(7), 0, 0, 0);
        int visualColor = colorForLabel(declaredColor);
        pair.addView(thumbnail(silhouettePath, visualGlyph(format), visualColor, true), visualParams);
        content.addView(pair, new LinearLayout.LayoutParams(-1, dp(165)));
    }

    private View thumbnail(String path, String fallback, int fallbackColor) {
        return thumbnail(path, fallback, fallbackColor, false);
    }

    private View thumbnail(String path, String fallback, int fallbackColor, boolean tint) {
        FrameLayout tile = new FrameLayout(this);
        tile.setBackgroundColor(SURFACE_RAISED);
        if (path != null && !path.isEmpty() && new File(path).isFile()) {
            Bitmap bitmap = decodePreview(path, 320);
            if (bitmap != null) {
                ImageView image = new ImageView(this);
                image.setScaleType(ImageView.ScaleType.CENTER_INSIDE);
                image.setPadding(dp(5), dp(5), dp(5), dp(5));
                image.setImageBitmap(bitmap);
                if (tint) image.setColorFilter(new PorterDuffColorFilter(fallbackColor, PorterDuff.Mode.SRC_IN));
                tile.addView(image, new FrameLayout.LayoutParams(-1, -1));
                return tile;
            }
        }
        TextView placeholder = text(fallback, 30, fallbackColor == SURFACE_RAISED ? MUTED : fallbackColor);
        placeholder.setGravity(Gravity.CENTER);
        tile.addView(placeholder, new FrameLayout.LayoutParams(-1, -1));
        return tile;
    }

    private Bitmap decodePreview(String path, int maxDimension) {
        if (path == null || path.isEmpty()) return null;
        BitmapFactory.Options bounds = new BitmapFactory.Options();
        bounds.inJustDecodeBounds = true;
        BitmapFactory.decodeFile(path, bounds);
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null;
        int sample = 1;
        while (Math.max(bounds.outWidth / sample, bounds.outHeight / sample) > maxDimension) sample *= 2;
        BitmapFactory.Options options = new BitmapFactory.Options();
        options.inSampleSize = sample;
        options.inPreferredConfig = Bitmap.Config.RGB_565;
        return BitmapFactory.decodeFile(path, options);
    }

    private String visualGlyph(String format) {
        String value = format == null ? "" : format.toLowerCase(Locale.ROOT);
        if (value.contains("polvo")) return "∴";
        if (value.contains("cristal")) return "◇";
        if (value.contains("estampilla")) return "▧";
        if (value.contains("dulce")) return "✦";
        if (value.contains("líquido") || value.contains("liquido")) return "◌";
        return "▣";
    }

    private void addOptionStrip(String label, String[] options, String selected, OptionAction action) {
        content.addView(sectionLabel(label.toUpperCase(Locale.ROOT)));
        ScrollView horizontal = new ScrollView(this);
        horizontal.setHorizontalScrollBarEnabled(false);
        horizontal.setFillViewport(true);
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        for (String option : options) {
            boolean isSelected = option.equalsIgnoreCase(selected) || ("pastilla".equalsIgnoreCase(option) && "comprimido_prensado".equalsIgnoreCase(selected));
            Button choice = actionButton(option, isSelected ? TEAL : SURFACE, isSelected ? BG : TEXT);
            choice.setTextSize(11);
            choice.setContentDescription(label + ": " + option);
            LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(dp(Math.max(72, option.length() * 8 + 28)), dp(38));
            params.setMargins(0, 0, dp(5), 0);
            row.addView(choice, params);
            choice.setOnClickListener(view -> action.select(option));
        }
        horizontal.addView(row);
        content.addView(horizontal, new LinearLayout.LayoutParams(-1, dp(40)));
    }

    private TextView addColorRampControl(LinearLayout parent, String label, String selected,
                                         String description, RampAction action) {
        return addColorRampControl(parent, label, selected, description, action, null);
    }

    private TextView addColorRampControl(LinearLayout parent, String label, String selected,
                                         String description, RampAction action, Runnable commit) {
        if (label != null && !label.isEmpty()) parent.addView(sectionLabel(label));
        boolean hasSelection = selected != null && !selected.trim().isEmpty();
        TextView reading = text(hasSelection ? "color  " + selected : "sin color seleccionado", 12,
                hasSelection ? TEXT : MUTED);
        reading.setPadding(0, dp(4), 0, dp(4));
        ColorRampView ramp = new ColorRampView(this, rampInitialColor(selected), value -> {
            if (action != null) action.selected(value);
            reading.setText("color  " + value);
            reading.setTextColor(TEXT);
        });
        ramp.setOnCommit(commit);
        ramp.setContentDescription(description);
        parent.addView(ramp, new LinearLayout.LayoutParams(-1, dp(116)));
        parent.addView(reading);
        return reading;
    }

    private String rampInitialColor(String value) {
        if (value == null || value.trim().isEmpty()) return "";
        String clean = value.trim();
        if (clean.startsWith("#")) return clean;
        for (int i = 0; i < COLOR_OPTIONS.length; i++) {
            if (COLOR_OPTIONS[i].equalsIgnoreCase(clean)) {
                return String.format(Locale.US, "#%06X", COLOR_VALUES[i] & 0x00ffffff);
            }
        }
        return "";
    }

    private void addEntryRow(RdFieldDb.SampleRow row, SampleSession.Capture capture) {
        LinearLayout item = card();
        item.setOrientation(LinearLayout.HORIZONTAL);
        item.setGravity(Gravity.CENTER_VERTICAL);
        String photoPath = capture == null ? "" : capture.path;
        String silhouettePath = capture == null ? "" : capture.silhouettePreviewPath;
        VisualFeatures features = capture == null ? null : capture.features;
        int color = colorForLabel(row.observedColor);
        item.addView(thumbnail(photoPath, "⊘", MUTED), new LinearLayout.LayoutParams(dp(62), dp(62)));
        LinearLayout.LayoutParams visualParams = new LinearLayout.LayoutParams(dp(62), dp(62)); visualParams.setMargins(dp(5), 0, dp(9), 0);
        item.addView(thumbnail(silhouettePath, visualGlyph(row.presentation), color, true), visualParams);
        LinearLayout info = new LinearLayout(this); info.setOrientation(LinearLayout.VERTICAL); info.setGravity(Gravity.CENTER_VERTICAL);
        String substance = row.declaredSubstance == null || row.declaredSubstance.isEmpty() ? "sin declarar" : row.declaredSubstance;
        String format = row.presentation == null || row.presentation.isEmpty() ? "sin formato" : row.presentation;
        String observedColorLabel = row.observedColor == null || row.observedColor.trim().isEmpty()
                ? "sin color" : "color " + row.observedColor.trim();
        info.addView(text(substance + "  ·  " + format, 13, TEXT));
        info.addView(body(observedColorLabel));
        info.addView(body(formatTime(capture == null ? row.createdAt : capture.capturedAt) + "  ·  " + row.code));
        item.addView(info, new LinearLayout.LayoutParams(0, -1, 1f));
        content.addView(item, new LinearLayout.LayoutParams(-1, dp(82)));
    }

    private void addTestSelector(List<SampleSession.TestSession> tests) {
        ScrollView horizontal = new ScrollView(this);
        horizontal.setHorizontalScrollBarEnabled(false);
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        for (int i = 0; i < tests.size(); i++) {
            int index = i;
            SampleSession.TestSession test = tests.get(i);
            Button choice = actionButton("T" + (i + 1), i == activeTestIndex ? TEAL : SURFACE, i == activeTestIndex ? BG : TEXT);
            choice.setTextSize(12);
            choice.setContentDescription("Seleccionar test " + (i + 1) + ": " + test.reagent);
            LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(dp(72), dp(42));
            params.setMargins(i == 0 ? 0 : dp(5), 0, 0, 0);
            row.addView(choice, params);
            choice.setOnClickListener(view -> { activeTestIndex = index; render(); });
        }
        horizontal.addView(row);
        content.addView(horizontal, new LinearLayout.LayoutParams(-1, dp(45)));
        TextView reagent = text(tests.get(activeTestIndex).reagent, 19, TEXT);
        reagent.setTypeface(null, Typeface.BOLD);
        reagent.setPadding(0, dp(4), 0, dp(3));
        content.addView(reagent);
    }

    private void addColorimetryInput(SampleSession.TestSession test, int index) {
        LinearLayout row = card();
        row.setPadding(dp(10), dp(9), dp(10), dp(10));
        LinearLayout header = new LinearLayout(this);
        header.setGravity(Gravity.CENTER_VERTICAL);
        TextView name = text("T" + (index + 1) + "  " + test.reagent, 14, TEXT);
        name.setTypeface(null, Typeface.BOLD);
        header.addView(name, new LinearLayout.LayoutParams(0, dp(38), 1f));
        String timer = test.elapsedMs > 0 ? String.format(Locale.US, "%.1fs", test.elapsedMs / 1000f) : "—";
        Button timerButton = iconButton(test.status.equals("running") ? "■" : "▶", timer, test.status.equals("running") ? CORAL : SURFACE_RAISED, test.status.equals("running") ? TEXT : AMBER);
        timerButton.setContentDescription(test.status.equals("running") ? "Detener cronómetro" : "Iniciar cronómetro");
        header.addView(timerButton, new LinearLayout.LayoutParams(dp(58), dp(38)));
        row.addView(header);

        String selected = testColors.get(test.id);
        TextView reading = addColorRampControl(row, "", selected, "Rampa cromática del test " + (index + 1), value -> {
            testColors.put(test.id, value);
        });
        Button noReading = actionButton("—  SIN CAMBIO / NO LEGIBLE", SURFACE_RAISED, MUTED);
        noReading.setContentDescription("Registrar sin lectura");
        noReading.setOnClickListener(view -> { testColors.put(test.id, "sin lectura"); render(); });
        row.addView(noReading, new LinearLayout.LayoutParams(-1, dp(38)));
        timerButton.setOnClickListener(view -> { if (test.status.equals("running")) engine.stopTest(test); else engine.startTest(test); persist(); render(); });
        content.addView(row, new LinearLayout.LayoutParams(-1, dp(216)));
    }

    private List<SampleSession.TestSession> ensureColorimetryTests(SampleSession sample) {
        List<SampleSession.TestSession> result = new ArrayList<>();
        String[] plan = testPlanFor(sample.declaredSubstance);
        boolean changed = false;
        for (String reagent : plan) {
            SampleSession.TestSession found = null;
            for (SampleSession.TestSession test : sample.tests) {
                if (test.reagent != null && test.reagent.equalsIgnoreCase(reagent)) { found = test; break; }
            }
            if (found == null) { found = engine.addTest("Colorimetría", reagent); changed = true; }
            if (!testColors.containsKey(found.id) && !found.observations.isEmpty()) testColors.put(found.id, found.observations.get(found.observations.size() - 1).color);
            result.add(found);
        }
        if (plan.length == 0 && "OTRA".equalsIgnoreCase(sample.declaredSubstance)) {
            for (SampleSession.TestSession test : sample.tests) {
                if (!result.contains(test)) {
                    if (!testColors.containsKey(test.id) && !test.observations.isEmpty()) testColors.put(test.id, test.observations.get(test.observations.size() - 1).color);
                    result.add(test);
                }
            }
        }
        if (activeTestIndex >= result.size()) activeTestIndex = Math.max(0, result.size() - 1);
        if (changed) persist();
        return result;
    }

    private List<SampleSession.TestSession> applicableTests(SampleSession sample) {
        List<SampleSession.TestSession> result = new ArrayList<>();
        String[] plan = testPlanFor(sample.declaredSubstance);
        for (String reagent : plan) for (SampleSession.TestSession test : sample.tests) if (test.reagent != null && test.reagent.equalsIgnoreCase(reagent)) { result.add(test); break; }
        return result;
    }

    private String[] testPlanFor(String substance) {
        String value = substance == null ? "" : substance.toLowerCase(Locale.ROOT);
        if (value.contains("mdma") || value.contains("éxtasis") || value.contains("extasis")) return new String[]{"Marquis", "Mecke", "Simon's", "Froehde"};
        if (value.contains("coca")) return new String[]{"Liebermann", "Morris"};
        if (value.contains("lsd")) return new String[]{"Ehrlich", "Hofmann"};
        if (value.contains("ketamina")) return new String[]{"Morris", "Liebermann", "Froehde"};
        if (value.contains("cannabis")) return new String[]{"CBD:THC"};
        if (value.contains("opioide")) return new String[]{"Marquis", "Mecke", "Froehde"};
        if (value.contains("benzodiazepina")) return new String[]{"Zimmermann"};
        if (value.contains("anfetamina")) return new String[]{"Marquis", "Robadope", "Simon's"};
        return new String[0];
    }

    private void saveCurrentEntry() {
        SampleSession sample = engine.snapshot();
        if (sample.declaredSubstance.isEmpty() || sample.presentation.isEmpty() || sample.observedColor.isEmpty()) {
            Toast.makeText(this, "elige sustancia, formato y color", Toast.LENGTH_SHORT).show();
            return;
        }
        if (pendingCapture != null) {
            SampleSession.Capture capture = pendingCapture;
            engine.addCapture(capture);
            engine.addVisualProposal(capture.id, capture.features);
            database.insertCapture(sample.id, capture);
            pendingCapture = null;
            pendingCameraFile = null;
        } else {
            if (sample.captures.isEmpty()) sample.status = "saved_without_photo";
        }
        engine.transitionTo(SampleSession.Phase.OBSERVE);
        persist();
        activeTab = 2;
        Toast.makeText(this, "Ingreso guardado", Toast.LENGTH_SHORT).show();
        render();
    }

    private void discardPendingCapture(boolean rerender) {
        if (pendingCapture != null) {
            database.deleteCapture(engine.snapshot().id, pendingCapture.id);
            deleteEvidence(pendingCapture.path);
            deleteEvidence(pendingCapture.silhouettePath);
            deleteEvidence(pendingCapture.silhouettePreviewPath);
            deleteEvidence(pendingCapture.reliefPath);
        } else if (pendingCameraFile != null) deleteEvidence(pendingCameraFile.getAbsolutePath());
        pendingCapture = null;
        pendingCameraFile = null;
        if (rerender) { Toast.makeText(this, "Foto descartada", Toast.LENGTH_SHORT).show(); render(); }
    }

    private void saveCurrentColorimetryTest(List<SampleSession.TestSession> tests) {
        SampleSession.TestSession test = tests.get(activeTestIndex);
        String color = testColors.containsKey(test.id) ? testColors.get(test.id) : "sin lectura";
        if (test.status.equals("running")) engine.stopTest(test);
        String previous = test.observations.isEmpty() ? "" : test.observations.get(test.observations.size() - 1).color;
        if (!color.equals(previous)) engine.addObservation(test, color, "Color seleccionado por el operador");
        engine.completeTest(test, color, "Observación colorimétrica; no es identificación química");
        persist();
        if (activeTestIndex + 1 < tests.size()) {
            activeTestIndex++;
            Toast.makeText(this, "Test " + test.ordinal + " guardado", Toast.LENGTH_SHORT).show();
        } else {
            activeTab = 2;
            Toast.makeText(this, "Tests guardados", Toast.LENGTH_SHORT).show();
        }
        render();
    }

    private String[] formatsFor(String substance) {
        String value = substance == null ? "" : substance.toLowerCase(Locale.ROOT);
        if (value.contains("éxtasis") || value.contains("extasis")) return new String[]{"pastilla"};
        if (value.contains("mdma")) return new String[]{"cristal", "polvo"};
        if (value.contains("coca")) return new String[]{"polvo", "cristal"};
        if (value.contains("lsd")) return new String[]{"estampilla", "dulce", "líquido"};
        if (value.contains("ketamina")) return new String[]{"polvo", "líquido"};
        return new String[]{"polvo", "cristal", "pastilla", "líquido", "estampilla", "dulce", "otro"};
    }

    private boolean containsIgnoreCase(String[] values, String target) {
        if (target == null) return false;
        for (String value : values) if (value.equalsIgnoreCase(target) || (target.equalsIgnoreCase("comprimido_prensado") && value.equalsIgnoreCase("pastilla"))) return true;
        return false;
    }

    private int colorForLabel(String value) {
        if (value != null && value.trim().startsWith("#")) {
            try { return Color.parseColor(value.trim()); } catch (IllegalArgumentException ignored) { }
        }
        if (value != null) for (int i = 0; i < COLOR_OPTIONS.length; i++) if (COLOR_OPTIONS[i].equalsIgnoreCase(value)) return COLOR_VALUES[i];
        return SURFACE_RAISED;
    }

    private int readableOn(int color) {
        return ((Color.red(color) * 299 + Color.green(color) * 587 + Color.blue(color) * 114) / 1000) > 145 ? BG : TEXT;
    }

    private String formatTime(long value) {
        return new java.text.SimpleDateFormat("HH:mm:ss", Locale.US).format(new java.util.Date(value));
    }

    private void deleteEvidence(String path) {
        if (path == null || path.isEmpty()) return;
        File file = new File(path);
        if (file.isFile()) file.delete();
    }

    private interface OptionAction { void select(String value); }

    private void renderObserve(SampleSession sample) {
        content.addView(sectionLabel(sample.captures.isEmpty() ? "CAPTURA" : "OBSERVACIÓN"));
        content.addView(heading(sample.captures.isEmpty() ? "Capturar evidencia" : "Rasgos detectados"));
        if (sample.captures.isEmpty()) {
            addCaptureSurface(sample);
            content.addView(actionButton("▣  CAPTURAR", CORAL, TEXT), new LinearLayout.LayoutParams(-1, dp(50)));
            ((Button) content.getChildAt(content.getChildCount() - 1)).setOnClickListener(view -> openCamera());
        } else {
            addCaptureSurface(sample);
            VisualFeatures features = sample.captures.get(sample.captures.size() - 1).features;
            addVisualFeatureCard(features);
            Button anotherPhoto = actionButton("⊕  OTRA VISTA", SURFACE, TEAL);
            content.addView(anotherPhoto, new LinearLayout.LayoutParams(-1, dp(42)));
            anotherPhoto.setOnClickListener(view -> openCamera());
            Button next = actionButton("⏱  PRUEBA", CORAL, TEXT);
            content.addView(next, new LinearLayout.LayoutParams(-1, dp(48))); next.setOnClickListener(view -> { engine.transitionTo(SampleSession.Phase.TEST); persist(); render(); });
            Button memoryButton = actionButton("⌕  MEMORIA", SURFACE, TEAL);
            content.addView(memoryButton, new LinearLayout.LayoutParams(-1, dp(42))); memoryButton.setOnClickListener(view -> { engine.transitionTo(SampleSession.Phase.MEMORY); render(); });
        }
        content.addView(contextStrip(sample));
    }

    private void addCaptureSurface(SampleSession sample) {
        FrameLayout imageFrame = new FrameLayout(this);
        imageFrame.setBackgroundColor(SURFACE);
        imageFrame.setPadding(dp(1), dp(1), dp(1), dp(1));
        LinearLayout.LayoutParams frameParams = new LinearLayout.LayoutParams(-1, dp(230)); frameParams.setMargins(0, dp(10), 0, dp(10));
        if (!sample.captures.isEmpty()) {
            SampleSession.Capture capture = sample.captures.get(sample.captures.size() - 1);
            ImageView image = new ImageView(this); image.setScaleType(ImageView.ScaleType.CENTER_CROP); image.setImageBitmap(decodePreview(capture.path, 900));
            imageFrame.addView(image, new FrameLayout.LayoutParams(-1, -1));
            TextView badge = text("● " + capture.kind.toUpperCase(Locale.ROOT), 10, TEXT); badge.setBackgroundColor(Color.argb(205, 13, 18, 21)); badge.setPadding(dp(8), dp(5), dp(8), dp(5)); FrameLayout.LayoutParams badgeParams = new FrameLayout.LayoutParams(-2, -2, Gravity.TOP | Gravity.START); imageFrame.addView(badge, badgeParams);
        } else {
            TextView placeholder = text("▣\n\nCÁMARA", 18, MUTED); placeholder.setGravity(Gravity.CENTER); imageFrame.addView(placeholder, new FrameLayout.LayoutParams(-1, -1));
        }
        content.addView(imageFrame, frameParams);
    }

    private void addVisualFeatureCard(VisualFeatures features) {
        LinearLayout card = card();
        card.addView(sectionLabel("PROPUESTA VISUAL"));
        card.addView(text(features.compactDescription(), 17, TEXT));
        card.addView(body("◐ " + features.colorLabel + "   ·   ≋ " + String.format(Locale.US, "%.0f%%", features.textureScore * 100f) + "   ·   ▣ " + String.format(Locale.US, "%.0f%%", features.foregroundRatio * 100f)));
        if (features.silhouetteConfidence > 0f) card.addView(body("⌁ " + Math.round(features.silhouetteConfidence * 100f) + "%   ·   ◇ " + Math.round(features.circularity * 100f) + "%   ·   ⇄ " + Math.round(features.symmetry * 100f) + "%" + (features.reliefConfidence > 0f ? "   ·   ✦ " + Math.round(features.reliefConfidence * 100f) + "%" : "")));
        content.addView(card, new LinearLayout.LayoutParams(-1, -2));
    }

    private TextView contextStrip(SampleSession sample) {
        TextView strip = body("D  " + (sample.declaredSubstance.isEmpty() ? "—" : sample.declaredSubstance) + "     P  " + (sample.presentation.isEmpty() ? "—" : sample.presentation));
        strip.setPadding(dp(10), dp(9), dp(10), dp(9)); strip.setBackgroundColor(SURFACE_RAISED); return strip;
    }

    private void renderTest(SampleSession sample) {
        content.addView(sectionLabel("PRUEBA"));
        content.addView(heading("Medir y registrar"));
        if (sample.tests.isEmpty()) {
            Button add = actionButton("⊕  AÑADIR PRUEBA", CORAL, TEXT); content.addView(add, new LinearLayout.LayoutParams(-1, dp(50))); add.setOnClickListener(view -> { engine.addTest("Colorimetría", "Marquis"); persist(); render(); });
        } else {
            for (SampleSession.TestSession test : sample.tests) addTestCard(test);
            Button add = actionButton("⊕  OTRA PRUEBA", SURFACE, TEAL); content.addView(add, new LinearLayout.LayoutParams(-1, dp(42))); add.setOnClickListener(view -> { engine.addTest("Colorimetría", "Marquis"); persist(); render(); });
        }
        Button pause = iconButton(sample.paused ? "▶" : "Ⅱ", sample.paused ? "Retomar sesión" : "Pausar y guardar", sample.paused ? AMBER : SURFACE, BG); LinearLayout.LayoutParams pauseParams = new LinearLayout.LayoutParams(dp(48), dp(42)); pauseParams.gravity = Gravity.END; content.addView(pause, pauseParams); pause.setOnClickListener(view -> { if (sample.paused) engine.resume(); else engine.pause(); persist(); render(); });
        Button review = actionButton("✓  CORREGIR", TEAL, BG); content.addView(review, new LinearLayout.LayoutParams(-1, dp(48))); review.setOnClickListener(view -> { engine.transitionTo(SampleSession.Phase.REVIEW); persist(); render(); });
    }

    private void addTestCard(SampleSession.TestSession test) {
        LinearLayout card = card();
        card.addView(sectionLabel("PRUEBA " + test.ordinal + "  ·  " + test.reagent));
        String timer = test.elapsedMs > 0 ? String.format(Locale.US, "%.1f s", test.elapsedMs / 1000f) : "—";
        TextView timerText = text("⏱  " + timer, 22, test.status.equals("running") ? AMBER : TEXT); timerText.setTypeface(null, Typeface.BOLD); card.addView(timerText);
        Button timerButton = iconButton(test.status.equals("running") ? "■" : "▶", test.status.equals("running") ? "Detener y fijar tiempo" : "Iniciar cronómetro", test.status.equals("running") ? CORAL : AMBER, BG); card.addView(timerButton, new LinearLayout.LayoutParams(-1, dp(45))); timerButton.setOnClickListener(view -> { if (test.status.equals("running")) engine.stopTest(test); else engine.startTest(test); persist(); render(); });
        Button observation = actionButton("◌  OBSERVAR", SURFACE, TEAL); card.addView(observation, new LinearLayout.LayoutParams(-1, dp(40))); observation.setOnClickListener(view -> { engine.addObservation(test, "observación del operador", "observación registrada"); persist(); Toast.makeText(this, "Observación guardada", Toast.LENGTH_SHORT).show(); render(); });
        Button complete = actionButton(test.status.equals("done") ? "✓  CERRADA" : "✓  CERRAR", SURFACE_RAISED, TEXT); card.addView(complete, new LinearLayout.LayoutParams(-1, dp(40))); complete.setOnClickListener(view -> { engine.completeTest(test, "No concluyente", "Registro de operador; no es identificación química"); persist(); render(); });
        content.addView(card, new LinearLayout.LayoutParams(-1, -2));
    }

    private void renderReview(SampleSession sample) {
        content.addView(sectionLabel("CORREGIR"));
        content.addView(heading("Revisar lectura"));
        if (!sample.captures.isEmpty()) {
            VisualFeatures features = sample.captures.get(sample.captures.size() - 1).features;
            LinearLayout card = card(); card.addView(sectionLabel("PROPUESTA")); card.addView(text(features.compactDescription(), 17, TEXT)); card.addView(body("Sólo rasgos visibles · no composición"));
            Button confirm = actionButton("✓  ACEPTAR", TEAL, BG); card.addView(confirm, new LinearLayout.LayoutParams(-1, dp(46))); confirm.setOnClickListener(view -> saveReviewedExample(sample.captures.get(sample.captures.size() - 1), features.compactDescription(), "visual_summary"));
            Button mark = actionButton("✎  MARCA / LOGO", SURFACE, TEAL); card.addView(mark, new LinearLayout.LayoutParams(-1, dp(42))); mark.setOnClickListener(view -> askForMarkingLabel(sample.captures.get(sample.captures.size() - 1), features));
            content.addView(card, new LinearLayout.LayoutParams(-1, -2));
        } else {
            content.addView(body("Aún no hay captura visual que corregir."));
        }
        Button memoryButton = actionButton("⌕  MEMORIA", SURFACE, TEAL); content.addView(memoryButton, new LinearLayout.LayoutParams(-1, dp(42))); memoryButton.setOnClickListener(view -> { engine.transitionTo(SampleSession.Phase.MEMORY); render(); });
    }

    private void renderMemory(SampleSession sample) {
        content.addView(sectionLabel("MEMORIA"));
        content.addView(heading("Parecidos y recurrencia"));
        if (sample.captures.isEmpty()) { content.addView(body("Captura primero una muestra para consultar la memoria.")); return; }
        VisualFeatures query = sample.captures.get(sample.captures.size() - 1).features;
        List<BatchPatternDetector.Pattern> patterns = new BatchPatternDetector().detect(database.sampleVisualObservations(sample.eventId));
        BatchPatternDetector.Pattern currentPattern = null;
        for (BatchPatternDetector.Pattern pattern : patterns) if (pattern.sampleCodes.contains(sample.code)) { currentPattern = pattern; break; }
        if (currentPattern != null && currentPattern.repeatedInEvent()) {
            LinearLayout recurrence = card();
            recurrence.addView(sectionLabel("RECURRENCIA DEL EVENTO"));
            recurrence.addView(text("↻  " + currentPattern.recurrence() + " parecidas en este evento", 17, TEXT));
            recurrence.addView(body("prioridad de turno · no identificación"));
            content.addView(recurrence, new LinearLayout.LayoutParams(-1, -2));
        } else {
            content.addView(body("—  sin recurrencia en este evento"));
        }
        List<VisualMemory.Match> matches = memory.findSimilar(sample.eventId, System.currentTimeMillis(), query, 5);
        if (matches.isEmpty()) content.addView(body("—  sin ejemplos revisados"));
        for (VisualMemory.Match match : matches) {
            LinearLayout row = card();
            String origin = sample.eventId.equals(match.entry.eventId) ? "● turno" : "○ histórico";
            row.addView(text(origin + "  " + match.entry.sampleCode + "  ·  " + Math.round(match.similarity * 100f) + "%", 16, TEXT));
            row.addView(body(match.entry.reviewedLabel));
            content.addView(row, new LinearLayout.LayoutParams(-1, -2));
        }
        Button back = actionButton("←  CORREGIR", SURFACE, TEAL); content.addView(back, new LinearLayout.LayoutParams(-1, dp(42))); back.setOnClickListener(view -> { engine.transitionTo(SampleSession.Phase.REVIEW); render(); });
        Button export = actionButton("⇩  EXPORTAR", TEAL, BG); content.addView(export, new LinearLayout.LayoutParams(-1, dp(46))); export.setOnClickListener(view -> exportSample());
    }

    private void openCamera() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) { ActivityCompat.requestPermissions(this, new String[]{Manifest.permission.CAMERA}, REQUEST_PERMISSION); return; }
        launchCamera();
    }

    private void launchCamera() {
        String captureId = "capture-" + System.currentTimeMillis();
        try {
            pendingCameraFile = photoStore.prepareFile(engine.snapshot().id, captureId);
            Uri output = FileProvider.getUriForFile(this, "cl.reduciendodano.xiofield.files", pendingCameraFile);
            Intent intent = new Intent(MediaStore.ACTION_IMAGE_CAPTURE); intent.putExtra(MediaStore.EXTRA_OUTPUT, output); intent.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION | Intent.FLAG_GRANT_READ_URI_PERMISSION); startActivityForResult(intent, REQUEST_CAMERA);
        } catch (IOException error) { Toast.makeText(this, "No se pudo preparar el almacenamiento privado", Toast.LENGTH_LONG).show(); }
    }

    @Override public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] results) { super.onRequestPermissionsResult(requestCode, permissions, results); if (requestCode == REQUEST_PERMISSION && results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED) launchCamera(); }

    @Override protected void onActivityResult(int requestCode, int resultCode, @Nullable Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != REQUEST_CAMERA) return;
        if (resultCode != RESULT_OK || pendingCameraFile == null) { discardPendingCapture(false); return; }
        Bitmap bitmap = BitmapFactory.decodeFile(pendingCameraFile.getAbsolutePath());
        if (bitmap == null) { discardPendingCapture(false); Toast.makeText(this, "La captura no pudo leerse", Toast.LENGTH_LONG).show(); return; }
        processCapture(bitmap, pendingCameraFile);
    }

    private void useSyntheticCapture() {
        Bitmap bitmap = Bitmap.createBitmap(480, 360, Bitmap.Config.ARGB_8888); bitmap.eraseColor(Color.rgb(230, 201, 107));
        try { File file = photoStore.prepareFile(engine.snapshot().id, "synthetic-" + System.currentTimeMillis()); processCapture(bitmap, file); engine.snapshot().status = "synthetic_demo"; } catch (IOException error) { Toast.makeText(this, "No se pudo guardar la demo", Toast.LENGTH_LONG).show(); }
    }

    private void processCapture(Bitmap bitmap, File destination) {
        String captureId = destination.getName().replace(".jpg", "");
        try {
            PhotoStore.StoredPhoto stored = photoStore.store(engine.snapshot().id, captureId, bitmap);
            VisualFeatureExtractor.VisualAnalysis analysis = VisualFeatureExtractor.analyzeDetailed(bitmap);
            VisualFeatures features = analysis.features;
            File silhouetteFile = analysis.separated && !analysis.silhouetteSvg.isEmpty() ? photoStore.storeSilhouette(engine.snapshot().id, captureId, analysis.silhouetteSvg) : null;
            File silhouettePreviewFile = analysis.silhouettePreview == null ? null : photoStore.storeSilhouettePreview(engine.snapshot().id, captureId, analysis.silhouettePreview);
            File reliefFile = analysis.reliefSvg.isEmpty() ? null : photoStore.storeRelief(engine.snapshot().id, captureId, analysis.reliefSvg);
            if (analysis.silhouettePreview != null) analysis.silhouettePreview.recycle();
            String viewKind = "vista-" + (engine.snapshot().captures.size() + 1);
            pendingCapture = new SampleSession.Capture(captureId, viewKind, stored.file.getAbsolutePath(), silhouetteFile == null ? "" : silhouetteFile.getAbsolutePath(), silhouettePreviewFile == null ? "" : silhouettePreviewFile.getAbsolutePath(), reliefFile == null ? "" : reliefFile.getAbsolutePath(), stored.sha256, System.currentTimeMillis(), features);
            // The camera can recreate this Activity before the operator taps
            // GUARDAR. Persist the evidence row immediately so the photo,
            // silhouette and metadata survive that lifecycle boundary.
            database.insertCapture(engine.snapshot().id, pendingCapture);
            persist();
            pendingCameraFile = null;
            Toast.makeText(this, "Revisa la foto y guarda el ingreso", Toast.LENGTH_SHORT).show(); render();
        } catch (IOException error) { Toast.makeText(this, "No se pudo guardar la evidencia", Toast.LENGTH_LONG).show(); }
    }

    private void persist() { database.saveSession(engine.snapshot()); }

    /** Reconciles evidence written by the pre-draft build with the local DB. */
    private void recoverOrphanCaptureFiles(String sampleId) {
        File directory = new File(getFilesDir(), "evidence" + File.separator + sampleId);
        File[] photos = directory.listFiles((dir, name) -> name != null && name.endsWith(".jpg"));
        if (photos == null) return;
        for (File photo : photos) {
            String captureId = photo.getName().substring(0, photo.getName().length() - 4);
            SampleSession.Capture existing = null;
            int existingIndex = -1;
            for (int i = 0; i < engine.snapshot().captures.size(); i++) {
                SampleSession.Capture capture = engine.snapshot().captures.get(i);
                if (capture.id.equals(captureId)) { existing = capture; existingIndex = i; break; }
            }
            // A capture can already be registered while its first analysis
            // produced no silhouette. Re-run that exact evidence on launch
            // so a corrected extractor repairs the row instead of treating
            // the failed draft as permanently complete.
            boolean usableExisting = existing != null
                    && !existing.silhouettePreviewPath.isEmpty()
                    && new File(existing.silhouettePreviewPath).isFile()
                    && existing.features != null
                    && existing.features.circularity >= .12f
                    && !"no separada".equalsIgnoreCase(existing.features.silhouetteLabel);
            if (usableExisting) continue;
            Bitmap bitmap = BitmapFactory.decodeFile(photo.getAbsolutePath());
            if (bitmap == null) continue;
            try {
                VisualFeatureExtractor.VisualAnalysis analysis = VisualFeatureExtractor.analyzeDetailed(bitmap);
                File svg = new File(directory, captureId + ".svg");
                File preview = new File(directory, captureId + ".silhouette.png");
                File relief = new File(directory, captureId + ".relief.svg");
                String silhouettePath = svg.isFile() ? svg.getAbsolutePath() : "";
                String previewPath = preview.isFile() ? preview.getAbsolutePath() : "";
                String reliefPath = relief.isFile() ? relief.getAbsolutePath() : "";
                if (silhouettePath.isEmpty() && analysis.separated && !analysis.silhouetteSvg.isEmpty()) silhouettePath = photoStore.storeSilhouette(sampleId, captureId, analysis.silhouetteSvg).getAbsolutePath();
                if (previewPath.isEmpty() && analysis.silhouettePreview != null) previewPath = photoStore.storeSilhouettePreview(sampleId, captureId, analysis.silhouettePreview).getAbsolutePath();
                if (reliefPath.isEmpty() && !analysis.reliefSvg.isEmpty()) reliefPath = photoStore.storeRelief(sampleId, captureId, analysis.reliefSvg).getAbsolutePath();
                SampleSession.Capture capture = new SampleSession.Capture(captureId,
                        existing == null ? "vista-recuperada" : existing.kind,
                        photo.getAbsolutePath(), silhouettePath, previewPath, reliefPath,
                        sha256(photo), existing == null ? (photo.lastModified() > 0 ? photo.lastModified() : System.currentTimeMillis()) : existing.capturedAt,
                        analysis.features);
                database.insertCapture(sampleId, capture);
                if (existingIndex >= 0) engine.snapshot().captures.set(existingIndex, capture);
                else engine.restoreCapture(capture);
                engine.restoreVisualProposal(capture.id, capture.features, SampleSessionEngine.VISUAL_MODEL_VERSION, capture.capturedAt);
                if (analysis.silhouettePreview != null && !analysis.silhouettePreview.isRecycled()) analysis.silhouettePreview.recycle();
            } catch (IOException ignored) {
                // Keep the original evidence intact; a later launch may retry.
            } finally {
                if (bitmap != null && !bitmap.isRecycled()) bitmap.recycle();
            }
        }
    }

    private String sha256(File file) throws IOException {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            try (FileInputStream input = new FileInputStream(file)) {
                byte[] buffer = new byte[8192]; int count;
                while ((count = input.read(buffer)) != -1) digest.update(buffer, 0, count);
            }
            StringBuilder result = new StringBuilder();
            for (byte value : digest.digest()) result.append(String.format(Locale.US, "%02x", value));
            return result.toString();
        } catch (NoSuchAlgorithmException error) { return "hash-unavailable"; }
    }

    private void saveReviewedExample(SampleSession.Capture capture, String label, String field) {
        SampleSession sample = engine.snapshot();
        String proposed = capture.features.compactDescription();
        engine.addCorrection(capture.id, field, proposed, label);
        SampleSession.Correction correction = sample.corrections.get(sample.corrections.size() - 1);
        sample.status = "reviewed";
        database.saveCorrectionAndTrainingExample(sample.id, correction, label);
        memory.addReviewed(new VisualMemory.Entry(capture.id, sample.code, sample.eventId, capture.capturedAt, label, capture.features));
        persist();
        Toast.makeText(this, "Corrección conservada y disponible para recuperar", Toast.LENGTH_SHORT).show();
        render();
    }

    private void askForMarkingLabel(SampleSession.Capture capture, VisualFeatures features) {
        EditText input = new EditText(this);
        input.setHint("Ej.: corona, estrella, sin identificar");
        input.setSingleLine(true);
        new AlertDialog.Builder(this)
                .setTitle("¿Qué marca o logo observa la mesa?")
                .setMessage("Es una etiqueta visual para buscar casos parecidos; no es una identificación química.")
                .setView(input)
                .setNegativeButton("Cancelar", null)
                .setPositiveButton("GUARDAR CORRECCIÓN", (dialog, which) -> {
                    String label = input.getText().toString().trim();
                    if (label.isEmpty()) label = "marca observada sin nombre";
                    saveReviewedExample(capture, features.compactDescription() + " · operador: " + label, "marking_label");
                })
                .show();
    }

    private void startNextSample() {
        discardPendingCapture(false);
        SampleSession current = engine.snapshot();
        persist();
        engine = SampleSessionEngine.create(current.eventId, "XIO-" + System.currentTimeMillis());
        activeTab = 0;
        persist();
        render();
    }

    private void exportSample() {
        try {
            File archive = RdFieldExporter.export(this, engine.snapshot());
            Uri uri = FileProvider.getUriForFile(this, "cl.reduciendodano.xiofield.files", archive);
            Intent share = new Intent(Intent.ACTION_SEND);
            share.setType("application/zip");
            share.putExtra(Intent.EXTRA_STREAM, uri);
            share.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
            startActivity(Intent.createChooser(share, "Compartir registro XIO"));
        } catch (IOException error) {
            Toast.makeText(this, "No se pudo preparar la exportación", Toast.LENGTH_LONG).show();
        }
    }

    private void openRaider() {
        try {
            Intent intent = new Intent(Intent.ACTION_VIEW,
                    Uri.parse(rdEndpoint() + "/raider"));
            startActivity(intent);
        } catch (Exception error) {
            Toast.makeText(this, "No se pudo abrir RAIDER en XIO", Toast.LENGTH_LONG).show();
        }
    }

    private void syncCurrentSample() {
        loadBootstrapAndMaybeChoose(false, true);
    }

    private String rdEndpoint() {
        String stored = getSharedPreferences("xio_host", MODE_PRIVATE)
                .getString("rd_endpoint", FlujoGateway.DEFAULT_ENDPOINT);
        String value = stored == null ? "" : stored.trim();
        if (value.isEmpty()) value = FlujoGateway.DEFAULT_ENDPOINT;
        while (value.endsWith("/")) value = value.substring(0, value.length() - 1);
        String suffix = "/api/plugins/rd_field";
        return value.endsWith(suffix) ? value : value + suffix;
    }

    private String xioHostRoot() {
        String endpoint = rdEndpoint();
        String suffix = "/api/plugins/rd_field";
        return endpoint.endsWith(suffix) ? endpoint.substring(0, endpoint.length() - suffix.length()) : endpoint;
    }

    private void showHostDialog() {
        EditText input = eventInput("http://host:5000 o URL completa de rd_field", xioHostRoot());
        new AlertDialog.Builder(this)
                .setTitle("Host XIO-RD")
                .setMessage("Por defecto usa este Xiaomi (127.0.0.1). Si un PC ejecuta XIO, escribe su dirección LAN; no se agregan tokens.")
                .setView(input)
                .setNegativeButton("CANCELAR", null)
                .setNeutralButton("XIAOMI", (dialog, which) -> {
                    getSharedPreferences("xio_host", MODE_PRIVATE).edit().remove("rd_endpoint").apply();
                    Toast.makeText(this, "Host XIO-RD: Xiaomi local", Toast.LENGTH_SHORT).show();
                })
                .setPositiveButton("GUARDAR", (dialog, which) -> {
                    String value = input.getText() == null ? "" : input.getText().toString().trim();
                    if (!value.startsWith("http://") && !value.startsWith("https://")) {
                        Toast.makeText(this, "El host debe comenzar con http:// o https://", Toast.LENGTH_LONG).show();
                        return;
                    }
                    getSharedPreferences("xio_host", MODE_PRIVATE).edit().putString("rd_endpoint", value).apply();
                    Toast.makeText(this, "Host XIO-RD guardado", Toast.LENGTH_SHORT).show();
                    loadBootstrapAndMaybeChoose(true, false);
                })
                .show();
    }

    private void loadBootstrapAndMaybeChoose(boolean forcePicker, boolean syncAfter) {
        Toast.makeText(this, "⇧  consultando XIO-RD…", Toast.LENGTH_SHORT).show();
        flujo.loadBootstrap(rdEndpoint(), "", result -> {
            if (!result.isSuccess()) {
                Toast.makeText(this, "XIO-RD · sin conexión", Toast.LENGTH_LONG).show();
                if (forcePicker) showCreateEventDialog(syncAfter);
                return;
            }
            try {
                JSONArray events = mergeLocalEvents(result.response.optJSONArray("events"), result.response.optJSONArray("xioEvents"));
                int current = indexOfEvent(events, engine.snapshot().eventId);
                if (current >= 0) applyEventContext(events.optJSONObject(current));
                if (forcePicker || current < 0) showEventPicker(events, current, syncAfter);
                else syncCurrentEventThenSample();
            } catch (Exception error) {
                Toast.makeText(this, "XIO-RD · catálogo inválido", Toast.LENGTH_LONG).show();
            }
        });
    }

    private JSONArray mergeLocalEvents(JSONArray remoteEvents, JSONArray remoteXioEvents) {
        JSONArray merged = new JSONArray();
        if (remoteEvents != null) {
            for (int i = 0; i < remoteEvents.length(); i++) {
                JSONObject item = remoteEvents.optJSONObject(i);
                if (item != null) merged.put(item);
            }
        }
        if (remoteXioEvents != null) {
            for (int i = 0; i < remoteXioEvents.length(); i++) {
                JSONObject source = remoteXioEvents.optJSONObject(i);
                if (source == null) continue;
                String id = source.optString("client_event_id", source.optString("clientEventId", ""));
                if (id.isEmpty() || indexOfEvent(merged, id) >= 0) continue;
                try {
                    JSONObject item = new JSONObject();
                    item.put("event_id", id);
                    item.put("event_label_candidate", source.optString("event_name", source.optString("eventName", id)));
                    item.put("link_review_status", source.optString("review_status", source.optString("reviewStatus", "")));
                    item.put("event_origin", "xio_app");
                    JSONArray producers = new JSONArray();
                    String producerName = source.optString("producer_name", source.optString("producer", "")).trim();
                    if (!producerName.isEmpty()) producers.put(new JSONObject().put("productora_slug", producerName));
                    item.put("productoras", producers);
                    merged.put(item);
                } catch (Exception ignored) { }
            }
        }
        return merged;
    }

    private EditText eventInput(String hint, String value) {
        EditText input = new EditText(this);
        input.setHint(hint);
        input.setSingleLine(true);
        input.setText(value == null ? "" : value);
        input.setTextColor(TEXT);
        input.setHintTextColor(MUTED);
        input.setPadding(dp(10), dp(4), dp(10), dp(4));
        return input;
    }

    private void showCreateEventDialog(boolean syncAfter) {
        new AlertDialog.Builder(this)
                .setTitle("Evento no disponible")
                .setMessage("XIO-RD no crea eventos desde la mesa. El evento debe existir en la base RD del host y aparecer en el catálogo antes de registrar o sincronizar muestras.")
                .setPositiveButton("REINTENTAR", (dialog, which) -> loadBootstrapAndMaybeChoose(true, syncAfter))
                .setNegativeButton("CERRAR", null)
                .show();
    }

    private JSONArray commaArray(String raw) {
        JSONArray result = new JSONArray();
        if (raw == null) return result;
        for (String value : raw.split(",")) {
            String clean = value.trim();
            if (!clean.isEmpty()) result.put(clean);
        }
        return result;
    }

    private void saveNewEvent(String name, String venue, String producer, String startDate,
                              String endDate, String djs, String sources, String flyerRef,
                              String flyerSha256, boolean syncAfter) {
        String eventName = name == null ? "" : name.trim();
        if (eventName.isEmpty()) {
            Toast.makeText(this, "El nombre del evento es obligatorio", Toast.LENGTH_LONG).show();
            return;
        }
        String eventId = "xio-" + UUID.randomUUID();
        String cleanVenue = venue == null ? "" : venue.trim();
        String cleanProducer = producer == null ? "" : producer.trim();
        String cleanStart = startDate == null ? "" : startDate.trim();
        String cleanEnd = endDate == null ? "" : endDate.trim();
        String cleanFlyerRef = flyerRef == null ? "" : flyerRef.trim();
        String cleanFlyerSha256 = flyerSha256 == null ? "" : flyerSha256.trim().toLowerCase(Locale.ROOT);
        JSONArray djArray = commaArray(djs);
        JSONObject triangulation = new JSONObject();
        try {
            JSONArray sourceArray = commaArray(sources);
            if (sourceArray.length() > 0) triangulation.put("sources", sourceArray);
            database.upsertEvent(eventId, eventName, cleanVenue, cleanProducer, cleanStart, cleanEnd,
                    djArray.toString(), triangulation.toString(), cleanFlyerRef, cleanFlyerSha256, "pending");
            engine.setEventId(eventId);
            eventLabel = eventName;
            eventProducer = cleanProducer.isEmpty() ? "" : capitalize(cleanProducer);
            eventContextPending = true;
            getSharedPreferences("xio_event_context", MODE_PRIVATE).edit()
                    .putString("event_id", eventId)
                    .putString("event_label", eventLabel)
                    .putString("event_producer", eventProducer)
                    .putBoolean("pending", true)
                    .apply();
            persist();
            render();
            JSONObject payload = new JSONObject();
            payload.put("clientEventId", eventId);
            payload.put("eventName", eventName);
            payload.put("venue", cleanVenue);
            payload.put("producer", cleanProducer);
            payload.put("startDate", cleanStart);
            payload.put("endDate", cleanEnd);
            payload.put("djs", djArray);
            payload.put("triangulation", triangulation);
            payload.put("flyerRef", cleanFlyerRef);
            payload.put("flyerSha256", cleanFlyerSha256);
            flujo.syncEvent(payload, rdEndpoint(), "", result -> {
                if (result.isSuccess()) {
                    String review = result.response.optString("reviewStatus", "pendiente_revision_humana");
                    database.markEventSynced(eventId, review);
                    if (eventId.equals(engine.snapshot().eventId)) {
                        eventContextPending = !"confirmado".equalsIgnoreCase(review);
                        render();
                    }
                    Toast.makeText(this, "XIO-RD ✓ evento guardado", Toast.LENGTH_LONG).show();
                    if (syncAfter) sendCurrentSample();
                } else {
                    Toast.makeText(this, "Evento local ✓ · sincronización pendiente", Toast.LENGTH_LONG).show();
                }
            });
        } catch (Exception error) {
            Toast.makeText(this, "No se pudo guardar el evento local", Toast.LENGTH_LONG).show();
        }
    }

    private RdFieldDb.EventRow localEvent(String id) {
        for (RdFieldDb.EventRow row : database.recentEvents()) {
            if (id != null && id.equals(row.id)) return row;
        }
        return null;
    }

    private JSONObject eventPayload(RdFieldDb.EventRow row) throws Exception {
        JSONObject payload = new JSONObject();
        payload.put("clientEventId", row.id);
        payload.put("eventName", row.name == null ? row.id : row.name);
        payload.put("venue", row.venue == null ? "" : row.venue);
        payload.put("producer", row.producer == null ? "" : row.producer);
        payload.put("startDate", row.startDate == null ? "" : row.startDate);
        payload.put("endDate", row.endDate == null ? "" : row.endDate);
        payload.put("djs", row.djsJson == null || row.djsJson.trim().isEmpty() ? new JSONArray() : new JSONArray(row.djsJson));
        payload.put("triangulation", row.triangulationJson == null || row.triangulationJson.trim().isEmpty() ? new JSONObject() : new JSONObject(row.triangulationJson));
        payload.put("flyerRef", row.flyerRef == null ? "" : row.flyerRef);
        payload.put("flyerSha256", row.flyerSha256 == null ? "" : row.flyerSha256);
        payload.put("reviewStatus", row.reviewStatus == null ? "pendiente_revision_humana" : row.reviewStatus);
        return payload;
    }

    private void syncCurrentEventThenSample() {
        // The host catalog is authoritative. A local row may be a legacy draft
        // from an older build, but it must never be re-sent as an implicit event
        // after the RD endpoint has accepted only exact host eventRefs.
        sendCurrentSample();
    }

    private void showEventPicker(JSONArray events, int selected, boolean syncAfter) {
        if (events == null || events.length() == 0) {
            showCreateEventDialog(syncAfter);
            return;
        }
        Map<String, List<Integer>> byProducer = new LinkedHashMap<>();
        Map<String, Boolean> pendingProducer = new LinkedHashMap<>();
        String[] ids = new String[events.length()];
        String[] labels = new String[events.length()];
        try {
            for (int i = 0; i < events.length(); i++) {
                JSONObject item = events.getJSONObject(i);
                ids[i] = item.optString("event_id", "");
                String label = item.optString("event_label_candidate", ids[i]);
                if (label.trim().isEmpty()) label = ids[i];
                String review = item.optString("link_review_status", "");
                if (!"APROBADO".equalsIgnoreCase(review)) label += "  ·  ⏳";
                labels[i] = label;
                JSONArray producers = item.optJSONArray("productoras");
                String producer = "sin productora vinculada";
                if (producers != null && producers.length() > 0) {
                    JSONObject first = producers.optJSONObject(0);
                    if (first != null && !first.optString("productora_slug", "").trim().isEmpty()) producer = first.optString("productora_slug");
                }
                if (producers != null && producers.length() > 1) producer += " +" + (producers.length() - 1);
                boolean logoLoaded = false;
                if (producers != null) {
                    for (int producerIndex = 0; producerIndex < producers.length(); producerIndex++) {
                        JSONObject producerItem = producers.optJSONObject(producerIndex);
                        if (producerItem != null && producerItem.optBoolean("logo_loaded", false)) {
                            logoLoaded = true;
                            break;
                        }
                    }
                }
                producer = (logoLoaded ? "(LOGO) " : "(SIN LOGO) ") + producer;
                List<Integer> members = byProducer.get(producer);
                if (members == null) { members = new ArrayList<>(); byProducer.put(producer, members); }
                members.add(i);
                boolean pending = true;
                if (producers != null && producers.length() > 0) {
                    JSONObject first = producers.optJSONObject(0);
                    pending = first == null || !"APROBADO".equalsIgnoreCase(first.optString("estado_revision", ""));
                }
                pendingProducer.put(producer, pendingProducer.containsKey(producer) ? pendingProducer.get(producer) || pending : pending);
            }
        } catch (Exception error) {
            Toast.makeText(this, "XIO-RD · catálogo inválido", Toast.LENGTH_LONG).show();
            return;
        }
        LinearLayout grouped = new LinearLayout(this);
        grouped.setOrientation(LinearLayout.VERTICAL);
        grouped.setPadding(dp(18), 0, dp(18), 0);
        ScrollView scroll = new ScrollView(this);
        scroll.addView(grouped);
        AlertDialog dialog = new AlertDialog.Builder(this)
                .setTitle("Productora  /  evento")
                .setView(scroll)
                .setNegativeButton("CERRAR", null)
                .create();
        TextView hostOnly = text("Los eventos se preparan en el host RD; esta mesa sólo permite seleccionar uno existente.", 11, MUTED);
        hostOnly.setPadding(0, dp(8), 0, dp(4));
        grouped.addView(hostOnly, new LinearLayout.LayoutParams(-1, dp(48)));
        if (byProducer.isEmpty()) {
            TextView placeholder = text("El host RD no entregó eventos preparados en este snapshot.", 12, AMBER);
            placeholder.setPadding(0, dp(12), 0, dp(12));
            grouped.addView(placeholder, new LinearLayout.LayoutParams(-1, dp(72)));
        }
        for (Map.Entry<String, List<Integer>> group : byProducer.entrySet()) {
            String pendingLabel = Boolean.TRUE.equals(pendingProducer.get(group.getKey())) ? "  ·  candidato" : "";
            TextView producer = text(capitalize(group.getKey()) + "  ·  " + group.getValue().size() + pendingLabel, 12, AMBER);
            producer.setTypeface(null, Typeface.BOLD);
            producer.setPadding(0, dp(12), 0, dp(4));
            grouped.addView(producer, new LinearLayout.LayoutParams(-1, dp(40)));
            for (Integer index : group.getValue()) {
                Button event = actionButton(labels[index], ids[index].equals(engine.snapshot().eventId) ? TEAL : SURFACE, ids[index].equals(engine.snapshot().eventId) ? BG : TEXT);
                event.setGravity(Gravity.START | Gravity.CENTER_VERTICAL);
                event.setTextSize(12);
                event.setContentDescription("Evento " + labels[index]);
                grouped.addView(event, new LinearLayout.LayoutParams(-1, dp(48)));
                event.setOnClickListener(view -> {
                    String eventId = ids[index];
                    if (eventId == null || eventId.trim().isEmpty()) return;
                    try { applyEventContext(events.getJSONObject(index)); } catch (Exception ignored) { }
                    engine.setEventId(eventId);
                    persist();
                    dialog.dismiss();
                    render();
                    if (syncAfter) sendCurrentSample();
                });
            }
        }
        dialog.show();
    }

    private String capitalize(String value) {
        if (value == null || value.trim().isEmpty()) return "Sin productora vinculada";
        String normalized = value.replace('_', ' ').trim();
        return normalized.toUpperCase(Locale.ROOT);
    }

    private void applyEventContext(JSONObject item) {
        if (item == null) return;
        eventLabel = item.optString("event_label_candidate", "").trim();
        eventContextPending = !"APROBADO".equalsIgnoreCase(item.optString("link_review_status", ""));
        eventProducer = "";
        JSONArray producers = item.optJSONArray("productoras");
        if (producers != null && producers.length() > 0) {
            JSONObject first = producers.optJSONObject(0);
            if (first != null) eventProducer = capitalize(first.optString("productora_slug", ""));
            if (producers.length() > 1) eventProducer += " +" + (producers.length() - 1);
        }
        getSharedPreferences("xio_event_context", MODE_PRIVATE).edit()
                .putString("event_id", item.optString("event_id", ""))
                .putString("event_label", eventLabel)
                .putString("event_producer", eventProducer)
                .putBoolean("pending", eventContextPending)
                .apply();
    }

    private String eventContextText(SampleSession sample) {
        String base = eventLabel.isEmpty() ? sample.eventId : eventProducer.isEmpty() ? eventLabel : eventProducer + " > " + eventLabel;
        return eventContextPending && !eventLabel.isEmpty() ? base + "  ·  ⏳" : base;
    }

    private int indexOfEvent(JSONArray events, String eventId) {
        if (events == null || eventId == null) return -1;
        for (int i = 0; i < events.length(); i++) {
            JSONObject item = events.optJSONObject(i);
            if (item != null && eventId.equals(item.optString("event_id"))) return i;
        }
        return -1;
    }

    private void sendCurrentSample() {
        SampleSession sample = engine.snapshot();
        Toast.makeText(this, "⇧  enviando a XIO-RD…", Toast.LENGTH_SHORT).show();
        flujo.syncSample(sample, rdEndpoint(), "", result -> {
            if (result.isSuccess()) {
                boolean duplicate = result.response.optBoolean("duplicate", false);
                Toast.makeText(this, "XIO-RD ✓  " + sample.code + (duplicate ? " · actualizado" : " · recibido"), Toast.LENGTH_LONG).show();
            } else {
                Toast.makeText(this, "XIO-RD · sin conexión", Toast.LENGTH_LONG).show();
            }
        });
    }

    @Override protected void onDestroy() {
        if (flujo != null) flujo.shutdown();
        if (database != null) database.close();
        super.onDestroy();
    }

    private final class ColorRampView extends View {
        private final int[] hueColors = {0xffff3b30, 0xffff2dce, 0xff5b5ce2, 0xff00a7ff, 0xff00bd83, 0xffffc107, 0xffff3b30};
        private final float[] huePositions = {0f, .17f, .34f, .51f, .68f, .84f, 1f};
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint marker = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final RampAction action;
        private Runnable onCommit;
        private float selectedX = -1f;
        private float selectedY = -1f;
        private int selectedColor = Color.TRANSPARENT;

        ColorRampView(android.content.Context context, String initial, RampAction action) {
            super(context);
            this.action = action;
            setFocusable(true);
            if (initial != null && initial.startsWith("#")) {
                try { selectedColor = Color.parseColor(initial); } catch (IllegalArgumentException ignored) { selectedColor = Color.TRANSPARENT; }
            }
        }

        void setOnCommit(Runnable commit) { onCommit = commit; }

        @Override protected void onSizeChanged(int width, int height, int oldWidth, int oldHeight) {
            if (selectedColor == Color.TRANSPARENT || width <= 1 || height <= 1) return;
            // Find the marker in the same RGB ramp that is rendered and used
            // by colorAt(). HSV coordinates are not equivalent to the RGB
            // interpolation between the visible hue stops.
            float best = Float.MAX_VALUE;
            int steps = 64;
            for (int xi = 0; xi <= steps; xi++) for (int yi = 0; yi <= steps; yi++) {
                float x = (width - 1) * xi / (float) steps;
                float y = (height - 1) * yi / (float) steps;
                int candidate = colorAt(x, y);
                float distance = square(Color.red(candidate) - Color.red(selectedColor))
                        + square(Color.green(candidate) - Color.green(selectedColor))
                        + square(Color.blue(candidate) - Color.blue(selectedColor));
                if (distance < best) { best = distance; selectedX = x; selectedY = y; }
            }
        }

        private float square(float value) { return value * value; }

        @Override protected void onDraw(Canvas canvas) {
            super.onDraw(canvas);
            int width = getWidth();
            int height = getHeight();
            if (width <= 1 || height <= 1) return;
            paint.setShader(new LinearGradient(0, 0, width, 0, hueColors, huePositions, Shader.TileMode.CLAMP));
            canvas.drawRect(0, 0, width, height, paint);
            paint.setShader(null);
            canvas.save();
            canvas.clipRect(0, 0, width, height / 2f);
            paint.setShader(new LinearGradient(0, 0, 0, height / 2f, 0xffffffff, 0x00ffffff, Shader.TileMode.CLAMP));
            canvas.drawRect(0, 0, width, height / 2f, paint);
            canvas.restore();
            paint.setShader(null);
            canvas.save();
            canvas.clipRect(0, height / 2f, width, height);
            paint.setShader(new LinearGradient(0, height / 2f, 0, height, 0x00000000, 0xff000000, Shader.TileMode.CLAMP));
            canvas.drawRect(0, height / 2f, width, height, paint);
            canvas.restore();
            paint.setShader(null);
            if (selectedX >= 0 && selectedY >= 0) {
                marker.setStyle(Paint.Style.FILL);
                marker.setColor(selectedColor);
                canvas.drawCircle(selectedX, selectedY, dp(9), marker);
                marker.setStyle(Paint.Style.STROKE);
                marker.setStrokeWidth(dp(2));
                marker.setColor(readableOn(selectedColor));
                canvas.drawCircle(selectedX, selectedY, dp(10), marker);
            }
        }

        @Override public boolean onTouchEvent(MotionEvent event) {
            if (event.getAction() == MotionEvent.ACTION_DOWN || event.getAction() == MotionEvent.ACTION_MOVE || event.getAction() == MotionEvent.ACTION_UP) {
                float x = Math.max(0, Math.min(getWidth() - 1, event.getX()));
                float y = Math.max(0, Math.min(getHeight() - 1, event.getY()));
                selectedX = x; selectedY = y; selectedColor = colorAt(x, y);
                invalidate();
                if (action != null) action.selected(hexForColor(selectedColor));
                if (event.getAction() == MotionEvent.ACTION_UP && onCommit != null) onCommit.run();
                return true;
            }
            return true;
        }

        private int colorAt(float x, float y) {
            float position = x / Math.max(1f, getWidth() - 1f);
            int pure = hueColorAt(position);
            if (y <= getHeight() / 2f) return blend(Color.WHITE, pure, y / Math.max(1f, getHeight() / 2f));
            return blend(pure, Color.BLACK, (y - getHeight() / 2f) / Math.max(1f, getHeight() / 2f));
        }

        private int hueColorAt(float position) {
            float p = Math.max(0f, Math.min(1f, position));
            for (int i = 1; i < huePositions.length; i++) {
                if (p <= huePositions[i]) {
                    float span = huePositions[i] - huePositions[i - 1];
                    float amount = span <= 0f ? 0f : (p - huePositions[i - 1]) / span;
                    return blend(hueColors[i - 1], hueColors[i], amount);
                }
            }
            return hueColors[hueColors.length - 1];
        }

        private int blend(int from, int to, float amount) {
            float t = Math.max(0f, Math.min(1f, amount));
            return Color.rgb(Math.round(Color.red(from) + (Color.red(to) - Color.red(from)) * t), Math.round(Color.green(from) + (Color.green(to) - Color.green(from)) * t), Math.round(Color.blue(from) + (Color.blue(to) - Color.blue(from)) * t));
        }
    }

    private interface RampAction { void selected(String hex); }

    private String hexForColor(int color) {
        return String.format(Locale.US, "#%02X%02X%02X", Color.red(color), Color.green(color), Color.blue(color));
    }

    private LinearLayout card() { LinearLayout card = new LinearLayout(this); card.setOrientation(LinearLayout.VERTICAL); card.setPadding(dp(11), dp(10), dp(11), dp(10)); card.setBackgroundColor(SURFACE); return card; }
    private View divider() { View line = new View(this); line.setBackgroundColor(LINE); line.setLayoutParams(new LinearLayout.LayoutParams(-1, dp(1))); return line; }
    private TextView sectionLabel(String value) { TextView view = text(value, 10, TEAL); view.setTypeface(null, Typeface.BOLD); view.setPadding(0, dp(10), 0, dp(5)); return view; }
    private TextView heading(String value) { TextView view = text(value, 24, TEXT); view.setTypeface(null, Typeface.BOLD); view.setPadding(0, 0, 0, dp(5)); return view; }
    private TextView body(String value) { TextView view = text(value, 12, MUTED); view.setPadding(0, 0, 0, dp(8)); return view; }
    private TextView text(String value, int size, int color) { TextView view = new TextView(this); view.setText(value); view.setTextSize(size); view.setTextColor(color); view.setGravity(Gravity.START | Gravity.CENTER_VERTICAL); return view; }
    private Button actionButton(String label, int background, int foreground) { Button button = new Button(this); button.setText(label); button.setTextSize(11); button.setTextColor(foreground); button.setAllCaps(false); button.setGravity(Gravity.CENTER); button.setPadding(dp(6), 0, dp(6), 0); button.setMinHeight(0); button.setMinimumHeight(0); if (background != Color.TRANSPARENT) button.setBackgroundColor(background); return button; }
    private Button iconButton(String icon, String description, int background, int foreground) { Button button = actionButton(icon, background, foreground); button.setContentDescription(description); button.setTextSize(18); return button; }
    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }
}
