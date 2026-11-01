"""Legacy (no database) admin login. Run from the backend folder:  pytest -q"""
import importlib
import os

from fastapi.testclient import TestClient


def make_client(password="s3cret-pass", secret="x" * 40):
    os.environ["ADMIN_USERNAME"] = "admin"
    os.environ["ADMIN_PASSWORD"] = password
    os.environ["SESSION_SECRET"] = secret
    os.environ["DATABASE_URL"] = ""  # an empty value also wins over a real one in backend/.env
    import app.core.config as config
    import app.routers.auth as auth
    import app.main as main

    importlib.reload(config)
    importlib.reload(auth)
    importlib.reload(main)
    return TestClient(main.app)


def test_health():
    c = make_client()
    r = c.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_login_wrong_password():
    c = make_client()
    r = c.post("/api/auth/login", json={"username": "admin", "password": "nope"})
    assert r.status_code == 401


def test_login_and_me():
    c = make_client()
    r = c.post("/api/auth/login", json={"username": "Admin", "password": "s3cret-pass"})
    assert r.status_code == 200
    token = r.json()["access_token"]
    me = c.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200 and me.json() == {"user": "admin", "role": "admin"}


def test_tampered_token_rejected():
    c = make_client()
    token = c.post("/api/auth/login", json={"username": "admin", "password": "s3cret-pass"}).json()["access_token"]
    body, sig = token.split(".")
    bad = body + "." + ("A" if sig[0] != "A" else "B") + sig[1:]
    assert c.get("/api/auth/me", headers={"Authorization": f"Bearer {bad}"}).status_code == 401


def test_not_configured():
    c = make_client(password="", secret="")
    r = c.post("/api/auth/login", json={"username": "admin", "password": "x"})
    assert r.status_code == 503
