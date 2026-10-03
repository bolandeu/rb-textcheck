from __future__ import annotations

from pathlib import Path

import pytest

CONTRACT_DATA = Path(__file__).parent / "contracts" / "data"


@pytest.fixture
def contract_data(monkeypatch: pytest.MonkeyPatch) -> Path:
    """Consumer contract runs (tests/contracts/fixtures.yaml): the offline texts and profiles are the cwd."""
    monkeypatch.chdir(CONTRACT_DATA)
    return CONTRACT_DATA
