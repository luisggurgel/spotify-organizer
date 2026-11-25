from fastapi.testclient import TestClient

from app.main import app


def test_web_ui_health_and_auth_guards(monkeypatch, tmp_path):
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "test_id")
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "test_secret")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "api.db"))

    with TestClient(app) as client:
        home = client.get("/")
        assert home.status_code == 200
        assert "Spotify Language Organizer" in home.text

        assert client.get("/health").status_code == 200
        assert client.get("/auth/status").json() == {
            "authenticated": False,
            "display_name": None,
        }

        resp = client.post("/organize/run", json={"dry_run": True})
        assert resp.status_code == 401

        cb = client.get("/auth/callback?error=access_denied")
        assert cb.status_code == 400
