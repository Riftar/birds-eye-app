from fastapi.testclient import TestClient

from birds_eye.app import create_app


def test_home_script_escapes_truncation_newline(settings):
    with TestClient(create_app(settings)) as client:
        html = client.get("/").text

    assert "'\n(output truncated" not in html
