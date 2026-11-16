# Contributing to DataDash

Thanks for helping improve DataDash! Here is how to get a change merged.

## Getting started
1. Fork the repo and clone your fork.
2. Follow the **Local development** section of the [README](README.md).
3. Create a branch: `git checkout -b feat/short-description`.

## Branch & commit style
- Branches: `feat/...`, `fix/...`, `docs/...`, `chore/...`
- Commits follow [Conventional Commits](https://www.conventionalcommits.org/):
  `feat: add expense editing`, `fix: correct split rounding`, `docs: update API table`.

## Before opening a pull request
- `cd backend && pip install -r requirements-dev.txt && pytest` passes (add tests for new behaviour).
- `cd frontend && npm run build` succeeds.
- No secrets, `.env` files or uploaded datasets in the diff.
- Update `docs/API.md` if you changed an endpoint.

## Code guidelines
- **Never evaluate user input.** Columns, operators, aggregations and chart types are checked against allow-lists in `app/engine/query.py`; keep it that way (no `df.query(user_text)`, no `eval`).
- Keep data logic in `app/engine/` (pure pandas, no web framework) so it stays easy to test.
- New request fields go through a Pydantic model in `app/schemas.py` with length/range limits.
- Anything that reads another user's data must go through `owned_dataset` / `owned_dashboard` (404 for non-owners).

## Reporting bugs
Open an issue with steps to reproduce, expected vs actual behaviour, and your OS and Python/Node versions.
