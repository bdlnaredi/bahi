package com.bdlnaredi.bahi;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.graphics.Typeface;
import android.net.ConnectivityManager;
import android.net.NetworkInfo;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.inputmethod.EditorInfo;
import android.webkit.CookieManager;
import android.webkit.JavascriptInterface;
import android.webkit.URLUtil;
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
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

import androidx.core.content.FileProvider;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Bahi for Android: the Bahi web app in a full-screen view, with the server address set once, files (PDFs,
 * Excel, backups) opened or shared with other apps, WhatsApp/phone links handed to those apps, and the
 * offline copy the web app keeps on the phone.
 */
public class MainActivity extends Activity {
    private static final int REQ_FILE = 7;
    private static final String RELEASE_API = "https://api.github.com/repos/bdlnaredi/bahi/releases/tags/android";
    private static final String APK_URL = "https://github.com/bdlnaredi/bahi/releases/download/android/Bahi.apk";

    private SharedPreferences prefs;
    private WebView web;
    private ProgressBar bar;
    private ValueCallback<Uri[]> fileCallback;
    private final Handler ui = new Handler(Looper.getMainLooper());

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        prefs = getSharedPreferences("bahi", MODE_PRIVATE);
        if (server().isEmpty()) showSetup(null);
        else showWeb();
        checkForUpdate();
    }

    private String server() {
        return prefs.getString("server", "");
    }

    private int dp(int v) {
        return (int) TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v, getResources().getDisplayMetrics());
    }

    // ------------------------------------------------------------------ first start: where is the server?
    private void showSetup(String message) {
        if (web != null) {
            web.destroy();
            web = null;
        }
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(dp(24), dp(48), dp(24), dp(24));
        box.setBackgroundColor(Color.WHITE);

        TextView title = new TextView(this);
        title.setText("Bahi");
        title.setTextSize(32);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        title.setTextColor(Color.parseColor("#1D5FC4"));
        box.addView(title);

        TextView hint = new TextView(this);
        hint.setText("Enter the address of your Bahi server, the same one you open in the browser, for example https://books.yourdomain.com\n\nUse the https:// address so the offline copy works.");
        hint.setTextSize(16);
        hint.setTextColor(Color.parseColor("#374151"));
        hint.setPadding(0, dp(12), 0, dp(16));
        box.addView(hint);

        final EditText url = new EditText(this);
        url.setHint("https://books.yourdomain.com");
        url.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        url.setImeOptions(EditorInfo.IME_ACTION_GO);
        url.setSingleLine(true);
        url.setText(server());
        box.addView(url, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        final TextView msg = new TextView(this);
        msg.setTextColor(Color.parseColor("#B42318"));
        msg.setPadding(0, dp(8), 0, dp(8));
        if (message != null) msg.setText(message);
        box.addView(msg);

        final Button go = new Button(this);
        go.setText("Connect");
        box.addView(go, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        View.OnClickListener connect = v -> {
            String s = url.getText().toString().trim();
            if (s.isEmpty()) {
                msg.setText("Enter the server address.");
                return;
            }
            if (!s.startsWith("http://") && !s.startsWith("https://")) s = "https://" + s;
            while (s.endsWith("/")) s = s.substring(0, s.length() - 1);
            final String addr = s;
            msg.setTextColor(Color.parseColor("#374151"));
            msg.setText("Checking " + addr + " ...");
            go.setEnabled(false);
            new Thread(() -> {
                String err = reach(addr);
                ui.post(() -> {
                    go.setEnabled(true);
                    if (err == null) {
                        prefs.edit().putString("server", addr).apply();
                        showWeb();
                    } else {
                        msg.setTextColor(Color.parseColor("#B42318"));
                        msg.setText(err);
                    }
                });
            }).start();
        };
        go.setOnClickListener(connect);
        url.setOnEditorActionListener((v, id, e) -> {
            connect.onClick(v);
            return true;
        });
        setContentView(box);
    }

    /** null when the address answers like a Bahi server, otherwise what went wrong, in plain words. */
    private String reach(String addr) {
        try {
            HttpURLConnection c = (HttpURLConnection) new URL(addr + "/manifest.webmanifest").openConnection();
            c.setConnectTimeout(10000);
            c.setReadTimeout(10000);
            int code = c.getResponseCode();
            String landed = c.getURL().getHost();
            if (landed != null && landed.endsWith("cloudflareaccess.com")) {
                c.disconnect();
                return null;          // Cloudflare Access login comes first; the app shows it
            }
            if (code == 302 || code == 303) {
                String loc = c.getHeaderField("Location");
                c.disconnect();
                if (loc != null && loc.contains("cloudflareaccess.com")) return null;
                return "That address sends the phone elsewhere (" + loc + ").";
            }
            InputStream in = code < 400 ? c.getInputStream() : c.getErrorStream();
            String body = in == null ? "" : new String(readAll(in, 20000), "UTF-8");
            c.disconnect();
            if (code == 200 && body.contains("Bahi")) return null;
            if (code == 200 || code == 302 || code == 403) return "That address answered, but it isn't the Bahi app (got " + code + "). If Cloudflare Access asks for a login, open the address in Chrome once, then try again.";
            return "That address answered with error " + code + ".";
        } catch (Exception e) {
            return "Couldn't reach that address. Check it, and check the phone's internet. (" + e.getClass().getSimpleName() + ")";
        }
    }

    // ------------------------------------------------------------------ the app
    private void showWeb() {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setBackgroundColor(Color.WHITE);
        bar = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        bar.setIndeterminate(false);
        bar.setMax(100);
        box.addView(bar, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(3)));

        web = new WebView(this);
        box.addView(web, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
        setContentView(box);

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setAllowFileAccess(false);
        s.setMediaPlaybackRequiresUserGesture(true);
        s.setSupportMultipleWindows(false);
        s.setUserAgentString(s.getUserAgentString() + " BahiAndroid/" + BuildConfig.VERSION_NAME);
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, true);
        web.addJavascriptInterface(new Bridge(), "BahiAndroid");

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
                return route(req.getUrl());
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest req, WebResourceError error) {
                if (req.isForMainFrame()) showOfflinePage();
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                CookieManager.getInstance().flush();
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onProgressChanged(WebView view, int p) {
                bar.setProgress(p);
                bar.setVisibility(p < 100 ? View.VISIBLE : View.INVISIBLE);
            }

            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> cb, FileChooserParams params) {
                if (fileCallback != null) fileCallback.onReceiveValue(null);
                fileCallback = cb;
                try {
                    Intent i = new Intent(Intent.ACTION_GET_CONTENT);
                    i.addCategory(Intent.CATEGORY_OPENABLE);
                    i.setType("*/*");
                    startActivityForResult(Intent.createChooser(i, "Choose a file"), REQ_FILE);
                    return true;
                } catch (ActivityNotFoundException e) {
                    fileCallback = null;
                    return false;
                }
            }
        });
        web.setDownloadListener((url, ua, disposition, mime, length) ->
                fetchFile(url, URLUtil.guessFileName(url, disposition, mime), false));
        web.loadUrl(server() + "/");
    }

    private boolean sameServer(Uri u) {
        Uri s = Uri.parse(server());
        return u.getHost() != null && u.getHost().equalsIgnoreCase(s.getHost()) && u.getPort() == s.getPort();
    }

    /** true when the link was handled outside the app view */
    private boolean route(Uri u) {
        String scheme = u.getScheme() == null ? "" : u.getScheme().toLowerCase();
        // Cloudflare Access (the email-code login in front of the server) has to happen inside the app,
        // so its sign-in cookie is the one the app uses
        if ((scheme.equals("http") || scheme.equals("https")) && u.getHost() != null
                && (u.getHost().endsWith(".cloudflareaccess.com") || u.getHost().endsWith(".cloudflare.com"))) {
            return false;
        }
        if ((scheme.equals("http") || scheme.equals("https")) && sameServer(u)) {
            String path = u.getPath() == null ? "" : u.getPath();
            if (path.contains("_pdf") || path.endsWith("/export") || path.startsWith("/api/backups/")) {
                fetchFile(u.toString(), null, false);
                return true;
            }
            return false;
        }
        try {
            Intent i;
            if (scheme.equals("intent")) i = Intent.parseUri(u.toString(), Intent.URI_INTENT_SCHEME);
            else i = new Intent(Intent.ACTION_VIEW, u);
            startActivity(i);
        } catch (Exception e) {
            toast("No app on this phone can open that.");
        }
        return true;
    }

    private void showOfflinePage() {
        String html = "<html><head><meta name='viewport' content='width=device-width,initial-scale=1'></head>"
                + "<body style='font-family:sans-serif;padding:32px 24px;color:#111827'>"
                + "<h2 style='color:#1D5FC4'>Can't reach the server</h2>"
                + "<p>The phone couldn't open " + server().replace("<", "") + ". Check the internet connection.</p>"
                + "<p>Once the app has opened while connected, it keeps an offline copy and opens without internet too.</p>"
                + "<p><button style='font-size:16px;padding:10px 18px' onclick='BahiAndroid.reload()'>Try again</button></p>"
                + "<p><button style='font-size:16px;padding:10px 18px' onclick='BahiAndroid.changeServer()'>Change server address</button></p>"
                + "</body></html>";
        web.loadDataWithBaseURL(null, html, "text/html", "UTF-8", null);
    }

    // ------------------------------------------------------------------ files: PDFs, Excel, backups
    private void fetchFile(final String url, final String name, final boolean share) {
        toast(share ? "Preparing to share" : "Opening");
        new Thread(() -> {
            try {
                HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
                String cookie = CookieManager.getInstance().getCookie(url);
                if (cookie != null) c.setRequestProperty("Cookie", cookie);
                c.setRequestProperty("User-Agent", web != null ? web.getSettings().getUserAgentString() : "BahiAndroid");
                c.setConnectTimeout(20000);
                c.setReadTimeout(60000);
                int code = c.getResponseCode();
                if (code != 200) throw new Exception("server said " + code);
                String mime = c.getContentType() == null ? "application/octet-stream" : c.getContentType().split(";")[0].trim();
                String fname = name;
                String disp = c.getHeaderField("Content-Disposition");
                if (fname == null || fname.isEmpty()) fname = URLUtil.guessFileName(url, disp, mime);
                Matcher m = Pattern.compile("filename=\"?([^\";]+)\"?").matcher(disp == null ? "" : disp);
                if ((name == null || name.isEmpty()) && m.find()) fname = m.group(1);
                fname = fname.replaceAll("[\\\\/:*?\"<>|]+", " ").trim();
                if (fname.isEmpty()) fname = "bahi-file";
                File dir = new File(getCacheDir(), "shared");
                dir.mkdirs();
                File[] old = dir.listFiles();
                if (old != null) for (File f : old) if (System.currentTimeMillis() - f.lastModified() > 86400000L) f.delete();
                File out = new File(dir, fname);
                try (InputStream in = c.getInputStream(); OutputStream os = new FileOutputStream(out)) {
                    byte[] buf = new byte[16384];
                    int n;
                    while ((n = in.read(buf)) > 0) os.write(buf, 0, n);
                }
                c.disconnect();
                final String type = mime;
                final File file = out;
                ui.post(() -> handOver(file, type, share));
            } catch (Exception e) {
                ui.post(() -> toast("Couldn't get the file: " + e.getMessage()));
            }
        }).start();
    }

    private void handOver(File file, String mime, boolean share) {
        Uri uri = FileProvider.getUriForFile(this, getPackageName() + ".files", file);
        Intent send = new Intent(Intent.ACTION_SEND);
        send.setType(mime);
        send.putExtra(Intent.EXTRA_STREAM, uri);
        send.putExtra(Intent.EXTRA_SUBJECT, file.getName());
        send.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        if (!share) {
            Intent view = new Intent(Intent.ACTION_VIEW);
            view.setDataAndType(uri, mime);
            view.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
            try {
                startActivity(view);
                return;
            } catch (ActivityNotFoundException e) {
                // no viewer for this kind of file: offer to send it instead
            }
        }
        try {
            startActivity(Intent.createChooser(send, "Share " + file.getName()));
        } catch (ActivityNotFoundException e) {
            toast("No app on this phone can open that file.");
        }
    }

    /** Called by the web app (window.BahiAndroid). */
    private class Bridge {
        @JavascriptInterface
        public void share(String url, String name) {
            ui.post(() -> fetchFile(url, name, true));
        }

        @JavascriptInterface
        public void open(String url, String name) {
            ui.post(() -> fetchFile(url, name, false));
        }

        @JavascriptInterface
        public String server() {
            return MainActivity.this.server();
        }

        @JavascriptInterface
        public String version() {
            return BuildConfig.VERSION_NAME;
        }

        @JavascriptInterface
        public void changeServer() {
            ui.post(() -> showSetup(null));
        }

        @JavascriptInterface
        public void reload() {
            ui.post(() -> {
                if (web != null) web.loadUrl(MainActivity.this.server() + "/");
            });
        }

        @JavascriptInterface
        public void checkUpdate() {
            prefs.edit().putLong("update_checked", 0).apply();
            ui.post(() -> MainActivity.this.checkForUpdate());
        }
    }

    // ------------------------------------------------------------------ new app versions
    private void checkForUpdate() {
        long last = prefs.getLong("update_checked", 0);
        if (System.currentTimeMillis() - last < 12 * 3600 * 1000L || !online()) return;
        prefs.edit().putLong("update_checked", System.currentTimeMillis()).apply();
        new Thread(() -> {
            try {
                HttpURLConnection c = (HttpURLConnection) new URL(RELEASE_API).openConnection();
                c.setRequestProperty("Accept", "application/vnd.github+json");
                c.setConnectTimeout(10000);
                c.setReadTimeout(10000);
                if (c.getResponseCode() != 200) return;
                String body = new String(readAll(c.getInputStream(), 200000), "UTF-8");
                Matcher m = Pattern.compile("versionCode:\\s*(\\d+)").matcher(body);
                if (m.find() && Integer.parseInt(m.group(1)) > BuildConfig.VERSION_CODE) {
                    ui.post(() -> new AlertDialog.Builder(this)
                            .setTitle("New version of the Bahi app")
                            .setMessage("A newer version of this app is ready. Download it and tap it to install; your login and saved data stay.")
                            .setPositiveButton("Download", (d, w) -> route(Uri.parse(APK_URL)))
                            .setNegativeButton("Later", null)
                            .show());
                }
            } catch (Exception ignored) {
                // no update check this time
            }
        }).start();
    }

    // ------------------------------------------------------------------ plumbing
    private boolean online() {
        ConnectivityManager cm = (ConnectivityManager) getSystemService(Context.CONNECTIVITY_SERVICE);
        NetworkInfo n = cm == null ? null : cm.getActiveNetworkInfo();
        return n != null && n.isConnected();
    }

    private static byte[] readAll(InputStream in, int max) throws java.io.IOException {
        java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        int n;
        while ((n = in.read(buf)) > 0 && out.size() < max) out.write(buf, 0, n);
        in.close();
        return out.toByteArray();
    }

    private void toast(String s) {
        Toast.makeText(this, s, Toast.LENGTH_SHORT).show();
    }

    @Override
    protected void onActivityResult(int req, int result, Intent data) {
        super.onActivityResult(req, result, data);
        if (req == REQ_FILE && fileCallback != null) {
            Uri[] picked = null;
            if (result == RESULT_OK && data != null) {
                if (data.getClipData() != null) {
                    picked = new Uri[data.getClipData().getItemCount()];
                    for (int i = 0; i < picked.length; i++) picked[i] = data.getClipData().getItemAt(i).getUri();
                } else if (data.getData() != null) {
                    picked = new Uri[]{data.getData()};
                }
            }
            fileCallback.onReceiveValue(picked);
            fileCallback = null;
        }
    }

    @Override
    public void onBackPressed() {
        if (web != null && web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }

    @Override
    protected void onPause() {
        super.onPause();
        CookieManager.getInstance().flush();
    }
}
