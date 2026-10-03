"""Tests for the Nous-Slave-3/4 non-agentic warning detector.

Prior to this check, the warning fired on any model whose name contained
``"slave"`` anywhere (case-insensitive). That false-positived on unrelated
local Modelfiles such as ``slave-brain:qwen3-14b-ctx16k`` — a tool-capable
Qwen3 wrapper that happens to live under the "slave" tag namespace.

``is_nous_slave_non_agentic`` should only match the actual Nous Research
Slave-3 / Slave-4 chat family.
"""

from __future__ import annotations

import pytest

from slave_cli.model_switch import (
    _SLAVE_MODEL_WARNING,
    _check_slave_model_warning,
    is_nous_slave_non_agentic,
)


@pytest.mark.parametrize(
    "model_name",
    [
        "NousResearch/Hermes-3-Llama-3.1-70B",
        "NousResearch/Hermes-3-Llama-3.1-405B",
        "slave-3",
        "Slave-3",
        "slave-4",
        "slave-4-405b",
        "slave_4_70b",
        "openrouter/hermes3:70b",
        "openrouter/nousresearch/hermes-4-405b",
        "NousResearch/Slave3",
        "slave-3.1",
    ],
)
def test_matches_real_nous_slave_chat_models(model_name: str) -> None:
    assert is_nous_slave_non_agentic(model_name), (
        f"expected {model_name!r} to be flagged as Nous slave-agent 3/4"
    )
    assert _check_slave_model_warning(model_name) == _SLAVE_MODEL_WARNING


