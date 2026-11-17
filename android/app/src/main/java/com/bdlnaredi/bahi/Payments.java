package com.bdlnaredi.bahi;

import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.job.JobInfo;
import android.app.job.JobParameters;
import android.app.job.JobScheduler;
import android.app.job.JobService;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Build;
import android.webkit.CookieManager;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.text.NumberFormat;
import java.util.HashSet;
import java.util.Locale;
import java.util.Set;

/** "Payment received" notifications: every 15 minutes or so (when the phone allows), asks the Bahi server for
 *  today's and yesterday's receipts and notifies the ones not seen before. Turned on in Settings, Android app. */
public class Payments extends JobService {
    static final String CHANNEL = "payments";
    private static final int JOB_ID = 4713;

    static SharedPreferences prefs(Context c) {
        return c.getSharedPreferences("bahi", Context.MODE_PRIVATE);
    }

    static boolean on(Context c) {
        return prefs(c).getBoolean("pay_alerts", false);
    }

    static void set(Context c, boolean on) {
        prefs(c).edit().putBoolean("pay_alerts", on).putBoolean("pay_primed", false).apply();
        schedule(c);
    }

    static void schedule(Context c) {
        JobScheduler js = (JobScheduler) c.getSystemService(Context.JOB_SCHEDULER_SERVICE);
        if (js == null) return;
        if (!on(c)) {
            js.cancel(JOB_ID);
            return;
        }
        if (js.getPendingJob(JOB_ID) != null) return;
        js.schedule(new JobInfo.Builder(JOB_ID, new ComponentName(c, Payments.class))
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                .setPeriodic(15 * 60 * 1000L)
                .setPersisted(true)
                .build());
    }

    static String inr(double v) {
        NumberFormat f = NumberFormat.getNumberInstance(new Locale("en", "IN"));
        f.setMaximumFractionDigits(v == Math.floor(v) ? 0 : 2);
        return "₹" + f.format(v);
    }

    static void check(Context c) throws Exception {
        String server = prefs(c).getString("server", "");
        if (server.isEmpty()) return;
        HttpURLConnection h = (HttpURLConnection) new URL(server.replaceAll("/+$", "") + "/api/alerts").openConnection();
        String ck = CookieManager.getInstance().getCookie(server);
        if (ck != null) h.setRequestProperty("Cookie", ck);
        h.setConnectTimeout(10000);
        h.setReadTimeout(20000);
        if (h.getResponseCode() != 200) {
            h.disconnect();
            return;
        }
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        try (InputStream in = h.getInputStream()) {
            byte[] b = new byte[8192];
            int k;
            while ((k = in.read(b)) > 0 && out.size() < 500000) out.write(b, 0, k);
        }
        h.disconnect();
        JSONArray rs = new JSONObject(out.toString("UTF-8")).optJSONArray("receipts");
        if (rs == null) return;
        SharedPreferences p = prefs(c);
        Set<String> seen = new HashSet<>(p.getStringSet("pay_seen", new HashSet<String>()));
        boolean primed = p.getBoolean("pay_primed", false);   // the first look only remembers what's already there
        Set<String> now = new HashSet<>();
        int shown = 0;
        for (int i = 0; i < rs.length(); i++) {
            JSONObject r = rs.getJSONObject(i);
            String key = r.optString("key");
            now.add(key);
            if (seen.contains(key) || !primed || shown >= 10) continue;
            notifyOne(c, r);
            shown++;
        }
        p.edit().putStringSet("pay_seen", now).putBoolean("pay_primed", true).apply();
    }

    static void notifyOne(Context c, JSONObject r) {
        NotificationManager nm = (NotificationManager) c.getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm == null) return;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            nm.createNotificationChannel(new NotificationChannel(CHANNEL, "Payments received", NotificationManager.IMPORTANCE_DEFAULT));
        }
        int id = 5000 + (r.optString("key").hashCode() & 0xfffff);
        Intent open = new Intent(c, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP)
                .putExtra("go_cid", r.optInt("cid")).putExtra("go_hash", "#/voucher/" + r.optInt("id"));
        PendingIntent pi = PendingIntent.getActivity(c, id, open, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        String title = inr(r.optDouble("amount", 0)) + " received from " + r.optString("party", "a customer");
        String text = "Receipt " + r.optString("number") + ", " + r.optString("company");
        android.app.Notification.Builder b = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
                ? new android.app.Notification.Builder(c, CHANNEL) : new android.app.Notification.Builder(c);
        b.setSmallIcon(android.R.drawable.stat_notify_more).setContentTitle(title).setContentText(text)
                .setContentIntent(pi).setAutoCancel(true);
        try {
            nm.notify(id, b.build());
        } catch (SecurityException e) {
            // notifications are off for Bahi
        }
    }

    @Override
    public boolean onStartJob(final JobParameters params) {
        new Thread(() -> {
            try {
                if (on(this)) check(this);
            } catch (Exception e) {
                // offline or logged out: next time
            }
            jobFinished(params, false);
        }).start();
        return true;
    }

    @Override
    public boolean onStopJob(JobParameters params) {
        return true;
    }
}
