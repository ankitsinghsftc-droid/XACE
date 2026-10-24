// NEC-013 owner-pipe client. Gameplay and package admission remain in Rust.
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Security.Cryptography;
using System.Text;

namespace Xace.Adapter.Unity
{
    public sealed class XaceNativeHostClient : IDisposable
    {
        readonly ConcurrentQueue<string> messages = new ConcurrentQueue<string>();
        Process process;
        bool disposed;
        volatile string fault;
        public int ProcessId => process == null ? 0 : process.Id;
        public string Fault => fault;

        public static string FileHash(string path)
        {
            using (var input = File.OpenRead(path))
            using (var sha = SHA256.Create())
            {
                var result = new StringBuilder(64);
                foreach (byte value in sha.ComputeHash(input)) result.Append(value.ToString("x2"));
                return result.ToString();
            }
        }
        static void RequireHash(string value)
        {
            if (value == null || value.Length != 64) throw new ArgumentException("Pinned SHA256 required");
            foreach (char c in value) if (!(c >= '0' && c <= '9') && !(c >= 'a' && c <= 'f')) throw new ArgumentException("Invalid SHA256");
        }
        // ProcessStartInfo.Arguments uses Windows CRT quoting, not shell parsing.
        static string Quote(string value)
        {
            if (value == null || value.IndexOfAny(new[] {'\r','\n','\0'}) >= 0) throw new ArgumentException("Invalid process argument");
            var output = new StringBuilder("\""); int slashes = 0;
            foreach (char c in value)
            {
                if (c == '\\') { slashes++; continue; }
                if (c == '\"') { output.Append('\\', slashes * 2 + 1); output.Append(c); }
                else { output.Append('\\', slashes); output.Append(c); }
                slashes = 0;
            }
            output.Append('\\', slashes * 2); output.Append('\"'); return output.ToString();
        }
        public void Start(string launcher, string launcherSha256, string release, string releaseSha256, string history, ulong controller)
        {
            if (disposed || process != null) throw new InvalidOperationException("Host client cannot be reused");
            RequireHash(launcherSha256); RequireHash(releaseSha256);
            if (controller == 0 || !Path.IsPathRooted(launcher) || !Path.IsPathRooted(release) || !Path.IsPathRooted(history)) throw new ArgumentException("Absolute paths and positive controller required");
            if (!string.Equals(FileHash(launcher), launcherSha256, StringComparison.Ordinal)) throw new InvalidOperationException("Native launcher identity changed");
            var info = new ProcessStartInfo {
                FileName = launcher,
                Arguments = "--native-host --source " + Quote(release) + " --expected " + Quote(releaseSha256) + " --history " + Quote(history) + " --controller " + controller.ToString(System.Globalization.CultureInfo.InvariantCulture),
                UseShellExecute = false, CreateNoWindow = true,
                RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true,
                WorkingDirectory = release
            };
            process = new Process { StartInfo = info };
            process.OutputDataReceived += Receive;
            process.ErrorDataReceived += (sender, row) => { if (!string.IsNullOrEmpty(row.Data)) fault = "Native host diagnostic: " + row.Data.Substring(0, Math.Min(row.Data.Length, 2048)); };
            try
            {
                if (!process.Start()) throw new InvalidOperationException("Native host did not start");
                process.BeginOutputReadLine(); process.BeginErrorReadLine();
            }
            catch { Dispose(); throw; }
        }
        void Receive(object sender, DataReceivedEventArgs row)
        {
            if (row.Data == null) return;
            if (row.Data.Length > 65536 || messages.Count >= 64) { fault = "Native host response limit"; return; }
            messages.Enqueue(row.Data);
        }
        public bool TryReceive(out Dictionary<string, object> message)
        {
            message = null;
            if (messages.TryDequeue(out var raw)) { message = XaceCanonical.Parse(raw); return true; }
            if (fault != null) throw new InvalidOperationException(fault);
            if (process != null && process.HasExited) throw new InvalidOperationException("Native authority owner exited");
            return false;
        }
        void Send(Dictionary<string, object> command)
        {
            if (disposed || process == null || process.HasExited) throw new InvalidOperationException("Native host is not running");
            string line = XaceJson.Serialize(command);
            if (Encoding.UTF8.GetByteCount(line) > 8191) throw new ArgumentException("Native command too large");
            process.StandardInput.WriteLine(line); process.StandardInput.Flush();
        }
        public void Play() => Send(new Dictionary<string, object> {{"action", "play"}});
        public void Stop() => Send(new Dictionary<string, object> {{"action", "stop"}});
        public void CheckSave(string slot) => Send(new Dictionary<string, object> {{"action", "check-save"}, {"slot", slot}});
        public void Dispose()
        {
            if (disposed) return; disposed = true;
            if (process == null) return;
            try { process.StandardInput.Close(); } catch (InvalidOperationException) {} catch (IOException) {}
            try { if (!process.WaitForExit(2500)) { process.Kill(); process.WaitForExit(2500); } }
            catch (InvalidOperationException) {}
            finally { process.Dispose(); process = null; }
        }
    }
}
