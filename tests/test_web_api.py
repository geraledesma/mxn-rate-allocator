"""Tests for the FastAPI web app: pages, /instituciones, /api/allocate contract."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from rate_allocator.core.finance.rates import discrete_compounding_accumulation_factor
from rate_allocator.web.app import CETES_28_RATE, TOTAL_MAX, TOTAL_MIN, _PERIODS_PER_YEAR, app

client = TestClient(app)


# ── HTML pages ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    ["/", "/sofipo", "/ipab", "/glosario", "/como-funciona", "/privacidad", "/v2"],
)
def test_page_renders(path):
    resp = client.get(path)
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    # Legal disclaimer must appear on every page (FOUNDATION requirement)
    assert "carácter informativo" in resp.text


def test_v2_wizard_structure():
    resp = client.get("/v2")
    assert resp.status_code == 200
    # Wizard shell and all 3 panels present
    assert "wiz-shell" in resp.text
    assert "wiz-panel" in resp.text
    assert "calc_v2.js" in resp.text
    assert "style_v2.css" in resp.text


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
    data = resp.json()
    comp = data["comparativa"]
    expected_cetes = 100_000 * (discrete_compounding_accumulation_factor(CETES_28_RATE, 1.0, _PERIODS_PER_YEAR) - 1.0)
    assert comp["rendimiento_cetes"] == pytest.approx(expected_cetes)
    assert comp["delta"] == pytest.approx(data["rendimiento_esperado"] - comp["rendimiento_cetes"])


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


# ── MXN-BUG-001: infeasible optimizer → 422 with friendly message ─────────────


def _names_by_type(tipo: str) -> list[str]:
    insts = client.get("/instituciones").json()["instituciones"]
    return [i["nombre"] for i in insts if i["tipo"] == tipo]


def test_sofipo_only_exceeds_prosofipo_limit():
    """Single SOFIPO + amount > its Prosofipo limit (208K) → 422 with user-friendly message."""
    sofipo_names = _names_by_type("sofipo")
    if not sofipo_names:
        pytest.skip("no SOFIPO institutions in dataset")

    # Use just one SOFIPO so its individual cap (208K) is the binding constraint
    resp = client.post(
        "/api/allocate",
        json={"total": 250_000, "instituciones_habilitadas": sofipo_names[:1]},
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["tipo"] == "monto_excede_cobertura"
    msg = detail["mensaje_usuario"].lower()
    assert "sofipo" in msg or "prosofipo" in msg


def test_single_banco_exceeds_ipab_limit():
    """Single banco + amount > IPAB limit (3.3M) → 422 with institution name in message."""
    banco_names = _names_by_type("banco")
    if not banco_names:
        pytest.skip("no banco institutions in dataset")

    one_banco = [banco_names[0]]
    resp = client.post(
        "/api/allocate",
        json={"total": 4_000_000, "instituciones_habilitadas": one_banco},
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["tipo"] == "monto_excede_cobertura"
    assert one_banco[0] in detail["mensaje_usuario"]


def test_infeasible_returns_422_not_500():
    """All-SOFIPO selection + amount > combined Prosofipo cap → 422, never 500."""
    sofipo_names = _names_by_type("sofipo")
    if not sofipo_names:
        pytest.skip("no SOFIPO institutions in dataset")

    # Use TOTAL_MAX — guaranteed to exceed any realistic combined Prosofipo cap
    # (would need 47+ SOFIPO institutions at 208K each to reach 9.9M)
    resp = client.post(
        "/api/allocate",
        json={"total": TOTAL_MAX, "instituciones_habilitadas": sofipo_names},
    )
    assert resp.status_code == 422
    assert resp.status_code != 500


# ── /noticias ─────────────────────────────────────────────────────────────────


def test_noticias_endpoint():
    resp = client.get("/noticias")
    assert resp.status_code == 200
    data = resp.json()
    assert "noticias" in data
    for item in data["noticias"]:
        for key in ("institucion", "fecha_label", "cambios"):
            assert key in item
        assert isinstance(item["cambios"], list)
        assert len(item["cambios"]) > 0
        for cambio in item["cambios"]:
            for ck in ("tramo", "tasa_anterior_label", "tasa_nueva_label", "subio"):
                assert ck in cambio
