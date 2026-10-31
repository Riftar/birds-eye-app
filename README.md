# Birds Eye

**An AI-agent content factory: agents write and review short-video and carousel posts, and nothing ships without passing two human approval gates.**

Built for the Meta AI Hackathon, Theme 1: my world, my problem, solved with Meta's models.

## The Problem

Running a fleet of AI agents that produce short-video and carousel content taught me one thing: the hard problem is not generation. It is control.

- Agents drift. The post you approved is not the post that gets published.
- Agent output is unreviewable. A wall of chat messages is not an audit trail.
- Agents overwrite each other. Two workers touching the same post with no protocol means silent data loss.

Content factories fail at the coordination layer, not the model layer.

## The Solution: Birds Eye

Birds Eye turns content production into a disciplined, auditable pipeline where every agent action is explicit, every transition is validated, and a human holds the only keys that matter.

### Posts are files in git

Every post lives as a file in a git repository. Ideas, scripts, slide decks, captions, and thumbnails are all versioned artifacts. Nothing lives in a chat window. Every change is a commit with an author, which means full blame, full diff, full history, per post.

### Agents claim work with tokens

An agent cannot touch a post unless it holds the claim for that post. Claims are explicit tokens: acquire, work, release. If a claim goes stale or another agent has taken over, the state machine returns `CLAIM_LOST` and the work stops cleanly. No silent overwrites, ever.

### A state machine that refuses everything invalid

Posts move through a fixed lifecycle: idea, draft, approved, in review, review passed, scheduled, published. Every transition is checked. Invalid transitions are refused with hard error codes:

- `HUMAN_ONLY`: a stage that requires a human decision was attempted by an agent.
- `CLAIM_LOST`: the claiming agent no longer holds the claim.
- Plus explicit codes for every other illegal transition in the lifecycle.

The machine does not negotiate. If the transition is not valid, it does not happen.

### Exactly two human approval gates

The pipeline has one deliberate property: no post reaches the public without passing through exactly two human decisions.

1. **Idea to approved**: the human decides what is worth making.
2. **Review to scheduled**: the human decides what is ready to ship.

Everything between the gates is autonomous agent territory. Everything at the gates is human territory. The boundary is enforced by the state machine, not by trust.

### Full per-post audit history

Every post carries its complete history: which agent claimed it, which model produced which asset, what the review said, when the human approved, when it was scheduled. One file, one timeline, end to end.

## Meta Models as the Production Engines

For the hackathon, Meta's newest models are wired in as the production workers inside the gated pipeline:

- **Muse Spark**: the scripting and review agent. It drafts scripts and performs structured review passes, and its review verdict is just another gated transition in the state machine. If the review does not pass, the post does not move.
- **Muse Voice Transcribe**: the voiceover stage, producing aligned captions from generated narration.
- **Muse Image**: slide and thumbnail generation for carousels.
- **SAM 3.1**: cutting subjects out of footage to build clean carousel frames.

The critical design rule: every model output enters the same gated, audited pipeline as everything else. No model writes directly to a published post. Strong models make the factory faster; the state machine keeps it safe.

## Why This Is Different

Most agent demos show generation. Birds Eye shows governance:

| Common agent project | Birds Eye |
| --- | --- |
| Output appears in chat | Output is versioned files in git |
| Agents act on trust | Agents act on claims, or not at all |
| Errors are silent | Every refusal has a code and a cause |
| Human review is a suggestion | Human review is a hard gate, twice |
| History is a scrollback buffer | History is a per-post audit trail |

## Theme 1: My World, My Problem

This is not a hypothetical tool. Birds Eye industrializes a content pipeline I run for real: my fleet, my short videos, my carousels, my approval bottleneck. Meta's models are the engines; Birds Eye is the factory floor that keeps them productive and honest.

## Status

Meta 01 provides shared contracts, input loading, lifecycle validation, provider routing and two API entry points. The Meta demo runs a single Planner, Writer and Reviewer pass in live mode; the Tencent pipeline remains a stub.


## Built during the hackathon (event-start)

The Meta AI Hackathon kicked off Monday 26 Oct 2026, 12:00 PM ET (23:00 WIB). The repo's first commit `8322282` landed at 23:47 WIB that night. The `event-start` git tag marks that commit, so everything in the repo was built during the event (shared core included).

## Model usage

Planner, Writer and Reviewer call Muse Spark live when live mode is enabled; SAM 3.1 segments creator images and video frames. Logical IDs remain stable as routing selects Baseten, Modal, then Meta Model API, filtered by capabilities and credentials. SAM is configured only for Meta Model API. Muse text calls have a 400-token minimum. Attempt metadata is returned and logged with model and provider attribution; credentials and inputs are excluded. Muse Voice Transcribe and Muse Image are future scope. Live provider calls are opt-in.

## Architecture/layout

`birds_eye/core` holds shared inputs and lifecycle validation; `birds_eye/providers` holds routing contracts and transports; `birds_eye/meta` and `birds_eye/tencent` expose the two boundaries in one FastAPI app. `mock-data/default` contains a fake creator scenario. Inputs are read afresh for each run and retained as a snapshot. Git-backed artifacts, durable claims, authenticated decisions, scheduling and publishing are future work. Reviewer approval permits review passage, never human approval; revisions stay in review.

Per-run call and token caps limit the live demo. Live calls also use a persistent per-provider USD ledger and caps. The Meta contributor and standard models and the Baseten model have default prices; configure prices for Modal before using it. The full gated workflow and SAM integration remain future work.

## Setup and commands

Requires Python 3.11+ and `uv`; no provider credentials are needed for the scaffold or tests.

```bash
uv sync --frozen --extra dev
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
uv run uvicorn birds_eye.app:create_app --factory --host 0.0.0.0 --port 8000
```

The Dockerfile runs the same factory with one worker and a configurable `PORT`. Credentials are read from environment variables as secrets.

## Entry points

`GET /healthz`, `GET /meta` and `GET /tencent` expose health and placeholder metadata. `POST /meta/runs` accepts a creator brief in live mode and returns stage outputs and attempts; it remains a stub by default. `POST /tencent/runs` validates inputs and returns an explicit 501 response. WorkBuddy owns the Tencent pipeline and will connect it through the shared boundary. HTTP clients cannot supply scenario paths.

## Deadlines

Meta: **5 Nov 2026, 09:00 WIB**. Tencent: **7 Nov 2026**.

## Live demo (Meta 02)

Set `BASETEN_API_KEY` and/or `MODEL_API_KEY` in the environment, then run:

```bash
PROVIDER_MODE=live uv run uvicorn birds_eye.app:create_app --factory --port 8000
```

Open `/` and submit a brief. The product sheet and rulebook are MOCK data. To exercise fallback, set `FORCE_FAIL_PROVIDERS=baseten`; the forced attempt is recorded without making a provider request. The creator brief is the primary input for every stage; the mock product sheet and rulebook provide secondary constraints. `PLANNER_MAX_TOKENS=4000`, `WRITER_MAX_TOKENS=4000`, and `REVIEWER_MAX_TOKENS=3000` set completion budgets (minimum 400). `MAX_CALLS_PER_RUN=12` and `MAX_TOKENS_PER_RUN=24000` limit the run, including retries and prompt usage. Timeouts retain their full reservation. `META_MUSE_MODEL` defaults to `muse-spark-1.3-contributor`; `META_CONTRIBUTOR_RPM` defaults to 150, with calls limited to at most 140 RPM for headroom. Provider price overrides remain available; unknown Meta models need explicit input and output prices. `PROVIDER_MAX_RETRIES=2` and `PROVIDER_RETRY_BASE_SECONDS=1` control exponential backoff with jitter; `PROVIDER_TIMEOUT_SECONDS=120` controls the timeout. `REASONING_EFFORT=low` applies to both providers, with optional `META_REASONING_EFFORT` override. Truncated outputs and failed attempts are shown in the results.

To deploy, export both provider keys in the deployer's environment, then run:

```bash
MODAL_PROFILE=riftar-dev uv run --extra deploy modal deploy modal_app.py
```

The Modal app uses CPU only, 512 MB memory, zero minimum containers, a 60-second scale-down window, one maximum container, four concurrent inputs, and a 300-second timeout. The ledger persists settled costs at `LEDGER_PATH` (default `var/ledger.jsonl`); configure persistent storage when deploying.
