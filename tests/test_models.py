"""Contract and domain-model coverage."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from codex_lb_status.models import (
    AccountUsage,
    ContractError,
    parse_accounts_response,
    parse_dashboard_session,
    parse_iso8601,
)


def account_json(**overrides: object) -> dict[str, object]:
    account: dict[str, object] = {
        "accountId": "acc-1",
        "chatgptAccountId": "chatgpt-1",
        "email": "codex@example.com",
        "alias": "Primary",
        "displayName": "Codex Account",
        "workspaceId": "workspace-1",
        "workspaceLabel": "Engineering",
        "seatType": "member",
        "planType": "plus",
        "routingPolicy": "burn_first",
        "status": "active",
        "securityWorkAuthorized": True,
        "usage": {
            "primaryRemainingPercent": 86,
            "secondaryRemainingPercent": 37,
            "monthlyRemainingPercent": 50,
        },
        "resetAtPrimary": "2026-08-21T14:30:00.123Z",
        "resetAtSecondary": "2026-08-25T12:00:00+02:00",
        "resetAtMonthly": "2026-09-01T00:00:00Z",
        "windowMinutesPrimary": 300,
        "windowMinutesSecondary": 10080,
        "windowMinutesMonthly": 43200,
        "lastRefreshAt": "2026-08-21T12:00:00Z",
        "capacityCreditsPrimary": 100,
        "remainingCreditsPrimary": 86,
        "capacityCreditsSecondary": 200,
        "remainingCreditsSecondary": 74,
        "capacityCreditsMonthly": 300,
        "remainingCreditsMonthly": 150,
        "requestUsage": {
            "requestCount": 12,
            "totalTokens": 3456,
            "cachedInputTokens": 789,
            "totalCostUsd": 1.25,
        },
        "additionalQuotas": [
            {
                "quotaKey": "codex_spark",
                "limitName": "GPT-5.3-Codex-Spark",
                "meteredFeature": "codex_bengalfox",
                "displayLabel": "Codex Spark",
                "routingPolicy": "preserve",
                "primaryWindow": {
                    "usedPercent": 25,
                    "resetAt": 1_800_000_000,
                    "windowMinutes": 300,
                },
                "secondaryWindow": {
                    "usedPercent": 40,
                    "resetAt": None,
                    "windowMinutes": 10080,
                },
            }
        ],
        "creditsHas": True,
        "creditsUnlimited": False,
        "creditsBalance": 20.5,
        "deactivationReason": None,
        "auth": {
            "access": {"expiresAt": "2026-08-22T12:00:00Z", "state": None},
            "refresh": {"expiresAt": None, "state": "stored"},
            "idToken": {"state": "parsed"},
        },
        "limitWarmupEnabled": True,
        "limitWarmup": {
            "window": "primary",
            "resetAt": 1_800_000_000,
            "status": "failed",
            "model": "gpt-5.3-codex",
            "attemptedAt": "2026-08-21T11:00:00Z",
            "completedAt": "2026-08-21T11:01:00Z",
            "errorCode": "upstream_error",
            "errorMessage": "temporary failure",
        },
        "isEmailDuplicate": True,
        "availableResetCredits": 3,
        "resetCreditNearestExpiresAt": "2026-08-30T00:00:00Z",
        "unknownFutureField": {"safe": True},
    }
    account.update(overrides)
    return account


def session_json(**overrides: object) -> dict[str, object]:
    session: dict[str, object] = {
        "authenticated": True,
        "passwordRequired": True,
        "totpRequiredOnLogin": False,
        "totpConfigured": True,
        "bootstrapRequired": False,
        "bootstrapTokenConfigured": True,
        "authMode": "trusted_header",
        "passwordManagementEnabled": True,
        "passwordSessionActive": False,
        "role": "admin",
        "permissions": ["read", "write"],
        "guestAccessEnabled": True,
        "guestPasswordRequired": True,
        "unknownFutureField": True,
    }
    session.update(overrides)
    return session


def test_complete_current_account_contract_is_decoded() -> None:
    parsed = parse_accounts_response(
        {"accounts": [account_json()], "lastSyncAt": "not-an-api-field"}
    )
    account = parsed.accounts[0]
    assert account.account_id == "acc-1"
    assert account.chatgpt_account_id == "chatgpt-1"
    assert account.workspace_id == "workspace-1"
    assert account.workspace_label == "Engineering"
    assert account.seat_type == "member"
    assert account.security_work_authorized is True
    assert account.usage is not None
    assert account.usage.primary_remaining_percent == 86
    assert account.reset_at_secondary == datetime(2026, 8, 25, 10, tzinfo=UTC)
    assert account.window_minutes_monthly == 43200
    assert account.capacity_credits_secondary == 200
    assert account.remaining_credits_monthly == 150
    assert account.request_usage is not None
    assert account.request_usage.cached_input_tokens == 789
    assert account.additional_quotas[0].primary_window is not None
    assert account.additional_quotas[0].primary_window.used_percent == 25
    assert account.credits_has is True
    assert account.credits_unlimited is False
    assert account.credits_balance == 20.5
    assert account.auth is not None
    assert account.auth.refresh is not None
    assert account.auth.refresh.state == "stored"
    assert account.limit_warmup is not None
    assert account.limit_warmup.reset_at == 1_800_000_000
    assert account.limit_warmup.error_code == "upstream_error"
    assert account.limit_warmup.error_message == "temporary failure"
    assert account.is_email_duplicate is True
    assert account.available_reset_credits == 3
    assert not hasattr(account, "provider")
    assert not hasattr(parsed, "last_sync_at")


def test_complete_dashboard_session_contract_is_decoded() -> None:
    session = parse_dashboard_session(session_json())
    assert session.authenticated is True
    assert session.password_required is True
    assert session.totp_configured is True
    assert session.bootstrap_token_configured is True
    assert session.auth_mode == "trusted_header"
    assert session.password_management_enabled is True
    assert session.password_session_active is False
    assert session.role == "admin"
    assert session.permissions == ("read", "write")
    assert session.guest_password_required is True


def test_session_schema_defaults_match_upstream_defaults() -> None:
    session = parse_dashboard_session(
        {
            "authenticated": False,
            "passwordRequired": True,
            "totpRequiredOnLogin": False,
            "totpConfigured": False,
        }
    )
    assert session.auth_mode == "standard"
    assert session.role == "admin"
    assert session.permissions == ("read", "write")
    assert session.password_management_enabled is True


def test_accounts_must_be_an_array() -> None:
    with pytest.raises(ContractError, match="accounts must be an array"):
        parse_accounts_response({"accounts": {}})


def test_required_account_fields_are_validated() -> None:
    malformed = account_json()
    malformed.pop("email")
    with pytest.raises(ContractError, match="email"):
        parse_accounts_response({"accounts": [malformed]})


def test_optional_routing_policy_defaults_to_normal() -> None:
    account = account_json()
    account.pop("routingPolicy")
    parsed = parse_accounts_response({"accounts": [account]})
    assert parsed.accounts[0].routing_policy == "normal"


@pytest.mark.parametrize(
    "value",
    ["bad", float("nan"), float("inf"), True, -0.1, 100.1],
)
def test_invalid_percentages_are_rejected(value: object) -> None:
    with pytest.raises(ContractError, match="primaryRemainingPercent"):
        AccountUsage.from_json({"primaryRemainingPercent": value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "offline"),
        ("routingPolicy", "random"),
        ("securityWorkAuthorized", 1),
        ("limitWarmupEnabled", "yes"),
        ("isEmailDuplicate", 0),
        ("windowMinutesPrimary", 300.0),
        ("availableResetCredits", 1.5),
        ("capacityCreditsPrimary", float("nan")),
    ],
)
def test_invalid_account_enum_and_scalar_values_are_rejected(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ContractError, match=field):
        parse_accounts_response({"accounts": [account_json(**{field: value})]})


def test_invalid_nested_values_are_rejected() -> None:
    with pytest.raises(ContractError, match="cachedInputTokens"):
        parse_accounts_response(
            {
                "accounts": [
                    account_json(
                        requestUsage={
                            "requestCount": 1,
                            "totalTokens": 2,
                            "cachedInputTokens": 3.0,
                            "totalCostUsd": 4,
                        }
                    )
                ]
            }
        )
    with pytest.raises(ContractError, match="additionalQuotas"):
        parse_accounts_response(
            {"accounts": [account_json(additionalQuotas="invalid")]}
        )
    with pytest.raises(ContractError, match="routingPolicy"):
        parse_accounts_response(
            {
                "accounts": [
                    account_json(
                        additionalQuotas=[
                            {
                                "limitName": "Extra",
                                "meteredFeature": "extra",
                                "routingPolicy": "random",
                            }
                        ]
                    )
                ]
            }
        )


def test_credit_pairs_are_consistent() -> None:
    with pytest.raises(ContractError, match="requires capacity"):
        parse_accounts_response(
            {
                "accounts": [
                    account_json(
                        capacityCreditsPrimary=None,
                        remainingCreditsPrimary=10,
                    )
                ]
            }
        )
    with pytest.raises(ContractError, match="must not exceed"):
        parse_accounts_response(
            {
                "accounts": [
                    account_json(
                        capacityCreditsPrimary=10,
                        remainingCreditsPrimary=11,
                    )
                ]
            }
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("authenticated", 1),
        ("passwordRequired", "yes"),
        ("authMode", "proxy"),
        ("role", "operator"),
        ("permissions", "read"),
        ("permissions", ["delete"]),
        ("permissions", ["read", "read"]),
    ],
)
def test_invalid_session_values_are_rejected(field: str, value: object) -> None:
    with pytest.raises(ContractError, match=field):
        parse_dashboard_session(session_json(**{field: value}))


def test_malformed_optional_objects_and_timestamps_are_rejected() -> None:
    with pytest.raises(ContractError, match="usage must be an object"):
        parse_accounts_response({"accounts": [account_json(usage="invalid")]})
    with pytest.raises(ContractError, match="resetAtPrimary"):
        parse_accounts_response(
            {"accounts": [account_json(resetAtPrimary="not-a-date")]}
        )
    with pytest.raises(ContractError, match="attemptedAt"):
        warmup = dict(account_json()["limitWarmup"])
        warmup["attemptedAt"] = "not-a-date"
        parse_accounts_response({"accounts": [account_json(limitWarmup=warmup)]})


def test_optional_objects_and_nullable_fields_can_be_absent() -> None:
    parsed = parse_accounts_response(
        {
            "accounts": [
                account_json(
                    usage=None,
                    requestUsage=None,
                    additionalQuotas=[],
                    auth=None,
                    limitWarmup=None,
                    alias="",
                )
            ]
        }
    ).accounts[0]
    assert parsed.usage is None
    assert parsed.request_usage is None
    assert parsed.additional_quotas == ()
    assert parsed.auth is None
    assert parsed.limit_warmup is None
    assert parsed.alias is None


@pytest.mark.parametrize(
    "value",
    [
        "2026-08-21T14:30:00Z",
        "2026-08-21T14:30:00.123456Z",
        "2026-08-21T14:30:00+02:00",
    ],
)
def test_iso8601_timestamp_variants_are_accepted(value: str) -> None:
    parsed = parse_iso8601(value)
    assert parsed is not None
    assert parsed.tzinfo is UTC


def test_invalid_timestamp_is_unavailable() -> None:
    assert parse_iso8601("not a timestamp") is None
