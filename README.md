# SyKit-Packages

The official package library for [SyKit](https://github.com/Kasterfly/SyKit):
third-party integrations and add-ons, installable directly from this
repository by the SyKit package handler.

> [!WARNING]
> A package can replace executable SyKit source. Installing one grants it the
> same trust as running its code. Review the complete package and only install
> packages from sources you trust.

## Packages

| Package | Description |
| --- | --- |
| [auth0](auth0/) | Auth0 login flow for SyKit sessions; server-side code exchange, stdlib only |
| [db-base](db-base/) | Document database layer; sqlite by default, driver interface for other backends |
| [postgres](postgres/) | Native PostgreSQL backend for db-base through psycopg |
| [postgres-sessions](postgres-sessions/) | PostgreSQL backend for the session-store setting; shared, revocable sessions |
| [resend](resend/) | Send email through the Resend API |
| [supabase](supabase/) | Supabase backend for db-base over the project's REST API |
| [textbelt](textbelt/) | Send SMS through the TextBelt API |

Most of them add a module under `sykit/`, so installs need
`--yes --allow-core` (or an interactive yes plus `--allow-core`); the
pre-install report states exactly what each one touches
(`postgres-sessions` is the exception: it only adds a `files/core/`
module and installs with `--yes` alone). `supabase` builds on `db-base`
and must be installed after it (`package-req` enforces the order);
`postgres` and `supabase` build on `db-base` and must be installed after it;
`auth0` and `postgres-sessions` need SyKit 0.5.0 or newer
(`sykit-req`).

Run `python SyKit package add github:Kasterfly/SyKit-Packages` to print the
live listing straight from `index.json`.

## Installing

Requires SyKit 0.4.0 or newer:

```
python SyKit package add <name>              # latest release of this repo
python SyKit package add <name>@<tag>        # pinned to a tag
python SyKit package add github:Kasterfly/SyKit-Packages/<folder>@<ref>
```

On older SyKit versions, download a package folder from this repo and
install it as a local path: `python SyKit package add path/to/folder`.

Every install prints SyKit's pre-install analysis (files touched, URLs,
exec-style calls, core edits, and more) and asks for confirmation. See the
[SyKit packages documentation](https://github.com/Kasterfly/SyKit/blob/main/docs/packages.md)
for the full behavior, including the `--yes` and `--allow-core` flags.

## How resolution works

- A bare name (`package add aws`) looks up the name in `index.json` and
  installs from that folder. Without an explicit `@ref`, SyKit uses the
  latest GitHub release of this repo, or the default branch when no release
  exists.
- SyKit resolves the ref to an exact commit before downloading and records
  it, together with a content hash, in the install record. Installs from a
  moving branch are labeled with a warning, so prefer tagged releases.

## Repository layout

One folder per package, plus `index.json` at the root mapping names to
folders:

```json
{
    "packages": {
        "example": { "path": "example", "desc": "What it does." }
    }
}
```

Each package folder follows the standard SyKit package format:
`SyKitPackage.json` plus `add/`, `edit/`, and/or `remove/`.

Two checks keep the library healthy; CI runs both on every push and pull
request, and the compat check also runs weekly and on demand:

```
python validate.py               # layout and index rules
python compat.py path/to/SyKit   # install + test every package on SyKit
```

`compat.py` copies a SyKit checkout, installs each listed package, runs the
full SyKit test suite, and removes the package again. Run the compat
workflow manually after every SyKit release to confirm the library still
works against the new version.

## Adding a package

1. Create a folder with `SyKitPackage.json` and the change folders it
   needs. Paths mirror the SyKit tool layout; no symlinks, and nothing may
   touch `.git/`, `.packages/`, or `__pycache__/`.
2. Prefer purely additive packages (new files under `add/`, especially new
   `sykit/` modules) over edits to existing SyKit files; additive packages
   keep working across SyKit updates, while edits can lose their anchors.
3. Ship the package's tests as added files under `tests/` so the compat
   check exercises them automatically after every install.
4. Declare `"sykit-req"` with the minimum SyKit version the package needs
   (SyKit 0.4.1 or newer understands the key), and list any runtime
   dependencies under `"deps"` as pip requirement strings; SyKit shows
   them at install time but never installs them.
5. Add the package to `index.json` with a short description.
6. Run `python validate.py` locally; pull requests must pass validate and
   compat.
7. Tag a release after merging so bare-name installs pin to it.

## Hosting your own package repo

Nothing here is special: any GitHub repository with the same layout works.
Install from it with `github:Owner/Repo/<folder>@<ref>`, or point bare names
at it by setting `"package-default-repo"` in the SyKit tool's own
`sykit/config.json`.

## License

[MIT](LICENSE). Individual packages may declare additional credits in their
`SyKitPackage.json`.
