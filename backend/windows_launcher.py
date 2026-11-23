"""Windows entry point for the portable application."""
import argparse
import ctypes
import os
import socket
import sys
import webbrowser
from pathlib import Path
from threading import Thread

import uvicorn

from app import __version__
from app.desktop import serve_frontend

HOST = '127.0.0.1'


def main():
    parser = argparse.ArgumentParser(description='GB28181 Analyzer for Windows')
    parser.add_argument('--port', type=int, default=8791)
    parser.add_argument('--data-dir', type=Path)
    parser.add_argument('--desktop-child', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--version', action='version', version=__version__)
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error('--port must be between 1 and 65535')

    user_dir = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local')
    data_dir = (args.data_dir or user_dir / 'GB28181 Analyzer').resolve()
    data_dir.mkdir(parents=True, exist_ok=True)

    import msvcrt

    with (data_dir / 'instance.lock').open('a+b') as lock, socket.socket() as listener:
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            parser.exit(1, f'Another Analyzer instance is using {data_dir}.\n')
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            listener.bind((HOST, args.port))
        except OSError as error:
            parser.exit(1, f'Cannot use {HOST}:{args.port}. Try --port 8792. ({error})\n')
        args.port = listener.getsockname()[1]
        return run_desktop(args, data_dir, listener)


def run_desktop(args, data_dir, listener):
    os.environ.update(
        HOST=HOST, PORT=str(args.port), DATA_DIR=str(data_dir),
        DATABASE_URL='sqlite:///' + (data_dir / 'analyzer.db').as_posix(),
        ALLOWED_HOSTS=f'{HOST},localhost', CORS_ORIGINS='', DEBUG='0',
    )
    from app.main import app

    if getattr(sys, 'frozen', False):
        dist = Path(sys._MEIPASS) / 'frontend'
        # Let separately installed TShark and FFmpeg load their own DLLs.
        ctypes.windll.kernel32.SetDllDirectoryW(None)
    else:
        dist = Path(__file__).resolve().parents[1] / 'frontend' / 'dist'
    serve_frontend(app, dist)
    address = f'http://{HOST}:{args.port}'

    class DesktopServer(uvicorn.Server):
        async def startup(self, sockets=None):
            await super().startup(sockets=sockets)
            if self.started:
                print(f'DESKTOP_READY={args.port}', flush=True)
                print(f'GB28181 Analyzer {__version__} | {address}', flush=True)
                print(f'Data: {data_dir} | Ctrl+C to stop', flush=True)
                if not args.no_browser:
                    Thread(target=webbrowser.open, args=(address,), daemon=True).start()

    config = uvicorn.Config(app, host=HOST, port=args.port, proxy_headers=False,
                            http='h11', loop='asyncio', ws='none', access_log=False)
    server = DesktopServer(config)
    if args.desktop_child:
        def wait_for_window_close():
            sys.stdin.buffer.read(1)
            server.should_exit = True

        Thread(target=wait_for_window_close, daemon=True).start()
    server.run(sockets=[listener])
    return 0 if server.started else 1


if __name__ == '__main__':
    raise SystemExit(main())
