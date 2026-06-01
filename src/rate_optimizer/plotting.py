import numpy as np
import matplotlib.pyplot as plt

### Plotting functions 

def plot_allocation_result(result, total_amount, title=None, annotate=True, lang="en"):
    """
    Plot optimal allocation by fund (stacked by tier) and interest by fund.

    annotate: if True (default), label each tier segment with its MXN amount; if the segment is too
              small to fit the label, place it outside with an arrow back to the segment.
    lang: "en" (English) or "es" (Spanish) for axis labels and titles.
    """
    if not result.get("success") or not result.get("allocation"):
        return
    _ = "es" if (lang and str(lang).lower() == "es") else "en"
    L = {
        "en": {"amount": "Amount (MXN)", "alloc_title": "Optimal allocation by fund (stacked by tier)", "interest_axis": "Interest over horizon (MXN)", "interest_title": "Interest by fund", "tier": "Tier"},
        "es": {"amount": "Monto (MXN)", "alloc_title": "Asignación óptima por fondo (apilado por tramo)", "interest_axis": "Interés en el horizonte (MXN)", "interest_title": "Interés por fondo", "tier": "Tramo"},
    }[_]

    allocation_by_tier = result["allocation_by_tier"]
    interest_by_fund = result["interest_by_fund"]
    fund_names = list(allocation_by_tier.keys())
    n_tiers = max(len(allocation_by_tier[f]) for f in fund_names)
    tier_colors = plt.cm.viridis(np.linspace(0.2, 0.9, n_tiers))

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4))

    def _fmt_mxn(v):
        v = float(v)
        if v >= 1e6:
            s = v / 1e6
            return f"{s:.0f}M" if s == int(s) else f"{s:.1f}M"
        if v >= 1e3:
            return f"{v/1e3:.0f}k"
        return f"{v:.0f}"

    # Stacked bar: allocation by fund and tier
    x = np.arange(len(fund_names))
    width = 0.6
    bottom = np.zeros(len(fund_names))
    _stack_patches = []  # (patch, amount)

    for t in range(n_tiers):
        amounts = [
            allocation_by_tier[f][t] if t < len(allocation_by_tier[f]) else 0
            for f in fund_names
        ]
        container = ax1.bar(x, amounts, width, bottom=bottom, label=f"{L['tier']} {t + 1}", color=tier_colors[t])
        if annotate:
            for patch, amt in zip(container.patches, amounts):
                _stack_patches.append((patch, amt))
        bottom += amounts

    ax1.set_ylabel(L["amount"])
    ax1.set_title(L["alloc_title"])
    ax1.set_xticks(x)
    ax1.set_xticklabels(fund_names)
    ax1.legend(loc="upper right", fontsize=8)
    ax1.axhline(y=total_amount, color="gray", linestyle="--", alpha=0.7)

    # Labels for stacked tiers (with arrows when they don't fit)
    if annotate and _stack_patches:
        import matplotlib.patheffects as pe
        fig.canvas.draw()
        min_seg_px = 16
        y0, y1 = ax1.get_ylim()
        y_span = max(1e-9, y1 - y0)

        for patch, amt in _stack_patches:
            if amt <= 0:
                continue
            xmid = patch.get_x() + patch.get_width() / 2
            ymid = patch.get_y() + patch.get_height() / 2

            # segment height in pixels
            py0 = ax1.transData.transform((xmid, patch.get_y()))[1]
            py1 = ax1.transData.transform((xmid, patch.get_y() + patch.get_height()))[1]
            seg_px = abs(py1 - py0)

            label = _fmt_mxn(amt)
            if seg_px >= min_seg_px:
                ax1.text(
                    xmid,
                    ymid,
                    label,
                    ha="center",
                    va="center",
                    fontsize=8,
                    color="white",
                    path_effects=[pe.withStroke(linewidth=2, foreground="black")],
                    clip_on=True,
                )
            else:
                # Put label outside to the right, arrow back to segment center
                x_text = patch.get_x() + patch.get_width() / 2 + 0.25
                ax1.annotate(
                    label,
                    xy=(xmid, ymid),
                    xytext=(x_text, ymid + 0.01 * y_span),
                    textcoords="data",
                    ha="left",
                    va="center",
                    fontsize=8,
                    color="black",
                    arrowprops=dict(arrowstyle="->", lw=0.8, color="black", alpha=0.8),
                    path_effects=[pe.withStroke(linewidth=2, foreground="white")],
                    clip_on=True,
                )

    # Bar: interest by fund
    interests = [interest_by_fund[f] for f in fund_names]
    bars = ax2.bar(fund_names, interests, color=tier_colors[0 : len(fund_names)])
    ax2.set_ylabel(L["interest_axis"])
    ax2.set_title(L["interest_title"])
    for b in bars:
        ax2.text(b.get_x() + b.get_width() / 2, b.get_height(), f"{b.get_height():,.0f}", ha="center", va="bottom", fontsize=9)
    ax2.axhline(y=result["total_interest"], color="gray", linestyle="--", alpha=0.7)

    if title:
        fig.suptitle(title, fontsize=11, y=1.02)
    plt.tight_layout()
    plt.show()


def plot_rate_structure(funds, fund_names=None, x_max=None, log_x=True, annotate=True, benchmark_name=None, lang="en"):
    """
    Plot interest rate (Y) vs amount invested (X) for each fund as a step function.

    funds: list of tier lists, each tier = (cumulative_limit, rate).
    log_x: if True (default), use a symlog X scale (starts at 0) so small cutoffs (25k, 40k)
           are more visible while large amounts (500k, 1M) are compressed.
    annotate: if True, label each tier segment with i% (uses an arrow when the segment is too narrow).
    benchmark_name: optional fund name to highlight (e.g. "Cetes Bonddia"), drawn with dash-dot style.
    lang: "en" (English) or "es" (Spanish) for axis labels and titles.
    """
    _lang = "es" if (lang and str(lang).lower() == "es") else "en"
    L_rs = {
        "en": {"xlabel": "Amount invested (MXN) — tier cutoffs", "symlog_note": " [symlog: small amounts expanded]", "ylabel": "Rate i (%)", "title": "Tiered rates per fund: i% vs amount", "legend_fund": "Fund"},
        "es": {"xlabel": "Monto invertido (MXN) — límites de tramo", "symlog_note": " [symlog: montos pequeños expandidos]", "ylabel": "Tasa i (%)", "title": "Tasas por tramo por fondo: i% vs monto", "legend_fund": "Fondo"},
    }[_lang]
    if fund_names is None:
        fund_names = [f"Fund {i}" for i in range(len(funds))]
    INF = float("inf")
    x_max = x_max if x_max is not None else 2_500_000
    # Collect tier limits early for scale and first-point logic
    all_limits = sorted(set(
        lim for tiers in funds for lim, _ in tiers
        if lim != INF and 0 < lim <= x_max
    ))
    x_min = 0.0
    colors = plt.cm.tab10(np.linspace(0, 1, max(len(funds), 1)))
    fig, ax = plt.subplots(figsize=(11, 5.5))

    _segments_to_label = []  # (fund_idx, x0, x1, y)

    for i, tiers in enumerate(funds):
        if not tiers:
            continue
        # Include every tier boundary so cutoffs (e.g. 40k, 25k) are visible
        x = [0.0]
        for lim, rate in tiers:
            lim_cap = min(lim, x_max) if lim != INF else x_max
            x.append(lim_cap)
        y = [rate for _, rate in tiers]
        # Extend last segment to x_max so the final rate is visible
        if x[-1] < x_max:
            x.append(x_max)
        # step() requires len(x) == len(y): one rate per breakpoint (rate from this x to the next)
        while len(y) < len(x):
            y.append(y[-1])
        x_arr = np.array(x)
        y_arr = np.array(y)
        is_benchmark = benchmark_name is not None and fund_names[i] == benchmark_name
        # Matplotlib linestyles cannot be '.-'; approximate with dash-dot for the benchmark
        linestyle = "-." if is_benchmark else "-"
        ax.step(
            x_arr,
            y_arr,
            where="post",
            label=fund_names[i],
            color=colors[i % len(colors)],
            linewidth=2.4 if is_benchmark else 2,
            linestyle=linestyle,
        )

        if annotate:
            for j in range(len(x) - 1):
                x0, x1 = float(x[j]), float(x[j + 1])
                if x1 <= x0:
                    continue
                _segments_to_label.append((i, x0, x1, float(y[j])))

    x_scale_label = L_rs["symlog_note"] if log_x else ""
    ax.set_xlabel(L_rs["xlabel"] + x_scale_label)
    ax.set_ylabel(L_rs["ylabel"])
    ax.set_title(L_rs["title"])
    ax.legend(loc="upper right", framealpha=0.9, title=L_rs["legend_fund"])
    # Y limits: focus on the rate range in the data (add small margin) for clearer view
    all_rates = [r for tiers in funds for _, r in tiers]
    if all_rates:
        y_min = min(all_rates)
        y_max = max(all_rates)
        margin = max(0.002, 0.05 * (y_max - y_min if y_max > y_min else y_max or 0.01))
        y_lo = max(0, y_min - margin)
        y_hi = min(1, y_max + margin)
        ax.set_ylim(y_lo, y_hi)
    else:
        ax.set_ylim(bottom=0, top=0.1)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{100*x:.2f}%"))
    if log_x:
        # symlog allows x=0 and expands the region near 0 for readability.
        # Use a larger linthresh and a smaller linscale so very small amounts
        # are not over-expanded and the axis looks more balanced.
        if all_limits:
            min_lim = min(all_limits)
            linthresh = max(100_000.0, min_lim)
        else:
            linthresh = 100_000.0
        ax.set_xscale("symlog", linthresh=linthresh, linscale=0.5)
        ax.set_xlim(0, x_max)
    elif x_max:
        ax.set_xlim(0, x_max)

    # Vertical lines at tier thresholds to emphasize cutoffs
    if all_limits:
        for xv in all_limits:
            ax.axvline(
                xv,
                color="gray",
                linestyle=":",
                linewidth=1.1,
                alpha=0.6,
                zorder=0,
            )

    # Add i% labels (with "extension" arrows when they don't fit)
    if annotate and _segments_to_label:
        import matplotlib.patheffects as pe
        # Ensure transforms are ready for pixel-based "fits" checks
        fig.canvas.draw()
        y0, y1 = ax.get_ylim()
        y_span = max(1e-9, y1 - y0)
        n_funds = max(1, len(funds))
        # Threshold in pixels: below this we move text outside with an arrow
        min_seg_px = 38
        for fund_idx, x0, x1, yy in _segments_to_label:
            midx = (x0 + x1) / 2
            # Segment width in display (pixel) coords
            px0 = ax.transData.transform((x0, yy))[0]
            px1 = ax.transData.transform((x1, yy))[0]
            seg_px = abs(px1 - px0)

            # Stagger labels slightly between funds to reduce overlap
            stagger = ((fund_idx - (n_funds - 1) / 2) * 0.015) * y_span
            label = f"{100*yy:.1f}%"

            if seg_px >= min_seg_px:
                ax.text(
                    midx,
                    yy + stagger,
                    label,
                    ha="center",
                    va="center",
                    fontsize=8,
                    color=colors[fund_idx % len(colors)],
                    path_effects=[pe.withStroke(linewidth=2, foreground="white")],
                    clip_on=True,
                )
            else:
                # Place label just outside the segment with an arrow pointing back
                x_text = min(x_max, x1 + 0.04 * x_max)
                ha = "left"
                if x_text >= x_max * 0.98:
                    x_text = max(0.0, x0 - 0.04 * x_max)
                    ha = "right"
                ax.annotate(
                    label,
                    xy=(midx, yy),
                    xytext=(x_text, yy + stagger + 0.01 * y_span),
                    textcoords="data",
                    ha=ha,
                    va="center",
                    fontsize=8,
                    color=colors[fund_idx % len(colors)],
                    arrowprops=dict(arrowstyle="->", lw=0.8, color=colors[fund_idx % len(colors)], alpha=0.9),
                    path_effects=[pe.withStroke(linewidth=2, foreground="white")],
                    clip_on=True,
                )

    # X ticks: 0 + tier cutoffs + right edge
    ticks = [0.0] + (all_limits if all_limits else []) + ([x_max] if x_max else [])
    ax.set_xticks(sorted(set(ticks)))
    # Format X axis as 25k, 250k, 500k, 1M, etc.
    def _fmt_amount(x, _):
        if x >= 1e6:
            s = x / 1e6
            return f"{s:.0f}M" if s == int(s) else f"{s:.1f}M"
        if x >= 1e3:
            return f"{x / 1e3:.0f}k"
        return f"{x:.0f}"
    ax.xaxis.set_major_formatter(plt.FuncFormatter(_fmt_amount))
    plt.setp(ax.get_xticklabels(), rotation=35, ha="right")  # avoid overlapping labels
    ax.set_xlim(left=0, right=x_max)  # force X-axis to start at 0
    ax.grid(True, axis="both", linestyle="--", alpha=0.3)
    plt.tight_layout()
    plt.show()


def plot_tier_bars(funds, fund_names=None, x_max=None, lang="en"):
    """
    Horizontal stacked bars (heatmap) — one row per fund, segments = tier width (amount),
    color = interest rate i% (higher = redder). Good for comparing tier sizes and rates across funds.
    lang: "en" (English) or "es" (Spanish) for axis labels and titles.
    """
    _lang = "es" if (lang and str(lang).lower() == "es") else "en"
    L_tb = {
        "en": {"xlabel": "Amount (MXN) — tier width", "title": "Tier structure: segment width = amount in tier (color = i%)", "cbar": "Interest rate (i%)"},
        "es": {"xlabel": "Monto (MXN) — ancho por tramo", "title": "Estructura por tramos: ancho = monto en tramo (color = i%)", "cbar": "Tasa de interés (i%)"},
    }[_lang]
    if fund_names is None:
        fund_names = [f"Fund {i}" for i in range(len(funds))]
    INF = float("inf")
    x_max = x_max if x_max is not None else 2_500_000
    n = len(funds)
    fig, ax = plt.subplots(figsize=(8, max(3, n * 0.8)))
    y_pos = np.arange(n)
    import matplotlib as mpl
    import matplotlib.patheffects as pe
    # Heatmap by rate: higher i% -> redder
    all_rates = [r for tiers in funds for _, r in tiers]
    norm = mpl.colors.Normalize(vmin=min(all_rates) if all_rates else 0, vmax=max(all_rates) if all_rates else 1)
    cmap = plt.cm.Reds
    left = np.zeros(n)
    for t_idx in range(max(len(tiers) for tiers in funds)):
        widths = []
        rates = []
        for i, tiers in enumerate(funds):
            if t_idx >= len(tiers):
                widths.append(0.0)
                rates.append(None)
                continue
            lim, rate = tiers[t_idx]
            prev = tiers[t_idx - 1][0] if t_idx > 0 else 0
            cap_lim = min(lim, x_max) if lim != INF else x_max
            cap_prev = min(prev, x_max)
            w = max(0, cap_lim - cap_prev)
            widths.append(w)
            rates.append(rate)
        seg_colors = [
            (cmap(norm(r)) if r is not None else (0, 0, 0, 0))
            for r in rates
        ]
        bars = ax.barh(y_pos, widths, left=left, color=seg_colors, edgecolor="white", linewidth=0.6)
        # Add i% label in each tier box; if it doesn't fit, extend with an arrow
        fig.canvas.draw()  # ensures transforms are ready for pixel-based size checks
        min_seg_px = 42
        for j, b in enumerate(bars):
            r = rates[j]
            if r is None:
                continue
            if b.get_width() <= 0:
                continue
            rgba = seg_colors[j]
            lum = 0.2126 * rgba[0] + 0.7152 * rgba[1] + 0.0722 * rgba[2]
            txt_color = "black" if lum > 0.65 else "white"
            stroke_color = "white" if txt_color == "black" else "black"

            x0 = b.get_x()
            x1 = b.get_x() + b.get_width()
            ymid = b.get_y() + b.get_height() / 2
            # segment width in pixels
            px0 = ax.transData.transform((x0, ymid))[0]
            px1 = ax.transData.transform((x1, ymid))[0]
            seg_px = abs(px1 - px0)
            label = f"{100*r:.1f}%"

            if seg_px >= min_seg_px:
                ax.text(
                    x0 + b.get_width() / 2,
                    ymid,
                    label,
                    ha="center",
                    va="center",
                    fontsize=8,
                    color=txt_color,
                    path_effects=[pe.withStroke(linewidth=2, foreground=stroke_color)],
                    clip_on=True,
                )
            else:
                # Put label just outside, arrow back to segment center
                x_text = min(x_max, x1 + 0.03 * x_max)
                ha = "left"
                if x_text >= x_max * 0.98:
                    x_text = max(0.0, x0 - 0.03 * x_max)
                    ha = "right"
                ax.annotate(
                    label,
                    xy=(x0 + b.get_width() / 2, ymid),
                    xytext=(x_text, ymid),
                    textcoords="data",
                    ha=ha,
                    va="center",
                    fontsize=8,
                    color=txt_color,
                    arrowprops=dict(arrowstyle="->", lw=0.8, color=stroke_color, alpha=0.9),
                    path_effects=[pe.withStroke(linewidth=2, foreground=stroke_color)],
                    clip_on=True,
                )
        left += np.array(widths)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(fund_names[:n])  # match n = len(funds) to avoid FixedLocator/labels mismatch
    ax.set_xlabel(L_tb["xlabel"])
    ax.set_title(L_tb["title"])
    ax.set_xlim(0, x_max)
    sm = mpl.cm.ScalarMappable(norm=norm, cmap=cmap)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, pad=0.02)
    cbar.set_label(L_tb["cbar"])
    cbar.ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{100*v:.1f}%"))
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x/1e6:.1f}M" if x >= 1e6 else (f"{x/1e3:.0f}k" if x >= 1e3 else f"{x:.0f}")))
    plt.tight_layout()
    plt.show()

# Backward-compatible aliases
plot_sofipo_result = plot_allocation_result
plot_sofipo_rates = plot_rate_structure
plot_sofipo_rates_bars = plot_tier_bars