from birds_eye.core.contracts import RunContext, RunResult
from birds_eye.meta.agents import plan, review, write
from birds_eye.providers.contracts import MediaInput, ModelRequest, RoutingError
from birds_eye.providers.router import ModelRouter


async def run_meta(ctx: RunContext, router: ModelRouter) -> RunResult:
    stages = []
    stage = "Planner"
    try:
        content_plan = await plan(ctx, router)
        stages.append(
            {
                "stage": stage,
                "output": content_plan.summary,
                "attempts": content_plan.attempts,
                "truncated": content_plan.attempts[-1]["truncated"],
                "structured": content_plan.structured,
                "prompt_version": content_plan.prompt_version,
                "parse_error": content_plan.parse_error,
            }
        )
        if ctx.video_data_url:
            import base64
            import binascii

            stage = "Segmenter"
            subject = (content_plan.structured or {}).get(
                "segment_subject"
            ) or "subject"
            try:
                header, encoded = ctx.video_data_url.split(",", 1)
                mime = header.removeprefix("data:").removesuffix(";base64")
                if len(encoded) > 4 * ((router.settings.max_video_bytes + 2) // 3):
                    raise ValueError
                size = len(base64.b64decode(encoded, validate=True))
            except (ValueError, binascii.Error):
                raise RoutingError("INVALID_VIDEO", "Invalid video.", []) from None
            response = await router.call(
                ModelRequest(
                    run_id=str(ctx.run_id),
                    stage="segmenter",
                    call_id="segmenter",
                    logical_model="sam-3.1",
                    operation="segmentation",
                    prompt=subject,
                    media=MediaInput(
                        kind="video",
                        mime=mime,
                        data_url=ctx.video_data_url,
                        bytes_len=size,
                    ),
                )
            )
            tracks = {}
            for obj in response.output["objects"]:
                tracks.setdefault(obj["object_id"], []).append(
                    {"frame": obj["frame"], "box": obj["box"]}
                )
            attempt = response.metadata[-1]
            stages.append(
                {
                    "stage": "Segmenter (video)",
                    "subject": subject,
                    "frames_processed": (attempt.get("usage") or {}).get(
                        "video_frames_processed", attempt["frames"]
                    ),
                    "tracks": tracks,
                    "billed_frames": attempt["billed_frames"],
                    "cost_usd": attempt["cost_usd"],
                    "attempts": response.metadata,
                }
            )
        stage = "Writer"
        draft = await write(ctx, content_plan, router)
        stages.append(
            {
                "stage": stage,
                "output": draft.content,
                "attempts": draft.attempts,
                "truncated": draft.attempts[-1]["truncated"],
                "structured": draft.structured,
                "prompt_version": draft.prompt_version,
                "parse_error": draft.parse_error,
            }
        )
        stage = "Reviewer"
        verdict = await review(ctx, content_plan, draft, router)
        stages.append(
            {
                "stage": stage,
                "output": verdict.output,
                "attempts": verdict.attempts,
                "truncated": verdict.attempts[-1]["truncated"],
                "decision": verdict.decision,
                "findings": [f.model_dump() for f in verdict.findings],
                "structured": verdict.structured,
                "prompt_version": verdict.prompt_version,
                "parse_error": verdict.parse_error,
            }
        )
    except RoutingError as exc:
        exc.stages = stages
        exc.failed_stage = stage
        raise
    return RunResult(stages=stages)
