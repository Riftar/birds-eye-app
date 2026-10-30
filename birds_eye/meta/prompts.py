import re
from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

_VERSION_RE = re.compile(r"^version\s*:\s*(\d+)\s*$", re.IGNORECASE)


def parse_prompt_file(text: str) -> tuple[int, str]:
    lines = text.splitlines()
    if not lines or not _VERSION_RE.match(lines[0].strip()):
        raise ValueError("Prompt file is missing a version header (e.g. `version: 1`).")
    version = int(_VERSION_RE.match(lines[0].strip()).group(1))
    return version, "\n".join(lines[1:]).strip() + "\n"


def load_prompt(name: str) -> tuple[int, str]:
    return parse_prompt_file((PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_prompts() -> dict[str, dict]:
    return {
        name: {"version": version, "text": text}
        for name, (version, text) in (
            (stage, load_prompt(stage)) for stage in ("planner", "writer", "reviewer")
        )
    }
