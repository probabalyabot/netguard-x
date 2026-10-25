"""The plain-language parser (netguardx/nlp)."""
import json
from pathlib import Path

import pytest

from netguardx.nlp import interpret

SNAPSHOT = json.loads((Path(__file__).parent / "data" / "nlp_snapshot_v1.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", SNAPSHOT, ids=[c["text"][:40] for c in SNAPSHOT])
def test_output_matches_the_original_parser(net, case):
    """Recorded from the single-file parser before it became a package. Later steps may extend what
    is understood; when a case changes on purpose, update the snapshot in the same commit."""
    assert interpret(case["text"], net) == case["result"]
