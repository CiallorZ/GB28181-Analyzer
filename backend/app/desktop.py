"""Serve the prebuilt frontend from the local desktop process."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


def serve_frontend(app: FastAPI, dist: Path) -> None:
    index = dist / 'index.html'
    if not index.is_file():
        raise FileNotFoundError(f'Frontend build missing: {index}')

    def frontend():
        return FileResponse(index, headers={'Cache-Control': 'no-cache'})

    for directory in ('assets', 'brand', 'samples'):
        path = dist / directory
        if path.is_dir():
            app.mount(f'/{directory}', StaticFiles(directory=path), name=directory)

    for route in ('/', '/sip', '/media', '/diagnostics', '/packets',
                  '/tasks', '/tasks/{task_id:int}', '/sessions/{session_id:int}', '/settings'):
        app.add_api_route(route, frontend, methods=['GET', 'HEAD'], include_in_schema=False)
