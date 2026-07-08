"""Rotate the LLM API Key encryption secret (security Task E).

Re-encrypts every ``user_llm_configs.api_key_encrypted`` from the old
``LLM_CONFIG_SECRET_KEY`` to a new one, so a suspected-compromised key
can be rotated without losing stored API keys.

Usage:
    # Dry-run: report how many configs would be affected.
    python scripts/rotate_llm_config_secret.py --old-secret OLD --new-secret NEW --dry-run

    # Apply: re-encrypt in place.
    python scripts/rotate_llm_config_secret.py --old-secret OLD --new-secret NEW --apply

After a successful --apply, update backend/.env (or the deployment env)
to set ``LLM_CONFIG_SECRET_KEY=<new-secret>`` so the app decrypts with
the new key going forward.

To generate a strong Fernet key:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
import argparse
import sys
from pathlib import Path

# Ensure the backend package is importable when run from the repo root.
BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.database import SessionLocal  # noqa: E402
from app.services.llm_config_security import rotate_llm_config_secret  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rotate the LLM API Key encryption secret."
    )
    parser.add_argument(
        "--old-secret",
        required=True,
        help="The current LLM_CONFIG_SECRET_KEY used to decrypt existing keys.",
    )
    parser.add_argument(
        "--new-secret",
        required=True,
        help="The new LLM_CONFIG_SECRET_KEY to re-encrypt keys with.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--dry-run",
        action="store_true",
        help="Report the affected count without modifying anything.",
    )
    group.add_argument(
        "--apply",
        action="store_true",
        help="Re-encrypt and persist the new ciphertexts.",
    )
    args = parser.parse_args()

    if args.old_secret == args.new_secret:
        print("ERROR: --old-secret and --new-secret must differ.", file=sys.stderr)
        return 2

    db = SessionLocal()
    try:
        report = rotate_llm_config_secret(
            db,
            old_secret=args.old_secret,
            new_secret=args.new_secret,
            apply=args.apply,
        )
    finally:
        db.close()

    mode = "APPLIED" if report.applied else "DRY-RUN"
    print(f"[{mode}] LLM API Key rotation report:")
    print(f"  affected  (total configs): {report.affected}")
    print(f"  reencrypted (success):     {report.reencrypted}")
    print(f"  failed (could not decrypt): {report.failed}")

    if report.failed > 0:
        print(
            "WARNING: some configs could not be decrypted with --old-secret. "
            "They were left untouched. Investigate before re-running.",
            file=sys.stderr,
        )

    if not report.applied:
        print(
            "\nThis was a dry-run. Re-run with --apply to re-encrypt in place, "
            "then update LLM_CONFIG_SECRET_KEY in your environment to the new secret."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
