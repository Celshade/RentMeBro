# Contributing

Thanks for taking a look at RentMeBro. It's an early-stage,
solo-maintained project, so contributions are welcome but the process
is intentionally lightweight.

## Branch flow

- **Open pull requests against `develop`, not `master`.**
  `master` only receives release PRs (`develop` → `master`), staged by
  the maintainer when cutting a new version. A PR opened against
  `master` will be asked to retarget `develop`.
- `develop` is the active integration branch — this is where day-to-day
  feature and bugfix work lands.

## Before opening a PR

- Both branches require CI to pass: backend (`pytest` + `ruff check`)
  and frontend (`oxlint` + `tsc`/`vite build`). See the
  [README](README.md#testing) for how to run these locally.
- Keep PRs scoped to one change — smaller diffs are easier to review
  in a solo-maintainer project.
- New behavior should come with test coverage where the existing
  suites make that practical (`backend/src/{accounts,billing,payments}/tests/`).

## Reporting bugs / vulnerabilities

- Regular bugs: open a GitHub issue.
- Security vulnerabilities: **do not** open a public issue — see
  [SECURITY.md](SECURITY.md) for private reporting instructions.

## License

RentMeBro is licensed under
[PolyForm Noncommercial 1.0.0](LICENSE) with an attribution addendum.
By submitting a contribution, you agree it's licensed under those same
terms, and that the project maintainer (Celshade) retains full rights
to use it, including commercially, per the Licensor Note in
[LICENSE](LICENSE).
