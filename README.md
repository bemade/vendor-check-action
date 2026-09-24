# vendor-check-action

Reusable GitHub Action for Odoo projects that **vendor** shared addons: real
files under `vendored/<addon>/`, each pinned to a source commit in
`addons.lock`, managed with `odoo-dev vendor`. It is the consumer-side
counterpart of [vendor-autotag-action](https://github.com/bemade/vendor-autotag-action),
which tags addon versions in the source repositories.

`vendored/` is generated. An edit made directly there is not described by the
lock, so the next `odoo-dev vendor bump` silently discards it. This action
stops that.

## Modes

| mode | what it checks | needs |
|---|---|---|
| `offline` (default) | A pull request that changes `vendored/<addon>/` must also change that addon's entry in `addons.lock`. | git only. Pull requests only; other events skip. |
| `full` | `odoo-dev vendor check`: every vendored addon is byte-identical to its pinned commit. | Read access to every source in `addons.lock`. |

`offline` stops new drift but cannot see drift that is already there; `full`
proves the whole tree. Turn `full` on once a project's existing drift is
cleared.

## Usage

```yaml
name: vendor-check
on:
  pull_request:

jobs:
  vendor-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: bemade/vendor-check-action@v1
        # with:
        #   mode: full
        #   gitlab-token: ${{ secrets.VENDOR_SOURCES_TOKEN }}
```

`fetch-depth: 0` lets `offline` find the pull request's merge base without
refetching; a shallow checkout still works, it just deepens itself.

### Inputs

| input | default | |
|---|---|---|
| `mode` | `offline` | `offline` or `full` |
| `lock-file` | `addons.lock` | |
| `vendored-dir` | `vendored` | |
| `base-sha`, `head-sha` | the pull request's | `offline` only |
| `odoo-dev-ref` | `master` | `full`: ref of `github.com/bemade/odoo-dev` to install |
| `no-hybrid` | `true` | `full`: also fail if `addons/` still symlinks into `.repos/` |
| `gitlab-host` | `git.bemade.org` | `full`: host of private sources |
| `gitlab-token` | empty | `full`: `read_repository` token for private sources |

In `full` mode, SSH source URLs are rewritten to HTTPS: public GitHub sources
need no secret, private sources on `gitlab-host` use `gitlab-token`.

## Fixing a failure

`offline` names each addon edited without a re-pin. Make the change in the
addon's source repository instead, then run `odoo-dev vendor bump <addon>` in
the project. To iterate on the source from inside the project, use
`odoo-dev vendor develop <addon>`.

GitLab projects get the same `full` check from the `vendor_check` job of the
shared `odoo-ci` template.

## Tests

```sh
pip install pytest && pytest -q
```

License: LGPL-3.0-or-later. Author: Bemade Inc.
