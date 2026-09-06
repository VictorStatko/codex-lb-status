"""Presentation and aggregation coverage."""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from codex_lb_status.models import (
    AccountSummary,
    AccountUsage,
    RequestUsage,
    WarmUpState,
)
from codex_lb_status.presentation import (
    QuotaTone,
    account_connection_is_healthy,
    account_is_quota_eligible,
    account_summary_lines,
    account_title,
    compact_number,
    display_routing_policy,
    display_status,
    format_absolute_timestamp,
    format_cost,
    format_elapsed,
    format_pool_headline,
    format_reset_countdown,
    format_tray_account_summary,
    format_tray_quota_summary,
    format_tray_tooltip,
    menu_text,
    quota_tone,
    sort_accounts,
    summarize_accounts,
    tooltip_text,
)


def account(
    name: str,
    status: str = "active",
    primary: float | None = 80,
    secondary: float | None = 40,
    alias: str | None = None,
) -> AccountSummary:
    return AccountSummary(
        account_id=name,
        email=f"{name}@example.com",
        display_name=name.title(),
        plan_type="plus",
        routing_policy="normal",
        status=status,
        alias=alias,
        usage=AccountUsage(primary, secondary, None),
    )


def test_legacy_percentages_pool_routing_eligible_accounts_only() -> None:
    summary = summarize_accounts(
        [
            account("one", primary=50, secondary=80),
            account("limited", status="rate_limited", primary=0, secondary=0),
            account(
                "paused",
                status="paused",
                primary=100,
                secondary=100,
            ),
        ]
    )
    assert summary.primary == pytest.approx(25)
    assert summary.secondary == pytest.approx(40)
    assert format_pool_headline(summary) == "5h 25% W 40% (1/3)"
    assert summary.tone is QuotaTone.RED


@pytest.mark.parametrize(
    ("status", "healthy", "quota_eligible"),
    [
        ("active", True, True),
        ("rate_limited", False, True),
        ("quota_exceeded", False, True),
        ("reauth_required", False, True),
        ("paused", False, False),
        ("deactivated", False, False),
        ("unknown", False, False),
    ],
)
def test_health_and_quota_eligibility_use_distinct_status_semantics(
    status: str,
    healthy: bool,
    quota_eligible: bool,
) -> None:
    item = account("one", status=status)
    assert account_connection_is_healthy(item) is healthy
    assert account_is_quota_eligible(item) is quota_eligible
    summary = summarize_accounts([item])
    assert summary.active_count == int(healthy)
    assert (summary.primary is not None) is quota_eligible


def test_credit_fields_are_capacity_weighted_per_window() -> None:
    small = replace(
        account("small", primary=50, secondary=50),
        capacity_credits_primary=100,
        remaining_credits_primary=50,
        capacity_credits_secondary=200,
        remaining_credits_secondary=100,
    )
    large = replace(
        account("large", status="rate_limited", primary=0, secondary=0),
        capacity_credits_primary=900,
        remaining_credits_primary=900,
        capacity_credits_secondary=0,
        remaining_credits_secondary=0,
        capacity_credits_monthly=300,
        remaining_credits_monthly=150,
    )
    excluded = replace(
        account("paused", status="paused", primary=0, secondary=0),
        capacity_credits_primary=10_000,
        remaining_credits_primary=0,
    )
    summary = summarize_accounts([small, large, excluded])
    assert summary.primary == pytest.approx(95)
    assert summary.secondary == pytest.approx(50)
    assert summary.monthly == pytest.approx(50)
    assert summary.active_count == 1
    assert summary.total_count == 3


def test_credit_availability_and_fallback_are_independent_per_window() -> None:
    with_primary_credits = replace(
        account("credits", primary=1, secondary=60),
        capacity_credits_primary=0,
        remaining_credits_primary=0,
    )
    legacy = account("legacy", primary=90, secondary=20)
    summary = summarize_accounts([with_primary_credits, legacy])
    assert summary.primary is None
    assert summary.secondary == pytest.approx(40)


def test_pool_summary_uses_nearest_reset_for_each_quota_window() -> None:
    first_primary = datetime(2026, 9, 6, 10, tzinfo=UTC)
    first_secondary = datetime(2026, 9, 8, 10, tzinfo=UTC)
    first_monthly = datetime(2026, 9, 20, 10, tzinfo=UTC)
    later = replace(
        account("later"),
        usage=AccountUsage(80, 40, 20),
        reset_at_primary=first_primary + timedelta(hours=2),
        reset_at_secondary=first_secondary,
        reset_at_monthly=first_monthly + timedelta(days=2),
    )
    earlier = replace(
        account("earlier", status="rate_limited"),
        usage=AccountUsage(20, 10, 70),
        reset_at_primary=first_primary,
        reset_at_secondary=first_secondary + timedelta(days=1),
        reset_at_monthly=first_monthly,
    )

    summary = summarize_accounts([later, earlier])

    assert summary.primary_increases_at == first_primary
    assert summary.secondary_increases_at == first_secondary
    assert summary.monthly_increases_at == first_monthly


def test_pool_summary_uses_resets_from_all_accounts() -> None:
    pooled_reset = datetime(2026, 9, 6, 10, tzinfo=UTC)
    pooled = replace(account("pooled"), reset_at_primary=pooled_reset)
    paused_reset = pooled_reset - timedelta(hours=1)
    paused = replace(
        account("paused", status="paused"),
        reset_at_primary=paused_reset,
    )

    assert summarize_accounts([pooled, paused]).primary_increases_at == paused_reset


@pytest.mark.parametrize(
    ("value", "tone"),
    [(70, QuotaTone.GREEN), (30, QuotaTone.AMBER), (29.9, QuotaTone.RED)],
)
def test_indicator_thresholds(value: float, tone: QuotaTone) -> None:
    assert (
        summarize_accounts([account("one", primary=value, secondary=value)]).tone
        is tone
    )
    assert quota_tone(value) is tone


def test_tray_tooltip_names_both_icon_values() -> None:
    summary = summarize_accounts([account("one", primary=82, secondary=47)])
    assert format_tray_tooltip(summary) == "5h: 82% · Weekly: 47%"
    assert format_tray_quota_summary(summary) == "5h: 82% | Weekly: 47%"
    assert format_tray_account_summary(summary) == (
        "Accounts: 1 total | 1 active | Reset credits: 0"
    )


def test_tray_account_summary_compacts_large_pool_counts() -> None:
    accounts = [
        replace(account(str(index)), available_reset_credits=10)
        for index in range(1_250)
    ]
    summary = summarize_accounts(accounts)

    assert format_tray_account_summary(summary) == (
        "Accounts: 1.2K total | 1.2K active | Reset credits: 12.5K"
    )


def test_empty_pool_is_red_but_no_usable_quota_is_gray() -> None:
    assert summarize_accounts([]).tone is QuotaTone.RED
    assert (
        summarize_accounts([account("one", primary=None, secondary=None)]).tone
        is QuotaTone.GRAY
    )


def test_monthly_only_data_is_used_when_primary_and_secondary_are_absent() -> None:
    item = account("monthly", primary=None, secondary=None)
    item = replace(item, usage=AccountUsage(None, None, 55))
    summary = summarize_accounts([item])
    assert format_pool_headline(summary) == "M 55% (1/1)"
    assert format_tray_quota_summary(summary) == "Monthly: 55%"


def test_sorting_puts_active_then_pool_eligible_then_excluded_accounts() -> None:
    sorted_accounts = sort_accounts(
        [
            account("z", status="paused", alias="A"),
            account("c", status="rate_limited", alias="C"),
            account("b", alias="B"),
            account("a", alias="A"),
        ]
    )
    assert [item.account_id for item in sorted_accounts] == ["a", "b", "c", "z"]


def test_countdown_is_independent_of_display_time_zone() -> None:
    now = datetime(2026, 8, 21, 12, tzinfo=UTC)
    target = now + timedelta(hours=2, minutes=35)
    assert format_reset_countdown(target, now) == "2h 35m"
    assert format_reset_countdown(target.astimezone(), now) == "2h 35m"
    assert format_reset_countdown(None, now) is None
    assert format_reset_countdown(now, now) == "now"
    assert format_reset_countdown(now + timedelta(minutes=5), now) == "5m"
    assert format_reset_countdown(now + timedelta(days=2, hours=3), now) == "2d 3h"


def test_absolute_timestamp_can_be_rendered_in_utc_or_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timestamp = datetime(2026, 8, 21, 12, tzinfo=UTC)
    assert format_absolute_timestamp(timestamp, "utc") == "2026-08-21 12:00 UTC"
    monkeypatch.setenv("TZ", "Europe/Minsk")
    import time

    time.tzset()
    assert format_absolute_timestamp(timestamp, "local").startswith("2026-08-21 15:00")


def test_elapsed_and_numeric_formatting_cover_compact_display_ranges() -> None:
    now = datetime(2026, 8, 21, 12, tzinfo=UTC)
    assert format_elapsed(None, now) is None
    assert format_elapsed(now - timedelta(seconds=10), now) == "just now"
    assert format_elapsed(now - timedelta(minutes=5), now) == "5m ago"
    assert format_elapsed(now - timedelta(hours=2, minutes=5), now) == "2h 5m ago"
    assert format_elapsed(now - timedelta(days=2, hours=3), now) == "2d 3h ago"
    assert (
        format_elapsed(now.replace(tzinfo=None), now.replace(tzinfo=None)) == "just now"
    )
    assert format_absolute_timestamp(None, "utc") is None
    assert compact_number(None) is None
    assert compact_number(math.nan) is None
    assert compact_number(12) == "12"
    assert compact_number(12.5) == "12.5"
    assert compact_number(1_250) == "1.2K"
    assert compact_number(1_250_000) == "1.2M"
    assert compact_number(1_250_000_000) == "1.2B"
    assert format_cost(None) is None
    assert format_cost(math.inf) is None
    assert format_cost(1234.5) == "$1,234.50"
    assert display_status(None) == "Unknown"
    assert display_status("rate_limited") == "Rate Limited"
    assert display_routing_policy(None) == "Routing unavailable"
    assert display_routing_policy("burn_first") == "Burn First"


def test_dynamic_text_is_bounded_and_safe_for_tooltips_and_menus() -> None:
    value = "<b>bad & text</b>\n" + "x" * 500
    assert "<b>" not in tooltip_text(value)
    assert "&amp;" in tooltip_text(value)
    assert "&&" in menu_text(value)
    assert "\n" not in menu_text(value)


def test_account_lines_include_available_windows_credits_warmup_and_traffic() -> None:
    now = datetime(2026, 8, 21, 12, tzinfo=UTC)
    item = replace(
        account("full", alias=""),
        usage=AccountUsage(90, None, 40),
        reset_at_primary=now + timedelta(hours=1),
        reset_at_secondary=now + timedelta(hours=2),
        available_reset_credits=1250,
        reset_credit_nearest_expires_at=now + timedelta(days=1),
        limit_warmup=WarmUpState(
            window="5h",
            status="completed",
            model="gpt",
            attempted_at=now - timedelta(minutes=5),
            reset_at=1_800_000_000,
        ),
        request_usage=RequestUsage(12, 1_250_000, 2.5),
    )
    lines = account_summary_lines(item, now, "utc")
    assert lines[0] == "Full"
    assert any(line.startswith("5h: 90%") for line in lines)
    assert any(line.startswith("W: unavailable") for line in lines)
    assert any(line.startswith("M: 40%") for line in lines)
    assert any("Reset credits: 1.2K" in line for line in lines)
    assert any("Warm-up: Completed" in line for line in lines)
    assert any("Traffic: 12 req" in line for line in lines)
    assert account_title(replace(item, alias=None, display_name="Name")) == "Name"
