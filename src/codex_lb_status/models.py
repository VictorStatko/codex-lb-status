"""Typed Codex LB responses that tolerate additive server API changes."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class ContractError(ValueError):
    """Raised when a required part of a dashboard response is malformed."""


JsonObject = Mapping[str, Any]

# Known labels are reference data, not exhaustive response validation rules.
ACCOUNT_STATUSES = frozenset(
    {
        "active",
        "rate_limited",
        "quota_exceeded",
        "paused",
        "reauth_required",
        "deactivated",
    }
)
ACCOUNT_ROUTING_POLICIES = frozenset({"normal", "burn_first", "preserve"})
ADDITIONAL_QUOTA_ROUTING_POLICIES = frozenset(
    {"inherit", "normal", "burn_first", "preserve"}
)
DASHBOARD_ROLES = frozenset({"admin", "guest"})
DASHBOARD_AUTH_MODES = frozenset({"standard", "trusted_header", "disabled"})
DASHBOARD_PERMISSIONS = frozenset({"read", "write"})


def _object(value: Any, path: str) -> JsonObject:
    if not isinstance(value, Mapping):
        raise ContractError(f"{path} must be an object")
    return value


def _required_string(body: JsonObject, key: str, path: str) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{path}.{key} must be a non-empty string")
    return value


def _optional_string(body: JsonObject, key: str, path: str) -> str | None:
    if key not in body or body[key] is None:
        return None
    value = body[key]
    if not isinstance(value, str):
        raise ContractError(f"{path}.{key} must be a string or null")
    return value if value.strip() else None


def _string_with_default(
    body: JsonObject,
    key: str,
    path: str,
    *,
    default: str,
) -> str:
    if key not in body:
        return default
    return _required_string(body, key, path)


def _required_bool(body: JsonObject, key: str, path: str) -> bool:
    value = body.get(key)
    if not isinstance(value, bool):
        raise ContractError(f"{path}.{key} must be a boolean")
    return value


def _bool_with_default(
    body: JsonObject,
    key: str,
    path: str,
    default: bool,
) -> bool:
    if key not in body:
        return default
    return _required_bool(body, key, path)


def _optional_bool(body: JsonObject, key: str, path: str) -> bool | None:
    if key not in body or body[key] is None:
        return None
    return _required_bool(body, key, path)


def _finite_number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{path} must be a finite number")
    converted = float(value)
    if not math.isfinite(converted):
        raise ContractError(f"{path} must be a finite number")
    return converted


def _optional_number(body: JsonObject, key: str, path: str) -> float | None:
    if key not in body or body[key] is None:
        return None
    return _finite_number(body[key], f"{path}.{key}")


def _optional_nonnegative_number(
    body: JsonObject,
    key: str,
    path: str,
) -> float | None:
    value = _optional_number(body, key, path)
    if value is not None and value < 0:
        raise ContractError(f"{path}.{key} must be non-negative")
    return value


def _number_with_default(
    body: JsonObject,
    key: str,
    path: str,
    default: float,
    *,
    nonnegative: bool = False,
) -> float:
    if key not in body:
        return default
    value = _finite_number(body[key], f"{path}.{key}")
    if nonnegative and value < 0:
        raise ContractError(f"{path}.{key} must be non-negative")
    return value


def _optional_integer(
    body: JsonObject,
    key: str,
    path: str,
    *,
    nonnegative: bool = False,
) -> int | None:
    if key not in body or body[key] is None:
        return None
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractError(f"{path}.{key} must be an integer or null")
    if nonnegative and value < 0:
        raise ContractError(f"{path}.{key} must be non-negative")
    return value


def _integer_with_default(
    body: JsonObject,
    key: str,
    path: str,
    default: int,
    *,
    nonnegative: bool = False,
) -> int:
    if key not in body:
        return default
    value = _optional_integer(body, key, path, nonnegative=nonnegative)
    if value is None:
        raise ContractError(f"{path}.{key} must be an integer")
    return value


def _optional_percentage(body: JsonObject, key: str, path: str) -> float | None:
    value = _optional_number(body, key, path)
    if value is not None and not 0 <= value <= 100:
        raise ContractError(f"{path}.{key} must be between 0 and 100")
    return value


def _optional_timestamp(body: JsonObject, key: str, path: str) -> datetime | None:
    if key not in body or body[key] is None:
        return None
    value = body[key]
    if not isinstance(value, str):
        raise ContractError(f"{path}.{key} must be an ISO-8601 timestamp or null")
    parsed = parse_iso8601(value)
    if parsed is None:
        raise ContractError(f"{path}.{key} must be an ISO-8601 timestamp or null")
    return parsed


def parse_iso8601(value: str) -> datetime | None:
    """Parse an ISO-8601 timestamp and normalize it to aware UTC time."""

    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip()
    if normalized.endswith(("Z", "z")):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class DashboardSession:
    authenticated: bool
    password_required: bool = False
    totp_required_on_login: bool = False
    totp_configured: bool = False
    bootstrap_required: bool = False
    bootstrap_token_configured: bool = False
    auth_mode: str = "standard"
    password_management_enabled: bool = True
    password_session_active: bool = False
    role: str = "admin"
    permissions: tuple[str, ...] = ("read", "write")
    guest_access_enabled: bool = False
    guest_password_required: bool = False

    @classmethod
    def from_json(cls, value: Any) -> DashboardSession:
        path = "response"
        body = _object(value, path)
        raw_permissions = body.get("permissions", ["read", "write"])
        if not isinstance(raw_permissions, list):
            raise ContractError("response.permissions must be an array")
        permissions: list[str] = []
        for index, permission in enumerate(raw_permissions):
            # Permissions are server metadata; this client grants no access
            # based on their names and must tolerate new permissions/scopes.
            if not isinstance(permission, str) or not permission.strip():
                raise ContractError(
                    f"response.permissions[{index}] must be a non-empty string"
                )
            if permission not in permissions:
                permissions.append(permission)
        return cls(
            authenticated=_required_bool(body, "authenticated", path),
            password_required=_required_bool(body, "passwordRequired", path),
            totp_required_on_login=_required_bool(body, "totpRequiredOnLogin", path),
            totp_configured=_required_bool(body, "totpConfigured", path),
            bootstrap_required=_bool_with_default(
                body, "bootstrapRequired", path, False
            ),
            bootstrap_token_configured=_bool_with_default(
                body, "bootstrapTokenConfigured", path, False
            ),
            auth_mode=_string_with_default(
                body,
                "authMode",
                path,
                default="standard",
            ),
            password_management_enabled=_bool_with_default(
                body, "passwordManagementEnabled", path, True
            ),
            password_session_active=_bool_with_default(
                body, "passwordSessionActive", path, False
            ),
            role=_string_with_default(body, "role", path, default="admin"),
            permissions=tuple(permissions),
            guest_access_enabled=_bool_with_default(
                body, "guestAccessEnabled", path, False
            ),
            guest_password_required=_bool_with_default(
                body, "guestPasswordRequired", path, False
            ),
        )


@dataclass(frozen=True, slots=True)
class AccountUsage:
    primary_remaining_percent: float | None = None
    secondary_remaining_percent: float | None = None
    monthly_remaining_percent: float | None = None

    @classmethod
    def from_json(
        cls,
        value: Any,
        path: str = "usage",
    ) -> AccountUsage | None:
        if value is None:
            return None
        body = _object(value, path)
        return cls(
            primary_remaining_percent=_optional_percentage(
                body, "primaryRemainingPercent", path
            ),
            secondary_remaining_percent=_optional_percentage(
                body, "secondaryRemainingPercent", path
            ),
            monthly_remaining_percent=_optional_percentage(
                body, "monthlyRemainingPercent", path
            ),
        )


@dataclass(frozen=True, slots=True)
class RequestUsage:
    request_count: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0
    cached_input_tokens: int = 0

    @classmethod
    def from_json(
        cls,
        value: Any,
        path: str = "requestUsage",
    ) -> RequestUsage | None:
        if value is None:
            return None
        body = _object(value, path)
        return cls(
            request_count=_integer_with_default(
                body, "requestCount", path, 0, nonnegative=True
            ),
            total_tokens=_integer_with_default(
                body, "totalTokens", path, 0, nonnegative=True
            ),
            total_cost_usd=_number_with_default(
                body, "totalCostUsd", path, 0, nonnegative=True
            ),
            cached_input_tokens=_integer_with_default(
                body, "cachedInputTokens", path, 0, nonnegative=True
            ),
        )


@dataclass(frozen=True, slots=True)
class AccountTokenStatus:
    expires_at: datetime | None = None
    state: str | None = None

    @classmethod
    def from_json(
        cls,
        value: Any,
        path: str,
    ) -> AccountTokenStatus | None:
        if value is None:
            return None
        body = _object(value, path)
        return cls(
            expires_at=_optional_timestamp(body, "expiresAt", path),
            state=_optional_string(body, "state", path),
        )


@dataclass(frozen=True, slots=True)
class AccountAuthStatus:
    access: AccountTokenStatus | None = None
    refresh: AccountTokenStatus | None = None
    id_token: AccountTokenStatus | None = None

    @classmethod
    def from_json(
        cls,
        value: Any,
        path: str = "auth",
    ) -> AccountAuthStatus | None:
        if value is None:
            return None
        body = _object(value, path)
        return cls(
            access=AccountTokenStatus.from_json(body.get("access"), f"{path}.access"),
            refresh=AccountTokenStatus.from_json(
                body.get("refresh"), f"{path}.refresh"
            ),
            id_token=AccountTokenStatus.from_json(
                body.get("idToken"), f"{path}.idToken"
            ),
        )


@dataclass(frozen=True, slots=True)
class WarmUpState:
    window: str
    status: str
    model: str
    attempted_at: datetime
    reset_at: int
    completed_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None

    @classmethod
    def from_json(
        cls,
        value: Any,
        path: str = "limitWarmup",
    ) -> WarmUpState | None:
        if value is None:
            return None
        body = _object(value, path)
        attempted_at = _optional_timestamp(body, "attemptedAt", path)
        if attempted_at is None:
            raise ContractError(f"{path}.attemptedAt must be an ISO-8601 timestamp")
        reset_at = _optional_integer(body, "resetAt", path, nonnegative=True)
        if reset_at is None:
            raise ContractError(f"{path}.resetAt must be an integer")
        return cls(
            window=_required_string(body, "window", path),
            status=_required_string(body, "status", path),
            model=_required_string(body, "model", path),
            attempted_at=attempted_at,
            reset_at=reset_at,
            completed_at=_optional_timestamp(body, "completedAt", path),
            error_code=_optional_string(body, "errorCode", path),
            error_message=_optional_string(body, "errorMessage", path),
        )


@dataclass(frozen=True, slots=True)
class AccountAdditionalWindow:
    used_percent: float
    reset_at: int | None = None
    window_minutes: int | None = None

    @classmethod
    def from_json(cls, value: Any, path: str) -> AccountAdditionalWindow | None:
        if value is None:
            return None
        body = _object(value, path)
        used_percent = _optional_percentage(body, "usedPercent", path)
        if used_percent is None:
            raise ContractError(f"{path}.usedPercent must be between 0 and 100")
        return cls(
            used_percent=used_percent,
            reset_at=_optional_integer(body, "resetAt", path, nonnegative=True),
            window_minutes=_optional_integer(
                body, "windowMinutes", path, nonnegative=True
            ),
        )


@dataclass(frozen=True, slots=True)
class AccountAdditionalQuota:
    limit_name: str
    metered_feature: str
    routing_policy: str = "inherit"
    quota_key: str | None = None
    display_label: str | None = None
    primary_window: AccountAdditionalWindow | None = None
    secondary_window: AccountAdditionalWindow | None = None

    @classmethod
    def from_json(cls, value: Any, path: str) -> AccountAdditionalQuota:
        body = _object(value, path)
        return cls(
            quota_key=_optional_string(body, "quotaKey", path),
            limit_name=_required_string(body, "limitName", path),
            metered_feature=_required_string(body, "meteredFeature", path),
            display_label=_optional_string(body, "displayLabel", path),
            routing_policy=_string_with_default(
                body,
                "routingPolicy",
                path,
                default="inherit",
            ),
            primary_window=AccountAdditionalWindow.from_json(
                body.get("primaryWindow"), f"{path}.primaryWindow"
            ),
            secondary_window=AccountAdditionalWindow.from_json(
                body.get("secondaryWindow"), f"{path}.secondaryWindow"
            ),
        )


@dataclass(frozen=True, slots=True)
class AccountSummary:
    account_id: str
    email: str
    display_name: str
    plan_type: str
    routing_policy: str
    status: str
    chatgpt_account_id: str | None = None
    alias: str | None = None
    workspace_id: str | None = None
    workspace_label: str | None = None
    seat_type: str | None = None
    security_work_authorized: bool = False
    usage: AccountUsage | None = None
    reset_at_primary: datetime | None = None
    reset_at_secondary: datetime | None = None
    reset_at_monthly: datetime | None = None
    window_minutes_primary: int | None = None
    window_minutes_secondary: int | None = None
    window_minutes_monthly: int | None = None
    last_refresh_at: datetime | None = None
    capacity_credits_primary: float | None = None
    remaining_credits_primary: float | None = None
    capacity_credits_secondary: float | None = None
    remaining_credits_secondary: float | None = None
    capacity_credits_monthly: float | None = None
    remaining_credits_monthly: float | None = None
    request_usage: RequestUsage | None = None
    additional_quotas: tuple[AccountAdditionalQuota, ...] = ()
    credits_has: bool | None = None
    credits_unlimited: bool | None = None
    credits_balance: float | None = None
    deactivation_reason: str | None = None
    auth: AccountAuthStatus | None = None
    limit_warmup_enabled: bool = False
    limit_warmup: WarmUpState | None = None
    is_email_duplicate: bool = False
    available_reset_credits: int = 0
    reset_credit_nearest_expires_at: datetime | None = None

    @classmethod
    def from_json(cls, value: Any, index: int = 0) -> AccountSummary:
        path = f"accounts[{index}]"
        body = _object(value, path)
        raw_additional_quotas = body.get("additionalQuotas", [])
        if not isinstance(raw_additional_quotas, list):
            raise ContractError(f"{path}.additionalQuotas must be an array")
        additional_quotas = tuple(
            AccountAdditionalQuota.from_json(
                quota, f"{path}.additionalQuotas[{quota_index}]"
            )
            for quota_index, quota in enumerate(raw_additional_quotas)
        )
        account = cls(
            account_id=_required_string(body, "accountId", path),
            chatgpt_account_id=_optional_string(body, "chatgptAccountId", path),
            email=_required_string(body, "email", path),
            alias=_optional_string(body, "alias", path),
            display_name=_required_string(body, "displayName", path),
            workspace_id=_optional_string(body, "workspaceId", path),
            workspace_label=_optional_string(body, "workspaceLabel", path),
            seat_type=_optional_string(body, "seatType", path),
            plan_type=_required_string(body, "planType", path),
            routing_policy=_string_with_default(
                body,
                "routingPolicy",
                path,
                default="normal",
            ),
            status=_required_string(body, "status", path),
            security_work_authorized=_bool_with_default(
                body, "securityWorkAuthorized", path, False
            ),
            usage=AccountUsage.from_json(body.get("usage"), f"{path}.usage"),
            reset_at_primary=_optional_timestamp(body, "resetAtPrimary", path),
            reset_at_secondary=_optional_timestamp(body, "resetAtSecondary", path),
            reset_at_monthly=_optional_timestamp(body, "resetAtMonthly", path),
            window_minutes_primary=_optional_integer(
                body, "windowMinutesPrimary", path, nonnegative=True
            ),
            window_minutes_secondary=_optional_integer(
                body, "windowMinutesSecondary", path, nonnegative=True
            ),
            window_minutes_monthly=_optional_integer(
                body, "windowMinutesMonthly", path, nonnegative=True
            ),
            last_refresh_at=_optional_timestamp(body, "lastRefreshAt", path),
            capacity_credits_primary=_optional_nonnegative_number(
                body, "capacityCreditsPrimary", path
            ),
            remaining_credits_primary=_optional_nonnegative_number(
                body, "remainingCreditsPrimary", path
            ),
            capacity_credits_secondary=_optional_nonnegative_number(
                body, "capacityCreditsSecondary", path
            ),
            remaining_credits_secondary=_optional_nonnegative_number(
                body, "remainingCreditsSecondary", path
            ),
            capacity_credits_monthly=_optional_nonnegative_number(
                body, "capacityCreditsMonthly", path
            ),
            remaining_credits_monthly=_optional_nonnegative_number(
                body, "remainingCreditsMonthly", path
            ),
            request_usage=RequestUsage.from_json(
                body.get("requestUsage"), f"{path}.requestUsage"
            ),
            additional_quotas=additional_quotas,
            credits_has=_optional_bool(body, "creditsHas", path),
            credits_unlimited=_optional_bool(body, "creditsUnlimited", path),
            credits_balance=_optional_number(body, "creditsBalance", path),
            deactivation_reason=_optional_string(body, "deactivationReason", path),
            auth=AccountAuthStatus.from_json(body.get("auth"), f"{path}.auth"),
            limit_warmup_enabled=_bool_with_default(
                body, "limitWarmupEnabled", path, False
            ),
            limit_warmup=WarmUpState.from_json(
                body.get("limitWarmup"), f"{path}.limitWarmup"
            ),
            is_email_duplicate=_bool_with_default(
                body, "isEmailDuplicate", path, False
            ),
            available_reset_credits=_integer_with_default(
                body, "availableResetCredits", path, 0, nonnegative=True
            ),
            reset_credit_nearest_expires_at=_optional_timestamp(
                body, "resetCreditNearestExpiresAt", path
            ),
        )
        for window in ("primary", "secondary", "monthly"):
            capacity = getattr(account, f"capacity_credits_{window}")
            remaining = getattr(account, f"remaining_credits_{window}")
            if remaining is not None and capacity is None:
                raise ContractError(
                    f"{path}.remainingCredits{window.title()} requires "
                    f"capacityCredits{window.title()}"
                )
            if capacity is not None and remaining is not None and remaining > capacity:
                raise ContractError(
                    f"{path}.remainingCredits{window.title()} must not exceed "
                    f"capacityCredits{window.title()}"
                )
        return account


@dataclass(frozen=True, slots=True)
class AccountsResponse:
    accounts: tuple[AccountSummary, ...]

    @classmethod
    def from_json(cls, value: Any) -> AccountsResponse:
        body = _object(value, "response")
        raw_accounts = body.get("accounts")
        if not isinstance(raw_accounts, list):
            raise ContractError("response.accounts must be an array")
        return cls(
            accounts=tuple(
                AccountSummary.from_json(account, index)
                for index, account in enumerate(raw_accounts)
            )
        )


class ApplicationStateKind(StrEnum):
    LOADING = "loading"
    READY = "ready"
    EMPTY = "empty"
    STALE = "stale"
    LOGIN_REQUIRED = "login-required"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ApplicationState:
    kind: ApplicationStateKind
    accounts: tuple[AccountSummary, ...] = ()
    refreshed_at: datetime | None = None
    server_version: str | None = None
    error_message: str | None = None
    session: DashboardSession | None = None

    @classmethod
    def loading(cls) -> ApplicationState:
        return cls(ApplicationStateKind.LOADING)

    @property
    def has_data(self) -> bool:
        return self.refreshed_at is not None or bool(self.accounts)


def parse_accounts_response(value: Any) -> AccountsResponse:
    """Decode the camelCase accounts response, ignoring unknown fields."""

    return AccountsResponse.from_json(value)


def parse_dashboard_session(value: Any) -> DashboardSession:
    """Decode the dashboard session response, ignoring unknown fields."""

    return DashboardSession.from_json(value)


__all__ = [
    "ACCOUNT_ROUTING_POLICIES",
    "ACCOUNT_STATUSES",
    "ADDITIONAL_QUOTA_ROUTING_POLICIES",
    "DASHBOARD_AUTH_MODES",
    "DASHBOARD_PERMISSIONS",
    "DASHBOARD_ROLES",
    "AccountAdditionalQuota",
    "AccountAdditionalWindow",
    "AccountAuthStatus",
    "AccountSummary",
    "AccountTokenStatus",
    "AccountUsage",
    "AccountsResponse",
    "ApplicationState",
    "ApplicationStateKind",
    "ContractError",
    "DashboardSession",
    "RequestUsage",
    "WarmUpState",
    "parse_accounts_response",
    "parse_dashboard_session",
    "parse_iso8601",
]
