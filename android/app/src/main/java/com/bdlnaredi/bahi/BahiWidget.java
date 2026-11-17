package com.bdlnaredi.bahi;

import android.app.PendingIntent;
import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.webkit.CookieManager;
import android.widget.RemoteViews;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

/** Home-screen widget: today's sales, cash and money to receive for the company last opened in the app.
 *  The app hands it fresh figures whenever Home is opened; every 30 minutes it also asks the server itself,
 *  with the app's login (cookies), and keeps showing the last figures when that fails. */
public class BahiWidget extends AppWidgetProvider {

    static SharedPreferences prefs(Context c) {
        return c.getSharedPreferences("bahi", Context.MODE_PRIVATE);
    }

    /** Called by the app with the server's /api/widget answer */
    static void store(Context c, String json) {
        prefs(c).edit().putString("widget_json", json).putLong("widget_at", System.currentTimeMillis()).apply();
        refreshAll(c);
    }

    static void refreshAll(Context c) {
        AppWidgetManager m = AppWidgetManager.getInstance(c);
        int[] ids = m.getAppWidgetIds(new ComponentName(c, BahiWidget.class));
        for (int id : ids) m.updateAppWidget(id, views(c));
    }

    private static String inr(double n) {
        double a = Math.abs(n);
        String s;
        if (a >= 1e7) s = String.format(Locale.US, "%.2f Cr", a / 1e7);
        else if (a >= 1e5) s = String.format(Locale.US, "%.2f L", a / 1e5);
        else {
            // Indian grouping: 12,34,567
            String w = String.valueOf(Math.round(a));
            if (w.length() > 3) {
                String last = w.substring(w.length() - 3), rest = w.substring(0, w.length() - 3);
                StringBuilder b = new StringBuilder();
                while (rest.length() > 2) { b.insert(0, "," + rest.substring(rest.length() - 2)); rest = rest.substring(0, rest.length() - 2); }
                s = rest + b + "," + last;
            } else s = w;
        }
        return (n < 0 ? "-" : "") + "₹" + s;
    }

    static RemoteViews views(Context c) {
        RemoteViews v = new RemoteViews(c.getPackageName(), R.layout.widget);
        Intent open = new Intent(c, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        v.setOnClickPendingIntent(R.id.w_root, PendingIntent.getActivity(c, 2, open, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE));
        String j = prefs(c).getString("widget_json", "");
        if (j.isEmpty()) {
            v.setTextViewText(R.id.w_company, "Bahi");
            v.setTextViewText(R.id.w_time, "open the app once");
            return v;
        }
        try {
            JSONObject o = new JSONObject(j);
            v.setTextViewText(R.id.w_company, o.optString("company", "Bahi"));
            v.setTextViewText(R.id.w_sales, inr(o.optDouble("sales_today", 0)));
            int n = o.optInt("bills_today", 0);
            v.setTextViewText(R.id.w_bills, n + (n == 1 ? " bill" : " bills"));
            v.setTextViewText(R.id.w_cash, inr(o.optDouble("cash", 0)));
            v.setTextViewText(R.id.w_rec, inr(o.optDouble("receivable", 0)));
            double at = o.optDouble("data_at", 0);
            v.setTextViewText(R.id.w_time, at > 0 ? "as of " + new SimpleDateFormat("d MMM, h:mm a", Locale.ENGLISH).format(new Date((long) (at * 1000))) : "");
        } catch (Exception e) {
            v.setTextViewText(R.id.w_time, "");
        }
        return v;
    }

    @Override
    public void onUpdate(final Context c, AppWidgetManager m, int[] ids) {
        for (int id : ids) m.updateAppWidget(id, views(c));
        final String server = prefs(c).getString("server", "");
        if (server.isEmpty()) return;
        final PendingResult pr = goAsync();
        new Thread(() -> {
            try {
                String cid = prefs(c).getString("widget_cid", "");
                URL u = new URL(server.replaceAll("/+$", "") + "/api/widget" + (cid.isEmpty() ? "" : "?cid=" + cid));
                HttpURLConnection h = (HttpURLConnection) u.openConnection();
                String ck = CookieManager.getInstance().getCookie(server);
                if (ck != null) h.setRequestProperty("Cookie", ck);
                h.setConnectTimeout(10000);
                h.setReadTimeout(15000);
                if (h.getResponseCode() == 200) {
                    ByteArrayOutputStream out = new ByteArrayOutputStream();
                    try (InputStream in = h.getInputStream()) {
                        byte[] b = new byte[4096];
                        int k;
                        while ((k = in.read(b)) > 0 && out.size() < 65536) out.write(b, 0, k);
                    }
                    String body = out.toString("UTF-8");
                    if (body.trim().startsWith("{") && !body.contains("\"error\"")) store(c, body);
                }
                h.disconnect();
            } catch (Exception ignored) {
                // offline or logged out: keep the last figures
            } finally {
                pr.finish();
            }
        }).start();
    }
}
