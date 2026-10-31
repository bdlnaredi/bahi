using System;
using System.Collections.Generic;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Net;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;

namespace BahiSync
{
    /// <summary>Which Tally companies go to Bahi, and from which date. Each one is its own company in the app,
    /// picked with the company name at the top of the app.</summary>
    class CompaniesForm : Form
    {
        readonly Dictionary<string, object> cfg;
        readonly TableLayoutPanel grid = new TableLayoutPanel();
        readonly Label status = new Label();
        readonly Button save = new Button(), cancel = new Button(), refresh = new Button();
        readonly Dictionary<string, Row> rows = new Dictionary<string, Row>(StringComparer.OrdinalIgnoreCase);
        DateTime general;

        class Row { public CheckBox On; public DateTimePicker From; public Label State; public string BooksFrom = ""; public string LastOpen = ""; public bool OpenNow; }

        public CompaniesForm(Dictionary<string, object> cfg)
        {
            this.cfg = cfg;
            Text = "Bahi Sync - companies";
            Font = new Font("Segoe UI", 10f);
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false; MinimizeBox = false;
            StartPosition = FormStartPosition.CenterParent;
            AutoScaleMode = AutoScaleMode.Dpi;
            ClientSize = new Size(700, 520);
            try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { }

            DateTime d;
            if (!DateTime.TryParseExact(Engine.Get(cfg, "FromDate", ""), "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out d))
            {
                var now = DateTime.Today; d = new DateTime(now.Month >= 4 ? now.Year : now.Year - 1, 4, 1);
            }
            general = d;

            var t = new FlowLayoutPanel();
            t.Dock = DockStyle.Fill; t.Padding = new Padding(18); t.FlowDirection = FlowDirection.TopDown; t.WrapContents = false; t.AutoScroll = true;
            Controls.Add(t);

            var head = new Label(); head.Text = "Companies to sync"; head.AutoSize = true; head.Font = new Font(Font, FontStyle.Bold);
            t.Controls.Add(head);
            var hint = new Label(); hint.AutoSize = true; hint.ForeColor = Color.DimGray; hint.MaximumSize = new Size(660, 0); hint.Margin = new Padding(0, 4, 0, 8);
            hint.Text = "Tick every company you want in the Bahi app. Each one becomes its own company there: tap the company name at the top of the app to switch.\n\n" +
                        "Tally only lets Bahi read companies that are open in it. Open all of them together (Alt+F3, Select Company, pick each one), " +
                        "or have TallyPrime open them when it starts (F1 > Settings > Startup). A company not open in Tally keeps what it last synced " +
                        "and catches up when it is opened again.\n\nLeave \"From\" unticked to use the general start date (" + general.ToString("d MMM yyyy") + ", in Settings).";
            t.Controls.Add(hint);

            grid.AutoSize = true; grid.ColumnCount = 3; grid.Width = 660;
            grid.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 300));
            grid.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 170));
            grid.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 190));
            t.Controls.Add(grid);

            status.AutoSize = true; status.ForeColor = Color.DimGray; status.MaximumSize = new Size(660, 0); status.Margin = new Padding(0, 10, 0, 0);
            t.Controls.Add(status);

            var b = new FlowLayoutPanel(); b.FlowDirection = FlowDirection.RightToLeft; b.Width = 660; b.AutoSize = true; b.Margin = new Padding(0, 12, 0, 0);
            save.Text = "Save"; cancel.Text = "Cancel"; refresh.Text = "Look in Tally again";
            foreach (var x in new[] { save, cancel, refresh }) { x.AutoSize = true; b.Controls.Add(x); }
            t.Controls.Add(b);
            AcceptButton = save; CancelButton = cancel;
            save.Click += delegate { Save(); };
            cancel.Click += delegate { DialogResult = DialogResult.Cancel; Close(); };
            refresh.Click += delegate { AskTally(); };

            // what this PC has seen before, then what is set, then what Tally has open right now
            foreach (var e in Engine.SeenCompanies())
            {
                var r = Add(Engine.Get(e, "Name", ""));
                if (r == null) continue;
                r.BooksFrom = Engine.Get(e, "BooksFrom", ""); r.LastOpen = Engine.Get(e, "LastOpen", "");
            }
            foreach (var kv in Engine.CompanySettings(cfg)) Add(kv.Key);
            ShowStates();
            AskTally();
        }

        protected override void OnShown(EventArgs e)
        {
            base.OnShown(e);
            // an unticked date picker shows today once its window is made: show the general start date instead
            foreach (var r in rows.Values) if (!r.From.Checked) { r.From.Value = general; r.From.Checked = false; }
        }

        Row Add(string name)
        {
            if (string.IsNullOrEmpty(name)) return null;
            Row r;
            if (rows.TryGetValue(name, out r)) return r;
            r = new Row();
            var set = Engine.CompanySettings(cfg);
            Dictionary<string, object> mine;
            set.TryGetValue(name, out mine);
            r.On = new CheckBox(); r.On.Text = name; r.On.AutoSize = false; r.On.Width = 292; r.On.Height = 28;
            r.On.Checked = mine == null || Engine.Get(mine, "Sync", "True") != "False";
            r.From = new DateTimePicker(); r.From.Format = DateTimePickerFormat.Custom; r.From.CustomFormat = "d MMM yyyy";
            r.From.ShowCheckBox = true; r.From.Width = 160;
            DateTime d;
            string f = mine == null ? "" : Engine.Get(mine, "From", "");
            if (DateTime.TryParseExact(f, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out d)) { r.From.Value = d; r.From.Checked = true; }
            else { r.From.Value = general; r.From.Checked = false; }
            r.State = new Label(); r.State.AutoSize = true; r.State.ForeColor = Color.DimGray; r.State.Margin = new Padding(3, 6, 3, 0);
            if (rows.Count == 0)
            {
                foreach (var h in new[] { "Company", "From", "In Tally" })
                {
                    var l = new Label(); l.Text = h; l.AutoSize = true; l.ForeColor = Color.DimGray; l.Font = new Font(Font.FontFamily, 8.5f);
                    grid.Controls.Add(l);
                }
            }
            grid.Controls.Add(r.On); grid.Controls.Add(r.From); grid.Controls.Add(r.State);
            rows[name] = r;
            return r;
        }

        void ShowStates()
        {
            foreach (var r in rows.Values)
            {
                r.State.Text = r.OpenNow ? "open now" : (r.LastOpen != "" ? "last open " + r.LastOpen : "not open");
                r.State.ForeColor = r.OpenNow ? Color.DarkGreen : Color.DimGray;
            }
            if (rows.Count == 0) status.Text = "No company found yet. Open TallyPrime with your companies, then click \"Look in Tally again\".";
        }

        void AskTally()
        {
            string url = Engine.Get(cfg, "TallyUrl", "http://localhost:9000");
            status.ForeColor = Color.DimGray; status.Text = "Asking Tally which companies are open ...";
            refresh.Enabled = false;
            ThreadPool.QueueUserWorkItem(delegate
            {
                List<string> open = null; string err = null;
                try { open = Engine.OpenCompanies(url); } catch (Exception e) { err = e.Message; }
                try
                {
                    BeginInvoke((MethodInvoker)delegate
                    {
                        refresh.Enabled = true;
                        if (open == null) { status.ForeColor = Color.Firebrick; status.Text = "Tally isn't reachable (" + err + "). Showing the companies seen before."; ShowStates(); return; }
                        foreach (var r in rows.Values) r.OpenNow = false;
                        foreach (var n in open) { var r = Add(n); r.OpenNow = true; r.LastOpen = DateTime.Now.ToString("yyyy-MM-dd HH:mm"); }
                        status.ForeColor = Color.DimGray;
                        status.Text = open.Count == 0 ? "Tally is open but no company is loaded in it." :
                            open.Count + " compan" + (open.Count == 1 ? "y is" : "ies are") + " open in Tally now.";
                        ShowStates();
                    });
                }
                catch { }
            });
        }

        void Save()
        {
            var all = new Dictionary<string, object>();
            int on = 0;
            foreach (var kv in rows)
            {
                var c = new Dictionary<string, object>();
                c["Sync"] = kv.Value.On.Checked;
                if (kv.Value.On.Checked) on++;
                if (kv.Value.From.Checked) c["From"] = kv.Value.From.Value.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);
                all[kv.Key] = c;
            }
            if (rows.Count > 0 && on == 0 &&
                MessageBox.Show(this, "No company is ticked, so nothing will be synced. Save anyway?", "Bahi Sync", MessageBoxButtons.OKCancel, MessageBoxIcon.Warning) != DialogResult.OK)
                return;
            cfg["Companies"] = all;
            try { Engine.SaveConfig(cfg); }
            catch (Exception e) { status.ForeColor = Color.Firebrick; status.Text = "Couldn't save: " + e.Message; return; }
            DialogResult = DialogResult.OK;
            Close();
        }
    }
}
