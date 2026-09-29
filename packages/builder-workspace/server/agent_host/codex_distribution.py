"""Versioned AG-023 policy for acquiring the Codex App Server runtime.

This module is deliberately declarative.  AG-023 decides which sources XACE may
trust; AG-024 owns all download, install, update, repair, rollback, and removal
behavior.  Importing this module must never inspect credentials or touch the
network/filesystem.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


CODEX_DISTRIBUTION_POLICY_SCHEMA = "xace.codex_distribution_policy.v1"
CODEX_DISTRIBUTION_DECISION_ID = "ADR-0023"
CODEX_DISTRIBUTION_DECISION_DATE = "2026-09-18"
CODEX_DISTRIBUTION_ADR = "docs/adr/ADR-0023-CODEX-RUNTIME-DISTRIBUTION.md"
CODEX_MANAGED_RUNTIME_SOURCE = "official_pinned_python_sdk_runtime"
CODEX_EXTERNAL_RUNTIME_SOURCE = "official_external_cli"


_POLICY: dict[str, Any] = {
    "schema": CODEX_DISTRIBUTION_POLICY_SCHEMA,
    "decision_id": CODEX_DISTRIBUTION_DECISION_ID,
    "decision_date": CODEX_DISTRIBUTION_DECISION_DATE,
    "decision_status": "complete_guided_lifecycle_ag024",
    "owner": "xace_agent_integration_maintainers",
    "acquisition_model": "xace_managed_official_package_acquisition",
    "preferred_runtime_source": CODEX_MANAGED_RUNTIME_SOURCE,
    "current_runtime_lifecycle": {
        "mode": "guided_official_external_install",
        "status": "complete",
        "operator_entry_point": "tools/codex_runtime.py",
        "provenance_basis": "user_confirmed_official_install",
        "vendor_signature_verified": False,
        "pin_scope": "machine_local_integrity_and_generated_schema",
        "automatic_install": False,
        "ui_setup_owner": "AG-026",
    },
    "app_server_integration": "direct_stdio_jsonrpc",
    "official_package": {
        "name": "openai-codex",
        "ecosystem": "python",
        "channel": "official_openai_documented_stable_sdk",
        "minimum_python": "3.10",
        "version_policy": "exact_certified_pin",
        "prerelease_allowed": False,
        "includes_pinned_codex_runtime": True,
        "runtime_override_allowed": False,
    },
    "redistribution": {
        "bundling_allowed": False,
        "raw_binary_redistribution_allowed": False,
        "repackaging_allowed": False,
        "permission_basis": "not_relied_upon_managed_acquisition_only",
        "automatic_acquisition_enabled": False,
        "implementation_owner": "AG-024",
    },
    "integrity": {
        "artifact_policy": "official_package_exact_pin_and_sha256_lock",
        "vendor_signature_status": "not_documented_in_official_openai_docs",
        "verify_package_hash": True,
        "verify_runtime_version": True,
        "verify_app_server_schema": True,
        "fail_closed_on_missing_integrity_evidence": True,
    },
    "authentication": {
        "owner": "codex_provider",
        "xace_reads_credentials": False,
        "xace_copies_auth_cache": False,
        "xace_persists_credentials": False,
        "managed_credential_store": "os_keyring",
        "keyring_unavailable_behavior": "guided_external_install_or_api_byok",
    },
    "supported_sources": [
        {
            "source": CODEX_MANAGED_RUNTIME_SOURCE,
            "support_tier": "preferred_production_after_ag024",
            "acquisition": "official_openai_python_package",
        },
        {
            "source": CODEX_EXTERNAL_RUNTIME_SOURCE,
            "support_tier": "supported_fallback_after_compatibility_probe",
            "acquisition": "user_installed_official_channel",
        },
        {
            "source": "custom_path",
            "support_tier": "development_or_test_only",
            "acquisition": "operator_supplied",
        },
        {
            "source": "host_extension_private",
            "support_tier": "development_fallback_only",
            "acquisition": "never_copy_or_modify",
        },
    ],
    "platform_policy": {
        "allowlist_required": True,
        "artifact_matrix_status": "managed_acquisition_deferred_no_supported_launch_surface",
        "unsupported_behavior": "guided_external_install_or_api_byok",
    },
    "updates": {
        "owner": "xace_agent_integration_maintainers",
        "automatic_unpinned_updates": False,
        "security_review_sla_days": 7,
        "standard_compatibility_review_sla_days": 30,
        "last_known_good_required": True,
        "user_consent_required": True,
    },
    "compatibility": {
        "profile": "xace.codex_app_server_contract.v1",
        "candidate_version_range": ">=0.143.0,<0.155.0",
        "requires_consumed_schema_match": True,
        "real_account_certified_versions": [],
        "deprecation_notice_days": 30,
        "security_revocation_grace_days": 0,
        "automatic_turn_replay": False,
    },
    "revocation": {
        "machine_readable_blocklist_required": True,
        "revoked_sha256": [],
        "revoked_versions": [],
        "revoked_runtime_behavior": "disable_agent_mode_and_offer_api_byok",
        "fallback_requires_compatibility_probe": True,
    },
    "external_detection_enabled": True,
    "fallback_mode": "api_byok",
    "unresolved_constraints": [
        "certified_platform_artifact_matrix",
        "supported_sdk_runtime_launch_surface",
        "vendor_signature_not_documented",
    ],
    "adr": CODEX_DISTRIBUTION_ADR,
}


def codex_distribution_policy() -> dict[str, Any]:
    """Return a detached JSON-compatible policy payload."""

    payload = deepcopy(_POLICY)
    validate_codex_distribution_policy(payload)
    return payload


def validate_codex_distribution_policy(policy: dict[str, Any]) -> None:
    """Fail closed if a caller weakens an AG-023 safety decision."""

    if policy.get("schema") != CODEX_DISTRIBUTION_POLICY_SCHEMA:
        raise ValueError("Unsupported Codex distribution policy schema")
    redistribution = dict(policy.get("redistribution") or {})
    if redistribution.get("bundling_allowed") is not False:
        raise ValueError("Codex bundling is not approved by AG-023")
    if redistribution.get("raw_binary_redistribution_allowed") is not False:
        raise ValueError("Raw Codex binary redistribution is not approved")
    if redistribution.get("automatic_acquisition_enabled") is not False:
        raise ValueError("AG-024 must implement and certify acquisition first")
    package = dict(policy.get("official_package") or {})
    if package.get("name") != "openai-codex":
        raise ValueError("Only the official documented Codex SDK package is allowed")
    if package.get("version_policy") != "exact_certified_pin":
        raise ValueError("Managed Codex must use an exact certified pin")
    auth = dict(policy.get("authentication") or {})
    if auth.get("owner") != "codex_provider":
        raise ValueError("Codex must own its authentication lifecycle")
    for field in ("xace_reads_credentials", "xace_copies_auth_cache", "xace_persists_credentials"):
        if auth.get(field) is not False:
            raise ValueError(f"Credential boundary weakened: {field}")
    if policy.get("fallback_mode") != "api_byok":
        raise ValueError("API/BYOK fallback is mandatory")


__all__ = [
    "CODEX_DISTRIBUTION_ADR",
    "CODEX_DISTRIBUTION_DECISION_DATE",
    "CODEX_DISTRIBUTION_DECISION_ID",
    "CODEX_DISTRIBUTION_POLICY_SCHEMA",
    "CODEX_EXTERNAL_RUNTIME_SOURCE",
    "CODEX_MANAGED_RUNTIME_SOURCE",
    "codex_distribution_policy",
    "validate_codex_distribution_policy",
]
