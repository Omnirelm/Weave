#!/usr/bin/env python3
"""Mint a tenant API key (plaintext printed once on stdout).

**Production / no DB access:** use ``--print-only`` — nothing is written to the database;
you get a SQL ``INSERT`` on stderr to run manually (same pepper as the running service).

**Local:** omit ``--print-only`` to insert via the app storage layer (needs DB URL).

From the **orchestrator** directory:

  uv run python scripts/mint_api_key.py -p my-tenant-slug
  ORCHESTRATOR_AUTH__API_KEY_PEPPER=... uv run python scripts/mint_api_key.py -p my-tenant-slug

  uv run python scripts/mint_api_key.py my-tenant-slug   # inserts row (needs DATABASE URL)
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    import sqlalchemy  # noqa: F401
except ModuleNotFoundError:
    sys.stderr.write(
        "Missing dependencies (e.g. sqlalchemy). Use the orchestrator venv, not system python.\n"
        "From the orchestrator directory:\n"
        "  uv sync && uv run python scripts/mint_api_key.py -p <tenant_slug>\n"
        "Or: source .venv/bin/activate && python scripts/mint_api_key.py -p <tenant_slug>\n"
    )
    raise SystemExit(1) from None

from src.config.settings import get_config
from src.security import hash_api_key, key_prefix
from src.storage import get_storage


def _sql_string_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _emit_print_only(tenant_slug: str, *, secret: str, key_prefix_val: str, key_hash: str) -> None:
    t, pre, h = (
        _sql_string_literal(tenant_slug),
        _sql_string_literal(key_prefix_val),
        _sql_string_literal(key_hash),
    )
    sql = (
        "INSERT INTO tenant_api_keys (tenant_slug, key_prefix, key_hash)\n"
        f"VALUES ({t}, {pre}, {h});\n"
    )
    print(
        "Copy/paste into psql (or your SQL client). id/created_at use table defaults.\n",
        file=sys.stderr,
    )
    print(sql, file=sys.stderr, end="")
    print("\nColumns (for spreadsheets / other tools):", file=sys.stderr)
    print(f"  tenant_slug={tenant_slug!r}", file=sys.stderr)
    print(f"  key_prefix={key_prefix_val!r}", file=sys.stderr)
    print(f"  key_hash={key_hash!r}", file=sys.stderr)


async def _run(tenant_slug: str, *, print_only: bool) -> int:
    secret = f"wv_sk_v1.{secrets.token_urlsafe(32)}"
    prefix = key_prefix(secret)
    config = get_config()
    digest = hash_api_key(secret, config.auth.api_key_pepper)
    if print_only:
        _emit_print_only(tenant_slug, secret=secret, key_prefix_val=prefix, key_hash=digest)
    else:
        storage = get_storage()
        await storage.api_keys.create_key(
            tenant_slug=tenant_slug,
            key_prefix=prefix,
            key_hash=digest,
        )
    print("API key (save now; shown once):", file=sys.stderr)
    print(secret)
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="Mint a hashed API key for a tenant.")
    p.add_argument("tenant_slug", help="Existing tenants.slug value")
    p.add_argument(
        "-p",
        "--print-only",
        action="store_true",
        help="Do not connect to the DB; print a manual INSERT on stderr",
    )
    args = p.parse_args()
    raise SystemExit(asyncio.run(_run(args.tenant_slug, print_only=args.print_only)))


if __name__ == "__main__":
    main()
