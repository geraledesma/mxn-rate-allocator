"""FastAPI TestClient exercises for ``web.server``."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

INST_YAML = """\
institutions:
  - name: BankA
    institution_type: banco
    tiers:
      - limit: inf
        rate: 0.12
  - name: SofipoZ
    institution_type: sofipo
    tiers:
      - limit: inf
        rate: 0.11
"""

NOT_YAML = """\
noticias:
  - fecha: "2026-02-10"
    institucion: BankA
    titulo: Subida ejemplo
    resumen: Ejemplo para prueba.
    tasa_anterior: "10%"
    tasa_nueva: "12%"
  - fecha: "2026-05-01"
    institucion: SofipoZ
    titulo: Más reciente
    resumen: Debe aparecer primero.
"""


@pytest.fixture
def api_client(tmp_path: Path):
    import matplotlib

    matplotlib.use("Agg")

    inst_file = tmp_path / "inst.yaml"
    inst_file.write_text(INST_YAML, encoding="utf-8")
    news_file = tmp_path / "news.yaml"
    news_file.write_text(NOT_YAML, encoding="utf-8")

    from web.server import create_app

    app = create_app(
        institutions_yaml=inst_file,
        noticias_yaml=news_file,
        mount_static=False,
    )
    return TestClient(app)


def test_api_institutions(api_client: TestClient):
    r = api_client.get("/api/institutions")
    assert r.status_code == 200
    data = r.json()
    names = {row["name"] for row in data}
    assert names == {"BankA", "SofipoZ"}
    for row in data:
        assert "institution_type" in row
        assert "constraints_label" in row


def test_api_report_ok(api_client: TestClient):
    r = api_client.post(
        "/api/report",
        json={
            "total_mxn": 50_000,
            "selected": ["BankA"],
            "horizon_years": 1.0,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert "html" in body
    assert "Institución" in body["html"]


def test_api_report_empty_selected(api_client: TestClient):
    r = api_client.post(
        "/api/report",
        json={"total_mxn": 10_000, "selected": [], "horizon_years": 1.0},
    )
    assert r.status_code == 422


def test_api_report_unknown_institution(api_client: TestClient):
    r = api_client.post(
        "/api/report",
        json={
            "total_mxn": 10_000,
            "selected": ["NoExiste"],
            "horizon_years": 1.0,
        },
    )
    assert r.status_code == 400
    assert "desconocidas" in r.json()["detail"]


def test_api_noticias_sorted_desc(api_client: TestClient):
    r = api_client.get("/api/noticias")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 2
    assert items[0]["fecha"] == "2026-05-01"
    assert items[1]["fecha"] == "2026-02-10"
