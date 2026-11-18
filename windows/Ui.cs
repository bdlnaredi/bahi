using System;
using System.Drawing;
using System.Windows.Forms;

namespace BahiSync
{
    /// <summary>Window sizes that suit the screen: sizes are given as at 100% Windows scaling, multiplied by the
    /// scaling in use (125%, 150% ...), and never larger than the screen (a 1366 x 768 laptop, say).</summary>
    static class Ui
    {
        public static float K(Control c)
        {
            try { using (var g = c.CreateGraphics()) return Math.Max(1f, g.DpiX / 96f); }
            catch { return 1f; }
        }

        public static int S(float k, int px) { return (int)Math.Round(px * k); }

        /// <summary>Size the window's inside to w x h (at 100%), but leave room on the screen it opens on.</summary>
        public static void Fit(Form f, int w, int h, int minW, int minH)
        {
            float k = K(f);
            Rectangle wa = Screen.FromPoint(Cursor.Position).WorkingArea;
            int cw = Math.Min(S(k, w), wa.Width - S(k, 40));
            int ch = Math.Min(S(k, h), wa.Height - S(k, 70));     // the title bar and a margin
            f.ClientSize = new Size(cw, ch);
            f.MinimumSize = new Size(Math.Min(S(k, minW), wa.Width), Math.Min(S(k, minH), wa.Height));
        }

        /// <summary>A bar at the bottom of the window for the message line and the buttons, always in view
        /// however long the page above it is.</summary>
        public static FlowLayoutPanel Bar(float k, Label message, Control[] buttons, out FlowLayoutPanel row)
        {
            var bar = new FlowLayoutPanel();
            bar.Dock = DockStyle.Bottom; bar.FlowDirection = FlowDirection.TopDown; bar.WrapContents = false; bar.AutoSize = true;
            bar.Padding = new Padding(S(k, 18), S(k, 4), S(k, 18), S(k, 12));
            message.AutoSize = true; message.Margin = new Padding(0, 0, 0, S(k, 6));
            bar.Controls.Add(message);
            row = new FlowLayoutPanel();
            row.FlowDirection = FlowDirection.RightToLeft; row.WrapContents = false; row.AutoSize = true; row.Margin = new Padding(0);
            foreach (var b in buttons) { b.AutoSize = true; row.Controls.Add(b); }
            bar.Controls.Add(row);
            return bar;
        }
    }
}
