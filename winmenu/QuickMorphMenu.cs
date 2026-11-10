// QuickMorph - Windows 11 context-menu command.
//
// Windows 11 only lets *packaged* apps put an entry in its right-click menu, and such an entry must be a COM
// object implementing IExplorerCommand. This tiny program is that object: Explorer starts it on demand, asks
// for the title/icon, and on a click it hands the selected files to QuickMorph (pythonw run.pyw --queue ...).
// It stays around for a few minutes after the last right-click, so only the first menu after a pause pays for
// starting it; then it exits and nothing stays running. (Each entry has its own package and therefore its own
// copy: Windows does not let one package's program answer for another package's entry.)
//
// install.py compiles it with the C# compiler that ships with Windows (no SDK, no binary in the repository),
// which is why this file sticks to C# 5 syntax.
using System;
using System.Collections.Generic;
using System.Diagnostics;  // only touched when an entry is clicked
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

[assembly: System.Reflection.AssemblyTitle("QuickMorph menu")]
[assembly: System.Reflection.AssemblyProduct("QuickMorph")]
[assembly: System.Reflection.AssemblyVersion("1.0.0.0")]

namespace QuickMorph
{
    [ComImport, Guid("43826d1e-e718-42ee-bc55-a1e261c37bfe"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IShellItem
    {
        [PreserveSig] int BindToHandler(IntPtr pbc, ref Guid bhid, ref Guid riid, out IntPtr ppv);
        [PreserveSig] int GetParent(out IShellItem ppsi);
        [PreserveSig] int GetDisplayName(uint sigdnName, out IntPtr ppszName);
        [PreserveSig] int GetAttributes(uint sfgaoMask, out uint psfgaoAttribs);
        [PreserveSig] int Compare(IShellItem psi, uint hint, out int piOrder);
    }

    [ComImport, Guid("b63ea76d-1f85-456f-a19c-48159efa858b"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IShellItemArray
    {
        [PreserveSig] int BindToHandler(IntPtr pbc, ref Guid bhid, ref Guid riid, out IntPtr ppvOut);
        [PreserveSig] int GetPropertyStore(int flags, ref Guid riid, out IntPtr ppv);
        [PreserveSig] int GetPropertyDescriptionList(IntPtr keyType, ref Guid riid, out IntPtr ppv);
        [PreserveSig] int GetAttributes(int attribFlags, uint sfgaoMask, out uint psfgaoAttribs);
        [PreserveSig] int GetCount(out uint pdwNumItems);
        [PreserveSig] int GetItemAt(uint dwIndex, out IShellItem ppsi);
        [PreserveSig] int EnumItems(out IntPtr ppenumShellItems);
    }

    [ComImport, Guid("a08ce4d0-fa25-44ab-b57c-c7b1c323e0b9"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IExplorerCommand
    {
        [PreserveSig] int GetTitle(IShellItemArray items, out IntPtr name);
        [PreserveSig] int GetIcon(IShellItemArray items, out IntPtr icon);
        [PreserveSig] int GetToolTip(IShellItemArray items, out IntPtr infoTip);
        [PreserveSig] int GetCanonicalName(out Guid commandName);
        [PreserveSig] int GetState(IShellItemArray items, [MarshalAs(UnmanagedType.Bool)] bool okToBeSlow, out uint state);
        [PreserveSig] int Invoke(IShellItemArray items, IntPtr bindCtx);
        [PreserveSig] int GetFlags(out uint flags);
        [PreserveSig] int EnumSubCommands(out IntPtr enumerator);
    }

    /// <summary>Settings written next to the .exe by install.py (key=value lines, UTF-8).</summary>
    internal static class Config
    {
        public static string Action = "";   // view | save: the entry this copy answers for
        public static string ViewTitle = "View as PDF";
        public static string SaveTitle = "Convert to PDF";
        public static string Python = "";   // full path to pythonw.exe
        public static string Script = "";   // full path to run.pyw
        public static string Icon = "";     // "C:\...\some.dll,-68"

        public static bool Load()
        {
            try
            {
                // (deliberately nothing from System.Diagnostics here: start-up only needs mscorlib, which is faster)
                string cfg = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "QuickMorphMenu.cfg");
                foreach (string raw in File.ReadAllLines(cfg, Encoding.UTF8))
                {
                    int eq = raw.IndexOf('=');
                    if (eq <= 0) continue;
                    string key = raw.Substring(0, eq).Trim().ToLowerInvariant();
                    string value = raw.Substring(eq + 1).Trim();
                    if (key == "action") Action = value;
                    else if (key == "view") ViewTitle = value;
                    else if (key == "save") SaveTitle = value;
                    else if (key == "python") Python = value;
                    else if (key == "script") Script = value;
                    else if (key == "icon") Icon = value;
                }
            }
            catch (Exception)
            {
                return false;
            }
            return (Action == "view" || Action == "save") && File.Exists(Python) && File.Exists(Script);
        }
    }

    [ComVisible(true), ClassInterface(ClassInterfaceType.None)]
    public abstract class CommandBase : IExplorerCommand
    {
        private const int S_OK = 0;
        private const int E_NOTIMPL = unchecked((int)0x80004001);
        private const int E_FAIL = unchecked((int)0x80004005);
        private const uint SIGDN_FILESYSPATH = 0x80058000;
        private const int MAX_COMMAND_LINE = 30000;  // CreateProcess allows 32767 characters

        internal static int Live;                    // objects Explorer still holds
        internal static long LastUse = DateTime.UtcNow.Ticks;

        protected abstract string Action { get; }  // view | save
        protected abstract string Title { get; }

        protected CommandBase()
        {
            Interlocked.Increment(ref Live);
            Touch();
        }

        ~CommandBase()
        {
            Interlocked.Decrement(ref Live);
        }

        private static void Touch()
        {
            Interlocked.Exchange(ref LastUse, DateTime.UtcNow.Ticks);
        }

        int IExplorerCommand.GetTitle(IShellItemArray items, out IntPtr name)
        {
            Touch();
            name = Marshal.StringToCoTaskMemUni(Title);
            return S_OK;
        }

        int IExplorerCommand.GetIcon(IShellItemArray items, out IntPtr icon)
        {
            Touch();
            if (Config.Icon.Length == 0)
            {
                icon = IntPtr.Zero;
                return E_NOTIMPL;
            }
            icon = Marshal.StringToCoTaskMemUni(Config.Icon);
            return S_OK;
        }

        int IExplorerCommand.GetToolTip(IShellItemArray items, out IntPtr infoTip)
        {
            infoTip = IntPtr.Zero;
            return E_NOTIMPL;
        }

        int IExplorerCommand.GetCanonicalName(out Guid commandName)
        {
            commandName = GetType().GUID;
            return S_OK;
        }

        int IExplorerCommand.GetState(IShellItemArray items, bool okToBeSlow, out uint state)
        {
            Touch();
            state = 0;  // ECS_ENABLED - QuickMorph itself explains what it cannot convert
            return S_OK;
        }

        int IExplorerCommand.GetFlags(out uint flags)
        {
            flags = 0;  // ECF_DEFAULT
            return S_OK;
        }

        int IExplorerCommand.EnumSubCommands(out IntPtr enumerator)
        {
            enumerator = IntPtr.Zero;
            return E_NOTIMPL;
        }

        int IExplorerCommand.Invoke(IShellItemArray items, IntPtr bindCtx)
        {
            Touch();
            try
            {
                List<string> files = Paths(items);
                if (files.Count == 0) return S_OK;
                // One QuickMorph process per ~30,000 characters of paths; its --queue mode converts
                // everything one file at a time no matter how many processes drop work in.
                string head = Quote(Config.Script) + " --queue --action " + Action + " --";
                StringBuilder args = new StringBuilder(head);
                foreach (string f in files)
                {
                    string q = " " + Quote(f);
                    if (args.Length > head.Length && Config.Python.Length + args.Length + q.Length > MAX_COMMAND_LINE)
                    {
                        Launch(args.ToString());
                        args = new StringBuilder(head);
                    }
                    args.Append(q);
                }
                Launch(args.ToString());
                return S_OK;
            }
            catch (Exception)
            {
                return E_FAIL;
            }
            finally
            {
                Touch();
            }
        }

        private static List<string> Paths(IShellItemArray items)
        {
            List<string> files = new List<string>();
            uint count;
            if (items == null || items.GetCount(out count) != S_OK) return files;
            for (uint i = 0; i < count; i++)
            {
                IShellItem item;
                if (items.GetItemAt(i, out item) != S_OK || item == null) continue;
                IntPtr p;
                if (item.GetDisplayName(SIGDN_FILESYSPATH, out p) == S_OK && p != IntPtr.Zero)
                {
                    string path = Marshal.PtrToStringUni(p);
                    Marshal.FreeCoTaskMem(p);
                    if (!string.IsNullOrEmpty(path)) files.Add(path);
                }
                Marshal.ReleaseComObject(item);
            }
            return files;
        }

        private static void Launch(string arguments)
        {
            ProcessStartInfo psi = new ProcessStartInfo(Config.Python, arguments);
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;
            // never start inside the folder that was clicked (QuickMorph leaves it anyway)
            psi.WorkingDirectory = Path.GetDirectoryName(Config.Script);
            using (Process.Start(psi)) { }
        }

        /// <summary>Quote one argument the way the Microsoft C runtime (and so Python) parses it back.</summary>
        internal static string Quote(string arg)
        {
            StringBuilder sb = new StringBuilder("\"");
            int backslashes = 0;
            foreach (char c in arg)
            {
                if (c == '\\')
                {
                    backslashes++;
                }
                else if (c == '"')
                {
                    sb.Append('\\', backslashes * 2 + 1);
                    sb.Append('"');
                    backslashes = 0;
                }
                else
                {
                    sb.Append('\\', backslashes);
                    sb.Append(c);
                    backslashes = 0;
                }
            }
            sb.Append('\\', backslashes * 2);
            sb.Append('"');
            return sb.ToString();
        }
    }

    [ComVisible(true), Guid("A10E8A86-B250-4050-8D12-295FA3DD7532"), ClassInterface(ClassInterfaceType.None)]
    public sealed class ViewCommand : CommandBase
    {
        protected override string Action { get { return "view"; } }
        protected override string Title { get { return Config.ViewTitle; } }
    }

    [ComVisible(true), Guid("FBE6F860-8DB7-433F-BC65-3C682A26C1EC"), ClassInterface(ClassInterfaceType.None)]
    public sealed class SaveCommand : CommandBase
    {
        protected override string Action { get { return "save"; } }
        protected override string Title { get { return Config.SaveTitle; } }
    }

    internal static class Program
    {
        private const int IDLE_SECONDS = 300;      // stay warm this long after the last right-click, then quit
        private const int ABANDONED_SECONDS = 900; // ...or if a menu has been left open for 15 minutes
        private const string QUIT_EVENT = "Local\\QuickMorph.MenuHelper.Quit";  // install.py sets it before replacing us

        [MTAThread]
        private static int Main(string[] args)
        {
            if (!Config.Load()) return 2;
            Type type = Config.Action == "view" ? typeof(ViewCommand) : typeof(SaveCommand);
            RegistrationServices services = new RegistrationServices();
            int cookie = services.RegisterTypeForComClients(type, RegistrationClassContext.LocalServer,
                                                            RegistrationConnectionType.MultipleUse);
            try
            {
                using (EventWaitHandle quit = QuitEvent())
                {
                    while (true)
                    {
                        // sleep straight through the warm period: no timer ticks, no CPU, until it is over
                        double left = IDLE_SECONDS - IdleSeconds();
                        if (quit.WaitOne(left > 0 ? (int)(left * 1000) + 500 : 5000)) break;
                        double idle = IdleSeconds();
                        if (idle > ABANDONED_SECONDS) break;
                        if (idle <= IDLE_SECONDS) continue;
                        // Explorer releasing a command makes it garbage; collecting it is how we notice.
                        GC.Collect();
                        GC.WaitForPendingFinalizers();
                        if (Thread.VolatileRead(ref CommandBase.Live) <= 0) break;
                    }
                }
            }
            finally
            {
                services.UnregisterTypeForComClients(cookie);
            }
            return 0;
        }

        private static double IdleSeconds()
        {
            return (DateTime.UtcNow - new DateTime(Interlocked.Read(ref CommandBase.LastUse), DateTimeKind.Utc)).TotalSeconds;
        }

        private static EventWaitHandle QuitEvent()
        {
            try
            {
                return new EventWaitHandle(false, EventResetMode.ManualReset, QUIT_EVENT);
            }
            catch (Exception)
            {
                return new EventWaitHandle(false, EventResetMode.ManualReset);  // no early quit, the idle timer still works
            }
        }
    }
}
