using System;
using System.Collections.Generic;
using System.Drawing;
using System.Globalization;
using System.Threading;
using System.Windows.Forms;

namespace BahiSync
{
    /// <summary>Where the server and Tally are, and from which date to sync (what Setup.bat used to ask).</summary>
    class SettingsForm : Form
    {
        readonly Dictionary<string, object> cfg;
        readonly TextBox server = new TextBox(), token = new TextBox(), tally = new TextBox(), server2 = new TextBox(), token2 = new TextBox();
        readonly DateTimePicker from = new DateTimePicker();
        readonly CheckBox showToken = new CheckBox(), startup = new CheckBox();
        readonly Label result = new Label();
        readonly Button test = new Button(), save = new Button(), cancel = new Button();

        public SettingsForm(Dictionary<string, object> cfg)
        {
            this.cfg = cfg;
            Text = "Bahi Sync - settings";
            Font = new Font("Segoe UI", 10f);
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false; MinimizeBox = false;
            StartPosition = FormStartPosition.CenterScreen;
            AutoScaleMode = AutoScaleMode.Dpi;
            ClientSize = new Size(580, 680);
            try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { }

            var t = new FlowLayoutPanel();
            t.Dock = DockStyle.Fill; t.Padding = new Padding(18); t.FlowDirection = FlowDirection.TopDown; t.WrapContents = false; t.AutoScroll = true;
            Controls.Add(t);

            AddField(t, "Bahi server address", "The address you open the app with, for example https://books.yourdomain.com", server);
            server.Text = Engine.Get(cfg, "ServerUrl", "");
            AddField(t, "Sync token", "The SYNC_TOKEN set on the Bahi container in Unraid", token);
            token.Text = Engine.Get(cfg, "SyncToken", "");
            token.UseSystemPasswordChar = true;
            showToken.Text = "Show"; showToken.AutoSize = true;
            showToken.CheckedChanged += delegate { token.UseSystemPasswordChar = !showToken.Checked; };
            t.Controls.Add(showToken);
            AddField(t, "Tally address", "Leave as it is unless Tally uses another port (F1 > Settings > Connectivity in TallyPrime)", tally);
            tally.Text = Engine.Get(cfg, "TallyUrl", "http://localhost:9000");

            var lf = new Label(); lf.Text = "Sync vouchers from"; lf.AutoSize = true; lf.Font = new Font(Font, FontStyle.Bold); lf.Margin = new Padding(0, 10, 0, 2);
            t.Controls.Add(lf);
            from.Format = DateTimePickerFormat.Custom; from.CustomFormat = "d MMM yyyy"; from.Width = 200;
            DateTime d;
            string fd = Engine.Get(cfg, "FromDate", "");
            if (DateTime.TryParseExact(fd, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out d)) from.Value = d;
            else { var now = DateTime.Today; from.Value = new DateTime(now.Month >= 4 ? now.Year : now.Year - 1, 4, 1); }
            t.Controls.Add(from);

            var l2 = new Label(); l2.Text = "Also sync to (optional)"; l2.AutoSize = true; l2.Font = new Font(Font.FontFamily, 11f, FontStyle.Bold); l2.Margin = new Padding(0, 18, 0, 0);
            t.Controls.Add(l2);
            var h2 = new Label(); h2.AutoSize = true; h2.ForeColor = Color.DimGray; h2.MaximumSize = new Size(520, 0);
            h2.Text = "A second Bahi server (for example the cloud one while you try it, besides Unraid). After each sync to the server above, the same sync goes to this one. Tally does the work twice, so each sync takes about twice as long. Leave empty for one server.";
            t.Controls.Add(h2);
            AddField(t, "Second server address", "e.g. https://140-245-2-139.sslip.io", server2);
            server2.Text = Engine.Get(cfg, "ServerUrl2", "");
            AddField(t, "Second server's sync token", "The sync token the second server's installer printed", token2);
            token2.Text = Engine.Get(cfg, "SyncToken2", "");
            token2.UseSystemPasswordChar = true;
            showToken.CheckedChanged += delegate { token2.UseSystemPasswordChar = !showToken.Checked; };

            startup.Text = "Start with Windows (syncs whenever this PC is on)";
            startup.AutoSize = true; startup.Margin = new Padding(0, 12, 0, 0);
            startup.Checked = !Engine.Configured(cfg) || Engine.StartsWithWindows();
            t.Controls.Add(startup);

            result.AutoSize = true; result.MaximumSize = new Size(520, 0); result.Margin = new Padding(0, 10, 0, 0);
            t.Controls.Add(result);

            var b = new FlowLayoutPanel(); b.FlowDirection = FlowDirection.RightToLeft; b.Width = 520; b.AutoSize = true; b.Margin = new Padding(0, 12, 0, 0);
            save.Text = "Save"; save.AutoSize = true; cancel.Text = "Cancel"; cancel.AutoSize = true; test.Text = "Test connection"; test.AutoSize = true;
            b.Controls.Add(save); b.Controls.Add(cancel); b.Controls.Add(test);
            t.Controls.Add(b);
            AcceptButton = save; CancelButton = cancel;

            test.Click += delegate { RunTest(); };
            cancel.Click += delegate { DialogResult = DialogResult.Cancel; Close(); };
            save.Click += delegate { Save(); };
        }

        void AddField(FlowLayoutPanel t, string label, string hint, TextBox box)
        {
            var l = new Label(); l.Text = label; l.AutoSize = true; l.Font = new Font(Font, FontStyle.Bold); l.Margin = new Padding(0, 10, 0, 2);
            var h = new Label(); h.Text = hint; h.AutoSize = true; h.ForeColor = Color.DimGray; h.MaximumSize = new Size(520, 0);
            box.Width = 520;
            t.Controls.Add(l); t.Controls.Add(h); t.Controls.Add(box);
        }

        string Server() { return server.Text.Trim().TrimEnd('/'); }
        string Server2()
        {
            string s = server2.Text.Trim().TrimEnd('/');
            if (s != "" && !s.StartsWith("http://") && !s.StartsWith("https://")) s = "https://" + s;
            return s;
        }

        void RunTest()
        {
            string s = Server(), tk = token.Text.Trim(), tl = tally.Text.Trim(), tk2 = token2.Text.Trim();
            result.ForeColor = Color.DimGray; result.Text = "Checking ...";
            test.Enabled = false;
            ThreadPool.QueueUserWorkItem(delegate
            {
                string se = s == "" ? "enter the address" : Engine.CheckServer(s, tk);
                string te = Engine.CheckTally(tl);
                string s2 = Server2(), se2 = s2 == "" ? null : Engine.CheckServer(s2, tk2);
                BeginInvoke((MethodInvoker)delegate
                {
                    test.Enabled = true;
                    bool ok = se == null && (s2 == "" || se2 == null);
                    result.ForeColor = ok ? Color.DarkGreen : Color.Firebrick;
                    result.Text = "Server: " + (se == null ? "connected, token accepted" : se) +
                                  (s2 == "" ? "" : "\nSecond server: " + (se2 == null ? "connected, token accepted" : se2)) +
                                  "\nTally: " + (te == null ? "connected" : te);
                });
            });
        }

        void Save()
        {
            if (Server() == "" || token.Text.Trim() == "")
            {
                result.ForeColor = Color.Firebrick; result.Text = "Enter the server address and the sync token.";
                return;
            }
            string s = Server();
            if (!s.StartsWith("http://") && !s.StartsWith("https://")) s = "https://" + s;
            cfg["ServerUrl"] = s;
            cfg["SyncToken"] = token.Text.Trim();
            cfg["TallyUrl"] = tally.Text.Trim() == "" ? "http://localhost:9000" : tally.Text.Trim();
            cfg["FromDate"] = from.Value.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);
            string s2 = Server2();
            if (s2 != "" && token2.Text.Trim() == "")
            {
                result.ForeColor = Color.Firebrick; result.Text = "Enter the second server's sync token too (or clear its address).";
                return;
            }
            if (s2 != "" && s2.TrimEnd('/') == s.TrimEnd('/'))
            {
                result.ForeColor = Color.Firebrick; result.Text = "The second server is the same as the first.";
                return;
            }
            if (s2 == "") { cfg.Remove("ServerUrl2"); cfg.Remove("SyncToken2"); }
            else { cfg["ServerUrl2"] = s2; cfg["SyncToken2"] = token2.Text.Trim(); }
            try
            {
                Engine.SaveConfig(cfg);
                Engine.SetStartWithWindows(startup.Checked);
            }
            catch (Exception e)
            {
                result.ForeColor = Color.Firebrick; result.Text = "Couldn't save: " + e.Message;
                return;
            }
            DialogResult = DialogResult.OK;
            Close();
        }
    }
}
