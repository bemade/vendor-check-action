"""Tests for the offline vendored-drift check.

Acceptance criteria:
1. A pull request that changes vendored/<addon>/ without changing that
   addon's addons.lock entry fails, naming the addon.
2. The same change with a matching lock change (a bump) passes.
3. Adding an addon (files + entry) and removing one (files + entry) pass.
4. Changes outside vendored/, and lock-only changes, pass.
5. Only the offending addon is reported when several change.
6. Outside a pull request (no base/head) the check is skipped, not failed.
"""
import subprocess

import pytest
import vendor_check_offline as vc

LOCK = """\
# pins
alpha:
  source: git@github.com:bemade/addons
  commit: aaaa
beta:
  source: git@github.com:bemade/addons
  version: 19.0.1.0.0
  commit: bbbb
"""


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _write(repo, path, text):
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)


@pytest.fixture
def repo(tmp_path):
    repo = tmp_path / "project"
    repo.mkdir()
    _write(repo, "addons.lock", LOCK)
    _write(repo, "vendored/alpha/__manifest__.py", "{'version': '1'}\n")
    _write(repo, "vendored/beta/__manifest__.py", "{'version': '1'}\n")
    _write(repo, "addons/local/__manifest__.py", "{'version': '1'}\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    return repo


def _commit(repo, message="change"):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", message)
    return _git(repo, "rev-parse", "HEAD")


def _base(repo):
    return _git(repo, "rev-parse", "HEAD")


def test_in_place_edit_fails_and_names_the_addon(repo):
    base = _base(repo)
    _write(repo, "vendored/alpha/models.py", "x = 1\n")
    head = _commit(repo)
    assert list(vc.check(str(repo), base, head)) == ["alpha"]


def test_edit_with_a_lock_bump_passes(repo):
    base = _base(repo)
    _write(repo, "vendored/alpha/models.py", "x = 1\n")
    _write(repo, "addons.lock", LOCK.replace("commit: aaaa", "commit: cccc"))
    head = _commit(repo)
    assert vc.check(str(repo), base, head) == {}


def test_adding_and_removing_addons_with_their_entries_passes(repo):
    base = _base(repo)
    _write(repo, "vendored/gamma/__manifest__.py", "{'version': '1'}\n")
    _git(repo, "rm", "-rq", "vendored/beta")
    lock = LOCK.split("beta:")[0] + "gamma:\n  source: s\n  commit: gggg\n"
    _write(repo, "addons.lock", lock)
    head = _commit(repo)
    assert vc.check(str(repo), base, head) == {}


def test_changes_outside_vendored_and_lock_only_changes_pass(repo):
    base = _base(repo)
    _write(repo, "addons/local/models.py", "x = 1\n")
    _write(repo, "addons.lock", LOCK.replace("commit: bbbb", "commit: dddd"))
    head = _commit(repo)
    assert vc.check(str(repo), base, head) == {}


def test_only_the_unpinned_addon_is_reported(repo):
    base = _base(repo)
    _write(repo, "vendored/alpha/models.py", "x = 1\n")
    _write(repo, "vendored/beta/models.py", "y = 1\n")
    _write(repo, "addons.lock", LOCK.replace("commit: bbbb", "commit: dddd"))
    head = _commit(repo)
    assert list(vc.check(str(repo), base, head)) == ["alpha"]


def test_measures_from_the_merge_base_not_the_base_tip(repo):
    """Changes landing on the base branch after the PR branched are not the
    PR's own and must not count against it."""
    fork = _base(repo)
    _git(repo, "checkout", "-qb", "feature")
    _write(repo, "addons/local/models.py", "x = 1\n")
    head = _commit(repo)
    _git(repo, "checkout", "-q", "main")
    _write(repo, "vendored/beta/models.py", "y = 1\n")
    base = _commit(repo, "hand edit already on main")
    assert fork != base
    assert vc.check(str(repo), base, head) == {}


def test_parse_lock_reads_entries_and_ignores_comments():
    entries = vc.parse_lock(LOCK)
    assert entries["beta"] == {
        "source": "git@github.com:bemade/addons",
        "version": "19.0.1.0.0",
        "commit": "bbbb",
    }
    assert set(entries) == {"alpha", "beta"}


def test_main_skips_outside_a_pull_request(monkeypatch, capsys):
    monkeypatch.setenv("BASE_SHA", "")
    monkeypatch.setenv("HEAD_SHA", "")
    assert vc.main() == 0
    assert "Skipped" in capsys.readouterr().out


def test_main_fails_with_an_annotation(repo, monkeypatch, capsys):
    base = _base(repo)
    _write(repo, "vendored/alpha/models.py", "x = 1\n")
    head = _commit(repo)
    monkeypatch.setenv("GITHUB_WORKSPACE", str(repo))
    monkeypatch.setenv("BASE_SHA", base)
    monkeypatch.setenv("HEAD_SHA", head)
    assert vc.main() == 1
    out = capsys.readouterr().out
    assert "::error file=vendored/alpha/models.py" in out
    assert "odoo-dev vendor bump alpha" in out
