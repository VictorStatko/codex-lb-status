"""Pure presentation helpers shared by the window and tray indicator."""

from __future__ import annotations

import html
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from .models import AccountSummary


class QuotaTone(StrEnum):
    GREEN = "green"
    AMBER = "amber"
    RED = "red"
    GRAY = "gray"


@dataclass(frozen=True, slots=True)
class PoolSummary:
    primary: float | None
    secondary: float | None
    monthly: float | None
    primary_increases_at: datetime | None
    secondary_increases_at: datetime | None
    monthly_increases_at: datetime | None
    active_count: int
    total_count: int
    reset_credits: int

    @property
    def displayed_values(self) -> tuple[float, ...]:
        primary_and_secondary = tuple(
            value for value in (self.primary, self.secondary) if value is not None
        )
        return primary_and_secondary or tuple(
            value for value in (self.monthly,) if value is not None
        )

    @property
    def tone(self) -> QuotaTone:
        return indicator_tone(self)

    @property
    def headline(self) -> str:
        return format_pool_headline(self)


def _average(values: Iterable[float | None]) -> float | None:
    usable = [value for value in values if value is not None and math.isfinite(value)]
    return sum(usable) / len(usable) if usable else None


_QUOTA_POOL_STATUSES = frozenset(
    {
        "active",
        "quota_exceeded",
        "rate_limited",
        "reauth_required",
    }
)


def account_connection_is_healthy(account: AccountSummary) -> bool:
    """Return whether the account is in Codex LB's canonical active state."""

    return account.status == "active"


def account_is_quota_eligible(account: AccountSummary) -> bool:
    """Match the statuses Codex LB considers selectable for pooled routing."""

    return account.status in _QUOTA_POOL_STATUSES


def _pooled_window(
    accounts: list[AccountSummary],
    window: str,
) -> float | None:
    capacity_field = f"capacity_credits_{window}"
    remaining_field = f"remaining_credits_{window}"
    has_credit_fields = any(
        getattr(account, capacity_field) is not None
        or getattr(account, remaining_field) is not None
        for account in accounts
    )
    if has_credit_fields:
        total_capacity = 0.0
        total_remaining = 0.0
        for account in accounts:
            capacity = getattr(account, capacity_field)
            remaining = getattr(account, remaining_field)
            if capacity is None or capacity <= 0 or remaining is None:
                continue
            total_capacity += capacity
            total_remaining += remaining
        if total_capacity <= 0:
            return None
        return 100.0 * total_remaining / total_capacity

    percentage_field = f"{window}_remaining_percent"
    return _average(
        getattr(account.usage, percentage_field) if account.usage else None
        for account in accounts
    )


def _nearest_reset(
    accounts: Iterable[AccountSummary],
    window: str,
) -> datetime | None:
    resets = [
        reset
        for account in accounts
        if (reset := getattr(account, f"reset_at_{window}")) is not None
    ]
    if not resets:
        return None

    def timestamp(reset: datetime) -> float:
        aware = reset.replace(tzinfo=UTC) if reset.tzinfo is None else reset
        return aware.timestamp()

    return min(resets, key=timestamp)


def summarize_accounts(accounts: Iterable[AccountSummary]) -> PoolSummary:
    account_list = list(accounts)
    quota_pool = [
        account for account in account_list if account_is_quota_eligible(account)
    ]
    return PoolSummary(
        primary=_pooled_window(quota_pool, "primary"),
        secondary=_pooled_window(quota_pool, "secondary"),
        monthly=_pooled_window(quota_pool, "monthly"),
        primary_increases_at=_nearest_reset(account_list, "primary"),
        secondary_increases_at=_nearest_reset(account_list, "secondary"),
        monthly_increases_at=_nearest_reset(account_list, "monthly"),
        active_count=sum(
            account_connection_is_healthy(account) for account in account_list
        ),
        total_count=len(account_list),
        reset_credits=sum(account.available_reset_credits for account in account_list),
    )


def round_percentage(value: float | None) -> int | None:
    """Round a valid percentage using conventional half-up rounding."""

    if value is None or not math.isfinite(value):
        return None
    return math.floor(value + 0.5)


def indicator_tone(summary: PoolSummary) -> QuotaTone:
    if summary.active_count == 0:
        return QuotaTone.RED
    values = summary.displayed_values
    if not values:
        return QuotaTone.GRAY
    return quota_tone(min(values))


def quota_tone(value: float | None) -> QuotaTone:
    """Return the presentation tone for one remaining-quota percentage."""

    if value is None or not math.isfinite(value):
        return QuotaTone.GRAY
    if value >= 70:
        return QuotaTone.GREEN
    if value >= 30:
        return QuotaTone.AMBER
    return QuotaTone.RED


def format_pool_headline(summary: PoolSummary) -> str:
    parts: list[str] = []
    if summary.primary is not None:
        parts.extend(("5h", f"{round_percentage(summary.primary)}%"))
    if summary.secondary is not None:
        parts.extend(("W", f"{round_percentage(summary.secondary)}%"))
    if (
        summary.primary is None
        and summary.secondary is None
        and summary.monthly is not None
    ):
        parts.extend(("M", f"{round_percentage(summary.monthly)}%"))
    if not parts:
        parts.append("quota unavailable")
    return f"{' '.join(parts)} ({summary.active_count}/{summary.total_count})"


def format_tray_tooltip(summary: PoolSummary) -> str:
    """Name both exact percentages represented by the compact tray icon."""

    primary = (
        "unavailable"
        if summary.primary is None
        else f"{round_percentage(summary.primary)}%"
    )
    weekly = (
        "unavailable"
        if summary.secondary is None
        else f"{round_percentage(summary.secondary)}%"
    )
    return f"5h: {primary} · Weekly: {weekly}"


def format_tray_quota_summary(summary: PoolSummary) -> str:
    """Return only the pooled quota values for the first tray-menu row."""

    if summary.primary is not None or summary.secondary is not None:
        primary = (
            "unavailable"
            if summary.primary is None
            else f"{round_percentage(summary.primary)}%"
        )
        weekly = (
            "unavailable"
            if summary.secondary is None
            else f"{round_percentage(summary.secondary)}%"
        )
        return f"5h: {primary} | Weekly: {weekly}"
    if summary.monthly is not None:
        return f"Monthly: {round_percentage(summary.monthly)}%"
    return "Quota unavailable"


def format_tray_account_summary(summary: PoolSummary) -> str:
    """Return fixed-size pool counts suitable for arbitrarily large pools."""

    total = compact_number(summary.total_count) or "0"
    active = compact_number(summary.active_count) or "0"
    resets = compact_number(summary.reset_credits) or "0"
    return f"Accounts: {total} total | {active} active | Reset credits: {resets}"


def format_reset_countdown(
    reset_at: datetime | None,
    now: datetime | None = None,
) -> str | None:
    """Format a duration without depending on the display time zone."""

    if reset_at is None:
        return None
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    if reset_at.tzinfo is None:
        reset_at = reset_at.replace(tzinfo=UTC)
    seconds = max(0, math.floor((reset_at - current).total_seconds()))
    if seconds == 0:
        return "now"
    days, remainder = divmod(seconds, 86_400)
    hours, remainder = divmod(remainder, 3_600)
    minutes = remainder // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def format_elapsed(
    occurred_at: datetime | None,
    now: datetime | None = None,
) -> str | None:
    if occurred_at is None:
        return None
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=UTC)
    seconds = max(0, math.floor((current - occurred_at).total_seconds()))
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes}m ago"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h ago"


def format_absolute_timestamp(
    timestamp: datetime | None,
    display_time_zone: str = "local",
) -> str | None:
    if timestamp is None:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    if display_time_zone == "utc":
        return timestamp.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
    local = timestamp.astimezone()
    zone_name = local.tzname() or "local"
    return local.strftime("%Y-%m-%d %H:%M ") + zone_name


def compact_number(value: float | int | None) -> str | None:
    if value is None or not math.isfinite(float(value)):
        return None
    absolute = abs(float(value))
    for divisor, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if absolute >= divisor:
            number = float(value) / divisor
            return f"{number:.1f}{suffix}".rstrip("0").rstrip(".")
    return f"{int(value)}" if float(value).is_integer() else f"{value:.1f}"


def format_cost(value: float | None) -> str | None:
    if value is None or not math.isfinite(value):
        return None
    return f"${value:,.2f}"


def display_status(status: str | None) -> str:
    if not status:
        return "Unknown"
    return status.replace("_", " ").strip().title()


def display_routing_policy(policy: str | None) -> str:
    if not policy:
        return "Routing unavailable"
    return policy.replace("_", " ").strip().title()


def sanitize_text(value: object, limit: int = 240) -> str:
    """Make server text a bounded, single-line plain-text label."""

    text = str(value) if value is not None else ""
    text = re.sub(r"[\x00-\x1f\x7f]", " ", text)
    text = " ".join(text.split())
    return text[:limit]


def tooltip_text(value: object, limit: int = 240) -> str:
    return html.escape(sanitize_text(value, limit), quote=True)


def menu_text(value: object, limit: int = 120) -> str:
    """Escape ampersands so server text cannot create Qt mnemonics."""

    return sanitize_text(value, limit).replace("&", "&&")


def account_title(account: AccountSummary) -> str:
    return sanitize_text(account.alias or account.display_name or account.email, 100)


def account_sort_key(account: AccountSummary) -> tuple[int, str, str, str]:
    if account_connection_is_healthy(account):
        status_rank = 0
    elif account_is_quota_eligible(account):
        status_rank = 1
    else:
        status_rank = 2
    return (
        status_rank,
        (account.alias or "").casefold(),
        account.display_name.casefold(),
        account.email.casefold(),
    )


def sort_accounts(accounts: Iterable[AccountSummary]) -> list[AccountSummary]:
    return sorted(accounts, key=account_sort_key)


def account_summary_lines(
    account: AccountSummary,
    now: datetime | None = None,
    display_time_zone: str = "local",
) -> list[str]:
    """Return bounded plain-text lines for a details card or compact menu row."""

    lines = [
        account_title(account),
        f"{sanitize_text(account.email, 120)} · {sanitize_text(account.plan_type, 60)}",
        f"{display_status(account.status)} · "
        f"{display_routing_policy(account.routing_policy)}",
    ]
    usage = account.usage
    windows = (
        (
            "5h",
            usage.primary_remaining_percent if usage else None,
            account.reset_at_primary,
        ),
        (
            "W",
            usage.secondary_remaining_percent if usage else None,
            account.reset_at_secondary,
        ),
        (
            "M",
            usage.monthly_remaining_percent if usage else None,
            account.reset_at_monthly,
        ),
    )
    for label, remaining, reset_at in windows:
        if remaining is None and reset_at is None:
            continue
        percentage = (
            "unavailable"
            if remaining is None
            else f"{round_percentage(remaining)}% left"
        )
        countdown = format_reset_countdown(reset_at, now)
        reset = f" · resets in {countdown}" if countdown else ""
        lines.append(f"{label}: {percentage}{reset}")
    if account.available_reset_credits is not None:
        credits = compact_number(account.available_reset_credits)
        expiry = format_absolute_timestamp(
            account.reset_credit_nearest_expires_at,
            display_time_zone,
        )
        suffix = f" · next expires {expiry}" if expiry else ""
        lines.append(f"Reset credits: {credits}{suffix}")
    if account.limit_warmup:
        warmup = account.limit_warmup
        warmup_elapsed = format_elapsed(warmup.attempted_at, now)
        state = display_status(warmup.status)
        lines.append(
            f"Warm-up: {state}{f' · {warmup_elapsed}' if warmup_elapsed else ''}"
        )
    request_usage = account.request_usage
    if request_usage:
        requests = compact_number(request_usage.request_count)
        tokens = compact_number(request_usage.total_tokens)
        cost = format_cost(request_usage.total_cost_usd)
        traffic = " · ".join(
            part for part in (f"{requests} req", f"{tokens} tokens", cost) if part
        )
        if traffic:
            lines.append(f"Traffic: {traffic}")
    return lines


__all__ = [
    "PoolSummary",
    "QuotaTone",
    "account_connection_is_healthy",
    "account_is_quota_eligible",
    "account_sort_key",
    "account_summary_lines",
    "account_title",
    "compact_number",
    "display_routing_policy",
    "display_status",
    "format_absolute_timestamp",
    "format_cost",
    "format_elapsed",
    "format_pool_headline",
    "format_reset_countdown",
    "format_tray_account_summary",
    "format_tray_quota_summary",
    "format_tray_tooltip",
    "indicator_tone",
    "menu_text",
    "quota_tone",
    "round_percentage",
    "sanitize_text",
    "sort_accounts",
    "summarize_accounts",
    "tooltip_text",
]
