"""Tests for the FastAPI web app: pages, /instituciones, /api/allocate contract."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from rate_allocator.web.app import TOTAL_MAX, TOTAL_MIN, app

client = TestClient(app)


# ── HTML pages ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    ["/", "/sofipo", "/ipab", "/glosario", "/como-funciona", "/privacidad"],
)
def test_page_renders(path):
    resp = client.get(path)
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    # Legal disclaimer must appear on every page (FOUNDATION requirement)
    assert "carácter informativo" in resp.text


def test_robots_and_sitemap():
    robots = client.get("/robots.txt")
    assert robots.status_code == 200
    assert "Sitemap:" in robots.text

    sitemap = client.get("/sitemap.xml")
    assert sitemap.status_code == 200
    assert "<urlset" in sitemap.text
    assert "/sofipo" in sitemap.text


# ── /instituciones ────────────────────────────────────────────────────────────


def test_instituciones_payload():
    resp = client.get("/instituciones")
    assert resp.status_code == 200
    data = resp.json()
    assert data["instituciones"], "expected at least one institution"
    assert data["ultima_actualizacion"]

    first = data["instituciones"][0]
    for key in (
        "nombre", "tipo", "tipo_label", "cobertura_label",
        "tasa_max", "tasa_max_label", "tramos", "condicion", "tiene_condicion",
    ):
        assert key in first

    # Sorted by best rate descending
    rates = [i["tasa_max"] for i in data["instituciones"]]
    assert rates == sorted(rates, reverse=True)


# ── /api/allocate ─────────────────────────────────────────────────────────────


def _all_names() -> list[str]:
    return [i["nombre"] for i in client.get("/instituciones").json()["instituciones"]]


def test_allocate_happy_path():
    names = _all_names()
    resp = client.post(
        "/api/allocate",
        json={"total": 100_000, "instituciones_habilitadas": names},
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["total_asignado"] == pytest.approx(100_000)
    assert data["tasa_efectiva"] > 0
    assert data["rendimiento_esperado"] > 0
    assert data["asignaciones"]

    # Allocations sum to total
    total = sum(a["monto_total"] for a in data["asignaciones"])
    assert total == pytest.approx(100_000)

    # Sorted by amount descending
    amounts = [a["monto_total"] for a in data["asignaciones"]]
    assert amounts == sorted(amounts, reverse=True)

    # Chart arrays are parallel
    chart = data["chart_data"]
    assert len(chart["labels"]) == len(chart["montos"]) == len(chart["tasas"])
    assert len(chart["labels"]) == len(data["asignaciones"])


def test_allocate_comparativa():
    names = _all_names()
    resp = client.post(
        "/api/allocate",
        json={"total": 100_000, "instituciones_habilitadas": names},
    )
    comp = resp.json()["comparativa"]
    assert comp["rendimiento_tradicional"] == pytest.approx(3_000)
    assert comp["delta"] == pytest.approx(
        resp.json()["rendimiento_esperado"] - 3_000
    )


def test_allocate_unknown_institutions_400():
    resp = client.post(
        "/api/allocate",
        json={"total": 50_000, "instituciones_habilitadas": ["No Existe"]},
    )
    assert resp.status_code == 400


def test_allocate_validation_errors():
    names = _all_names()
    # Below minimum
    assert client.post(
        "/api/allocate",
        json={"total": TOTAL_MIN - 1, "instituciones_habilitadas": names},
    ).status_code == 422
    # Above maximum
    assert client.post(
        "/api/allocate",
        json={"total": TOTAL_MAX + 1, "instituciones_habilitadas": names},
    ).status_code == 422
    # Empty institution list
    assert client.post(
        "/api/allocate",
        json={"total": 50_000, "instituciones_habilitadas": []},
    ).status_code == 422


def test_allocate_subset_respects_selection():
    names = _all_names()[:2]
    resp = client.post(
        "/api/allocate",
        json={"total": 30_000, "instituciones_habilitadas": names},
    )
    assert resp.status_code == 200
    used = {a["institucion"] for a in resp.json()["asignaciones"]}
    assert used.issubset(set(names))


# ── /noticias ─────────────────────────────────────────────────────────────────


def test_noticias_endpoint():
    resp = client.get("/noticias")
    assert resp.status_code == 200
    data = resp.json()
    assert "noticias" in data
    for item in data["noticias"]:
        for key in ("institucion", "tramo", "fecha_label", "tasa_nueva_label", "subio"):
            assert key in item
