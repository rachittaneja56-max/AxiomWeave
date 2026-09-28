import pytest
from fastapi.testclient import TestClient

from app.main import app

client: TestClient = TestClient(app)


def valid_request(**overrides: object) -> dict[str, object]:
    request: dict[str, object] = {
        "source_text": "The project team will open the new community garden on Saturday.",
        "output_types": ["executive_summary"],
        "audience": "Local residents",
        "tone": "Welcoming",
        "language": "English",
        "detail_level": "standard",
        "objective": "Announce the opening",
        "style": "Plain language",
    }
    request.update(overrides)
    return request


def test_prepare_accepts_single_output_and_applies_defaults() -> None:
    request = valid_request()
    request.pop("language")
    request.pop("detail_level")

    response = client.post("/api/transformations/prepare", json=request)

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "request": {
            **request,
            "language": "English",
            "detail_level": "standard",
        },
    }


def test_prepare_accepts_multiple_output_types() -> None:
    request = valid_request(output_types=["executive_summary", "linkedin_post", "presentation"])

    response = client.post("/api/transformations/prepare", json=request)

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "request": request}


@pytest.mark.parametrize("source_text", ["", " \n\t"])
def test_prepare_rejects_empty_or_whitespace_source(source_text: str) -> None:
    response = client.post(
        "/api/transformations/prepare", json=valid_request(source_text=source_text)
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert response.json()["error"]["fields"][0]["field"] == "source_text"


def test_prepare_rejects_empty_output_selection() -> None:
    response = client.post("/api/transformations/prepare", json=valid_request(output_types=[]))

    assert response.status_code == 422
    assert response.json()["error"]["fields"][0]["field"] == "output_types"


def test_prepare_rejects_unsupported_output_type() -> None:
    response = client.post(
        "/api/transformations/prepare", json=valid_request(output_types=["generic_text"])
    )

    assert response.status_code == 422
    assert response.json()["error"]["fields"][0]["field"] == "output_types.0"


def test_prepare_rejects_duplicate_output_types() -> None:
    response = client.post(
        "/api/transformations/prepare",
        json=valid_request(output_types=["advisory", "advisory"]),
    )

    assert response.status_code == 422
    assert response.json()["error"]["fields"][0]["field"] == "output_types"


def test_prepare_rejects_oversized_source() -> None:
    response = client.post(
        "/api/transformations/prepare",
        json=valid_request(source_text="a" * 20_001),
    )

    assert response.status_code == 422
    assert response.json()["error"]["fields"][0]["field"] == "source_text"


def test_prepare_rejects_invalid_detail_level() -> None:
    response = client.post(
        "/api/transformations/prepare", json=valid_request(detail_level="extreme")
    )

    assert response.status_code == 422
    assert response.json()["error"]["fields"][0]["field"] == "detail_level"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("audience", "a" * 121),
        ("tone", "t" * 81),
        ("language", "l" * 81),
        ("objective", "o" * 161),
        ("style", "s" * 121),
    ],
)
def test_prepare_rejects_control_text_over_limit(field: str, value: str) -> None:
    response = client.post("/api/transformations/prepare", json=valid_request(**{field: value}))

    assert response.status_code == 422
    assert response.json()["error"]["fields"][0]["field"] == field
