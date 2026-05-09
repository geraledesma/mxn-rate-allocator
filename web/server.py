"""FastAPI app: Spanish static UI + JSON APIs that run `allocate` from `src/`."""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from rate_allocator import allocate, build_interactive_report_html
from rate_allocator.adapters.yaml_loader import load_institutions_with_overrides

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INSTITUTIONS_YAML = REPO_ROOT / "data" / "sample1.yaml"
DEFAULT_NOTICIAS_YAML = REPO_ROOT / "data" / "noticias_tasas.yaml"
STATIC_DIR = Path(__file__).resolve().parent / "static"

TOTAL_MIN = 0
TOTAL_MAX = 1_200_000
NO_FEES_ES = "sin comisiones modeladas"


def _brief_constraints_label(inst) -> str:
    parts = []
    for tier in inst.tiers:
        for c in tier.constraints:
            parts.append(f"{c.type} ${c.cost:.2f}")
    return ", ".join(parts) if parts else NO_FEES_ES


def load_noticias(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    rows = list(data.get("noticias") or [])
    rows.sort(key=lambda row: str(row.get("fecha", "")), reverse=True)
    return rows


class ReportRequest(BaseModel):
    total_mxn: int = Field(ge=TOTAL_MIN, le=TOTAL_MAX)
    selected: list[str]
    horizon_years: float = Field(default=1.0, ge=0.25, le=5.0)

    @field_validator("selected")
    @classmethod
    def non_empty_selected(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("Selecciona al menos una institución.")
        return v


def create_app(
    *,
    institutions_yaml: Path | None = None,
    noticias_yaml: Path | None = None,
    mount_static: bool = True,
) -> FastAPI:
    inst_path = Path(institutions_yaml or DEFAULT_INSTITUTIONS_YAML)
    news_path = Path(noticias_yaml or DEFAULT_NOTICIAS_YAML)

    app = FastAPI(title="Rate Allocator Web", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/institutions")
    def api_institutions() -> list[dict]:
        institutions = load_institutions_with_overrides(str(inst_path), {})
        return [
            {
                "name": i.name,
                "institution_type": i.institution_type,
                "constraints_label": _brief_constraints_label(i),
            }
            for i in institutions
        ]

    @app.get("/api/noticias")
    def api_noticias() -> dict:
        return {"items": load_noticias(news_path)}

    @app.post("/api/report")
    def api_report(body: ReportRequest) -> dict[str, str]:
        all_institutions = load_institutions_with_overrides(str(inst_path), {})
        known = {i.name for i in all_institutions}
        missing = [n for n in body.selected if n not in known]
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Instituciones desconocidas: {', '.join(missing)}",
            )
        institutions = [i for i in all_institutions if i.name in body.selected]
        result = allocate(
            total=body.total_mxn,
            institutions=institutions,
            horizon_years=body.horizon_years,
            periods_per_year=365,
        )
        html_fragment = build_interactive_report_html(
            result,
            institutions,
            total=float(body.total_mxn),
            horizon_years=body.horizon_years,
            periods_per_year=365,
            locale="es",
        )
        return {"html": html_fragment}

    if mount_static and STATIC_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

    return app


app = create_app()
