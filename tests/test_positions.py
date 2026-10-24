"""The 2D/3D player positions model (web/js/formation.js), checked with Node: shape, ball, defenders."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_positions_keep_shape_ball_and_defenders() -> None:
    result = subprocess.run(["node", str(ROOT / "tests" / "positions.test.mjs")], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr or result.stdout
