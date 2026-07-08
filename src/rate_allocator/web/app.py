"""FastAPI app — serves the public calculator and the /api/allocate endpoint."""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, field_validator

from rate_allocator import Institution, RegulatoryRules, allocate
from rate_allocator.adapters.noticias_yaml import load_noticias_yaml
from rate_allocator.adapters.regulatory_loader import load_regulatory_rules_from_yaml
from rate_allocator.adapters.yaml_loader import load_institutions_with_overrides
from rate_allocator.core.finance.rates import discrete_compounding_accumulation_factor

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_FILE = REPO_ROOT / "data" / "sample1.yaml"
RULES_FILE = REPO_ROOT / "data" / "regulatory_rules.mx.yaml"
DEFAULT_DB_FILE = REPO_ROOT / "data" / "rates.db"
NOTICIAS_YAML_FILE = REPO_ROOT / "data" / "noticias.yaml"
DB_URL_ENV = "RATE_ALLOCATOR_DB_URL"

# Sole benchmark: CETES 28 días, the risk-free reference of Mexican saving.
# Curated manually like institution rates; update alongside them.
# Last set 2026-06-12 (verify at banxico.org.mx).
CETES_28_RATE = 0.0625
_PERIODS_PER_YEAR = 365
NOTICIAS_LIMIT = 30

WEB_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

TOTAL_MIN = 1_000
TOTAL_MAX = 9_900_000
HORIZON_MIN = 0.25
HORIZON_MAX = 5.0

TIPO_LABEL = {"sofipo": "SOFIPO", "banco": "Banco", "none": "Fintech / Gob."}

_MONTHS_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


# ── data loading ─────────────────────────────────────────────────────────────


def _resolve_database_url() -> str:
    return os.environ.get(DB_URL_ENV, f"sqlite:///{DEFAULT_DB_FILE}")


def _try_load_db_snapshot() -> tuple[list[Institution], RegulatoryRules | None, datetime | None] | None:
    try:
        from rate_allocator.adapters.db_loader import (
            load_institutions_from_db,
            load_regulatory_rules_from_db,
        )
        from rate_allocator.persistence import create_db_engine, session_scope
    except ModuleNotFoundError:
        return None
    try:
        engine = create_db_engine(_resolve_database_url())
        with session_scope(engine) as session:
            institutions = load_institutions_from_db(session)
            rules = load_regulatory_rules_from_db(session, country="MX")
            return institutions, rules, datetime.now(timezone.utc)
    except Exception:
        return None


def _load_snapshot() -> tuple[list[Institution], RegulatoryRules, datetime]:
    snapshot = _try_load_db_snapshot()
    fallback_rules = load_regulatory_rules_from_yaml(str(RULES_FILE))
    if snapshot:
        insts, rules, ts = snapshot
        if insts:
            return insts, rules or fallback_rules, ts
    insts = load_institutions_with_overrides(str(DATA_FILE), {})
    mtime = datetime.fromtimestamp(DATA_FILE.stat().st_mtime, tz=timezone.utc)
    return insts, fallback_rules, mtime


# ── formatting helpers (mirror streamlit_app.py) ─────────────────────────────


def _best_rate(inst: Institution) -> float:
    return max(t.rate for t in inst.tiers)


def _coverage_label(inst: Institution, rules: RegulatoryRules) -> str:
    tipo = (inst.institution_type or "").lower()
    limit = inst.protection_limit_for(rules)
    if tipo == "banco":
        return f"IPAB · hasta ${limit:,.0f}" if limit else "IPAB"
    if tipo == "sofipo":
        return f"Prosofipo · hasta ${limit:,.0f}" if limit else "Prosofipo"
    return "Sin cobertura aplicable"


def _constraint_text(inst: Institution) -> tuple[str, bool]:
    texts: list[str] = []
    for tier in inst.tiers:
        for c in tier.constraints:
            if not c.active:
                continue
            if c.benefit == "membership_plan":
                texts.append(f"Membresía ${c.cost:,.0f}/mes")
            elif c.benefit == "high_rate_tier" and c.cost <= 10:
                texts.append("1 compra al mes")
            elif c.benefit == "high_rate_tier" and c.cost > 10:
                texts.append(f"Gastar ${c.cost:,.0f}/mes")
    if not texts:
        return "Sin condición", False
    return " · ".join(texts), True


def _tier_payload(inst: Institution) -> list[dict]:
    out = []
    for tier in inst.tiers:
        if tier.limit == float("inf"):
            limite_label = "sin límite"
            limite_value: float | None = None
        else:
            limite_label = f"hasta ${tier.limit:,.0f}"
            limite_value = float(tier.limit)
        out.append({
            "limite": limite_value,
            "limite_label": limite_label,
            "tasa": float(tier.rate),
            "tasa_label": f"{tier.rate:.0%}",
        })
    return out


def _institucion_payload(inst: Institution, rules: RegulatoryRules) -> dict:
    cond_text, tiene_cond = _constraint_text(inst)
    tipo = (inst.institution_type or "").lower()
    best = _best_rate(inst)
    best_tier = max(inst.tiers, key=lambda t: t.rate)
    limite_label = "" if best_tier.limit == float("inf") else f"hasta ${best_tier.limit:,.0f}"
    return {
        "nombre": inst.name,
        "tipo": tipo,
        "tipo_label": TIPO_LABEL.get(tipo, "—"),
        "cobertura_label": _coverage_label(inst, rules),
        "tasa_max": float(best),
        "tasa_max_label": f"{best:.0%}",
        "tasa_max_limite_label": limite_label,
        "tramos": _tier_payload(inst),
        "condicion": cond_text,
        "tiene_condicion": tiene_cond,
    }


def _max_allocatable(institutions: list[Institution], rules: RegulatoryRules) -> float:
    """Sum of protection limits across institutions. Returns inf if any institution has no cap."""
    total = 0.0
    for inst in institutions:
        limit = inst.protection_limit_for(rules)
        if limit is None:
            return float("inf")
        total += limit
    return total


def _fmt_mxn(amount: float) -> str:
    return f"${amount:,.0f} MXN"


def _date_es(d: date) -> str:
    return f"{d.day} de {_MONTHS_ES[d.month - 1]} de {d.year}"


def _to_date(dt: datetime) -> date:
    if dt.tzinfo is None:
        return date(dt.year, dt.month, dt.day)
    return dt.astimezone(timezone.utc).date()


# ── FastAPI app ──────────────────────────────────────────────────────────────

app = FastAPI(title="MXN Rate Allocator", docs_url="/api/docs", redoc_url=None)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ── request / response models ────────────────────────────────────────────────


class AllocateRequest(BaseModel):
    total: float = Field(..., ge=TOTAL_MIN, le=TOTAL_MAX)
    instituciones_habilitadas: list[str] = Field(..., min_length=1)
    horizonte_anos: float = Field(default=1.0, ge=HORIZON_MIN, le=HORIZON_MAX)

    @field_validator("instituciones_habilitadas")
    @classmethod
    def _no_empty_names(cls, v: list[str]) -> list[str]:
        cleaned = [s.strip() for s in v if s and s.strip()]
        if not cleaned:
            raise ValueError("instituciones_habilitadas no puede estar vacío")
        return cleaned


# ── routes: HTML pages ───────────────────────────────────────────────────────


def _page_context(request: Request, extra: dict | None = None) -> dict:
    _, _, ts = _load_snapshot()
    ctx = {
        "request": request,
        "ultima_actualizacion": _date_es(ts.astimezone(timezone.utc).date()),
        "anio_actual": datetime.now(timezone.utc).year,
    }
    if extra:
        ctx.update(extra)
    return ctx


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        _page_context(request, {
            "monto_min": TOTAL_MIN,
            "monto_max": 3_000_000,
            "monto_default": 100_000,
        }),
    )


@app.get("/v2", response_class=HTMLResponse)
async def index_v2(request: Request) -> HTMLResponse:
    """Wizard beta — mobile-first step-by-step flow. Does not replace /."""
    return templates.TemplateResponse(
        request,
        "index_v2.html",
        _page_context(request, {
            "monto_min": TOTAL_MIN,
            "monto_max": 3_000_000,
            "monto_default": 100_000,
        }),
    )


@app.get("/compare-v2", response_class=HTMLResponse)
async def compare_v2(request: Request) -> HTMLResponse:
    """Dev-only comparison page: desktop vs mobile side by side."""
    return templates.TemplateResponse(request, "compare_v2.html", {})


@app.get("/sofipo", response_class=HTMLResponse)
async def page_sofipo(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "sofipo.html", _page_context(request))


@app.get("/ipab", response_class=HTMLResponse)
async def page_ipab(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "ipab.html", _page_context(request))


@app.get("/glosario", response_class=HTMLResponse)
async def page_glosario(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "glosario.html", _page_context(request))


@app.get("/como-funciona", response_class=HTMLResponse)
async def page_como_funciona(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "como-funciona.html", _page_context(request))


@app.get("/privacidad", response_class=HTMLResponse)
async def page_privacidad(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "privacidad.html", _page_context(request))


@app.get("/acerca", response_class=HTMLResponse)
async def page_acerca(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "acerca.html", _page_context(request))


@app.get("/terminos", response_class=HTMLResponse)
async def page_terminos(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "terminos.html", _page_context(request))


@app.get("/isr-intereses", response_class=HTMLResponse)
async def page_isr(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "articulo-isr-intereses.html", _page_context(request))


@app.get("/cetes-vs-cuentas", response_class=HTMLResponse)
async def page_cetes(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "articulo-cetes-vs-vista.html", _page_context(request))


@app.get("/donde-poner-ahorros", response_class=HTMLResponse)
async def page_donde_poner(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "articulo-donde-poner-ahorros.html", _page_context(request))


# ── routes: API ──────────────────────────────────────────────────────────────


@app.get("/instituciones")
async def get_instituciones() -> JSONResponse:
    institutions, rules, ts = _load_snapshot()
    institutions_sorted = sorted(institutions, key=_best_rate, reverse=True)
    payload = {
        "instituciones": [_institucion_payload(i, rules) for i in institutions_sorted],
        "ultima_actualizacion": _date_es(ts.astimezone(timezone.utc).date()),
    }
    return JSONResponse(payload)


@app.post("/api/allocate")
async def post_allocate(body: AllocateRequest) -> JSONResponse:
    institutions, rules, _ = _load_snapshot()
    by_name = {i.name: i for i in institutions}

    selected: list[Institution] = []
    missing: list[str] = []
    for name in body.instituciones_habilitadas:
        inst = by_name.get(name)
        if inst is None:
            missing.append(name)
        else:
            selected.append(inst)

    if not selected:
        raise HTTPException(
            status_code=400,
            detail=f"Ninguna institución seleccionada existe en la base de datos. No encontradas: {missing}",
        )

    max_cap = _max_allocatable(selected, rules)
    if body.total > max_cap:
        solo_sofipo = all(
            (inst.institution_type or "").lower() == "sofipo" for inst in selected
        )
        if solo_sofipo:
            msg = (
                f"Con solo SOFIPOs seleccionadas, el monto máximo cubierto por Prosofipo es "
                f"${max_cap:,.0f} MXN. Tu monto (${body.total:,.0f} MXN) excede ese límite. "
                "Agrega al menos un banco para poder optimizar montos mayores."
            )
        elif len(selected) == 1:
            inst_name = selected[0].name
            msg = (
                f"Con solo {inst_name} seleccionada, el máximo cubierto es "
                f"${max_cap:,.0f} MXN. Selecciona más instituciones o ajusta el monto."
            )
        else:
            msg = (
                f"Tu monto (${body.total:,.0f} MXN) excede la cobertura total de las instituciones "
                f"seleccionadas (${max_cap:,.0f} MXN). Selecciona más instituciones o reduce el monto."
            )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"tipo": "monto_excede_cobertura", "mensaje_usuario": msg},
        )

    try:
        result = allocate(
            total=body.total,
            institutions=selected,
            horizon_years=body.horizonte_anos,
            periods_per_year=_PERIODS_PER_YEAR,
            regulatory_rules=rules,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "tipo": "optimizer_infeasible",
                "mensaje_usuario": (
                    "No fue posible encontrar una asignación con los parámetros seleccionados. "
                    "Intenta ajustar el monto o seleccionar más instituciones."
                ),
                "detalle_tecnico": str(exc),
            },
        ) from exc

    asignaciones = []
    chart_labels: list[str] = []
    chart_montos: list[float] = []
    chart_tasas: list[float] = []

    inst_rows = []
    for inst in selected:
        tier_amounts = result.allocations.get(inst.name, [])
        total_inst = sum(tier_amounts)
        if total_inst < 1:
            continue
        inst_interest = sum(
            amt * (discrete_compounding_accumulation_factor(tier.rate, body.horizonte_anos, _PERIODS_PER_YEAR) - 1.0)
            for amt, tier in zip(tier_amounts, inst.tiers, strict=True)
        )
        inst_rows.append((inst, tier_amounts, total_inst, inst_interest))

    inst_rows.sort(key=lambda x: x[2], reverse=True)

    for inst, tier_amounts, total_inst, inst_interest in inst_rows:
        cond_text, tiene_cond = _constraint_text(inst)
        tipo = (inst.institution_type or "").lower()
        tramos_payload = []
        n_visible = 0
        for i, (amt, tier) in enumerate(
            zip(tier_amounts, inst.tiers, strict=True), 1
        ):
            if amt < 1:
                continue
            n_visible += 1
            tramos_payload.append({
                "numero": n_visible,
                "indice_original": i,
                "monto": float(amt),
                "monto_label": _fmt_mxn(amt),
                "limite_label": (
                    "sin límite" if tier.limit == float("inf")
                    else f"hasta ${tier.limit:,.0f}"
                ),
                "tasa": float(tier.rate),
                "tasa_label": f"{tier.rate:.2%}",
                "rendimiento": float(amt * (discrete_compounding_accumulation_factor(tier.rate, body.horizonte_anos, _PERIODS_PER_YEAR) - 1.0)),
                "rendimiento_label": _fmt_mxn(amt * (discrete_compounding_accumulation_factor(tier.rate, body.horizonte_anos, _PERIODS_PER_YEAR) - 1.0)),
            })

        asignaciones.append({
            "institucion": inst.name,
            "tipo": tipo,
            "tipo_label": TIPO_LABEL.get(tipo, "—"),
            "monto_total": float(total_inst),
            "monto_total_label": _fmt_mxn(total_inst),
            "rendimiento": float(inst_interest),
            "rendimiento_label": _fmt_mxn(inst_interest),
            "cobertura_label": _coverage_label(inst, rules),
            "condicion": cond_text,
            "tiene_condicion": tiene_cond,
            "tramos": tramos_payload,
            "tasa_promedio": (
                float(inst_interest / total_inst) if total_inst > 0 else 0.0
            ),
            "tasa_promedio_label": (
                f"{(inst_interest / total_inst):.2%}" if total_inst > 0 else "0%"
            ),
        })
        chart_labels.append(inst.name)
        chart_montos.append(float(total_inst))
        chart_tasas.append(
            float(inst_interest / total_inst) if total_inst > 0 else 0.0
        )

    # Mission impact framing (FOUNDATION): show the user the value delivered —
    # what this plan earns vs. CETES 28, the risk-free benchmark.
    cetes_return = body.total * (discrete_compounding_accumulation_factor(CETES_28_RATE, body.horizonte_anos, _PERIODS_PER_YEAR) - 1.0)
    delta = result.expected_return - cetes_return

    return JSONResponse({
        "tasa_efectiva": float(result.effective_rate),
        "tasa_efectiva_label": f"{result.effective_rate:.2%} anual",
        "rendimiento_esperado": float(result.expected_return),
        "rendimiento_esperado_label": _fmt_mxn(result.expected_return),
        "total_asignado": float(result.total_allocated),
        "total_asignado_label": _fmt_mxn(result.total_allocated),
        "comparativa": {
            "tasa_cetes": CETES_28_RATE,
            "tasa_cetes_label": f"{CETES_28_RATE:.2%}",
            "rendimiento_cetes": float(cetes_return),
            "rendimiento_cetes_label": _fmt_mxn(cetes_return),
            "delta": float(delta),
            "delta_label": _fmt_mxn(delta),
        },
        "asignaciones": asignaciones,
        "chart_data": {
            "labels": chart_labels,
            "montos": chart_montos,
            "tasas": chart_tasas,
        },
    })



@app.get("/noticias")
async def get_noticias() -> JSONResponse:
    """Recent rate changes grouped by institution+batch, newest first.

    Each group: {institucion, fecha_label, cambios:[{tramo, tasa_anterior_label,
    tasa_nueva_label, subio}]}. Only changes with a confirmed institutional
    effective date (vigente_desde) are published.
    """
    # key=(institution_key, batch_group) → (sort_ts, group_dict)
    groups: dict[tuple[str, str], tuple[float, dict]] = {}

    try:
        from rate_allocator.persistence import create_db_engine, session_scope
        from rate_allocator.persistence.history import load_recent_tier_rate_changes

        engine = create_db_engine(_resolve_database_url())
        with session_scope(engine) as session:
            events = load_recent_tier_rate_changes(session, limit=NOTICIAS_LIMIT)

        for e in events:
            if not e.vigente_desde:
                continue  # only publish changes with a confirmed institutional effective date
            ref_date = e.vigente_desde
            ts = float(datetime.combine(ref_date, datetime.min.time()).replace(tzinfo=timezone.utc).timestamp())
            group_key = (e.institution_key, e.change_id or str(ref_date))

            if group_key not in groups:
                groups[group_key] = (ts, {
                    "institucion": e.institution_name,
                    "fecha_label": _date_es(ref_date),
                    "cambios": [],
                })
            groups[group_key][1]["cambios"].append({
                "tramo": str(e.tier_index + 1),
                "tasa_anterior_label": f"{e.old_rate:.2%}",
                "tasa_nueva_label": f"{e.new_rate:.2%}",
                "subio": e.new_rate > e.old_rate,
            })
    except Exception:
        pass

    # YAML fallback — effective_from in YAML is curated and IS the institution's date
    seen_keys = set(groups.keys())
    for e in load_noticias_yaml(NOTICIAS_YAML_FILE):
        ref_date = _to_date(e.effective_from)
        inst_key = e.institution.lower().replace(" ", "_")
        group_key = (inst_key, str(ref_date))
        if group_key in seen_keys:
            continue
        ts = float(datetime.combine(ref_date, datetime.min.time()).replace(tzinfo=timezone.utc).timestamp())
        if group_key not in groups:
            groups[group_key] = (ts, {
                "institucion": e.institution,
                "fecha_label": _date_es(ref_date),
                "cambios": [],
            })
            seen_keys.add(group_key)
        groups[group_key][1]["cambios"].append({
            "tramo": str(e.tier_display),
            "tasa_anterior_label": f"{e.old_rate:.2%}",
            "tasa_nueva_label": f"{e.new_rate:.2%}",
            "subio": e.new_rate > e.old_rate,
        })

    sorted_groups = sorted(groups.values(), key=lambda x: x[0], reverse=True)
    return JSONResponse({"noticias": [g for _, g in sorted_groups[:NOTICIAS_LIMIT]]})


# ── SEO ──────────────────────────────────────────────────────────────────────

_SITE_PATHS = [
    "/", "/sofipo", "/ipab", "/glosario", "/como-funciona",
    "/privacidad", "/acerca", "/terminos",
    "/isr-intereses", "/cetes-vs-cuentas", "/donde-poner-ahorros",
]


@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots(request: Request) -> str:
    base = str(request.base_url).rstrip("/")
    return f"User-agent: *\nAllow: /\nDisallow: /api/\n\nSitemap: {base}/sitemap.xml\n"


@app.get("/sitemap.xml")
async def sitemap(request: Request) -> Response:
    base = str(request.base_url).rstrip("/")
    today = datetime.now(timezone.utc).date().isoformat()
    urls = "\n".join(
        f"  <url><loc>{base}{p}</loc><lastmod>{today}</lastmod></url>"
        for p in _SITE_PATHS
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}\n</urlset>\n"
    )
    return Response(content=xml, media_type="application/xml")


# ── entry point helper ───────────────────────────────────────────────────────


def run() -> None:
    """Convenience entry point for `rate-web` script.

    Binds to 0.0.0.0 so the site is reachable from your phone on the same
    Wi-Fi network — find your Mac's IP with `ipconfig getifaddr en0` and open
    http://<IP>:8000 from the phone's browser.
    """
    import uvicorn
    uvicorn.run(
        "rate_allocator.web.app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
