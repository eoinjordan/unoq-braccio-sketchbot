"""End-to-end: the full CLI pipeline draws the sample image on the simulator."""

from __future__ import annotations

from argparse import Namespace

from PIL import Image

from sketch_artist import cli


def _args(**overrides) -> Namespace:
    base = dict(
        image=None, dry_run=False, no_arm=False, sim=False,
        sim_render="output/sim_drawing.png", slow=False, debug=False,
        title="Test", style="none", host="127.0.0.1", port=8765,
    )
    base.update(overrides)
    return Namespace(**base)


def test_full_pipeline_against_simulator(sample_image, tmp_path):
    out = tmp_path / "sim_drawing.png"
    rc = cli.run(_args(image=sample_image, sim=True, style="engineer",
                       sim_render=str(out)))
    assert rc == 0
    assert out.exists()
    # The simulator drew something recognisable, not a blank page.
    assert Image.open(out).convert("L").getextrema()[0] < 128


def test_dry_run_skips_arm(sample_image, tmp_path):
    rc = cli.run(_args(image=sample_image, dry_run=True, style="none"))
    assert rc == 0
