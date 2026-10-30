import json
from pathlib import Path

import pytest

from birds_eye.core.inputs import FILES, load_inputs, make_context


@pytest.mark.parametrize("document", ["product_sheet", "rulebook"])
def test_missing_required_document_fails(scenario, document):
    (scenario / FILES[document]).unlink()
    with pytest.raises(FileNotFoundError):
        load_inputs(scenario)


def test_files_are_reread_for_each_run_and_snapshot_is_retained(scenario):
    first = make_context(load_inputs(scenario))
    path = scenario / FILES["creator_brief"]
    data = json.loads(path.read_text())
    data["goal"] = "MOCK changed goal"
    path.write_text(json.dumps(data))
    second = make_context(load_inputs(scenario))
    assert first.inputs.creator_brief.goal != second.inputs.creator_brief.goal
    assert first.input_hashes["creator_brief"] != second.input_hashes["creator_brief"]
    assert first.input_hashes["rulebook"] == second.input_hashes["rulebook"]


def test_tencent_scenario_uses_same_loader(scenario):
    data = json.loads((scenario / FILES["creator_brief"]).read_text())
    data["label"] = "MOCK Tencent creator"
    (scenario / FILES["creator_brief"]).write_text(json.dumps(data))
    assert load_inputs(scenario).creator_brief.label == "MOCK Tencent creator"


def test_all_mock_files_have_mock_in_filename_and_content():
    files = list(Path("mock-data").rglob("*"))
    files = [path for path in files if path.is_file()]
    assert files
    for path in files:
        content = path.read_text()
        assert "MOCK" in path.name and "MOCK" in content
        assert "MOCK" in json.loads(content)["label"]
