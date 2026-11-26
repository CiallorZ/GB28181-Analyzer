"""Run the Windows NSH workspace against a private, dynamically allocated engine."""
import argparse
import asyncio
import json
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]


async def run(args):
    if not (ROOT / "frontend/dist/index.html").is_file():
        raise SystemExit("Build the frontend first with npm run build.")
    options = ["--data-dir", args.data_dir] if args.data_dir else []
    engine = await asyncio.create_subprocess_exec(
        sys.executable, ROOT / "backend/windows_launcher.py", "--desktop-child",
        "--no-browser", "--port", "0", *options, stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
    )
    try:
        async def ready():
            while line := await engine.stdout.readline():
                if line.startswith(b"DESKTOP_READY="):
                    return int(line.partition(b"=")[2])
            raise RuntimeError("Analysis engine exited before startup")

        port = await asyncio.wait_for(ready(), timeout=45)
        with TemporaryDirectory(prefix="gb28181-nsh-") as directory:
            project = Path(directory)
            for source in (ROOT / "desktop-nsh").iterdir():
                if source.suffix in {".tsx", ".ts", ".json"}:
                    shutil.copyfile(source, project / source.name)
            origin = json.dumps(f"http://127.0.0.1:{port}")
            (project / "engine.ts").write_text(f"export const origin = {origin};", encoding="utf8")
            command = ["test", "--target", "windows"] if args.test else ["run", "--target", "windows"]
            host = await asyncio.create_subprocess_exec(args.nsh, *command, cwd=project)
            try:
                return await host.wait()
            finally:
                if host.returncode is None:
                    host.terminate()
                    await host.wait()
    finally:
        engine.stdin.close()
        await engine.stdin.wait_closed()
        try:
            await asyncio.wait_for(engine.stdout.read(), timeout=15)
            await asyncio.wait_for(engine.wait(), timeout=15)
        except TimeoutError:
            engine.kill()
            await engine.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--nsh", default="nsh")
    parser.add_argument("--data-dir")
    parser.add_argument("--test", action="store_true")
    sys.exit(asyncio.run(run(parser.parse_args())))
