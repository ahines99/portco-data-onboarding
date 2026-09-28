"""Verify an authorized synthetic live deployment without printing or persisting tokens.

Set PORTCO_SMOKE_TOKEN to an agent access token. Optional --complete-synthetic also
requires PORTCO_SMOKE_REVIEWER_TOKEN and performs explicitly automated synthetic review.
No restart, database restore or cloud resource creation is performed by this script.
"""

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx2

from scripts.smoke_container import check, complete


async def probe(base: str, token: str, reviewer: str | None = None) -> dict:
    url = urlsplit(base)
    if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError("base must be the public HTTPS origin without credentials, query or fragment")
    base = base.rstrip("/")
    async with httpx2.AsyncClient(timeout=15, follow_redirects=False) as http:
        ready = await http.get(base + "/readyz")
        if ready.status_code != 200 or ready.json() != {"status": "ready"}:
            raise RuntimeError("service is not ready")
        metadata = await http.get(base + "/.well-known/oauth-protected-resource")
        if metadata.status_code != 200 or metadata.json().get("resource") != base:
            raise RuntimeError("protected resource metadata does not match the requested service")
    run = await check(base, token)
    if run["gate"] != "mapping_review":
        raise RuntimeError("synthetic run did not stop at mapping review")
    result = {
        "checked_at": datetime.now(UTC).isoformat(),
        "base_url": base,
        "run_id": run["run_id"],
        "anonymous_and_invalid_tokens_denied": True,
        "readiness": "ready",
        "gate": run["gate"],
        "review_method": "none",
    }
    if reviewer:
        publication = await complete(base, token, reviewer, run)
        result.update(
            review_method="automated synthetic smoke reviewer; not independent human review",
            gate="complete",
            published_metrics=publication["published_metrics"],
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--out", type=Path, default=Path("var/live-smoke.json"))
    parser.add_argument("--complete-synthetic", action="store_true")
    args = parser.parse_args()
    token = os.environ.get("PORTCO_SMOKE_TOKEN")
    reviewer = os.environ.get("PORTCO_SMOKE_REVIEWER_TOKEN") if args.complete_synthetic else None
    if not token or (args.complete_synthetic and not reviewer):
        parser.error("required access tokens must be supplied through the environment, never command arguments")
    result = asyncio.run(probe(args.base, token, reviewer))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"PASS: synthetic live smoke; evidence saved to {args.out}")


if __name__ == "__main__":
    main()
