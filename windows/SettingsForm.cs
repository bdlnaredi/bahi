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
        readonly TextBox server = new TextBox(), token = new TextBox(), tally = new TextBox();
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
            ClientSize = new Size(560, 470);
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

        void RunTest()
        {
            string s = Server(), tk = token.Text.Trim(), tl = tally.Text.Trim();
            result.ForeColor = Color.DimGray; result.Text = "Checking ...";
            test.Enabled = false;
            ThreadPool.QueueUserWorkItem(delegate
            {
                string se = s == "" ? "enter the address" : Engine.CheckServer(s, tk);
                string te = Engine.CheckTally(tl);
                BeginInvoke((MethodInvoker)delegate
                {
                    test.Enabled = true;
                    result.ForeColor = se == null ? Color.DarkGreen : Color.Firebrick;
                    result.Text = "Server: " + (se == null ? "connected, token accepted" : se) + "\nTally: " + (te == null ? "connected" : te);
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
