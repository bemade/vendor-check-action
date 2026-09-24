#!/usr/bin/env python3
# Copyright 2026 Bemade Inc.
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).
"""Fail a pull request that edits a vendored addon without re-pinning it.

Consumer-side counterpart of vendor-autotag-action. A project that vendors
shared addons keeps real files under ``vendored/<addon>/`` and pins each one
in ``addons.lock``. ``vendored/`` is generated (``odoo-dev vendor bump``), so a
change to ``vendored/<addon>/`` is only legitimate when the same pull request
also changes that addon's lock entry. A hand edit, which the lock no longer
describes, is what this rejects: the next bump silently discards it.

Offline: git only, no access to the addons' source repositories. It cannot
prove a vendored tree matches its pinned commit (``odoo-dev vendor check``
does that); it stops new drift from being introduced.

Env: ``GITHUB_WORKSPACE`` (repo path), ``BASE_SHA`` / ``HEAD_SHA`` (the pull
request's base and head; empty outside a pull request, which skips the
check), ``LOCK_FILE`` (default ``addons.lock``), ``VENDORED_DIR`` (default
``vendored``).
"""
from __future__ import annotations

import os
import subprocess
import sys


def _git(repo: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True
    )


def parse_lock(text: str) -> dict[str, dict[str, str]]:
    """Parse ``addons.lock``: a top-level ``<addon>:`` key per addon, each
    followed by indented ``key: value`` lines. Stdlib only, by design."""
    entries: dict[str, dict[str, str]] = {}
    current = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if not line[0].isspace():
            key, _, value = line.partition(":")
            current = None if value.strip() else key.strip().strip("'\"")
            if current is not None:
                entries[current] = {}
        elif current is not None and ":" in line:
            key, _, value = line.strip().partition(":")
            entries[current][key.strip()] = value.strip().strip("'\"")
    return entries


def lock_at(repo: str, sha: str, lock_file: str) -> dict[str, dict[str, str]]:
    shown = _git(repo, "show", f"{sha}:{lock_file}")
    return parse_lock(shown.stdout) if shown.returncode == 0 else {}


def ensure_merge_base(repo: str, base: str, head: str) -> str:
    """Merge base of the pull request, fetching history a shallow checkout
    lacks."""
    for attempt in range(3):
        mb = _git(repo, "merge-base", base, head)
        if mb.returncode == 0:
            return mb.stdout.strip()
        if attempt == 0:
            _git(repo, "fetch", "--no-tags", "origin", base, head)
        elif _git(repo, "rev-parse", "--is-shallow-repository").stdout.strip() == "true":
            _git(repo, "fetch", "--no-tags", "--unshallow", "origin")
    raise SystemExit(
        f"vendor-check: no merge base between {base} and {head}; check out "
        "with fetch-depth: 0"
    )


def touched_addons(repo: str, since: str, head: str, vendored_dir: str) -> dict[str, list[str]]:
    """Vendored addons changed between two commits, with their changed paths."""
    prefix = vendored_dir.strip("/") + "/"
    out = _git(repo, "diff", "--name-only", "--no-renames", since, head).stdout
    touched: dict[str, list[str]] = {}
    for path in out.splitlines():
        if path.startswith(prefix):
            addon, _, rest = path[len(prefix):].partition("/")
            if rest:
                touched.setdefault(addon, []).append(path)
    return touched


def check(repo: str, base: str, head: str, lock_file: str = "addons.lock",
          vendored_dir: str = "vendored") -> dict[str, list[str]]:
    """Addons whose vendored files changed while their lock entry did not."""
    since = ensure_merge_base(repo, base, head)
    before = lock_at(repo, since, lock_file)
    after = lock_at(repo, head, lock_file)
    return {
        addon: paths
        for addon, paths in touched_addons(repo, since, head, vendored_dir).items()
        if before.get(addon) == after.get(addon)
    }


def main() -> int:
    repo = os.environ.get("GITHUB_WORKSPACE", ".")
    base = os.environ.get("BASE_SHA", "").strip()
    head = os.environ.get("HEAD_SHA", "").strip()
    lock_file = os.environ.get("LOCK_FILE") or "addons.lock"
    vendored_dir = os.environ.get("VENDORED_DIR") or "vendored"
    if not (base and head):
        print("vendor-check: not a pull request; offline mode checks pull "
              "requests only. Skipped.")
        return 0
    offenders = check(repo, base, head, lock_file, vendored_dir)
    if not offenders:
        print(f"vendor-check: every change under {vendored_dir}/ comes with "
              f"a matching {lock_file} change.")
        return 0
    for addon, paths in sorted(offenders.items()):
        print(
            f"::error file={paths[0]},title=Vendored addon edited in place::"
            f"{addon}: {len(paths)} file(s) under {vendored_dir}/{addon}/ "
            f"changed but its {lock_file} entry did not. {vendored_dir}/ is "
            "generated: change the addon in its source repo, then "
            f"`odoo-dev vendor bump {addon}`."
        )
    return 1


if __name__ == "__main__":
    sys.exit(main())
