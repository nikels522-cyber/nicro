package app.nicro;

import android.app.Activity;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.CookieManager;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * nicro for Android: the web panel in its own window. The panel address (with its secret path) is remembered on
 * the first start: taken from the clipboard (the panel copies it when "Download the app" is tapped), from a
 * nicro://set?url=... link, or typed in. Links to other sites (Telegram, payments, VPN apps) open outside.
 */
public class MainActivity extends Activity {
    private static final Pattern PANEL_URL = Pattern.compile("https?://[^\\s/]+(:\\d+)?/[0-9a-f]{8,}/?", Pattern.CASE_INSENSITIVE);
    private static final int FILE_REQUEST = 7;

    private SharedPreferences prefs;
    private WebView web;
    private EditText input;
    private ValueCallback<Uri[]> fileCallback;
    private final boolean ru = Locale.getDefault().getLanguage().matches("ru|uk|be|kk|uz|az");

    private String t(String ruText, String enText) { return ru ? ruText : enText; }

    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        prefs = getSharedPreferences("nicro", MODE_PRIVATE);
        rememberFromIntent(getIntent());
        String url = prefs.getString("url", "");
        if (url.isEmpty()) showSetup(""); else showPanel(url);
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        if (rememberFromIntent(intent)) showPanel(prefs.getString("url", ""));
    }

    private boolean rememberFromIntent(Intent intent) {
        Uri data = intent == null ? null : intent.getData();
        if (data == null || !"nicro".equals(data.getScheme())) return false;
        String url = data.getQueryParameter("url");
        if (url == null || !url.startsWith("http")) return false;
        prefs.edit().putString("url", normalize(url)).apply();
        return true;
    }

    private static String normalize(String url) {
        url = url.trim();
        int q = url.indexOf('?');
        if (q > 0) url = url.substring(0, q);
        int h = url.indexOf('#');
        if (h > 0) url = url.substring(0, h);
        return url.endsWith("/") ? url : url + "/";
    }

    // ---------------------------------------------------------------- first start: the panel address

    private void showSetup(String error) {
        web = null;
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setGravity(Gravity.CENTER);
        int pad = dp(28);
        box.setPadding(pad, pad, pad, pad);
        box.setBackgroundColor(Color.parseColor("#0a0b14"));

        TextView logo = new TextView(this);
        logo.setText("n");
        logo.setTextColor(Color.WHITE);
        logo.setTextSize(34);
        logo.setTypeface(Typeface.DEFAULT_BOLD);
        logo.setGravity(Gravity.CENTER);
        GradientDrawable g = new GradientDrawable(GradientDrawable.Orientation.TL_BR,
                new int[]{Color.parseColor("#7c6cff"), Color.parseColor("#22d3ee")});
        g.setCornerRadius(dp(22));
        logo.setBackground(g);
        box.addView(logo, new LinearLayout.LayoutParams(dp(76), dp(76)));

        box.addView(text("nicro", 26, true, "#eceef6"), wrap(dp(14)));
        box.addView(text(error.isEmpty()
                ? t("Адрес вашей панели. Если вы скачали приложение из панели — он уже в буфере обмена: нажмите «Вставить».",
                    "Your panel address. If you downloaded the app from the panel, it is already in the clipboard: tap “Paste”.")
                : error, 15, false, error.isEmpty() ? "#8b8fa8" : "#fca5a5"), wrap(dp(10)));

        input = new EditText(this);
        input.setHint("https://…/…/");
        input.setSingleLine(true);
        input.setInputType(InputType.TYPE_TEXT_VARIATION_URI);
        input.setTextColor(Color.parseColor("#eceef6"));
        input.setHintTextColor(Color.parseColor("#5b5f78"));
        input.setText(prefs.getString("url", ""));
        box.addView(input, wrap(dp(22)));

        box.addView(button(t("Вставить из буфера", "Paste from clipboard"), false, v -> {
            String c = clipboardUrl();
            if (c != null) input.setText(c);
        }), wrap(dp(12)));
        box.addView(button(t("Открыть панель", "Open the panel"), true, v -> {
            Matcher m = PANEL_URL.matcher(input.getText().toString());
            if (!m.find()) { input.setError(t("Нужна ссылка вида https://адрес:2053/секретный-путь/", "Expected https://host:2053/secret-path/")); return; }
            String url = normalize(m.group());
            prefs.edit().putString("url", url).apply();
            showPanel(url);
        }), wrap(dp(10)));
        setContentView(box);
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        // Android 10+ lets an app read the clipboard only while focused: fill the address in automatically
        if (hasFocus && web == null && input != null && input.getText().length() == 0) {
            String c = clipboardUrl();
            if (c != null) {
                prefs.edit().putString("url", c).apply();
                showPanel(c);
            }
        }
    }

    private String clipboardUrl() {
        try {
            ClipboardManager cm = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
            ClipData clip = cm == null ? null : cm.getPrimaryClip();
            if (clip == null || clip.getItemCount() == 0) return null;
            CharSequence s = clip.getItemAt(0).coerceToText(this);
            Matcher m = PANEL_URL.matcher(s == null ? "" : s);
            return m.find() ? normalize(m.group()) : null;
        } catch (Exception e) {
            return null;
        }
    }

    // ---------------------------------------------------------------- the panel

    private void showPanel(String url) {
        input = null;
        web = new WebView(this);
        web.setBackgroundColor(Color.parseColor("#0a0b14"));
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setUserAgentString(s.getUserAgentString() + " nicroApp/1");
        CookieManager.getInstance().setAcceptCookie(true);
        final String host = Uri.parse(url).getHost();

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
                Uri u = req.getUrl();
                if (("https".equals(u.getScheme()) || "http".equals(u.getScheme())) && host != null && host.equals(u.getHost())) {
                    return false;  // the panel itself
                }
                openOutside(u);  // Telegram, payment pages, happ:// / v2raytun:// links, stores
                return true;
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest req, WebResourceError err) {
                if (req.isForMainFrame()) {
                    showSetup(t("Панель не открылась: ", "The panel didn't open: ") + err.getDescription()
                            + t(". Проверьте интернет или адрес.", ". Check the connection or the address."));
                }
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> cb, FileChooserParams params) {
                fileCallback = cb;  // CSV import of clients, restoring a backup
                try {
                    startActivityForResult(params.createIntent(), FILE_REQUEST);
                } catch (Exception e) {
                    fileCallback = null;
                    return false;
                }
                return true;
            }
        });
        web.setDownloadListener((dl, ua, cd, mime, len) -> {
            if (dl.startsWith("http")) openOutside(Uri.parse(dl));
        });
        setContentView(web, new ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        web.loadUrl(url);
    }

    private void openOutside(Uri u) {
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, u).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        } catch (Exception ignored) {
        }
    }

    @Override
    protected void onActivityResult(int request, int result, Intent data) {
        if (request == FILE_REQUEST && fileCallback != null) {
            fileCallback.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(result, data));
            fileCallback = null;
            return;
        }
        super.onActivityResult(request, result, data);
    }

    @Override
    public void onBackPressed() {
        if (web != null && web.canGoBack()) web.goBack();
        else if (web != null && web.getUrl() != null && web.getUrl().contains("#") && !web.getUrl().endsWith("#dashboard")) web.loadUrl("javascript:location.hash='#dashboard'");
        else super.onBackPressed();
    }

    // ---------------------------------------------------------------- tiny UI helpers

    private int dp(int v) { return Math.round(v * getResources().getDisplayMetrics().density); }

    private LinearLayout.LayoutParams wrap(int top) {
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        p.topMargin = top;
        return p;
    }

    private TextView text(String s, int size, boolean bold, String color) {
        TextView v = new TextView(this);
        v.setText(s);
        v.setTextSize(size);
        v.setTextColor(Color.parseColor(color));
        v.setGravity(Gravity.CENTER);
        if (bold) v.setTypeface(Typeface.DEFAULT_BOLD);
        return v;
    }

    private Button button(String label, boolean primary, View.OnClickListener click) {
        Button b = new Button(this);
        b.setText(label);
        b.setAllCaps(false);
        b.setTextColor(Color.WHITE);
        GradientDrawable bg = new GradientDrawable();
        bg.setCornerRadius(dp(14));
        bg.setColor(Color.parseColor(primary ? "#7c6cff" : "#1b1d2e"));
        b.setBackground(bg);
        b.setOnClickListener(click);
        return b;
    }
}
