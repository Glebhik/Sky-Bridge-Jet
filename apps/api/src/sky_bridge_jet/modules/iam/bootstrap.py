"""One-time CLI to establish the first platform Product Owner.

Run:  ``uv run python -m sky_bridge_jet.modules.iam.bootstrap --email owner@example.com``

The password is read from the ``SBJ_BOOTSTRAP_PASSWORD`` environment variable or an
interactive prompt — never a command-line argument (shell history) and never a
committed default. The command refuses to run once a Product Owner exists, so it
cannot be used to mint additional superusers. This is intentionally NOT an HTTP
endpoint: there is no unauthenticated "make me admin" route.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys

from sky_bridge_jet.db.session import SessionLocal
from sky_bridge_jet.modules.iam.domain import IamError
from sky_bridge_jet.modules.iam.services import bootstrap_product_owner


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bootstrap the first Sky Bridge Jet product owner")
    parser.add_argument("--email", required=True, help="Product owner email address")
    parser.add_argument("--display-name", default=None, help="Optional display name")
    args = parser.parse_args(argv)

    password = os.environ.get("SBJ_BOOTSTRAP_PASSWORD")
    if not password:
        password = getpass.getpass("Product owner password: ")

    try:
        with SessionLocal() as session:
            user, org = bootstrap_product_owner(
                session, email=args.email, password=password, display_name=args.display_name
            )
    except IamError as error:
        # Never echo the password; only a safe message.
        print(f"Bootstrap failed: {error}", file=sys.stderr)
        return 1

    print(f"Product owner created: user={user.id} organization={org.id}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
