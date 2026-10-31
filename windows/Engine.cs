using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Reflection;
using System.Text;
using System.Text.RegularExpressions;
using System.Web.Script.Serialization;
using Microsoft.Win32;

namespace BahiSync
{
    /// <summary>Settings, the sync script that does the work, and the plumbing around them.</summary>
    static class Engine
    {
        public static readonly string Dir = Path.GetDirectoryName(Application_ExecutablePath());
        public static readonly string ConfigPath = Path.Combine(Dir, "TallySync.config.json");
        public static readonly string LogPath = Path.Combine(Dir, "TallySync.log");
        public static readonly string Script = Path.Combine(Dir, "TallySync.ps1");
        const string RunKey = @"Software\Microsoft\Windows\CurrentVersion\Run";

        static string Application_ExecutablePath()
        {
            return Assembly.GetExecutingAssembly().Location;
        }

        // ------------------------------------------------------------ settings (the same file the script reads)
        public static Dictionary<string, object> LoadConfig()
        {
            try
            {
                if (File.Exists(ConfigPath))
                {
                    var d = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(File.ReadAllText(ConfigPath));
                    if (d != null) return d;
                }
            }
            catch { }
            return new Dictionary<string, object>();
        }

        public static string Get(Dictionary<string, object> cfg, string key, string fallback)
        {
            object v;
            if (cfg.TryGetValue(key, out v) && v != null && v.ToString().Trim() != "") return v.ToString().Trim();
            return fallback;
        }

        public static void SaveConfig(Dictionary<string, object> cfg)
        {
            string json = new JavaScriptSerializer().Serialize(cfg);
            string tmp = ConfigPath + ".tmp";
            File.WriteAllText(tmp, json, new UTF8Encoding(false));
            if (File.Exists(ConfigPath)) File.Delete(ConfigPath);
            File.Move(tmp, ConfigPath);
        }

        public static bool Configured(Dictionary<string, object> cfg)
        {
            return Get(cfg, "ServerUrl", "") != "" && Get(cfg, "SyncToken", "") != "";
        }

        // ------------------------------------------------------------ companies
        /// <summary>Per-company settings: name to {Sync, From}.</summary>
        public static Dictionary<string, Dictionary<string, object>> CompanySettings(Dictionary<string, object> cfg)
        {
            var o = new Dictionary<string, Dictionary<string, object>>(StringComparer.OrdinalIgnoreCase);
            object v;
            var all = cfg.TryGetValue("Companies", out v) ? v as Dictionary<string, object> : null;
            if (all == null) return o;
            foreach (var kv in all)
            {
                var c = kv.Value as Dictionary<string, object>;
                if (c != null) o[kv.Key] = c;
            }
            return o;
        }

        /// <summary>Companies the sync has seen open in Tally (it keeps the list in TallySync.companies.json).</summary>
        public static List<Dictionary<string, object>> SeenCompanies()
        {
            var o = new List<Dictionary<string, object>>();
            try
            {
                string path = Path.Combine(Dir, "TallySync.companies.json");
                if (!File.Exists(path)) return o;
                object x = new JavaScriptSerializer().DeserializeObject(File.ReadAllText(path));
                var one = x as Dictionary<string, object>;
                if (one != null) { o.Add(one); return o; }
                var many = x as object[];
                if (many != null) foreach (var e in many) { var d = e as Dictionary<string, object>; if (d != null) o.Add(d); }
            }
            catch { }
            return o;
        }

        /// <summary>The companies open in Tally right now (only reads; Tally is asked for a list of names).</summary>
        public static List<string> OpenCompanies(string url)
        {
            string xml = "<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Collection</TYPE><ID>BSCompanies</ID></HEADER>" +
                         "<BODY><DESC><STATICVARIABLES><SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT></STATICVARIABLES><TDL><TDLMESSAGE>" +
                         "<COLLECTION NAME=\"BSCompanies\" ISMODIFY=\"No\"><TYPE>Company</TYPE><FETCH>Name</FETCH></COLLECTION>" +
                         "</TDLMESSAGE></TDL></DESC></BODY></ENVELOPE>";
            var wc = new WebClient();
            wc.Headers.Add("Content-Type", "text/xml;charset=utf-8");
            string body = Encoding.UTF8.GetString(wc.UploadData(url, "POST", Encoding.UTF8.GetBytes(xml)));
            var names = new List<string>();
            foreach (Match m in Regex.Matches(body, "<COMPANY NAME=\"([^\"]*)\""))
            {
                string n = WebUtility.HtmlDecode(m.Groups[1].Value).Trim();
                if (n != "" && !names.Contains(n)) names.Add(n);
            }
            return names;
        }

        // ------------------------------------------------------------ the scripts inside this .exe
        static int[] Ver(string s)
        {
            var m = Regex.Match(s ?? "", "\\$AgentVersion\\s*=\\s*\"(\\d+)\\.(\\d+)\"");
            if (!m.Success) return new int[] { 0, 0 };
            return new int[] { int.Parse(m.Groups[1].Value), int.Parse(m.Groups[2].Value) };
        }

        static bool Newer(int[] a, int[] b)
        {
            return a[0] > b[0] || (a[0] == b[0] && a[1] > b[1]);
        }

        /// <summary>Puts the sync scripts next to the .exe: when missing, or when the copy inside is newer than the
        /// one on disk (the script also updates itself from the server, so the disk copy is often newer).</summary>
        public static string ExtractScripts()
        {
            var asm = Assembly.GetExecutingAssembly();
            string inside = ReadResource(asm, "TallySync.ps1");
            string onDisk = File.Exists(Script) ? File.ReadAllText(Script) : null;
            bool replace = onDisk == null || Newer(Ver(inside), Ver(onDisk));
            foreach (string name in asm.GetManifestResourceNames())
            {
                if (!name.EndsWith(".ps1")) continue;
                string path = Path.Combine(Dir, name);
                if (replace || !File.Exists(path))
                    File.WriteAllText(path, ReadResource(asm, name), new UTF8Encoding(true));
            }
            return ScriptVersion();
        }

        public static string ScriptVersion()
        {
            try { var v = Ver(File.ReadAllText(Script)); return v[0] + "." + v[1]; } catch { return "?"; }
        }

        static string ReadResource(Assembly asm, string name)
        {
            using (var s = asm.GetManifestResourceStream(name))
            using (var r = new StreamReader(s, Encoding.UTF8))
                return r.ReadToEnd();
        }

        // ------------------------------------------------------------ running the script
        public static Process StartSync(string extra)
        {
            var p = new Process();
            p.StartInfo.FileName = "powershell.exe";
            p.StartInfo.Arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File \"" + Script + "\"" +
                                    (string.IsNullOrEmpty(extra) ? "" : " " + extra);
            p.StartInfo.WorkingDirectory = Dir;
            p.StartInfo.UseShellExecute = false;
            p.StartInfo.CreateNoWindow = true;
            p.EnableRaisingEvents = true;
            p.Start();
            return p;
        }

        /// <summary>The interactive tools (Diagnose, Save voucher, Save stock) run in a normal window.</summary>
        public static void StartTool(string script)
        {
            var p = new ProcessStartInfo("powershell.exe", "-NoProfile -ExecutionPolicy Bypass -File \"" + Path.Combine(Dir, script) + "\"");
            p.WorkingDirectory = Dir;
            p.UseShellExecute = true;
            Process.Start(p);
        }

        // ------------------------------------------------------------ checks shown in the window
        public static string CheckTally(string url)
        {
            try
            {
                var req = (HttpWebRequest)WebRequest.Create(url);
                req.Timeout = 5000;
                using (var res = (HttpWebResponse)req.GetResponse())
                using (var r = new StreamReader(res.GetResponseStream()))
                {
                    string body = r.ReadToEnd();
                    return body.IndexOf("Running", StringComparison.OrdinalIgnoreCase) >= 0 ? null : "answers, but isn't TallyPrime";
                }
            }
            catch (Exception) { return "not reachable - is TallyPrime open?"; }
        }

        /// <summary>null when the server answers and accepts the token, else what's wrong in plain words.</summary>
        public static string CheckServer(string server, string token)
        {
            try
            {
                var req = (HttpWebRequest)WebRequest.Create(server.TrimEnd('/') + "/agent/update");
                req.Timeout = 10000;
                req.Headers.Add("Authorization", "Bearer " + token);
                using (var res = (HttpWebResponse)req.GetResponse()) { return null; }
            }
            catch (WebException e)
            {
                var res = e.Response as HttpWebResponse;
                if (res != null && (int)res.StatusCode == 401) return "the sync token is wrong";
                if (res != null && (int)res.StatusCode == 404) return "it answers, but isn't a Bahi server (or an old one)";
                if (res != null) return "it answered with error " + (int)res.StatusCode;
                return "not reachable (" + e.Status + ")";
            }
            catch (Exception e) { return "not reachable (" + e.Message + ")"; }
        }

        // ------------------------------------------------------------ start with Windows
        public static bool StartsWithWindows()
        {
            using (var k = Registry.CurrentUser.OpenSubKey(RunKey))
                return k != null && k.GetValue("BahiSync") != null;
        }

        public static void SetStartWithWindows(bool on)
        {
            using (var k = Registry.CurrentUser.CreateSubKey(RunKey))
            {
                if (on) k.SetValue("BahiSync", "\"" + Application_ExecutablePath() + "\" --tray");
                else if (k.GetValue("BahiSync") != null) k.DeleteValue("BahiSync");
            }
        }

        /// <summary>First start of an installed copy: bring the settings and sync records over from the folder the
        /// earlier copy ran in (BahiSync.exe on its own, or the batch-file setup). Returns that folder, or null.</summary>
        public static string MigrateFromOld()
        {
            if (File.Exists(ConfigPath)) return null;
            var dirs = new List<string>();
            bool started = false;
            try
            {
                using (var k = Registry.CurrentUser.OpenSubKey(RunKey))
                {
                    var v = k == null ? null : k.GetValue("BahiSync") as string;
                    if (!string.IsNullOrEmpty(v))
                    {
                        var m = Regex.Match(v, "^\"([^\"]+)\"");
                        dirs.Add(Path.GetDirectoryName(m.Success ? m.Groups[1].Value : v.Split(' ')[0]));
                        started = true;
                    }
                }
            }
            catch { }
            try
            {
                var p = new ProcessStartInfo("schtasks.exe", "/Query /TN \"Tally Mobile Sync\" /XML");
                p.CreateNoWindow = true; p.UseShellExecute = false; p.RedirectStandardOutput = true; p.RedirectStandardError = true;
                using (var pr = Process.Start(p))
                {
                    string xml = pr.StandardOutput.ReadToEnd(); pr.WaitForExit(10000);
                    var m = Regex.Match(xml, "([A-Za-z]:\\\\[^\"<>]*?)\\\\run-hidden\\.vbs", RegexOptions.IgnoreCase);
                    if (m.Success) dirs.Add(m.Groups[1].Value);
                }
            }
            catch { }
            foreach (var c in new[] { @"C:\Bahi", @"C:\TallySync", @"C:\Tally Mobile", @"C:\TallyMobile", @"C:\Tally Sync" }) dirs.Add(c);
            foreach (var d in dirs)
            {
                try
                {
                    if (string.IsNullOrEmpty(d) || string.Equals(Path.GetFullPath(d).TrimEnd('\\'), Path.GetFullPath(Dir).TrimEnd('\\'), StringComparison.OrdinalIgnoreCase)) continue;
                    if (!File.Exists(Path.Combine(d, "TallySync.config.json"))) continue;
                    foreach (var f in new[] { "TallySync.config.json", "TallySync.sent", "TallySync.method", "TallySync.noguid", "TallySync.deep",
                                              "TallySync.companies.json", "TallySync.log" })
                    {
                        string from = Path.Combine(d, f), to = Path.Combine(Dir, f);
                        if (File.Exists(from) && !File.Exists(to)) File.Copy(from, to);
                    }
                    if (started) SetStartWithWindows(true);       // start this copy with Windows instead of the old one
                    return d;
                }
                catch { }
            }
            return null;
        }

        /// <summary>The scheduled task from the older batch-file setup would sync alongside this app: remove it.</summary>
        public static bool RemoveOldTask()
        {
            try
            {
                var p = new ProcessStartInfo("schtasks.exe", "/Delete /TN \"Tally Mobile Sync\" /F");
                p.CreateNoWindow = true;
                p.UseShellExecute = false;
                p.RedirectStandardOutput = true;
                p.RedirectStandardError = true;
                using (var pr = Process.Start(p)) { pr.WaitForExit(10000); return pr.ExitCode == 0; }
            }
            catch { return false; }
        }
    }
}
