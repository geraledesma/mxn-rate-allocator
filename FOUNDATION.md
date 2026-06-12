# FOUNDATION — MXN Rate Allocator

> The central reference for why this project exists, who it serves, and how it speaks.
> Everything else — roadmap, architecture, milestones — is downstream of this document.
> Last updated: 2026-06-12

---

## The Problem

Banks and SOFIPOs in Mexico change their rates constantly to attract new customers. Beyond the rates themselves, each institution has conditions that also change regularly: minimum deposit amounts, monthly spending requirements, paid memberships, coverage limits per tier.

For the average person, tracking all of this is practically impossible:

- Dozens of institutions with different tier structures.
- Rates change without advance notice.
- Conditions are not always easy to find in one place.
- Manual comparison takes time and financial knowledge most people don't have.

The result: most Mexicans leave their money in accounts paying 2–4% when regulated, safe options exist paying 10–15% — not out of lack of interest, but because the information gap makes it genuinely hard to know which is the best option at any point in time.

This is not a niche problem. Financial exclusion has a direct multiplier effect on quality of life, access to credit, small business growth, and ultimately job creation and economic development across the country.

---

## Mission

Close Mexico's financial information gap. The tool is free, built in Spanish, and designed so that anyone — without prior financial knowledge — can make an informed and safe savings decision.

**Financial inclusion should not depend on how much you have.**

---

## Product Vision

A single-page, public, free calculator that automatically distributes capital across Mexican banks and SOFIPOs to maximize real yield — net of taxes and inflation — with guaranteed IPAB/Prosofipo coverage.

The tool does the work that used to require hours of manual research: it compares all available options, accounts for tier structures and conditions, and tells the user exactly where to put their money.

---

## Target User

**Primary:** individual with $50k–$3M MXN in liquid savings who currently does not actively compare rates.

They are not financially unsophisticated — they simply don't have the time or tools to track a market that changes constantly. The tool meets them where they are: no jargon, no required prior knowledge, clear instructions.

**Key differentiator:** MILP engine calibrated for the Mexican regulatory framework (IPAB, Prosofipo, ISR) + SCD2 historical rate database. No generic comparator handles tier structures, conditions, and tax implications simultaneously.

---

## Methodology

The tool covers only **regulated institutions and their liquid products**:

- **Institutions in scope:** Banks and SOFIPOs with active CNBV authorization. No unregulated fintechs, cooperatives, or informal savings vehicles.
- **Products in scope:** Demand deposit accounts ("a la vista") only — cuentas de ahorro, cuentas nómina, and equivalent on-demand products.
- **Products excluded:** Fixed-term deposits (1 month, 3 months, 1 year, or any lock-up period), CETEs, investment funds, or any product that restricts capital access.

**Rationale:** The tool is designed for liquid savings. Recommending fixed-term products would introduce liquidity risk that conflicts with the tool's core promise: users can move their money at any time, with no penalty and no waiting period.

---

## Voice & Tone

| Principle | Description |
|-----------|-------------|
| **Personal** | Speak to "tú" and "tu dinero". The user is the protagonist, not the tool. |
| **Instructive** | Give concrete instructions, not abstract descriptions. "Abre una cuenta en X y deposita $Y" instead of "distribución óptima". |
| **Direct** | No unnecessary financial jargon. If a technical term is used (IPAB, Prosofipo, ISR), explain it briefly. |
| **Honest** | Rates are nominal, they change, and conditions apply. Don't promise what can't be guaranteed. |
| **Empathetic** | Acknowledge that the Mexican financial system is confusing by design. The tool exists to simplify it. |

**Language rule:** UI and all user-facing copy in Spanish. Codebase, documentation, and internal planning in English.

---

## Copy — by Section

### Header / General Description

> Los bancos y SOFIPOs en México **cambian sus tasas constantemente** para atraer clientes nuevos, y cada uno tiene condiciones distintas que también cambian con regularidad: montos mínimos, requisitos de consumo, membresías, límites por tramo. Seguir todo eso manualmente es complicado — y la mayoría de las personas termina dejando su dinero en cuentas que pagan **2–4%** cuando existen opciones reguladas y seguras que pagan **10–15%**.
>
> **Esta herramienta hace el trabajo por ti.** Compara automáticamente las opciones disponibles y te dice exactamente dónde poner tu dinero para obtener el mejor rendimiento posible, con cobertura institucional garantizada (IPAB / Prosofipo). Es completamente gratuita, está en español, y no necesitas ningún conocimiento financiero previo para usarla.

### Nota de actualización

> Las tasas y condiciones de los bancos y SOFIPOs cambian con frecuencia. **Te recomendamos revisar esta página regularmente** — especialmente antes de renovar o mover tu dinero — para asegurarte de que tu plan sigue siendo el más conveniente.

### Paso 1 — ¿Cuánto quieres invertir?

> Indica cuánto dinero quieres poner a trabajar. Puedes ajustar el monto en cualquier momento y el plan se actualiza al instante.

### Paso 2 — ¿Dónde invertirlo?

> Estas son las instituciones disponibles, ordenadas de mayor a menor tasa. Todas están pre-seleccionadas. **Desactiva las que tengan condiciones que no puedas o no quieras cumplir** — por ejemplo, si no quieres abrir cuenta en una institución específica o no puedes cumplir el requisito de compra mensual.

### Tu plan personalizado

> Estás invirtiendo **$X MXN**. Este es tu plan para maximizar lo que ganas:

Metrics:
- **Rendimiento esperado (1 año):** $Y MXN — *Lo que ganarás al final del año si sigues el plan.*
- **Tasa efectiva:** Z% anual — *El rendimiento promedio ponderado sobre todo tu capital.*

### Paso 3 — ¿Cómo distribuirlo?

> Así debes distribuir tu dinero. Sigue estas instrucciones:

Per institution card:
> **Abre una cuenta en [Institución]** y deposita **$X MXN**
> Tramo N: $X (hasta $Y) → **Z%**
> Ganarás aprox. **$W MXN** en el año · Cobertura [IPAB/Prosofipo]
> ⚠️ Para acceder a esta tasa necesitas: [condición]

---

## Legal Disclaimer

Required on every page and in every exported report:

> *"Esta herramienta es de carácter informativo. No constituye asesoría financiera, fiscal ni de inversión. Las tasas mostradas provienen de fuentes públicas y pueden variar. Consulta directamente con cada institución antes de tomar decisiones de inversión."*

**CNBV boundary:** showing publicly available rates and running a mathematical optimization does not constitute regulated financial advisory under Mexican law. The line is crossed when the tool makes personalized recommendations based on user-specific circumstances (risk profile, tax situation, financial goals). As long as the tool is a calculator — not an advisor — no CNBV license is required.

---

## Mission Impact Metrics

Pageviews and sessions are vanity metrics. The mission is financial inclusion — measuring it requires proxies tied to actual user behavior:

| Metric | What it measures |
|--------|-----------------|
| Optimization runs per month | Tool is being actively used, not just visited |
| Avg. yield delta shown (optimized vs. single-institution) | Value delivered per session |
| Unique institutions surfaced in results | Breadth of market exposure the tool creates |
| Return visits | Users treating the tool as ongoing reference |
| Organic search traffic share | Reaching users who were actively looking, not just stumbling in |

---

## Related Documents

| Document | Location | Purpose |
|----------|----------|---------|
| ROADMAP.md | `planning/mxn-rate-allocator/` | Milestones, architecture decisions, task backlog |
| findings-2026-06-10.md | `planning/mxn-rate-allocator/` | Hermes CTO code review findings |
| assumptions.md | `docs/` | Financial and regulatory assumptions in the engine |
