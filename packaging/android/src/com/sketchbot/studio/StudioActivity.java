package com.sketchbot.studio;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ClipData;
import android.content.Intent;
import android.graphics.Color;
import android.hardware.input.InputManager;
import android.net.Uri;
import android.os.Bundle;
import android.provider.MediaStore;
import android.view.InputDevice;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.WindowManager;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.InputMethodManager;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.PopupMenu;
import android.widget.Toast;
import org.json.JSONArray;
import org.json.JSONObject;
import java.net.URI;
import java.util.Locale;

public final class StudioActivity extends Activity {
    private static final String SETUP = "https://eoinjordan.github.io/unoq-braccio-sketchbot/";
    private static final int PHOTO_REQUEST = 41;
    private WebView web;
    private EditText address;
    private ValueCallback<Uri[]> fileCallback;
    private Uri cameraPhoto;
    private String deviceOrigin = "";
    private final float[] axes = new float[4];
    private final boolean[] buttons = new boolean[16];
    private boolean nativeController = false;
    private int controllerId = -1;
    private InputManager inputManager;
    private final InputManager.InputDeviceListener controllerListener = new InputManager.InputDeviceListener() {
        @Override public void onInputDeviceAdded(int deviceId) { }
        @Override public void onInputDeviceChanged(int deviceId) { }
        @Override public void onInputDeviceRemoved(int deviceId) {
            if (deviceId == controllerId) {
                releaseControls();
                if (web != null) web.evaluateJavascript("window.dispatchEvent(new Event('gamepaddisconnected'));", null);
            }
        }
    };

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        inputManager = (InputManager)getSystemService(INPUT_SERVICE);
        inputManager.registerInputDeviceListener(controllerListener, null);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.rgb(247, 250, 248));
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            view.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            return insets;
        });
        LinearLayout toolbar = new LinearLayout(this);
        toolbar.setPadding(12, 8, 12, 8);
        address = new EditText(this);
        address.setSingleLine(true);
        address.setHint("UNO Q address");
        address.setInputType(android.text.InputType.TYPE_CLASS_TEXT | android.text.InputType.TYPE_TEXT_VARIATION_URI);
        address.setImeOptions(EditorInfo.IME_ACTION_GO);
        address.setOnEditorActionListener((view, action, event) -> {
            if (action != EditorInfo.IME_ACTION_GO) return false;
            connect(address.getText().toString());
            return true;
        });
        toolbar.addView(address, new LinearLayout.LayoutParams(0, 56 * (int)Math.max(1, getResources().getDisplayMetrics().density), 1));
        Button connect = new Button(this); connect.setText("Connect");
        connect.setOnClickListener(view -> connect(address.getText().toString()));
        toolbar.addView(connect);
        android.widget.ImageButton menu = new android.widget.ImageButton(this);
        menu.setImageResource(android.R.drawable.ic_menu_more);
        menu.setContentDescription("Device menu");
        menu.setOnClickListener(view -> {
            PopupMenu popup = new PopupMenu(this, menu);
            popup.getMenu().add("Setup & downloads");
            popup.getMenu().add("Open in browser");
            popup.getMenu().add("Forget device");
            popup.setOnMenuItemClickListener(item -> {
                releaseControls();
                if (item.getTitle().equals("Setup & downloads")) web.loadUrl(SETUP);
                else if (item.getTitle().equals("Forget device")) {
                    getPreferences(MODE_PRIVATE).edit().remove("device").apply();
                    deviceOrigin = ""; address.setText(""); web.loadUrl(SETUP);
                } else external(web.getUrl());
                return true;
            });
            popup.show();
        });
        toolbar.addView(menu);
        root.addView(toolbar);
        web = new WebView(this);
        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setSupportMultipleWindows(true);
        settings.setMediaPlaybackRequiresUserGesture(true);
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                if (!request.isForMainFrame()) return false;
                return navigate(request.getUrl().toString());
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams parameters) {
                releaseControls();
                if (fileCallback != null) fileCallback.onReceiveValue(null);
                fileCallback = callback;
                cameraPhoto = null;
                Intent choose = new Intent(Intent.ACTION_OPEN_DOCUMENT);
                choose.addCategory(Intent.CATEGORY_OPENABLE); choose.setType("image/*");
                if (parameters.isCaptureEnabled()) {
                    Intent capture = new Intent(MediaStore.ACTION_IMAGE_CAPTURE);
                    if (capture.resolveActivity(getPackageManager()) != null) {
                        cameraPhoto = Uri.parse("content://com.sketchbot.studio.photos/capture.jpg");
                        capture.putExtra(MediaStore.EXTRA_OUTPUT, cameraPhoto);
                        capture.setClipData(ClipData.newRawUri("Sketchbot camera", cameraPhoto));
                        capture.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
                        choose = capture;
                    }
                }
                try { startActivityForResult(choose, PHOTO_REQUEST); }
                catch (RuntimeException error) { callback.onReceiveValue(null); fileCallback = null; toast("No camera or photo picker available"); }
                return true;
            }
            @Override public boolean onCreateWindow(WebView view, boolean dialog, boolean gesture, android.os.Message message) {
                if (!gesture) return false;
                WebView popup = new WebView(StudioActivity.this);
                popup.setWebViewClient(new WebViewClient() {
                    @Override public boolean shouldOverrideUrlLoading(WebView child, WebResourceRequest request) {
                        String target = request.getUrl().toString();
                        try {
                            String origin = normalAddress(target);
                            if (target.startsWith("http://") || origin.endsWith(".ts.net")) connect(origin);
                            else external(target);
                        } catch (Exception error) { external(target); }
                        child.destroy(); return true;
                    }
                });
                ((WebView.WebViewTransport)message.obj).setWebView(popup);
                message.sendToTarget(); return true;
            }
        });
        root.addView(web, new LinearLayout.LayoutParams(-1, 0, 1));
        setContentView(root);
        String saved = getPreferences(MODE_PRIVATE).getString("device", "");
        if (saved.isEmpty()) web.loadUrl(SETUP); else connect(saved);
    }

    private String normalAddress(String value) throws Exception {
        String input = value.trim();
        URI parsed = new URI(input.contains("://") ? input : "http://" + input);
        String scheme = parsed.getScheme();
        String host = parsed.getHost();
        if (host == null || parsed.getUserInfo() != null || !("http".equals(scheme) || "https".equals(scheme))) throw new Exception();
        host = host.toLowerCase(Locale.ROOT);
        boolean local = host.equals("localhost") || host.endsWith(".local") || host.endsWith(".lan") || host.matches("[a-z][a-z0-9-]*");
        String[] octets = host.split("\\.");
        if (octets.length == 4) {
            try {
                int first = Integer.parseInt(octets[0]), second = Integer.parseInt(octets[1]);
                local |= first == 10 || first == 127 || first == 192 && second == 168 || first == 172 && second >= 16 && second <= 31;
            } catch (NumberFormatException ignored) { }
        }
        if ("http".equals(scheme) && !local) throw new Exception();
        int port = parsed.getPort();
        if (port < 0 && "http".equals(scheme)) port = 7100;
        return new URI(scheme, null, host, port, null, null, null).toString();
    }
    private void connect(String value) {
        try {
            String origin = normalAddress(value);
            releaseControls(); deviceOrigin = origin; address.setText(origin);
            ((InputMethodManager)getSystemService(INPUT_METHOD_SERVICE)).hideSoftInputFromWindow(address.getWindowToken(), 0);
            address.clearFocus(); web.requestFocus();
            getPreferences(MODE_PRIVATE).edit().putString("device", origin).apply();
            web.loadUrl(origin + "/?event=1");
        } catch (Exception error) { toast("Use a local UNO Q address or your private HTTPS address"); }
    }
    private boolean navigate(String target) {
        try {
            URI uri = new URI(target);
            if (target.startsWith(SETUP)) return false;
            if (!deviceOrigin.isEmpty() && normalAddress(target).equals(deviceOrigin)) return false;
            if (uri.getScheme().equals("http") || uri.getScheme().equals("https")) { external(target); return true; }
        } catch (Exception ignored) { }
        return true;
    }
    private void external(String target) {
        if (target == null || !(target.startsWith("https://") || target.startsWith("http://"))) return;
        try { startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(target))); }
        catch (RuntimeException error) { toast("No browser is available"); }
    }
    private void toast(String message) { Toast.makeText(this, message, Toast.LENGTH_LONG).show(); }
    private void releaseControls() {
        if (web != null) web.evaluateJavascript("window.dispatchEvent(new Event('blur'));", null);
        nativeController = false;
        for (int index = 0; index < buttons.length; index++) buttons[index] = false;
        publishController();
    }
    @Override protected void onPause() { releaseControls(); super.onPause(); }
    @Override protected void onDestroy() {
        inputManager.unregisterInputDeviceListener(controllerListener);
        if (fileCallback != null) fileCallback.onReceiveValue(null);
        if (web != null) web.destroy();
        super.onDestroy();
    }
    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request != PHOTO_REQUEST || fileCallback == null) return;
        Uri selected = result == RESULT_OK ? (cameraPhoto != null ? cameraPhoto : data == null ? null : data.getData()) : null;
        fileCallback.onReceiveValue(selected == null ? null : new Uri[]{selected});
        fileCallback = null; cameraPhoto = null;
    }
    private void publishController() {
        if (web == null || deviceOrigin.isEmpty()) return;
        try {
            JSONObject controller = new JSONObject(); controller.put("id", "Android paired controller");
            controller.put("index", 0); controller.put("connected", nativeController);
            JSONArray axisValues = new JSONArray(); for (float value : axes) axisValues.put(value);
            JSONArray buttonValues = new JSONArray();
            for (boolean pressed : buttons) { JSONObject button = new JSONObject(); button.put("pressed", pressed); buttonValues.put(button); }
            controller.put("axes", axisValues); controller.put("buttons", buttonValues);
            web.evaluateJavascript("window.__sketchbotNativePad=" + controller.toString() + ";", null);
        } catch (Exception ignored) { }
    }
    @Override public boolean dispatchGenericMotionEvent(MotionEvent event) {
        if (event.isFromSource(InputDevice.SOURCE_JOYSTICK) && event.getAction() == MotionEvent.ACTION_MOVE) {
            nativeController = true;
            controllerId = event.getDeviceId();
            axes[0] = event.getAxisValue(MotionEvent.AXIS_X); axes[1] = event.getAxisValue(MotionEvent.AXIS_Y);
            axes[2] = event.getAxisValue(MotionEvent.AXIS_Z); axes[3] = event.getAxisValue(MotionEvent.AXIS_RZ);
            buttons[6] = event.getAxisValue(MotionEvent.AXIS_LTRIGGER) > 0.25f;
            buttons[7] = event.getAxisValue(MotionEvent.AXIS_RTRIGGER) > 0.25f;
            publishController(); return true;
        }
        return super.dispatchGenericMotionEvent(event);
    }
    @Override public boolean dispatchKeyEvent(KeyEvent event) {
        if (event.isFromSource(InputDevice.SOURCE_GAMEPAD)) {
            int index = -1;
            switch (event.getKeyCode()) {
                case KeyEvent.KEYCODE_BUTTON_A: index = 0; break;
                case KeyEvent.KEYCODE_BUTTON_B: index = 1; break;
                case KeyEvent.KEYCODE_BUTTON_X: index = 2; break;
                case KeyEvent.KEYCODE_BUTTON_Y: index = 3; break;
                case KeyEvent.KEYCODE_BUTTON_L1: index = 4; break;
                case KeyEvent.KEYCODE_BUTTON_R1: index = 5; break;
                case KeyEvent.KEYCODE_BUTTON_L2: index = 6; break;
                case KeyEvent.KEYCODE_BUTTON_R2: index = 7; break;
            }
            if (index >= 0) { nativeController = true; controllerId = event.getDeviceId(); buttons[index] = event.getAction() != KeyEvent.ACTION_UP; publishController(); return true; }
        }
        return super.dispatchKeyEvent(event);
    }
}