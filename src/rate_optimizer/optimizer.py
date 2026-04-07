import numpy as np
from scipy.optimize import linprog


def sofipo_optimal_allocation(
    total_amount,
    funds,
    fund_names=None,
):
    """
    Maximize total interest by allocating `total_amount` across products with
    tiered interest rates and strict sequential tranche access.

    The model assumes a fixed comparison horizon. Each tier rate in `funds` is
    interpreted as the effective rate for that horizon, so maximizing total
    interest is equivalent to maximizing the effective portfolio rate.

    Each fund is defined by a list of tiers `(cumulative_upper_limit, rate)`.
    A higher tier can only be used after all lower tiers are filled. We model
    this with cumulative decision variables:

        x[f, t] = amount allocated to fund f up to and including tier t

    so the amount invested in tier `t` is `x[f, t] - x[f, t-1]`.

    Example:
        [(40_000, 0.13), (10_000_000, 0.073), (float("inf"), 0.07)]

    Parameters
    ----------
    total_amount : float
        Total amount to allocate (e.g. MXN).
    funds : list of list of (float, float)
        For each fund, a list of (limit, rate). Limit is the cumulative upper
        bound of the tier (in currency); use float("inf") for the last tier.
        Rates are decimals (e.g. 0.13 for 13%) and should be interpreted as
        effective for the chosen horizon (e.g. annual effective rate).
    fund_names : list of str, optional
        Names for each fund (for the result). If None, uses "Fund 0", "Fund 1", ...

    Returns
    -------
    dict with keys:
        success : bool
        message : str
        allocation : dict[str, float]
            Amount to put in each fund.
        allocation_pct : dict[str, float]
            Allocation % per fund (sums to ~100), i.e. allocation / total_amount * 100.
        allocation_by_tier : dict[str, list[float]]
            Per fund, amount in each tier (list length = number of tiers).
        total_interest : float
            Total interest over the chosen horizon.
        total_interest_rate_pct : float
            Effective portfolio rate (in %) over the horizon, i.e. total_interest / total_amount * 100.
        interest_by_fund : dict[str, float]
    """
    total_amount = float(total_amount)
    if total_amount < 0:
        raise ValueError("total_amount must be non-negative.")

    n_funds = len(funds)
    if fund_names is None:
        fund_names = [f"Fund {i}" for i in range(n_funds)]
    if len(fund_names) != n_funds:
        raise ValueError("fund_names length must match number of funds.")
    if len(set(fund_names)) != len(fund_names):
        raise ValueError("fund_names must be unique.")

    if n_funds == 0:
        if total_amount == 0:
            return {
                "success": True,
                "message": "No funds and zero amount to allocate.",
                "allocation": {},
                "allocation_pct": {},
                "allocation_by_tier": {},
                "total_interest": 0.0,
                "total_interest_rate_pct": 0.0,
                "interest_by_fund": {},
            }
        raise ValueError("At least one fund is required when total_amount is positive.")

    # Normalize tiers: replace inf with a big number for LP (we'll use equality on total)
    BIG = max(total_amount * 2, 1e15)
    funds_normalized = []
    for tiers in funds:
        if not tiers:
            raise ValueError("Each fund must define at least one tier.")

        normalized = [
            (float(l) if l != float("inf") else BIG, float(r))
            for l, r in tiers
        ]
        prev_limit = 0.0
        for limit, _ in normalized:
            if limit <= 0:
                raise ValueError("Tier limits must be positive.")
            if limit < prev_limit:
                raise ValueError("Tier limits must be non-decreasing within each fund.")
            prev_limit = limit
        funds_normalized.append(normalized)

    # For each fund f we use cumulative variables x_f,0, x_f,1, ..., x_f,T.
    # This enforces strict sequential access to higher tiers.

    # Map (f, t) -> variable index
    var_index = {}
    idx = 0
    for f in range(n_funds):
        for t in range(len(funds_normalized[f])):
            var_index[(f, t)] = idx
            idx += 1
    n_vars = idx

    # Objective: maximize total interest over the horizon.
    # Using cumulative variables, the coefficient of x_f,t is -(i_t - i_{t+1}).
    c = np.zeros(n_vars)
    for f in range(n_funds):
        tiers = funds_normalized[f]
        for t in range(len(tiers)):
            i_t = tiers[t][1]
            i_next = tiers[t + 1][1] if t + 1 < len(tiers) else 0.0
            c[var_index[(f, t)]] = -(i_t - i_next)

    # Budget equality: the sum of final cumulative allocations equals the budget.
    A_eq = np.zeros((1, n_vars))
    for f in range(n_funds):
        T_f = len(funds_normalized[f]) - 1
        A_eq[0, var_index[(f, T_f)]] = 1.0
    b_eq = np.array([total_amount])

    # Bounds: 0 <= x_f,t <= L_f,t
    lb = np.zeros(n_vars)
    ub = np.full(n_vars, np.inf)
    for f in range(n_funds):
        for t, (lim, _) in enumerate(funds_normalized[f]):
            i = var_index[(f, t)]
            ub[i] = lim

    # Inequalities: x_f,t-1 <= x_f,t  =>  x_f,t-1 - x_f,t <= 0  (linprog uses A_ub x <= b_ub)
    ineq_rows = []
    for f in range(n_funds):
        for t in range(1, len(funds_normalized[f])):
            row = np.zeros(n_vars)
            row[var_index[(f, t - 1)]] = 1.0
            row[var_index[(f, t)]] = -1.0
            ineq_rows.append(row)
    if ineq_rows:
        A_ub = np.vstack(ineq_rows)
        b_ub = np.zeros(len(ineq_rows))
    else:
        A_ub = np.zeros((0, n_vars))
        b_ub = np.array([])

    # Solve: min c'x  s.t.  A_eq x = b_eq,  A_ub x <= b_ub,  lb <= x <= ub
    bounds = list(zip(lb, ub))
    result = linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs")

    if not result.success:
        return {
            "success": False,
            "message": result.message,
            "allocation": {},
            "allocation_pct": {},
            "allocation_by_tier": {},
            "total_interest": 0.0,
            "total_interest_rate_pct": 0.0,
            "interest_by_fund": {},
        }

    x = result.x
    # Recover allocation per fund (last cumulative) and per tier (cumulative differences).
    allocation = {}
    allocation_by_tier = {}
    interest_by_fund = {}
    total_interest = 0.0

    def _float(v):
        return float(v) if hasattr(v, "item") else float(v)

    for f in range(n_funds):
        name = fund_names[f]
        tiers = funds_normalized[f]
        cumuls = [x[var_index[(f, t)]] for t in range(len(tiers))]
        allocation[name] = _float(cumuls[-1])

        tier_amounts = [_float(cumuls[0])]
        for t in range(1, len(cumuls)):
            tier_amounts.append(_float(cumuls[t] - cumuls[t - 1]))
        allocation_by_tier[name] = tier_amounts

        interest_f = sum(
            (tiers[t][1] - (tiers[t + 1][1] if t + 1 < len(tiers) else 0.0)) * cumuls[t]
            for t in range(len(tiers))
        )
        interest_by_fund[name] = _float(interest_f)
        total_interest += interest_f

    allocation_pct = {k: (v / total_amount * 100.0 if total_amount > 0 else 0.0) for k, v in allocation.items()}

    total_interest_val = _float(total_interest)
    total_interest_rate_pct = (total_interest_val / total_amount * 100.0) if total_amount > 0 else 0.0

    return {
        "success": True,
        "message": str(result.message),
        "allocation": allocation,
        "allocation_pct": allocation_pct,
        "allocation_by_tier": allocation_by_tier,
        "total_interest": total_interest_val,
        "total_interest_rate_pct": total_interest_rate_pct,
        "interest_by_fund": interest_by_fund,
    }
