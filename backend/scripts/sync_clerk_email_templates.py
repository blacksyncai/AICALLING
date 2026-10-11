"""
Push BlackSync-branded sign-in emails to Clerk (codes, sign-in links, invitations).

    CLERK_SECRET_KEY=sk_... python -m scripts.sync_clerk_email_templates           # preview + update
    CLERK_SECRET_KEY=sk_... python -m scripts.sync_clerk_email_templates --check   # preview only
    CLERK_SECRET_KEY=sk_... python -m scripts.sync_clerk_email_templates --revert  # back to Clerk's defaults

Each template is first sent to Clerk's preview endpoint (which validates the
variables) and only then saved. Bodies come from app/services/email_templates.py.
"""

from __future__ import annotations

import os
import sys

import httpx

from app.services.email_templates import clerk_templates

API = "https://api.clerk.com/v1/templates/email"


def main() -> int:
    key = os.environ.get("CLERK_SECRET_KEY", "")
    if not key:
        print("Set CLERK_SECRET_KEY")
        return 1
    h = {"Authorization": f"Bearer {key}"}
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    failed = 0
    with httpx.Client(timeout=20, headers=h) as c:
        for slug, t in clerk_templates().items():
            if mode == "--revert":
                r = c.post(f"{API}/{slug}/revert")
                print(f"{slug}: revert {r.status_code}")
                continue
            current = c.get(f"{API}/{slug}").json()
            pv = c.post(f"{API}/{slug}/preview", json={"subject": t["subject"], "body": t["body"]})
            if pv.status_code >= 300:
                print(f"{slug}: preview failed {pv.status_code} {pv.text[:300]}")
                failed += 1
                continue
            if mode == "--check":
                print(f"{slug}: preview ok")
                continue
            r = c.put(f"{API}/{slug}", json={
                "name": current.get("name") or slug, "subject": t["subject"], "body": t["body"],
                "delivered_by_clerk": True, "from_email_name": current.get("from_email_name") or None,
            })
            ok = r.status_code < 300
            failed += not ok
            print(f"{slug}: {'updated' if ok else f'update failed {r.status_code} {r.text[:300]}'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
