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

Active development for the Meta AI Hackathon. This repository currently carries the project pitch; implementation code lands as the hackathon build progresses.
