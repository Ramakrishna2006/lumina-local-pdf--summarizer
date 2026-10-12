"""Image generation API – uses a fake model, so no PyTorch/diffusers needed."""

from PIL import Image

from backend.app.services import image_gen


def fake_local(prompt, size, steps, seed):
    return Image.new("RGB", (size, size), (seed % 255, 80, 200))


def test_image_generate_and_download(client, monkeypatch):
    monkeypatch.setattr(image_gen, "missing_packages", lambda: [])
    monkeypatch.setattr(image_gen, "_generate_local", fake_local)

    st = client.get("/api/images/status").json()
    assert st["provider"] == "local" and st["ready"] is True

    r = client.post("/api/images/generate", json={"prompt": "a lighthouse at sunset", "size": 300, "seed": 7})
    assert r.status_code == 200, r.text
    img = r.json()
    assert img["width"] == 320 and img["height"] == 320   # rounded to a multiple of 64
    assert img["seed"] == 7 and img["prompt"] == "a lighthouse at sunset"

    png = client.get(img["url"])
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"
    assert png.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_image_errors(client, monkeypatch):
    # Libraries not installed -> clear install instructions, not a crash.
    monkeypatch.setattr(image_gen, "missing_packages", lambda: ["torch", "diffusers"])
    r = client.post("/api/images/generate", json={"prompt": "a cat"})
    assert r.status_code == 503 and "requirements-image.txt" in r.json()["detail"]
    assert client.get("/api/images/status").json()["ready"] is False

    # Empty prompt, unknown or unsafe ids.
    assert client.post("/api/images/generate", json={"prompt": ""}).status_code == 422
    assert client.get("/api/images/" + "0" * 32).status_code == 404
    assert client.get("/api/images/..%2F..%2Fapp.db").status_code == 404

    # Turned off in .env.
    monkeypatch.setattr(image_gen.settings(), "image_provider", "off")
    assert client.post("/api/images/generate", json={"prompt": "a cat"}).status_code == 403


def test_image_openai_provider(client, monkeypatch):
    import base64
    import io

    import httpx

    buf = io.BytesIO()
    Image.new("RGB", (64, 64), "red").save(buf, format="PNG")
    payload = {"data": [{"b64_json": base64.b64encode(buf.getvalue()).decode()}]}
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json=payload)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(image_gen.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(image_gen.settings(), "image_provider", "openai")
    r = client.post("/api/images/generate", json={"prompt": "a red square"})
    assert r.status_code == 200, r.text
    assert seen["url"].endswith("/v1/images/generations")
    assert client.get(r.json()["url"]).status_code == 200
