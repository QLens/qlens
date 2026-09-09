"""KeyCall preflight for the shiplock semantic audit.

The audit is billable, so this runs first and gates it: it validates the
audit keys and confirms the primary model is in its provider's catalogue
through KeyCall, failing fast before a cent is spent on a bad key or a
retired model id.

Reads two secrets in shiplock's ``provider/key`` form from the environment:

    AUDIT_API_KEY           the primary key, e.g. ``openai/sk-...``
    AUDIT_FALLBACK_API_KEY  the fallback key, e.g. ``anthropic/sk-ant-...``

and the model ids the workflow declares (``AUDIT_MODEL``,
``AUDIT_FALLBACK_MODEL``). KeyCall wraps keys in a redacting type, so no key
reaches stdout, a log, or a trace. Exit 0 when every set key validates and
the primary model is present; exit 1 on any hard failure.

An unset key is not a failure: the audit skips that attempt on its own, and
fork pull requests never receive the secrets.
"""

from __future__ import annotations

import os
import sys

from keycall import KeyCall, ModelCategory


def _split(raw: str) -> tuple[str, str]:
    provider, _, key = raw.partition("/")
    return provider.strip().lower(), key.strip()


def _model_present(want: str, ids: set[str]) -> bool:
    return any(mid == want or mid.startswith(want) for mid in ids)


def _check(label: str, raw: str, want_model: str, *, hard_model: bool) -> bool:
    if not raw:
        print(f"{label}: no key set, skipping")
        return True
    provider, key = _split(raw)
    if not provider or not key:
        print(f"{label}: malformed secret, expected 'provider/key'")
        return False
    try:
        with KeyCall(provider=provider, api_key=key) as client:
            discovery = client.list_models(categories={ModelCategory.TEXT_GENERATION})
    except Exception as failure:  # noqa: BLE001 - any failure means "don't run the audit"
        print(f"{label}: {provider} key did not validate ({type(failure).__name__})")
        return False

    ids = {model.id for model in discovery.models}
    print(f"{label}: {provider} key valid, {len(ids)} text models listed")
    if not want_model:
        return True
    if _model_present(want_model, ids):
        print(f"{label}: model '{want_model}' is in the catalogue")
        return True
    if hard_model:
        print(f"{label}: model '{want_model}' is not in the {provider} catalogue")
        return False
    print(f"{label}: model '{want_model}' not matched by id (an alias?); key is valid")
    return True


def main() -> int:
    ok = _check(
        "primary",
        os.environ.get("AUDIT_API_KEY", ""),
        os.environ.get("AUDIT_MODEL", ""),
        hard_model=True,
    )
    ok = _check(
        "fallback",
        os.environ.get("AUDIT_FALLBACK_API_KEY", ""),
        os.environ.get("AUDIT_FALLBACK_MODEL", ""),
        hard_model=False,
    ) and ok
    print("preflight OK" if ok else "preflight FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
