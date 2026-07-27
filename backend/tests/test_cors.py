from backend.main import cors_origins


def test_cors_origins_defaults_to_local_frontend(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)

    assert cors_origins() == ["http://localhost:3000"]


def test_cors_origins_adds_trimmed_configured_values(monkeypatch):
    monkeypatch.setenv(
        "CORS_ORIGINS",
        " https://app.example.com,https://preview.example.com ,",
    )

    assert cors_origins() == [
        "http://localhost:3000",
        "https://app.example.com",
        "https://preview.example.com",
    ]


def test_cors_origins_deduplicates_local_frontend(monkeypatch):
    monkeypatch.setenv(
        "CORS_ORIGINS",
        "http://localhost:3000,https://app.example.com,http://localhost:3000",
    )

    assert cors_origins() == [
        "http://localhost:3000",
        "https://app.example.com",
    ]
