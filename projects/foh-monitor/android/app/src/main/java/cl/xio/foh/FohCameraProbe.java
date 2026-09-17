package cl.xio.foh;

import android.content.Context;
import android.graphics.ImageFormat;
import android.hardware.camera2.CameraAccessException;
import android.hardware.camera2.CameraCaptureSession;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CameraDevice;
import android.hardware.camera2.CameraManager;
import android.hardware.camera2.CameraMetadata;
import android.hardware.camera2.CaptureRequest;
import android.hardware.camera2.CaptureResult;
import android.hardware.camera2.TotalCaptureResult;
import android.hardware.camera2.params.StreamConfigurationMap;
import android.media.Image;
import android.media.ImageReader;
import android.os.Handler;
import android.os.HandlerThread;
import android.util.Range;
import android.util.Size;

import java.nio.ByteBuffer;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/** One capture with a FIXED exposure, to measure the light of the room.
 *
 * A rolling-shutter sensor reads its rows in sequence, so ONE frame is a time
 * series along the vertical axis: a cheap photometer. This class does not take
 * a picture to look at -- it returns the mean luminance PER ROW of the Y plane,
 * which is exactly what `xio/flicker.py` consumes, plus the numbers that make
 * the reading interpretable.
 *
 * Why it lives here and not in Termux: `termux-camera-photo` cannot fix the
 * shutter or the ISO, and with automatic exposure this measurement does not
 * exist -- the sensor compensates precisely what we are trying to see.
 *
 * `SENSOR_ROLLING_SHUTTER_SKEW` del CaptureResult es el regalo: es el tiempo
 * entre la primera y la ultima fila, asi que el tiempo de LINEA sale de
 * dividirlo por las filas, sin necesidad de calibrar contra una lampara.
 */
public final class FohCameraProbe {

    /** Exposicion por omision: 1/10000 s. Tiene que ser MUCHO mas corta que el
     * periodo del pulso que se busca; para 100 Hz (10 ms) sobra de lejos. */
    public static final long DEFAULT_EXPOSURE_NANOS = 100_000L;
    public static final int DEFAULT_SENSITIVITY = 800;

    public static final class Result {
        public final double[] rows;
        public final int width;
        public final int height;
        public final String cameraId;
        public final long exposureNanos;
        public final int sensitivity;
        public final long rollingShutterSkewNanos;
        public final boolean manualExposure;
        public final String error;

        Result(double[] rows, int width, int height, String cameraId, long exposureNanos,
               int sensitivity, long skew, boolean manualExposure, String error) {
            this.rows = rows;
            this.width = width;
            this.height = height;
            this.cameraId = cameraId;
            this.exposureNanos = exposureNanos;
            this.sensitivity = sensitivity;
            this.rollingShutterSkewNanos = skew;
            this.manualExposure = manualExposure;
            this.error = error;
        }

        static Result failed(String message) {
            return new Result(null, 0, 0, "", 0L, 0, 0L, false, message);
        }

        /** Tiempo de linea en segundos, derivado del skew. Sin skew, null. */
        public Double lineSeconds() {
            if (rollingShutterSkewNanos <= 0 || height < 2) return null;
            return rollingShutterSkewNanos / 1e9d / (height - 1);
        }
    }

    private FohCameraProbe() { }

    /** Lista las camaras que declaran control manual del sensor. */
    public static List<String> manualCameras(Context context) {
        List<String> found = new ArrayList<>();
        CameraManager manager = (CameraManager) context.getSystemService(Context.CAMERA_SERVICE);
        if (manager == null) return found;
        try {
            for (String id : manager.getCameraIdList()) {
                CameraCharacteristics characteristics = manager.getCameraCharacteristics(id);
                int[] capabilities = characteristics.get(
                        CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES);
                if (capabilities == null) continue;
                for (int capability : capabilities) {
                    if (capability == CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_MANUAL_SENSOR) {
                        found.add(id);
                        break;
                    }
                }
            }
        } catch (Exception ignored) { }
        return found;
    }

    public static Result capture(Context context, String requestedId, long exposureNanos,
                                 int sensitivity, int timeoutMs) {
        CameraManager manager = (CameraManager) context.getSystemService(Context.CAMERA_SERVICE);
        if (manager == null) return Result.failed("sin CameraManager");

        HandlerThread thread = new HandlerThread("xio-foh-camera");
        thread.start();
        Handler handler = new Handler(thread.getLooper());
        CameraDevice[] device = new CameraDevice[1];
        CameraCaptureSession[] session = new CameraCaptureSession[1];
        ImageReader[] reader = new ImageReader[1];
        try {
            String cameraId = requestedId;
            if (cameraId == null || cameraId.isEmpty()) {
                List<String> manual = manualCameras(context);
                if (manual.isEmpty()) {
                    String[] all = manager.getCameraIdList();
                    if (all.length == 0) return Result.failed("el aparato no declara camaras");
                    cameraId = all[0];
                } else {
                    cameraId = manual.get(0);
                }
            }

            CameraCharacteristics characteristics = manager.getCameraCharacteristics(cameraId);
            StreamConfigurationMap map = characteristics.get(
                    CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP);
            if (map == null) return Result.failed("sin mapa de configuracion para " + cameraId);
            Size[] sizes = map.getOutputSizes(ImageFormat.YUV_420_888);
            if (sizes == null || sizes.length == 0) {
                return Result.failed("la camara " + cameraId + " no ofrece YUV_420_888");
            }
            // La ventana de medicion es rows * tiempo_de_linea: mas filas, mas
            // ventana, y con mas ventana se resuelven frecuencias mas bajas.
            Size chosen = sizes[0];
            for (Size candidate : sizes) {
                if ((long) candidate.getWidth() * candidate.getHeight()
                        > (long) chosen.getWidth() * chosen.getHeight()) {
                    chosen = candidate;
                }
            }

            Range<Long> exposureRange = characteristics.get(
                    CameraCharacteristics.SENSOR_INFO_EXPOSURE_TIME_RANGE);
            long exposure = exposureNanos > 0 ? exposureNanos : DEFAULT_EXPOSURE_NANOS;
            if (exposureRange != null) exposure = exposureRange.clamp(exposure);
            Range<Integer> isoRange = characteristics.get(
                    CameraCharacteristics.SENSOR_INFO_SENSITIVITY_RANGE);
            int iso = sensitivity > 0 ? sensitivity : DEFAULT_SENSITIVITY;
            if (isoRange != null) iso = isoRange.clamp(iso);

            reader[0] = ImageReader.newInstance(chosen.getWidth(), chosen.getHeight(),
                    ImageFormat.YUV_420_888, 2);
            final double[][] rows = new double[1][];
            final CountDownLatch imageReady = new CountDownLatch(1);
            reader[0].setOnImageAvailableListener(source -> {
                Image image = null;
                try {
                    image = source.acquireLatestImage();
                    if (image != null) rows[0] = rowLuminance(image);
                } catch (Exception ignored) {
                } finally {
                    if (image != null) image.close();
                    imageReady.countDown();
                }
            }, handler);

            final CountDownLatch opened = new CountDownLatch(1);
            final String[] failure = new String[1];
            manager.openCamera(cameraId, new CameraDevice.StateCallback() {
                @Override public void onOpened(CameraDevice camera) {
                    device[0] = camera;
                    opened.countDown();
                }
                @Override public void onDisconnected(CameraDevice camera) {
                    failure[0] = "la camara se desconecto";
                    camera.close();
                    opened.countDown();
                }
                @Override public void onError(CameraDevice camera, int error) {
                    failure[0] = "openCamera error " + error
                            + (error == ERROR_CAMERA_IN_USE ? " (en uso por otra app)" : "");
                    camera.close();
                    opened.countDown();
                }
            }, handler);
            if (!opened.await(timeoutMs, TimeUnit.MILLISECONDS)) {
                return Result.failed("openCamera no respondio en " + timeoutMs + " ms");
            }
            if (device[0] == null) {
                return Result.failed(failure[0] == null ? "no se pudo abrir la camara" : failure[0]);
            }

            final CountDownLatch configured = new CountDownLatch(1);
            device[0].createCaptureSession(Collections.singletonList(reader[0].getSurface()),
                    new CameraCaptureSession.StateCallback() {
                        @Override public void onConfigured(CameraCaptureSession configuredSession) {
                            session[0] = configuredSession;
                            configured.countDown();
                        }
                        @Override public void onConfigureFailed(CameraCaptureSession failed) {
                            failure[0] = "la sesion de captura no se pudo configurar";
                            configured.countDown();
                        }
                    }, handler);
            if (!configured.await(timeoutMs, TimeUnit.MILLISECONDS) || session[0] == null) {
                return Result.failed(failure[0] == null ? "sesion sin configurar" : failure[0]);
            }

            CaptureRequest.Builder request = device[0].createCaptureRequest(
                    CameraDevice.TEMPLATE_STILL_CAPTURE);
            request.addTarget(reader[0].getSurface());
            // Exposicion, ISO y balance FIJOS. Con auto-exposicion la medicion
            // no existe: el sensor compensa justo lo que se quiere ver.
            request.set(CaptureRequest.CONTROL_AE_MODE, CameraMetadata.CONTROL_AE_MODE_OFF);
            request.set(CaptureRequest.CONTROL_AWB_MODE, CameraMetadata.CONTROL_AWB_MODE_OFF);
            request.set(CaptureRequest.CONTROL_AF_MODE, CameraMetadata.CONTROL_AF_MODE_OFF);
            request.set(CaptureRequest.SENSOR_EXPOSURE_TIME, exposure);
            request.set(CaptureRequest.SENSOR_SENSITIVITY, iso);
            // Sin reduccion de ruido ni realce de bordes: los dos suavizan
            // exactamente las bandas que se estan midiendo.
            request.set(CaptureRequest.NOISE_REDUCTION_MODE,
                    CameraMetadata.NOISE_REDUCTION_MODE_OFF);
            request.set(CaptureRequest.EDGE_MODE, CameraMetadata.EDGE_MODE_OFF);

            final long[] reported = new long[]{exposure, iso, 0L};
            final CountDownLatch captured = new CountDownLatch(1);
            session[0].capture(request.build(), new CameraCaptureSession.CaptureCallback() {
                @Override public void onCaptureCompleted(CameraCaptureSession s,
                                                         CaptureRequest r,
                                                         TotalCaptureResult result) {
                    Long actualExposure = result.get(CaptureResult.SENSOR_EXPOSURE_TIME);
                    Integer actualIso = result.get(CaptureResult.SENSOR_SENSITIVITY);
                    Long skew = result.get(CaptureResult.SENSOR_ROLLING_SHUTTER_SKEW);
                    if (actualExposure != null) reported[0] = actualExposure;
                    if (actualIso != null) reported[1] = actualIso;
                    if (skew != null) reported[2] = skew;
                    captured.countDown();
                }
                @Override public void onCaptureFailed(CameraCaptureSession s, CaptureRequest r,
                                                      android.hardware.camera2.CaptureFailure f) {
                    failure[0] = "la captura fallo (reason " + f.getReason() + ")";
                    captured.countDown();
                }
            }, handler);

            if (!captured.await(timeoutMs, TimeUnit.MILLISECONDS)) {
                return Result.failed("la captura no completo en " + timeoutMs + " ms");
            }
            if (!imageReady.await(timeoutMs, TimeUnit.MILLISECONDS) || rows[0] == null) {
                return Result.failed(failure[0] == null
                        ? "la imagen no llego" : failure[0]);
            }
            return new Result(rows[0], chosen.getWidth(), chosen.getHeight(), cameraId,
                    reported[0], (int) reported[1], reported[2], true, null);
        } catch (SecurityException error) {
            return Result.failed("falta el permiso de camara: pm grant cl.xio.foh "
                    + "android.permission.CAMERA");
        } catch (CameraAccessException error) {
            return Result.failed("CameraAccessException: " + error.getReason());
        } catch (Exception error) {
            return Result.failed(error.getClass().getSimpleName() + ": " + error.getMessage());
        } finally {
            try { if (session[0] != null) session[0].close(); } catch (Exception ignored) { }
            try { if (device[0] != null) device[0].close(); } catch (Exception ignored) { }
            try { if (reader[0] != null) reader[0].close(); } catch (Exception ignored) { }
            thread.quitSafely();
        }
    }

    /** Media de luminancia por fila del plano Y.
     *
     * El plano Y de YUV_420_888 ES la luminancia: no hay conversion de color
     * que pueda introducir un artefacto propio.
     */
    static double[] rowLuminance(Image image) {
        Image.Plane plane = image.getPlanes()[0];
        ByteBuffer buffer = plane.getBuffer();
        int rowStride = plane.getRowStride();
        int pixelStride = plane.getPixelStride();
        int width = image.getWidth();
        int height = image.getHeight();
        double[] rows = new double[height];
        byte[] line = new byte[rowStride];
        for (int row = 0; row < height; row++) {
            int offset = row * rowStride;
            if (offset >= buffer.limit()) break;
            buffer.position(offset);
            int available = Math.min(rowStride, buffer.remaining());
            buffer.get(line, 0, available);
            long sum = 0;
            int counted = 0;
            for (int index = 0; index + 1 <= available && counted < width; index += pixelStride) {
                sum += (line[index] & 0xff);
                counted++;
            }
            rows[row] = counted == 0 ? 0d : (double) sum / counted;
        }
        return rows;
    }
}
