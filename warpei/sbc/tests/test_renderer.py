"""Task 4.2: GPU renderer against the CPU reference.

Acceptance: output for a test image matches reference.py with a mean
difference under 2 gray levels out of 255. Runs wherever an EGL context can
be created (Mesa on a PC, the Mali driver on the ROCK 5B); skips otherwise.
"""

from __future__ import annotations

import numpy as np
import pytest

from conftest import sim_camera
from warpei.calibration import pattern
from warpei.calibration.detect import detect_grid
from warpei.calibration.solve import solve_warp
from warpei.video import reference

PANEL = (pattern.PANEL_WIDTH, pattern.PANEL_HEIGHT)


@pytest.fixture(scope="module")
def gpu():
    moderngl = pytest.importorskip("moderngl")
    from warpei.video.renderer import OffscreenRenderer
    try:
        r = OffscreenRenderer(PANEL)
    except Exception as exc:                     # no EGL / no GPU here
        pytest.skip(f"no GL context: {exc}")
    yield r
    r.release()


def fitted_model():
    view = sim_camera(scale=0.17, bow=1.0, blur=1.5)
    det = detect_grid(view.image)
    return solve_warp(view.panel_points, view.camera.undistort_points(det.centers))


def test_passthrough_is_identity(gpu):
    src = reference.test_card(PANEL)[:, :, ::-1]            # BGR -> RGB
    gpu.warp.set_model(None)
    out = gpu.render(src)
    assert np.abs(out.astype(int) - src.astype(int)).mean() < 0.5


def test_shader_matches_cpu_reference(gpu):
    model = fitted_model()
    src_bgr = reference.test_card(PANEL)
    cpu = reference.warp_image(src_bgr, reference.build_maps(model))
    gpu.warp.set_model(model)
    out = gpu.render(src_bgr[:, :, ::-1])[:, :, ::-1]      # back to BGR
    diff = np.abs(out.astype(int) - cpu.astype(int))
    print(f"\nGPU vs CPU: mean {diff.mean():.3f}, 99th pct {np.percentile(diff, 99):.0f}, max {diff.max()}")
    assert diff.mean() < 2.0


def test_flip_mirrors_source(gpu):
    src = np.zeros((PANEL[1], PANEL[0], 3), np.uint8)
    src[:, :PANEL[0] // 2] = 255                            # left half white
    gpu.warp.set_model(None)
    gpu.warp.set_flip(True)
    out = gpu.render(src)
    gpu.warp.set_flip(False)
    assert out[:, PANEL[0] // 4].mean() < 5 and out[:, 3 * PANEL[0] // 4].mean() > 250


def test_rejects_wrong_sizes(gpu):
    with pytest.raises(ValueError):
        gpu.warp.upload(np.zeros((100, 100, 3), np.uint8))
    model = fitted_model()
    model.panel_size = (100, 100)
    with pytest.raises(ValueError):
        gpu.warp.set_model(model)
