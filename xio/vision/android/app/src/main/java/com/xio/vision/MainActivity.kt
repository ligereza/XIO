package com.xio.vision

import android.Manifest
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.FileProvider
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.security.MessageDigest
import java.text.DateFormat
import java.util.Date
import java.util.Locale
import java.util.UUID
import java.util.concurrent.Executors

/**
 * Capture workflow for dataset creation:
 * capture -> model proposal + pixel features -> human annotation -> training candidate.
 */
class MainActivity : AppCompatActivity() {
    private val executor = Executors.newSingleThreadExecutor()
    private lateinit var status: TextView
    private lateinit var substanceField: EditText
    private lateinit var formField: EditText
    private lateinit var colorField: EditText
    private lateinit var markingField: EditText
    private lateinit var notesField: EditText
    private lateinit var annotateButton: Button
    private lateinit var store: ProposalStore
    private lateinit var database: CaptureDatabase
    private var classifier: OfflineImageClassifier? = null
    private var currentCaptureId: String? = null
    private var pendingCaptureFile: File? = null

    private val requestCamera = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) {
            status.text = "Permiso concedido. Abriendo cámara…"
            launchCapture()
        } else {
            status.text = "Permiso de cámara denegado; no se capturó ninguna imagen."
        }
    }

    private val capture = registerForActivityResult(ActivityResultContracts.TakePicture()) { success: Boolean ->
        val sourceFile = pendingCaptureFile
        pendingCaptureFile = null
        if (!success || sourceFile == null || !sourceFile.exists()) {
            status.text = "Captura cancelada; no se generó registro."
            return@registerForActivityResult
        }
        status.text = "Imagen recibida; creando fila de dataset offline…"
        val eventId = "xio-${UUID.randomUUID()}"
        val capturedAt = System.currentTimeMillis()
        executor.execute {
            runCatching {
                val bitmap = decodeForInference(sourceFile)
                val proposal = classifier!!.classify(eventId, bitmap, capturedAt)
                val savedImage = storeCapturedFile(sourceFile, proposal.proposalId)
                database.insertCapture(proposal, savedImage.relativePath, savedImage.sha256)
                store.append(proposal)
                sourceFile.delete()
                runOnUiThread {
                    currentCaptureId = proposal.proposalId
                    colorField.setText(proposal.visualAttributes.dominantColor)
                    annotateButton.isEnabled = true
                    val labels = proposal.labels.joinToString("\n") {
                        "• ${it.label}: ${"%.3f".format(Locale.US, it.score)}"
                    }
                    val visual = proposal.visualAttributes
                    status.text = "Registro creado: candidato pendiente de anotación\n" +
                        "ID: ${proposal.proposalId}\n" +
                        "Evento: ${proposal.eventId}\n" +
                        "Hora: ${DateFormat.getDateTimeInstance().format(Date(proposal.capturedAtEpochMs))}\n" +
                        "Color medido: ${visual.dominantColor} " +
                        "RGB(${visual.averageRed}, ${visual.averageGreen}, ${visual.averageBlue})\n" +
                        "Brillo: ${"%.3f".format(Locale.US, visual.averageBrightness)} | " +
                        "Saturación: ${"%.3f".format(Locale.US, visual.averageSaturation)}\n\n" +
                        "Predicción genérica:\n$labels\n\n" +
                        "Completa la anotación humana para incorporarlo como ejemplo de entrenamiento."
                }
            }.onFailure { error ->
                runOnUiThread { status.text = "Error al crear registro: ${error.message}" }
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        store = ProposalStore(this)
        database = CaptureDatabase(this)

        status = TextView(this).apply {
            text = "Listo. Cada foto crea una fila local y no envía imágenes."
            textSize = 16f
            setPadding(32, 24, 32, 24)
        }
        val captureButton = Button(this).apply {
            text = "Capturar muestra para dataset"
            setOnClickListener {
                if (checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
                    launchCapture()
                } else {
                    requestCamera.launch(Manifest.permission.CAMERA)
                }
            }
        }

        substanceField = field("Sustancia o etiqueta humana (opcional)")
        formField = field("Forma o molde: pastilla, polvo, cristal…")
        colorField = field("Color observado")
        markingField = field("Marca, sello o estampado")
        notesField = field("Notas de la persona que testea")
        annotateButton = Button(this).apply {
            text = "Guardar anotación y candidato de entrenamiento"
            isEnabled = false
            setOnClickListener { saveAnnotation() }
        }

        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            addView(captureButton)
            addView(status)
            addView(section("ANOTACIÓN HUMANA / GROUND TRUTH"))
            addView(substanceField)
            addView(formField)
            addView(colorField)
            addView(markingField)
            addView(notesField)
            addView(annotateButton)
        }
        setContentView(ScrollView(this).apply { addView(content) })

        runCatching { classifier = OfflineImageClassifier(this) }
            .onFailure { status.text = "Modelo no disponible: ${it.message}" }
    }

    private fun saveAnnotation() {
        val captureId = currentCaptureId ?: return
        val substance = substanceField.text.toString()
        val form = formField.text.toString()
        val color = colorField.text.toString()
        val marking = markingField.text.toString()
        val notes = notesField.text.toString()
        executor.execute {
            runCatching {
                database.addHumanAnnotation(captureId, substance, form, color, marking, notes)
                store.appendAnnotation(captureId, substance, form, color, marking, notes)
                runOnUiThread {
                    annotateButton.isEnabled = false
                    status.text = "Anotación guardada. Captura marcada como candidata para entrenamiento; " +
                        "la aprobación y división train/validation/test quedan pendientes."
                }
            }.onFailure { error ->
                runOnUiThread { status.text = "Error al guardar anotación: ${error.message}" }
            }
        }
    }

    private fun field(hintText: String): EditText = EditText(this).apply {
        hint = hintText
        setPadding(32, 12, 32, 12)
        minLines = 1
    }

    private fun section(text: String): TextView = TextView(this).apply {
        this.text = text
        textSize = 14f
        setPadding(32, 28, 32, 8)
    }

    private fun launchCapture() {
        val file = File(cacheDir, "camera_${UUID.randomUUID()}.jpg")
        pendingCaptureFile = file
        val uri: Uri = FileProvider.getUriForFile(this, "com.xio.vision.fileprovider", file)
        capture.launch(uri)
    }

    private fun decodeForInference(source: File): Bitmap {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(source.absolutePath, bounds)
        var sample = 1
        while (bounds.outWidth / sample > 1600 || bounds.outHeight / sample > 1600) {
            sample *= 2
        }
        val options = BitmapFactory.Options().apply { inSampleSize = sample }
        return BitmapFactory.decodeFile(source.absolutePath, options)
            ?: error("No se pudo decodificar la captura")
    }

    private fun storeCapturedFile(source: File, captureId: String): SavedImage {
        val dir = File(filesDir, "captures").apply { mkdirs() }
        val file = File(dir, "$captureId.jpg")
        source.inputStream().use { input ->
            FileOutputStream(file).use { output -> input.copyTo(output) }
        }
        val digest = MessageDigest.getInstance("SHA-256")
        FileInputStream(file).use { input ->
            val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
            while (true) {
                val read = input.read(buffer)
                if (read <= 0) break
                digest.update(buffer, 0, read)
            }
        }
        return SavedImage("captures/${file.name}", digest.digest().toHex())
    }

    override fun onDestroy() {
        classifier?.close()
        database.close()
        executor.shutdownNow()
        super.onDestroy()
    }

    private data class SavedImage(val relativePath: String, val sha256: String)

    private fun ByteArray.toHex(): String = joinToString("") { "%02x".format(it) }
}
