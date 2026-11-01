"""The pack's runtime pulse questions must stay identical to the seeded survey."""

import json
from pathlib import Path

from packs.journey.services.pulse import PULSE_QUESTIONS

SEED = Path(__file__).resolve().parents[4] / "seed" / "journey" / "pulse_survey.json"


def test_runtime_pulse_questions_match_the_seeded_survey():
    payload = json.loads(SEED.read_text(encoding="utf-8"))
    seeded = {survey["kind"]: survey["questions"] for survey in payload["surveys"]}
    assert PULSE_QUESTIONS == seeded
