"""Build a single-file x64 Windows offline launcher from a verified release and vendor runtimes."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from zipfile import ZipFile, ZIP_DEFLATED

parser = argparse.ArgumentParser()
for arg in ("app", "wireshark", "ffmpeg", "webview", "output"):
    parser.add_argument("--" + arg, type=Path, required=True)
parser.add_argument("--tshark-version", default="unknown")
parser.add_argument("--ffmpeg-version", default="unknown")
parser.add_argument("--webview-version", default="unknown")
a = parser.parse_args()
required = {
    "app": a.app,
    "wireshark/dumpcap.exe": a.wireshark / "dumpcap.exe",
    "ffmpeg/bin/ffmpeg.exe": a.ffmpeg / "bin" / "ffmpeg.exe",
    "ffmpeg/bin/ffprobe.exe": a.ffmpeg / "bin" / "ffprobe.exe",
    "webview": a.webview,
}
missing = [name for name, path in required.items() if not path.exists()]
if missing:
    raise SystemExit("missing required inputs: " + ", ".join(missing))
system = Path(os.environ["SystemRoot"]) / "System32"
with tempfile.TemporaryDirectory(dir=a.output.parent) as temp:
    temp = Path(temp)
    archive = temp / "payload.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED, compresslevel=5) as z:
        def add(path, prefix):
            if path.is_dir():
                for file in path.rglob("*"):
                    if file.is_file():
                        z.write(file, Path(prefix) / file.relative_to(path))
            else:
                z.write(path, prefix)
        for child in a.app.iterdir():
            add(child, child.name)
        for file in a.wireshark.glob("*.dll"):
            add(file, "Wireshark/" + file.name)
        for name in ("tshark.exe", "capinfos.exe", "dumpcap.exe", "COPYING.txt", "README.txt",
                     "plugins", "profiles", "diameter", "dtds", "protobuf", "radius", "snmp",
                     "tpncp", "wimaxasncp"):
            add(a.wireshark/name, "Wireshark/"+name)
        for pat in ("msvcp140*.dll", "vcruntime140*.dll", "concrt140.dll"):
            for file in system.glob(pat):
                if "clr" not in file.name.lower() and not (a.wireshark/file.name).exists():
                    add(file, "Wireshark/" + file.name)
        for name in ("ffmpeg.exe", "ffprobe.exe"):
            add(a.ffmpeg/"bin"/name, "ffmpeg/"+name)
        add(a.ffmpeg/"LICENSE", "ffmpeg/LICENSE")
        add(a.ffmpeg/"README.txt", "ffmpeg/README.txt")
        add(a.webview, "WebView2")
        z.writestr("Third-party.txt", (
            f"TShark {a.tshark_version}: https://www.wireshark.org/download.html\n"
            f"FFmpeg {a.ffmpeg_version}: https://www.gyan.dev/ffmpeg/builds/\n"
            f"WebView2 {a.webview_version}: "
            "https://developer.microsoft.com/microsoft-edge/webview2/\n"
        ))
    with archive.open("rb") as f:
        digest = hashlib.file_digest(f, "sha256").hexdigest()
    source = Path(__file__).resolve()
    shutil.copy(source.with_name("main.go"), temp / "main.go")
    subprocess.run(["go", "run", "github.com/akavel/rsrc@v0.10.2", "-arch", "amd64",
                    "-ico", str(source.parents[2] / "desktop/icons/icon.ico"),
                    "-o", str(temp / "icon_windows_amd64.syso")], check=True)
    subprocess.run(["go","build","-trimpath","-ldflags",f"-s -w -H windowsgui -X main.buildID={digest}",
                    "-o",str(a.output.resolve()),"."], cwd=temp, env={**os.environ,"GO111MODULE":"off"},check=True)
    with a.output.open("ab") as dest, archive.open("rb") as src:
        shutil.copyfileobj(src,dest)
