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
        public static BottomBar Bar(float k, Label message, Control[] buttons)
        {
            var bar = new BottomBar(k, message, buttons);
            bar.Dock = DockStyle.Bottom;
            return bar;
        }
    }

    /// <summary>A page that puts its controls one under another, in the order added, and scrolls to the very
    /// end of the last one (a FlowLayoutPanel can leave the last line under the bottom edge, out of reach).</summary>
    class StackPage : Panel
    {
        readonly int pad, end;
        bool busy;

        public StackPage(float k)
        {
            pad = Ui.S(k, 18); end = Ui.S(k, 24);
            AutoScroll = true;
        }

        /// <summary>The width a line can use, inside the margins and the scroll bar.</summary>
        public int LineWidth
        {
            get { return Math.Max(100, ClientSize.Width - 2 * pad - SystemInformation.VerticalScrollBarWidth); }
        }

        protected override void OnLayout(LayoutEventArgs e)
        {
            base.OnLayout(e);
            if (busy) return;
            busy = true;
            try
            {
                int x = pad + AutoScrollPosition.X, y = pad + AutoScrollPosition.Y, widest = 0;
                foreach (Control c in Controls)
                {
                    if (!c.Visible) continue;
                    y += c.Margin.Top;
                    var at = new Point(x + c.Margin.Left, y);
                    if (c.Location != at) c.Location = at;
                    y += c.Height + c.Margin.Bottom;
                    widest = Math.Max(widest, c.Margin.Left + c.Width + c.Margin.Right);
                }
                var want = new Size(widest + 2 * pad, y - AutoScrollPosition.Y + end);
                if (AutoScrollMinSize != want) AutoScrollMinSize = want;
            }
            finally { busy = false; }
        }
    }

    /// <summary>The message line (wrapped to the window) above the buttons (on the right); as tall as they need.</summary>
    class BottomBar : Panel
    {
        readonly Label message;
        readonly Control[] buttons;
        readonly int pad, gap;
        bool busy;

        public BottomBar(float k, Label message, Control[] buttons)
        {
            this.message = message; this.buttons = buttons;
            pad = Ui.S(k, 18); gap = Ui.S(k, 8);
            message.AutoSize = true;
            Controls.Add(message);
            foreach (var b in buttons) { b.AutoSize = true; Controls.Add(b); }
            message.TextChanged += delegate { PerformLayout(); };
            Height = Ui.S(k, 60);
        }

        protected override void OnLayout(LayoutEventArgs e)
        {
            base.OnLayout(e);
            if (busy) return;
            busy = true;
            try
            {
                int w = Math.Max(100, ClientSize.Width - 2 * pad);
                message.MaximumSize = new Size(w, 0);
                int y = gap;
                message.Location = new Point(pad, y);
                if (message.Text.Length > 0) y += message.Height + gap;
                int x = ClientSize.Width - pad, tall = 0;
                foreach (var b in buttons)          // the first one rightmost
                {
                    x -= b.Width;
                    b.Location = new Point(Math.Max(pad, x), y);
                    x -= gap;
                    tall = Math.Max(tall, b.Height);
                }
                int h = y + tall + pad;
                if (Height != h) Height = h;
            }
            finally { busy = false; }
        }
    }
}
