"""Filter builder tests."""

from __future__ import annotations

from costsight.core.filters import (
    ALL_RECORD_TYPES,
    CostFilterSpec,
    build_ce_filter,
    console_default,
    pre_credit_gross,
)


def test_console_default_produces_no_filter():
    assert build_ce_filter(console_default()) is None


def test_console_default_effective_record_types_equal_all():
    assert set(console_default().effective_record_types()) == set(ALL_RECORD_TYPES)


def test_pre_credit_gross_excludes_three_record_types():
    spec = pre_credit_gross()
    effective = spec.effective_record_types()
    for rt in ("Credit", "Refund", "Upfront"):
        assert rt not in effective
    for rt in ("Usage", "Tax", "Recurring", "Support"):
        assert rt in effective


def test_single_service_filter_emits_bare_dimensions():
    spec = CostFilterSpec(service="Amazon EC2")
    built = build_ce_filter(spec)
    assert built == {"Dimensions": {"Key": "SERVICE", "Values": ["Amazon EC2"]}}


def test_multiple_filters_wrap_in_and():
    spec = CostFilterSpec(
        service="Amazon EC2",
        linked_accounts=("123456789012",),
    )
    built = build_ce_filter(spec)
    assert "And" in built
    assert len(built["And"]) == 2


def test_usage_type_substrings_use_contains():
    spec = CostFilterSpec(usage_type_substrings=("BoxUsage", "SpotUsage"))
    built = build_ce_filter(spec)
    # With >1 pattern, emits an Or wrapper
    assert "Or" in built
    for part in built["Or"]:
        assert part["Dimensions"]["MatchOptions"] == ["CONTAINS"]


def test_filter_summary_includes_all_set_fields():
    spec = CostFilterSpec(service="Amazon EC2", tags=(("Team", "Devs"),),
                           excluded_record_types=("Credit",))
    s = spec.summary()
    assert "service=Amazon EC2" in s
    assert "tags=Team:Devs" in s
    assert "exclude=Credit" in s


def test_filter_summary_empty_when_no_filters():
    assert "no filters" in console_default().summary()
