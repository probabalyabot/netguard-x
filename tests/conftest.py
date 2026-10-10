import json
from pathlib import Path

import pytest

from netguardx import Network

EX = Path(__file__).parent.parent / "netguardx" / "examples"


@pytest.fixture()
def net() -> Network:
    return Network.model_validate(json.loads((EX / "basic.json").read_text()))


def load_change(name: str) -> list:
    from netguardx import Change

    d = json.loads((EX / "changes" / f"{name}.json").read_text())
    return [Change.model_validate(c) for c in d["changes"]]
