from __future__ import annotations

from prompts.story import STAGE_GUIDANCE, get_stage_guidance


def test_stage_guidance_matches_copy_from_gemini_client():
    snapshot = get_stage_guidance()
    assert snapshot == STAGE_GUIDANCE
    # defensive copy check
    snapshot["발단"] = "modified"
    assert STAGE_GUIDANCE.get("발단") != "modified"
