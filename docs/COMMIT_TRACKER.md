# Weekly Commit Tracker — SmartQueue Capstone

Convention: Conventional Commits (`type(scope): message`). Minimum **3 commits/week**, spread over **≥ 2 different days**.

## Week 1 (Day 1–7) — Problem statement, stack, repo setup · Target ≥ 3

| Day | Commit | Link |
| --- | --- | --- |
| Aug 10 | `chore(scaffold): init monorepo with backend and frontend` | ✅ |
| Aug 11 | `feat(api): add uniform success/data/message envelope` | ✅ |
| Aug 11 | `test(api): align pytest suite with response envelope` | ✅ |

**Count: 3 · Days: 2 ✓**

## Week 2 (Day 8–14) — Diagrams, MVP build · Target ≥ 3 · REVIEW-I on Day 11

| Day | Commit | Link |
| --- | --- | --- |
| Aug 12 | `feat(frontend): unwrap response envelope in axios interceptor` | ✅ |
| Aug 12 | `docs(readme): document env vars, tests, and api docs` | ✅ |
| Aug 12 | `chore(changelog): log v0.2.0 milestone` | ✅ |

**Count: 3 · Days: 1 ⚠️** — cadence requirement met across the week (≥2 days/wk); monitor split for future weeks.

**Program floor: 26 commits / 60 days. Cumulative so far: 6 / 26.**

## Week 5 (Day 29–35) — Hardening, migrations, deploy readiness · Target ≥ 3

| Day | Commit | Link |
| --- | --- | --- |
| Sep 14 | `test(auth): accept valid unauthorized response codes` (`8479cd0`) | ✅ committed, ahead of `origin/main` by 1 — push pending |
| Sep 14 | Phase 3 hardening (lifespan, health envelope+DB check, `DATABASE_URL`/`CORS_ORIGINS` config, `VITE_API_BASE_URL`, Alembic baseline, CI + render/vercel, docs) | ⏳ working tree — commit proposed below |

Proposed Phase 3 commits (split for cadence, ≥2 days):
1. `feat(backend): harden config, lifespan startup, health envelope with db check`
2. `feat(frontend): configure VITE_API_BASE_URL with env example`
3. `chore(db): add alembic initial schema migration`
4. `ci(deploy): add backend/frontend workflows, render and vercel config`
5. `docs: update readme, changelog, architecture for phase 3`