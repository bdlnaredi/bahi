using System;
using System.Net;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;

namespace BahiSync
{
    static class Program
    {
        [DllImport("user32.dll")]
        static extern bool SetProcessDPIAware();

        [STAThread]
        static void Main(string[] args)
        {
            // https to the server and GitHub needs TLS 1.2, which older .NET Framework doesn't switch on by itself
            ServicePointManager.SecurityProtocol |= (SecurityProtocolType)3072;
            try { SetProcessDPIAware(); } catch { }

            bool first;
            using (Mutex one = new Mutex(true, "Local\\BahiSyncApp", out first))
            {
                if (!first)
                {
                    // already running: bring that window up instead of starting a second copy
                    try { EventWaitHandle.OpenExisting("Local\\BahiSyncAppShow").Set(); } catch { }
                    return;
                }
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                bool tray = Array.IndexOf(args, "--tray") >= 0;
                var main = new MainForm(tray);
                main.CompaniesAtStart = Array.IndexOf(args, "--companies") >= 0;
                Application.Run(main);
            }
        }
    }
}
