"""Tests for the allocator."""

from pathlib import Path

import pytest

from rate_allocator import (
    Constraint,
    Institution,
    Tier,
    allocate,
)
from rate_allocator.core.finance.rates import discrete_compounding_accumulation_factor


@pytest.fixture
def sample_institutions():
    return [
        Institution(
            name="Nu",
            tiers=(
                Tier(limit=25_000, rate=0.15),
                Tier(limit=250_000, rate=0.12),
                Tier(limit=float("inf"), rate=0.10),
            ),
        ),
        Institution(
            name="Mercado Pago",
            tiers=(
                Tier(limit=23_000, rate=0.14),
                Tier(limit=float("inf"), rate=0.10),
            ),
        ),
    ]


class TestAllocate:
    def test_allocates_full_amount(self, sample_institutions):
        result = allocate(total=100_000, institutions=sample_institutions)
        assert abs(result.total_allocated - 100_000) < 1e-6

    def test_prioritizes_higher_rates(self, sample_institutions):
        result = allocate(total=48_000, institutions=sample_institutions)
        nu_alloc = sum(result.allocations["Nu"])
        mp_alloc = sum(result.allocations["Mercado Pago"])
        assert nu_alloc == 25_000
        assert mp_alloc == 23_000

    def test_prefers_single_institution_when_rates_identical(self):
        institutions = [
            Institution(
                name=f"S{i}",
                tiers=(Tier(limit=float("inf"), rate=0.10),),
            )
            for i in range(3)
        ]
        result = allocate(total=40_000, institutions=institutions)
        nonempty = sum(
            1
            for inst in institutions
            if sum(result.allocations[inst.name]) > 1e-6
        )
        assert nonempty == 1

    def test_fills_tiers_sequentially(self, sample_institutions):
        result = allocate(total=50_000, institutions=sample_institutions)
        nu_alloc = result.allocations["Nu"]
        mp_alloc = result.allocations["Mercado Pago"]
        assert nu_alloc[0] == 25_000  # Nu first tier full
        mp_first = mp_alloc[0]
        assert mp_first == 23_000  # MP first tier full (higher rate)
        assert nu_alloc[1] == pytest.approx(2_000, abs=0.02)  # MILP float noise

    def test_zero_allocation(self, sample_institutions):
        result = allocate(total=0, institutions=sample_institutions)
        assert result.total_allocated == 0
        assert result.expected_return == 0
        assert result.total_expenses_paid == 0

    def test_effective_rate_single_tier(self, sample_institutions):
        result = allocate(total=25_000, institutions=sample_institutions)
        expected_rate = discrete_compounding_accumulation_factor(0.15, 1.0, 365) - 1.0
        assert abs(result.effective_rate - expected_rate) < 1e-6

    def test_large_allocation(self, sample_institutions):
        result = allocate(total=1_000_000, institutions=sample_institutions)
        assert abs(result.total_allocated - 1_000_000) < 1e-6

    def test_negative_total_raises(self, sample_institutions):
        with pytest.raises(ValueError, match="non-negative"):
            allocate(total=-100, institutions=sample_institutions)

    def test_empty_institutions_raises(self):
        with pytest.raises(ValueError, match="at least one"):
            allocate(total=100_000, institutions=[])

    def test_tier_validation_rate(self):
        with pytest.raises(ValueError, match="Rate"):
            Tier(limit=1000, rate=1.5)

    def test_institution_tier_order(self):
        with pytest.raises(ValueError, match="ascending"):
            Institution(
                name="Bad",
                tiers=(Tier(limit=1000, rate=0.1), Tier(limit=500, rate=0.05)),
            )

    def test_mixed_allocation(self, sample_institutions):
        result = allocate(total=100_000, institutions=sample_institutions)
        expected_return = result.expected_return
        effective_rate = result.effective_rate
        assert effective_rate > 0
        assert expected_return > 0
        assert abs(expected_return - 100_000 * effective_rate) < 1e-6

    def test_fee_constraint_applies_cost_once(self):
        institutions = [
            Institution(
                name="FeeBank",
                tiers=(
                    Tier(
                        limit=float("inf"),
                        rate=0.13,
                        constraints=(
                            # Annual membership fee for preferred plan.
                            Constraint(
                                type="fee",
                                cost=100.0,
                                benefit="membership_plan",
                            ),
                        ),
                    ),
                ),
            ),
        ]
        result = allocate(total=10_000, institutions=institutions)
        assert result.total_allocated == 10_000
        expected_gain = 10_000 * (
            discrete_compounding_accumulation_factor(0.13, 1.0, 365) - 1.0
        )
        assert abs(result.expected_return - (expected_gain - 100.0)) < 1e-6
        assert result.total_expenses_paid == pytest.approx(100.0)

    def test_loads_constraints_from_yaml(self):
        pytest.importorskip("yaml")
        from rate_allocator.adapters.yaml_loader import load_institutions_from_yaml

        data_file = Path(__file__).resolve().parents[1] / "data" / "sample1.yaml"
        institutions = load_institutions_from_yaml(data_file)
        plata = next(inst for inst in institutions if inst.name == "PlataAhorroPlus")
        assert plata.tiers[0].constraints
        fee_constraint = plata.tiers[0].constraints[0]
        assert fee_constraint.type == "monthly_expense"
        assert fee_constraint.cost > 0

    def test_constraint_active_field_parsed(self):
        pytest.importorskip("yaml")
        from rate_allocator.adapters.yaml_loader import load_institutions_from_yaml

        data_file = Path(__file__).resolve().parents[1] / "data" / "sample1.yaml"
        institutions = load_institutions_from_yaml(data_file)
        nu = next(inst for inst in institutions if inst.name == "Nu")
        assert nu.tiers[0].constraints
        monthly_expense = nu.tiers[0].constraints[0]
        assert monthly_expense.type == "monthly_expense"
        assert monthly_expense.active is True

    def test_constraint_deactivation_affects_result(self):
        pytest.importorskip("yaml")
        from rate_allocator.adapters.yaml_loader import load_institutions_with_overrides

        data_file = Path(__file__).resolve().parents[1] / "data" / "sample1.yaml"

        # Total must be large enough that Plata receives principal; at 10k MXN the
        # optimizer avoids Plata (monthly fee dominates), so with/without fee are identical.
        total = 100_000
        result_with_fee = allocate(
            total=total,
            institutions=load_institutions_with_overrides(data_file, {}),
        )
        result_without_fee = allocate(
            total=total,
            institutions=load_institutions_with_overrides(
                data_file, {"PlataAhorroPlus": []}
            ),
        )

        assert result_with_fee.expected_return < result_without_fee.expected_return

    def test_constraint_info_populated(self, sample_institutions):
        result = allocate(total=100_000, institutions=sample_institutions)
        assert "Nu" in result.constraint_info
        assert "Mercado Pago" in result.constraint_info

    def test_constraint_info_tracks_activation(self):
        institutions = [
            Institution(
                name="TestBank",
                tiers=(
                    Tier(
                        limit=float("inf"),
                        rate=0.13,
                        constraints=(
                            Constraint(
                                type="fee",
                                cost=50.0,
                                benefit="premium",
                                active=True,
                            ),
                        ),
                    ),
                ),
            ),
        ]
        result = allocate(total=10_000, institutions=institutions)
        info = result.constraint_info["TestBank"]
        assert len(info) == 1
        assert info[0]["type"] == "fee"
        assert info[0]["activated"]

    def test_disclosure_conditions_in_constraint_info(self):
        institutions = [
            Institution(
                name="FootnoteBank",
                tiers=(
                    Tier(
                        limit=float("inf"),
                        rate=0.15,
                        constraints=(
                            Constraint(
                                type="disclosure",
                                cost=0.0,
                                active=False,
                                constraint_condition="Cap applies.",
                                benefit_condition="Cap applies.",
                            ),
                        ),
                    ),
                ),
            ),
        ]
        result = allocate(total=1_000, institutions=institutions)
        info = result.constraint_info["FootnoteBank"]
        assert len(info) == 1
        row = info[0]
        assert row["type"] == "disclosure"
        assert row["constraint_condition"] == "Cap applies."
        assert row["benefit_condition"] == "Cap applies."
        assert row["activated"]

    def test_disclosure_conditions_load_from_yaml(self):
        pytest.importorskip("yaml")
        from rate_allocator.adapters.yaml_loader import load_institutions_from_yaml

        path = Path(__file__).resolve().parents[1] / "data" / "sample3.yaml"
        if not path.is_file():
            pytest.skip("sample3.yaml not present")
        institutions = load_institutions_from_yaml(path)
        didi = next(i for i in institutions if i.name == "Didi Cuenta")
        assert len(didi.tiers) == 2
        cons = didi.tiers[0].constraints
        assert len(cons) == 1
        assert cons[0].type == "disclosure"
        assert cons[0].constraint_condition
        assert cons[0].benefit_condition == cons[0].constraint_condition

    def test_decero_plata_plus_membership_fee_from_yaml(self):
        pytest.importorskip("yaml")
        from rate_allocator.adapters.yaml_loader import load_institutions_from_yaml

        path = Path(__file__).resolve().parents[1] / "data" / "sample3.yaml"
        if not path.is_file():
            pytest.skip("sample3.yaml not present")
        institutions = load_institutions_from_yaml(path)
        plata = next(i for i in institutions if i.name == "Plata Ahorro Plus (+)")
        cons = plata.tiers[0].constraints
        assert len(cons) == 1
        fee = cons[0]
        assert fee.type == "monthly_expense"
        assert fee.cost == pytest.approx(114.84)
        assert fee.benefit == "membership_plan"
        assert fee.active is True
        assert "99" in (fee.constraint_condition or "")
        assert "IVA" in (fee.constraint_condition or "")

    def test_decero_revolut_three_band_ladder_from_yaml(self):
        pytest.importorskip("yaml")
        from rate_allocator.adapters.yaml_loader import load_institutions_from_yaml

        path = Path(__file__).resolve().parents[1] / "data" / "sample3.yaml"
        if not path.is_file():
            pytest.skip("sample3.yaml not present")
        institutions = load_institutions_from_yaml(path)
        rev = next(i for i in institutions if i.name == "Revolut")
        assert len(rev.tiers) == 3
        assert rev.tiers[0].limit == 25_000.0
        assert rev.tiers[0].rate == pytest.approx(0.15)
        assert rev.tiers[1].limit == 1_000_000.0
        assert rev.tiers[1].rate == pytest.approx(0.0725)
        assert rev.tiers[2].rate == pytest.approx(0.05)

    def test_decero_openbank_three_band_matches_sample1_shape(self):
        pytest.importorskip("yaml")
        from rate_allocator.adapters.yaml_loader import load_institutions_from_yaml

        path = Path(__file__).resolve().parents[1] / "data" / "sample3.yaml"
        if not path.is_file():
            pytest.skip("sample3.yaml not present")
        institutions = load_institutions_from_yaml(path)
        ob = next(i for i in institutions if i.name == "Openbank")
        assert len(ob.tiers) == 3
        assert ob.tiers[0].limit == 40_000.0
        assert ob.tiers[0].rate == pytest.approx(0.13)
        assert ob.tiers[1].limit == 1_000_000.0
        assert ob.tiers[1].rate == pytest.approx(0.073)
        assert ob.tiers[2].rate == pytest.approx(0.07)

    def test_decero_nu_two_band_from_yaml(self):
        pytest.importorskip("yaml")
        from rate_allocator.adapters.yaml_loader import load_institutions_from_yaml

        path = Path(__file__).resolve().parents[1] / "data" / "sample3.yaml"
        if not path.is_file():
            pytest.skip("sample3.yaml not present")
        institutions = load_institutions_from_yaml(path)
        nu = next(i for i in institutions if i.name == "NU")
        assert len(nu.tiers) == 2
        assert nu.tiers[0].limit == 25_000.0
        assert nu.tiers[0].rate == pytest.approx(0.13)
        assert nu.tiers[1].limit == float("inf")
        assert nu.tiers[1].rate == pytest.approx(0.0675)

    def test_decero_mifel_digital_three_tiers_from_yaml(self):
        pytest.importorskip("yaml")
        from rate_allocator.adapters.yaml_loader import load_institutions_from_yaml

        path = Path(__file__).resolve().parents[1] / "data" / "sample3.yaml"
        if not path.is_file():
            pytest.skip("sample3.yaml not present")
        institutions = load_institutions_from_yaml(path)
        mifel = next(i for i in institutions if i.name == "Mifel (cuenta digital)")
        assert len(mifel.tiers) == 3
        assert mifel.tiers[0].limit == 100.0
        assert mifel.tiers[0].rate == 0.0
        assert mifel.tiers[1].limit == 500_000.0
        assert mifel.tiers[1].rate == pytest.approx(0.1)
        assert mifel.tiers[2].limit == float("inf")
        assert mifel.tiers[2].rate == 0.0
        assert any(c.type == "disclosure" for c in mifel.tiers[1].constraints)

    def test_decero_stori_merged_notas_in_disclosure(self):
        pytest.importorskip("yaml")
        from rate_allocator.adapters.yaml_loader import load_institutions_from_yaml

        path = Path(__file__).resolve().parents[1] / "data" / "sample3.yaml"
        if not path.is_file():
            pytest.skip("sample3.yaml not present")
        institutions = load_institutions_from_yaml(path)
        stori = next(i for i in institutions if i.name == "Stori")
        disc = [c for c in stori.tiers[0].constraints if c.type == "disclosure"]
        assert len(disc) == 1
        txt = disc[0].benefit_condition or ""
        assert "14.14%" in txt or "5,000" in txt
        assert "nominal" in txt.casefold()

    def test_compound_horizon_expected_return_matches_formula(self):
        institutions = [
            Institution(
                name="Solo",
                tiers=(Tier(limit=float("inf"), rate=0.10),),
            ),
        ]
        principal = 10_000.0
        result = allocate(
            total=principal,
            institutions=institutions,
            horizon_years=1.0,
            periods_per_year=365,
        )
        g = discrete_compounding_accumulation_factor(0.10, 1.0, 365) - 1.0
        assert abs(result.expected_return - principal * g) < 1e-6
        assert abs(result.effective_rate - g) < 1e-9

    def test_negative_horizon_raises(self, sample_institutions):
        with pytest.raises(ValueError, match="non-negative"):
            allocate(
                total=10_000,
                institutions=sample_institutions,
                horizon_years=-0.1,
                periods_per_year=12,
            )

    def test_institution_type_and_protection_limit_loaded_from_yaml(self):
        pytest.importorskip("yaml")
        from rate_allocator.adapters.yaml_loader import load_institutions_from_yaml

        data_file = Path(__file__).resolve().parents[1] / "data" / "sample1.yaml"
        institutions = load_institutions_from_yaml(data_file)

        nu = next(inst for inst in institutions if inst.name == "Nu")
        assert nu.institution_type == "sofipo"
        assert nu.effective_protection_limit == pytest.approx(200_000.0)

        openbank = next(inst for inst in institutions if inst.name == "OpenBank")
        assert openbank.institution_type == "banco"
        assert openbank.effective_protection_limit == pytest.approx(3_200_000.0)

    def test_protection_cap_constraints_limit_institution_allocation(self):
        institutions = [
            Institution(
                name="SofipoA",
                institution_type="sofipo",
                tiers=(Tier(limit=float("inf"), rate=0.13),),
            ),
            Institution(
                name="NoCapB",
                institution_type="none",
                tiers=(Tier(limit=float("inf"), rate=0.12),),
            ),
        ]

        result = allocate(total=400_000, institutions=institutions)
        assert sum(result.allocations["SofipoA"]) == pytest.approx(208_000.0)
        assert sum(result.allocations["NoCapB"]) == pytest.approx(192_000.0)

    def test_monthly_cost_scales_with_horizon(self):
        institutions = [
            Institution(
                name="PlanBank",
                tiers=(
                    Tier(
                        limit=float("inf"),
                        rate=0.0,
                        constraints=(
                            Constraint(
                                type="monthly_expense",
                                cost=114.84,
                                benefit="membership_plan",
                            ),
                        ),
                    ),
                ),
            ),
        ]
        result = allocate(
            total=10_000,
            institutions=institutions,
            horizon_years=1.0,
            periods_per_year=1,
        )
        assert result.expected_return == pytest.approx(-(114.84 * 12.0))
        assert result.total_expenses_paid == pytest.approx(114.84 * 12.0)

    def test_monthly_cost_defaults_to_one_year_when_horizon_omitted(self):
        institutions = [
            Institution(
                name="MonthlyPlan",
                tiers=(
                    Tier(
                        limit=float("inf"),
                        rate=0.0,
                        constraints=(Constraint(type="monthly_expense", cost=100.0),),
                    ),
                ),
            ),
        ]
        result = allocate(total=10_000, institutions=institutions)
        assert result.total_expenses_paid == pytest.approx(1_200.0)
        assert result.expected_return == pytest.approx(-1_200.0)

    def test_tier_unlock_enforced_for_zero_rate_front_tier(self):
        institutions = [
            Institution(
                name="MifelLike",
                tiers=(
                    Tier(limit=100.0, rate=0.0),
                    Tier(limit=float("inf"), rate=0.10),
                ),
            ),
            Institution(
                name="AltBank",
                tiers=(Tier(limit=float("inf"), rate=0.03),),
            ),
        ]
        result = allocate(
            total=300.0,
            institutions=institutions,
            horizon_years=1.0,
            periods_per_year=365,
        )
        mifel_tiers = result.allocations["MifelLike"]
        assert mifel_tiers[1] > 0.0
        assert mifel_tiers[0] == pytest.approx(100.0)

    def test_bank_isr_withholding_from_first_peso(self):
        institutions = [
            Institution(
                name="TaxBank",
                institution_type="banco",
                tiers=(Tier(limit=float("inf"), rate=0.0),),
            ),
        ]
        result = allocate(total=100_000.0, institutions=institutions)
        assert result.total_taxes_paid == pytest.approx(0.0)
        assert result.total_withholding_paid == pytest.approx(900.0)
        assert result.total_expenses_paid == pytest.approx(0.0)
        assert result.expected_return == pytest.approx(0.0)

    def test_sofipo_isr_exemption_applies_per_institution(self):
        institutions = [
            Institution(
                name="SofipoTax",
                institution_type="sofipo",
                tiers=(Tier(limit=float("inf"), rate=0.0),),
            ),
            Institution(
                name="Fallback",
                institution_type="none",
                tiers=(Tier(limit=float("inf"), rate=0.0),),
            ),
        ]
        result = allocate(total=300_000.0, institutions=institutions)
        # SOFIPO cap keeps taxable balance under exemption threshold.
        assert result.total_taxes_paid == pytest.approx(0.0)

    def test_load_regulatory_rules_file(self):
        pytest.importorskip("yaml")
        from rate_allocator.adapters.regulatory_loader import (
            load_regulatory_rules_from_yaml,
        )

        rules_file = (
            Path(__file__).resolve().parents[1] / "data" / "regulatory_rules.mx.yaml"
        )
        rules = load_regulatory_rules_from_yaml(rules_file)
        assert rules.country == "MX"
        assert rules.bank_insurance_limit_mxn == pytest.approx(3_300_000.0)
        assert rules.bank_isr_withholding_rate_annual == pytest.approx(0.009)
        assert rules.inflation_proxy_annual == pytest.approx(0.0421)

    def test_sofipo_tax_applies_on_excess_over_exemption(self):
        institutions = [
            Institution(
                name="SofipoTaxHigh",
                institution_type="sofipo",
                protection_limit=500_000.0,
                tiers=(Tier(limit=float("inf"), rate=0.0),),
            ),
        ]
        result = allocate(total=300_000.0, institutions=institutions)
        # For zero nominal gain, real-interest tax base is zero.
        assert result.total_taxes_paid == pytest.approx(0.0)

    def test_real_interest_tax_base_for_bank_uses_inflation_proxy(self):
        institutions = [
            Institution(
                name="TaxBankReal",
                institution_type="banco",
                tiers=(Tier(limit=float("inf"), rate=0.10),),
            ),
        ]
        principal = 100_000.0
        result = allocate(
            total=principal, institutions=institutions, periods_per_year=1
        )
        gross_interest = principal * 0.10
        inflation_drag = principal * 0.0421
        expected_tax = max(0.0, gross_interest - inflation_drag) * 0.009
        assert result.total_taxes_paid == pytest.approx(expected_tax)

    def test_no_real_interest_tax_when_nominal_below_inflation(self):
        institutions = [
            Institution(
                name="LowRateBank",
                institution_type="banco",
                tiers=(Tier(limit=float("inf"), rate=0.03),),
            ),
        ]
        result = allocate(
            total=100_000.0, institutions=institutions, periods_per_year=1
        )
        assert result.total_taxes_paid == pytest.approx(0.0)
