from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_desktop_serves_spa_routes_and_assets(tmp_path):
    from app.desktop import serve_frontend

    (tmp_path / 'index.html').write_text('<html>Workbench</html>', encoding='utf-8')
    (tmp_path / 'assets').mkdir()
    (tmp_path / 'assets' / 'app.js').write_text('/* app */', encoding='utf-8')
    app = FastAPI()
    serve_frontend(app, tmp_path)
    with TestClient(app) as client:
        assert client.get('/').text == '<html>Workbench</html>'
        assert client.get('/tasks/3').text == '<html>Workbench</html>'
        assert client.get('/assets/app.js').text == '/* app */'
        assert client.get('/api/v1/missing').status_code == 404
        assert client.get('/assets/missing.js').status_code == 404
