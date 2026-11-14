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

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Looks for a newer Bahi app on GitHub; in the background it does so twice a day and puts up a notification. */
public class Updates extends JobService {
    static final String RELEASE_API = "https://api.github.com/repos/bdlnaredi/bahi/releases/tags/android";
    static final String CHANNEL = "updates";
    private static final int JOB_ID = 4711;

    /** The newest version code on GitHub (0 when it can't be read). Not on the main thread. */
    static int latest() throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(RELEASE_API).openConnection();
        c.setRequestProperty("Accept", "application/vnd.github+json");
        c.setConnectTimeout(10000);
        c.setReadTimeout(10000);
        if (c.getResponseCode() != 200) throw new Exception("GitHub said " + c.getResponseCode());
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        try (InputStream in = c.getInputStream()) {
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) > 0 && out.size() < 300000) out.write(buf, 0, n);
        }
        c.disconnect();
        Matcher m = Pattern.compile("versionCode:\\s*(\\d+)").matcher(out.toString("UTF-8"));
        int v = m.find() ? Integer.parseInt(m.group(1)) : 0;
        return v;
    }

    /** Remembered so the app can show its reminder bar without asking GitHub again */
    static void remember(Context ctx, int latest) {
        prefs(ctx).edit().putInt("update_latest", latest).putLong("update_checked", System.currentTimeMillis()).apply();
    }

    static int known(Context ctx) {
        int v = prefs(ctx).getInt("update_latest", 0);
        return v > BuildConfig.VERSION_CODE ? v : 0;
    }

    static SharedPreferences prefs(Context ctx) {
        return ctx.getSharedPreferences("bahi", MODE_PRIVATE);
    }

    static void schedule(Context ctx) {
        JobScheduler js = (JobScheduler) ctx.getSystemService(Context.JOB_SCHEDULER_SERVICE);
        if (js == null || js.getPendingJob(JOB_ID) != null) return;
        js.schedule(new JobInfo.Builder(JOB_ID, new ComponentName(ctx, Updates.class))
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                .setPeriodic(12 * 3600 * 1000L)
                .setPersisted(true)
                .build());
    }

    static void notifyUpdate(Context ctx, int latest) {
        NotificationManager nm = (NotificationManager) ctx.getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm == null) return;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            nm.createNotificationChannel(new NotificationChannel(CHANNEL, "App updates", NotificationManager.IMPORTANCE_DEFAULT));
        }
        Intent open = new Intent(ctx, MainActivity.class).putExtra("update", true).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        PendingIntent pi = PendingIntent.getActivity(ctx, 1, open, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        android.app.Notification.Builder b = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
                ? new android.app.Notification.Builder(ctx, CHANNEL) : new android.app.Notification.Builder(ctx);
        b.setSmallIcon(android.R.drawable.stat_sys_download_done)
                .setContentTitle("Update the Bahi app")
                .setContentText("Version 1." + latest + " is ready. Tap to update: it's faster and fixes problems.")
                .setStyle(new android.app.Notification.BigTextStyle().bigText("Version 1." + latest
                        + " of the Bahi app is ready (you have " + BuildConfig.VERSION_NAME
                        + "). Tap to update: newer versions are faster and fix problems. Your login and saved data stay."))
                .setContentIntent(pi)
                .setAutoCancel(true);
        try {
            nm.notify(JOB_ID, b.build());
        } catch (SecurityException e) {
            // notifications turned off for Bahi: the app reminds on opening instead
        }
    }

    @Override
    public boolean onStartJob(final JobParameters params) {
        new Thread(() -> {
            try {
                int v = latest();
                remember(this, v);
                SharedPreferences p = prefs(this);
                // once a day at most while it stays out of date
                if (v > BuildConfig.VERSION_CODE && System.currentTimeMillis() - p.getLong("update_notified", 0) > 20 * 3600 * 1000L) {
                    p.edit().putLong("update_notified", System.currentTimeMillis()).apply();
                    notifyUpdate(this, v);
                }
            } catch (Exception e) {
                // no internet or GitHub busy: next time
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
