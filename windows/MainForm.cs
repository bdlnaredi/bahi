using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Windows.Forms;

namespace BahiSync
{
    class MainForm : Form
    {
        const string ReleaseApi = "https://api.github.com/repos/bdlnaredi/bahi/releases/tags/windows";
        const string ExeUrl = "https://github.com/bdlnaredi/bahi/releases/download/windows/BahiSync.exe";

        Dictionary<string, object> cfg;
        Process sync;
        bool exiting, startHidden, balloonShown;
        long logPos;
        readonly List<string> lines = new List<string>();

        readonly Label title = new Label(), tallyLbl = new Label(), serverLbl = new Label(), lastLbl = new Label(), stateLbl = new Label();
        readonly Button syncBtn = new Button(), pauseBtn = new Button(), setBtn = new Button(), coBtn = new Button(), toolsBtn = new Button();
        readonly TextBox log = new TextBox();
        readonly LinkLabel update = new LinkLabel();
        readonly Label foot = new Label();
        readonly NotifyIcon tray = new NotifyIcon();
        readonly ContextMenuStrip tools = new ContextMenuStrip(), trayMenu = new ContextMenuStrip();
        ToolStripMenuItem trayPause;
        readonly System.Windows.Forms.Timer every2min = new System.Windows.Forms.Timer(), everySec = new System.Windows.Forms.Timer(),
            every30s = new System.Windows.Forms.Timer();
        string newVersionUrl;
        public bool CompaniesAtStart;

        public MainForm(bool tray)
        {
            startHidden = tray;
            Text = "Bahi Sync";
            Font = new Font("Segoe UI", 10f);
            AutoScaleMode = AutoScaleMode.Dpi;
            ClientSize = new Size(820, 560);
            MinimumSize = new Size(640, 420);
            StartPosition = FormStartPosition.CenterScreen;
            try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { }

            // ---- the log fills the window; status and buttons on top; version and update link at the bottom
            log.Multiline = true; log.ReadOnly = true; log.ScrollBars = ScrollBars.Vertical; log.WordWrap = false;
            log.Font = new Font("Consolas", 9.5f); log.BackColor = Color.White; log.Dock = DockStyle.Fill;
            Controls.Add(log);

            var bottom = new FlowLayoutPanel(); bottom.Dock = DockStyle.Bottom; bottom.AutoSize = true; bottom.Padding = new Padding(12, 6, 12, 6);
            foot.AutoSize = true; foot.ForeColor = Color.DimGray; foot.Margin = new Padding(0, 3, 16, 0);
            update.AutoSize = true; update.Visible = false; update.Margin = new Padding(0, 3, 0, 0);
            update.LinkClicked += delegate { InstallUpdate(); };
            bottom.Controls.Add(foot); bottom.Controls.Add(update);
            Controls.Add(bottom);

            var top = new FlowLayoutPanel(); top.Dock = DockStyle.Top; top.AutoSize = true; top.FlowDirection = FlowDirection.TopDown;
            top.WrapContents = false; top.Padding = new Padding(14, 10, 14, 8);
            title.Text = "Bahi Sync"; title.Font = new Font("Segoe UI Semibold", 16f); title.ForeColor = Color.FromArgb(29, 95, 196); title.AutoSize = true;
            top.Controls.Add(title);
            foreach (var l in new[] { tallyLbl, serverLbl, lastLbl, stateLbl }) { l.AutoSize = true; l.Margin = new Padding(0, 2, 0, 0); top.Controls.Add(l); }

            var buttons = new FlowLayoutPanel(); buttons.AutoSize = true; buttons.Margin = new Padding(0, 10, 0, 0);
            syncBtn.Text = "Sync now"; pauseBtn.Text = "Pause"; setBtn.Text = "Settings"; coBtn.Text = "Companies"; toolsBtn.Text = "Tools ▾";
            foreach (var b in new[] { syncBtn, pauseBtn, setBtn, coBtn, toolsBtn }) { b.AutoSize = true; b.Padding = new Padding(8, 2, 8, 2); buttons.Controls.Add(b); }
            top.Controls.Add(buttons);
            Controls.Add(top);

            syncBtn.Click += delegate { RunSync("-Now", true); };
            pauseBtn.Click += delegate { TogglePause(); };
            setBtn.Click += delegate { OpenSettings(); };
            coBtn.Click += delegate { OpenCompanies(); };
            toolsBtn.Click += delegate { tools.Show(toolsBtn, new Point(0, toolsBtn.Height)); };

            tools.Items.Add("Diagnose (count vouchers per month in Tally)", null, delegate { Engine.StartTool("Diagnose.ps1"); });
            tools.Items.Add("Save one voucher from Tally (for a problem report)", null, delegate { Engine.StartTool("Save-Voucher.ps1"); });
            tools.Items.Add("Save stock figures from Tally (for a problem report)", null, delegate { Engine.StartTool("Save-Stock.ps1"); });
            tools.Items.Add(new ToolStripSeparator());
            tools.Items.Add("Send everything again (full sync, takes a while)", null, delegate { FullSync(); });
            tools.Items.Add(new ToolStripSeparator());
            tools.Items.Add("Open the log file", null, delegate { if (File.Exists(Engine.LogPath)) Process.Start("notepad.exe", "\"" + Engine.LogPath + "\""); });
            tools.Items.Add("Open the Bahi folder", null, delegate { Process.Start("explorer.exe", "\"" + Engine.Dir + "\""); });

            // ---- tray icon: syncing goes on with the window closed
            this.tray.Icon = Icon ?? SystemIcons.Application;
            this.tray.Text = "Bahi Sync";
            this.tray.Visible = true;
            this.tray.DoubleClick += delegate { ShowMain(); };
            trayMenu.Items.Add("Open Bahi Sync", null, delegate { ShowMain(); });
            trayMenu.Items.Add("Sync now", null, delegate { RunSync("-Now", true); });
            trayPause = new ToolStripMenuItem("Pause syncing", null, delegate { TogglePause(); });
            trayMenu.Items.Add(trayPause);
            trayMenu.Items.Add(new ToolStripSeparator());
            trayMenu.Items.Add("Exit (stop syncing)", null, delegate { ExitApp(); });
            this.tray.ContextMenuStrip = trayMenu;

            every2min.Interval = 120000; every2min.Tick += delegate { if (!Paused()) RunSync("", false); };
            everySec.Interval = 1000; everySec.Tick += delegate { TailLog(); ShowState(); };
            every30s.Interval = 30000; every30s.Tick += delegate { CheckConnections(); };

            // a second start of the app brings this window up
            var show = new EventWaitHandle(false, EventResetMode.AutoReset, "Local\\BahiSyncAppShow");
            var waiter = new Thread(delegate () { while (true) { show.WaitOne(); try { BeginInvoke((MethodInvoker)ShowMain); } catch { } } });
            waiter.IsBackground = true; waiter.Start();
        }

        protected override void SetVisibleCore(bool value)
        {
            if (startHidden && !IsHandleCreated) { CreateHandle(); value = false; OnLoad(EventArgs.Empty); }
            base.SetVisibleCore(value);
        }

        bool loaded;
        protected override void OnLoad(EventArgs e)
        {
            if (loaded) return;
            loaded = true;
            base.OnLoad(e);
            string ver = "?";
            try { ver = Engine.ExtractScripts(); } catch (Exception x) { AddLine("Couldn't put the sync files in place: " + x.Message); }
            foot.Text = "App " + BuildInfo.Version + "   Sync files " + ver + "   Folder " + Engine.Dir;
            string moved = null;
            try { moved = Engine.MigrateFromOld(); } catch { }
            cfg = Engine.LoadConfig();
            LoadLogTail();
            if (moved != null)
                AddLine("(Bahi Sync) Settings and sync records brought over from " + moved + ". This copy does the syncing now; the old folder can be deleted.");
            if (!Engine.Configured(cfg))
            {
                if (startHidden) ShowMain();
                BeginInvoke((MethodInvoker)delegate { if (OpenSettings()) RunSync("", false); });
            }
            else if (Engine.RemoveOldTask())
                AddLine("(Bahi Sync) Removed the old scheduled task; this app does the syncing now.");
            every2min.Start(); everySec.Start(); every30s.Start();
            CheckConnections();
            ThreadPool.QueueUserWorkItem(delegate { CheckForUpdate(); });
            if (Engine.Configured(cfg)) RunSync("", false);
            if (CompaniesAtStart && Engine.Configured(cfg)) BeginInvoke((MethodInvoker)OpenCompanies);
        }

        // ------------------------------------------------------------ syncing
        bool Paused() { return Engine.Get(cfg ?? new Dictionary<string, object>(), "AppPaused", "") == "True"; }

        void RunSync(string extra, bool asked)
        {
            if (cfg == null || !Engine.Configured(cfg)) { if (asked) OpenSettings(); return; }
            if (sync != null) { if (asked) AddLine("(Bahi Sync) A sync is already running."); return; }
            if (Paused() && asked) AddLine("(Bahi Sync) Syncing is paused on this PC; this one sync goes ahead.");
            try
            {
                sync = Engine.StartSync(extra);
                sync.SynchronizingObject = this;
                sync.Exited += delegate { sync = null; ShowState(); };
                if (asked) AddLine("(Bahi Sync) Checking Tally for changes now ...");
            }
            catch (Exception e) { sync = null; AddLine("(Bahi Sync) Couldn't start PowerShell: " + e.Message); }
            ShowState();
        }

        void FullSync()
        {
            if (MessageBox.Show(this, "Send every voucher again from the sync start date?\n\nThis is only needed if asked for; it can take half an hour with Tally busy.",
                    "Full sync", MessageBoxButtons.OKCancel, MessageBoxIcon.Question) == DialogResult.OK)
                RunSync("-Force", true);
        }

        void TogglePause()
        {
            cfg["AppPaused"] = !Paused();
            try { Engine.SaveConfig(cfg); } catch { }
            AddLine(Paused() ? "(Bahi Sync) Syncing paused on this PC." : "(Bahi Sync) Syncing resumed.");
            ShowState();
        }

        bool OpenSettings()
        {
            using (var f = new SettingsForm(cfg))
            {
                bool ok = f.ShowDialog(Visible ? this : null) == DialogResult.OK;
                cfg = Engine.LoadConfig();
                if (ok)
                {
                    if (Engine.RemoveOldTask()) AddLine("(Bahi Sync) Removed the old scheduled task; this app does the syncing now.");
                    CheckConnections();
                }
                ShowState();
                return ok;
            }
        }

        void OpenCompanies()
        {
            if (cfg == null || !Engine.Configured(cfg)) { OpenSettings(); return; }
            using (var f = new CompaniesForm(cfg))
            {
                bool ok = f.ShowDialog(Visible ? this : null) == DialogResult.OK;
                cfg = Engine.LoadConfig();
                if (ok) { AddLine("(Bahi Sync) Company list saved. " + CompanyLine()); RunSync("-Now", false); }
                ShowState();
            }
        }

        string CompanyLine()
        {
            var off = new List<string>();
            foreach (var kv in Engine.CompanySettings(cfg)) if (Engine.Get(kv.Value, "Sync", "True") == "False") off.Add(kv.Key);
            return off.Count == 0 ? "Every company open in Tally is synced." : "Not synced: " + string.Join(", ", off.ToArray()) + ".";
        }

        // ------------------------------------------------------------ what the window shows
        void ShowState()
        {
            string s;
            if (cfg == null || !Engine.Configured(cfg)) s = "Not set up yet: click Settings.";
            else if (sync != null) s = "Syncing now ...";
            else if (Paused()) s = "Syncing is paused on this PC. Click Resume to carry on.";
            else s = "Checks Tally every 2 minutes; the Bahi app decides how often to send (Settings in the app).";
            stateLbl.Text = s;
            stateLbl.ForeColor = Paused() ? Color.DarkOrange : Color.Black;
            pauseBtn.Text = Paused() ? "Resume" : "Pause";
            trayPause.Text = Paused() ? "Resume syncing" : "Pause syncing";
            syncBtn.Enabled = sync == null;
            tray.Text = "Bahi Sync - " + (sync != null ? "syncing" : Paused() ? "paused" : "on");
        }

        void CheckConnections()
        {
            if (cfg == null) return;
            string tallyUrl = Engine.Get(cfg, "TallyUrl", "http://localhost:9000"), server = Engine.Get(cfg, "ServerUrl", ""), token = Engine.Get(cfg, "SyncToken", "");
            ThreadPool.QueueUserWorkItem(delegate
            {
                string te = Engine.CheckTally(tallyUrl);
                string se = server == "" ? "not set" : Engine.CheckServer(server, token);
                try
                {
                    BeginInvoke((MethodInvoker)delegate
                    {
                        tallyLbl.Text = "Tally (" + tallyUrl + "): " + (te == null ? "connected" : te);
                        tallyLbl.ForeColor = te == null ? Color.DarkGreen : Color.Firebrick;
                        serverLbl.Text = "Server (" + server + "): " + (se == null ? "connected" : se);
                        serverLbl.ForeColor = se == null ? Color.DarkGreen : Color.Firebrick;
                    });
                }
                catch { }
            });
        }

        static readonly Regex Notable = new Regex("Done:|Sync failed|not reachable|didn't come back|stuck|Phone entry|updated from version|no company is loaded|didn't send its list|didn't answer", RegexOptions.IgnoreCase);

        void AddLine(string line)
        {
            if (line.StartsWith("(Bahi Sync)")) line = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + "  " + line.Substring(12);
            lines.Add(line);
            if (lines.Count > 600) lines.RemoveRange(0, lines.Count - 500);
            log.AppendText(line + "\r\n");
            if (log.TextLength > 200000) { log.Text = string.Join("\r\n", lines) + "\r\n"; log.SelectionStart = log.TextLength; log.ScrollToCaret(); }
            if (Notable.IsMatch(line))
            {
                // the plain-words part only: Windows' technical text comes after "(Exception ..." or "Exception calling"
                string shortLine = Regex.Replace(line, @"\s*\((Exception|The remote server|Unable to)[\s\S]*$", "");
                if (shortLine.Length > 150) shortLine = shortLine.Substring(0, 147) + "...";
                lastLbl.Text = "Last: " + shortLine;
                lastLbl.ForeColor = Regex.IsMatch(line, "failed|not reachable|didn't|stuck|no company", RegexOptions.IgnoreCase) ? Color.Firebrick : Color.Black;
            }
        }

        void LoadLogTail()
        {
            logPos = 0;
            if (!File.Exists(Engine.LogPath)) return;
            var len = new FileInfo(Engine.LogPath).Length;
            logPos = Math.Max(0, len - 48000);
            TailLog();
        }

        void TailLog()
        {
            try
            {
                if (!File.Exists(Engine.LogPath)) return;
                using (var fs = new FileStream(Engine.LogPath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
                {
                    if (fs.Length < logPos) logPos = 0;          // the log was started afresh
                    if (fs.Length == logPos) return;
                    fs.Seek(logPos, SeekOrigin.Begin);
                    var buf = new byte[fs.Length - logPos];
                    int n = fs.Read(buf, 0, buf.Length);
                    string text = Encoding.UTF8.GetString(buf, 0, n);
                    int cut = text.LastIndexOf('\n');
                    if (cut < 0) return;                           // wait for the whole line
                    logPos += Encoding.UTF8.GetByteCount(text.Substring(0, cut + 1));
                    foreach (var l in text.Substring(0, cut).Split('\n'))
                    {
                        var t = l.TrimEnd('\r').TrimStart('﻿');
                        if (t.Trim() != "") AddLine(t);
                    }
                }
            }
            catch { }
        }

        // ------------------------------------------------------------ window and tray
        void ShowMain()
        {
            startHidden = false;
            Show();
            if (WindowState == FormWindowState.Minimized) WindowState = FormWindowState.Normal;
            Activate();
        }

        protected override void OnFormClosing(FormClosingEventArgs e)
        {
            if (!exiting && e.CloseReason == CloseReason.UserClosing)
            {
                e.Cancel = true;
                Hide();
                if (!balloonShown)
                {
                    balloonShown = true;
                    tray.ShowBalloonTip(4000, "Bahi Sync", "Still syncing in the background. Right-click this icon to open it or exit.", ToolTipIcon.Info);
                }
                return;
            }
            tray.Visible = false;
            base.OnFormClosing(e);
        }

        void ExitApp()
        {
            if (MessageBox.Show(this, "Stop Bahi Sync? Tally data won't reach the app until you start it again.", "Bahi Sync",
                    MessageBoxButtons.OKCancel, MessageBoxIcon.Question) != DialogResult.OK) return;
            exiting = true;
            tray.Visible = false;
            Application.Exit();
        }

        // ------------------------------------------------------------ new versions of this app
        void CheckForUpdate()
        {
            if (BuildInfo.Number <= 0) return;
            try
            {
                var wc = new WebClient();
                wc.Headers.Add("User-Agent", "BahiSync");
                wc.Headers.Add("Accept", "application/vnd.github+json");
                string body = wc.DownloadString(ReleaseApi);
                var m = Regex.Match(body, "versionCode:\\s*(\\d+)");
                if (m.Success && int.Parse(m.Groups[1].Value) > BuildInfo.Number)
                {
                    newVersionUrl = ExeUrl;
                    BeginInvoke((MethodInvoker)delegate
                    {
                        update.Text = "A new version of Bahi Sync (1." + m.Groups[1].Value + ") is ready: click to install";
                        update.Visible = true;
                    });
                }
            }
            catch { }
        }

        void InstallUpdate()
        {
            if (newVersionUrl == null) return;
            update.Enabled = false; update.Text = "Downloading the new version ...";
            string exe = Application.ExecutablePath, fresh = exe + ".new";
            ThreadPool.QueueUserWorkItem(delegate
            {
                try
                {
                    var wc = new WebClient();
                    wc.Headers.Add("User-Agent", "BahiSync");
                    wc.DownloadFile(newVersionUrl, fresh);
                    if (new FileInfo(fresh).Length < 20000) throw new Exception("the download was incomplete");
                    // a small script swaps the files once this app has closed, then starts the new one
                    string cmd = Path.Combine(Path.GetTempPath(), "bahisync-update.cmd");
                    File.WriteAllText(cmd, "@echo off\r\nping 127.0.0.1 -n 3 >nul\r\nmove /y \"" + fresh + "\" \"" + exe + "\" >nul\r\nstart \"\" \"" + exe + "\"\r\ndel \"%~f0\"\r\n");
                    var p = new ProcessStartInfo("cmd.exe", "/c \"" + cmd + "\"");
                    p.CreateNoWindow = true; p.UseShellExecute = false;
                    BeginInvoke((MethodInvoker)delegate
                    {
                        Process.Start(p);
                        exiting = true; tray.Visible = false;
                        Application.Exit();
                    });
                }
                catch (Exception e)
                {
                    BeginInvoke((MethodInvoker)delegate { update.Enabled = true; update.Text = "Update failed (" + e.Message + "). Click to try again."; });
                }
            });
        }
    }
}
