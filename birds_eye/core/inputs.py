import hashlib
import json
from pathlib import Path

from birds_eye.core.contracts import RunContext, RunInputs

FILES = {
    "creator_brief": "creator-brief.MOCK.json",
    "product_sheet": "product-sheet.MOCK.json",
    "rulebook": "rulebook.MOCK.json",
}


def load_inputs(scenario_dir: Path) -> RunInputs:
    return RunInputs.model_validate(
        {
            key: json.loads((scenario_dir / name).read_text())
            for key, name in FILES.items()
        }
    )


def make_context(inputs: RunInputs) -> RunContext:
    hashes = {
        key: hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        for key, value in inputs.model_dump(mode="json").items()
    }
    return RunContext(inputs=inputs, input_hashes=hashes)
