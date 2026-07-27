// XaceUnityLiveValidationCommand.cs
// Batch/editor validation entry point for the live Unity adapter.

using System;
using System.Globalization;
using System.IO;
using System.Text;
using System.Threading;
using UnityEditor;
using UnityEngine;

namespace Xace.Adapter.Unity.Editor
{
    public static class XaceUnityLiveValidationCommand
    {
        public static void Run()
        {
            var args = Environment.GetCommandLineArgs();
            var host = ArgValue(args, "--xace-host", "127.0.0.1");
            var port = IntArg(args, "--xace-port", XaceTransport.DefaultPort);
            var cgsHash = ArgValue(args, "--xace-cgs-hash", "");
            var timeoutSeconds = FloatArg(args, "--xace-validation-seconds", 12f);
            var holdSeconds = FloatArg(args, "--xace-validation-hold-seconds", 0f);
            var outputPath = ArgValue(args, "--xace-validation-output", "");

            var snapshots = 0;
            var appliedSnapshots = 0;
            var appliedEntities = 0;
            var feedbackReady = 0;
            var protocolErrors = 0;
            var handshakeAccepted = false;
            var lastError = "";

            try
            {
                var root = XaceRuntimeBootstrap.EnsureRuntimeObjectForPlay();
                var transport = root.GetComponent<XaceTransport>();
                var input = root.GetComponent<XaceInputCollector>();
                var applicator = root.GetComponent<XaceDeltaApplicator>();

                transport.Disconnect("validation restart");
                transport.ConfigureConnection(host, port, cgsHash);
                applicator.BindTransportNow();

                transport.OnHandshakeAccepted += _ => handshakeAccepted = true;
                transport.OnTickSnapshot += _ => snapshots++;
                transport.OnProtocolError += error =>
                {
                    protocolErrors++;
                    lastError = error ?? "";
                };
                applicator.OnSnapshotApplied += (_, count) =>
                {
                    appliedSnapshots++;
                    appliedEntities = Math.Max(appliedEntities, count);
                };
                applicator.OnFeedbackReady += _ => feedbackReady++;

                transport.Connect();
                WriteOutput(outputPath, ResultJson(false, host, port, handshakeAccepted, transport.IsConnected, snapshots, appliedSnapshots, appliedEntities, feedbackReady, protocolErrors, "validation started"));

                var iterations = 0;
                var deadline = EditorApplication.timeSinceStartup + Math.Max(1f, timeoutSeconds);
                while (EditorApplication.timeSinceStartup < deadline)
                {
                    transport.PumpOnce();
                    input.FlushNow();
                    transport.PumpOnce();
                    iterations++;

                    if (iterations % 10 == 0)
                    {
                        var progress = ResultJson(false, host, port, handshakeAccepted, transport.IsConnected, snapshots, appliedSnapshots, appliedEntities, feedbackReady, protocolErrors, lastError);
                        WriteOutput(outputPath, progress);
                    }

                    if (handshakeAccepted && snapshots > 0 && appliedSnapshots > 0 && appliedEntities > 0 && feedbackReady > 0)
                        break;

                    Thread.Sleep(20);
                }

                transport.PumpOnce();

                var ok = handshakeAccepted
                    && transport.IsConnected
                    && snapshots > 0
                    && appliedSnapshots > 0
                    && appliedEntities > 0
                    && feedbackReady > 0
                    && protocolErrors == 0;

                var json = ResultJson(
                    ok,
                    host,
                    port,
                    handshakeAccepted,
                    transport.IsConnected,
                    snapshots,
                    appliedSnapshots,
                    appliedEntities,
                    feedbackReady,
                    protocolErrors,
                    string.IsNullOrEmpty(lastError) ? transport.LastError : lastError);
                WriteOutput(outputPath, json);
                Debug.Log("[XACE] Unity live validation result: " + json);
                if (ok && holdSeconds > 0f)
                    HoldConnection(transport, input, holdSeconds);
                EditorApplication.Exit(ok ? 0 : 1);
            }
            catch (Exception ex)
            {
                var json = ResultJson(false, host, port, handshakeAccepted, false, snapshots, appliedSnapshots, appliedEntities, feedbackReady, protocolErrors + 1, ex.Message);
                WriteOutput(outputPath, json);
                Debug.LogError("[XACE] Unity live validation failed: " + ex);
                EditorApplication.Exit(1);
            }
        }

        private static string ArgValue(string[] args, string name, string fallback)
        {
            for (var i = 0; i < args.Length - 1; i++)
            {
                if (string.Equals(args[i], name, StringComparison.Ordinal))
                    return args[i + 1] ?? fallback;
            }
            return fallback;
        }

        private static int IntArg(string[] args, string name, int fallback)
        {
            var raw = ArgValue(args, name, "");
            return int.TryParse(raw, NumberStyles.Integer, CultureInfo.InvariantCulture, out var value) ? value : fallback;
        }

        private static float FloatArg(string[] args, string name, float fallback)
        {
            var raw = ArgValue(args, name, "");
            return float.TryParse(raw, NumberStyles.Float, CultureInfo.InvariantCulture, out var value) ? value : fallback;
        }

        private static void WriteOutput(string path, string json)
        {
            if (string.IsNullOrWhiteSpace(path))
                return;
            var fullPath = Path.GetFullPath(path);
            var parent = Path.GetDirectoryName(fullPath);
            if (!string.IsNullOrEmpty(parent))
                Directory.CreateDirectory(parent);
            File.WriteAllText(fullPath, json, Encoding.UTF8);
        }

        private static void HoldConnection(XaceTransport transport, XaceInputCollector input, float holdSeconds)
        {
            var deadline = EditorApplication.timeSinceStartup + Math.Max(0f, holdSeconds);
            while (EditorApplication.timeSinceStartup < deadline)
            {
                transport.PumpOnce();
                input.FlushNow();
                transport.PumpOnce();
                Thread.Sleep(20);
            }
        }

        private static string ResultJson(
            bool ok,
            string host,
            int port,
            bool handshakeAccepted,
            bool connected,
            int snapshots,
            int appliedSnapshots,
            int appliedEntities,
            int feedbackReady,
            int protocolErrors,
            string error)
        {
            return "{"
                + "\"ok\":" + Bool(ok)
                + ",\"host\":\"" + JsonString(host) + "\""
                + ",\"port\":" + port.ToString(CultureInfo.InvariantCulture)
                + ",\"handshake_accepted\":" + Bool(handshakeAccepted)
                + ",\"connected\":" + Bool(connected)
                + ",\"snapshots\":" + snapshots.ToString(CultureInfo.InvariantCulture)
                + ",\"applied_snapshots\":" + appliedSnapshots.ToString(CultureInfo.InvariantCulture)
                + ",\"applied_entities\":" + appliedEntities.ToString(CultureInfo.InvariantCulture)
                + ",\"feedback_ready\":" + feedbackReady.ToString(CultureInfo.InvariantCulture)
                + ",\"protocol_errors\":" + protocolErrors.ToString(CultureInfo.InvariantCulture)
                + ",\"error\":\"" + JsonString(error ?? "") + "\""
                + "}";
        }

        private static string Bool(bool value)
        {
            return value ? "true" : "false";
        }

        private static string JsonString(string value)
        {
            var builder = new StringBuilder();
            foreach (var ch in value ?? "")
            {
                switch (ch)
                {
                    case '\\': builder.Append("\\\\"); break;
                    case '"': builder.Append("\\\""); break;
                    case '\n': builder.Append("\\n"); break;
                    case '\r': builder.Append("\\r"); break;
                    case '\t': builder.Append("\\t"); break;
                    default:
                        if (ch < ' ')
                            builder.Append("\\u").Append(((int)ch).ToString("x4", CultureInfo.InvariantCulture));
                        else
                            builder.Append(ch);
                        break;
                }
            }
            return builder.ToString();
        }
    }
}
