"""GPU warp renderer (task 4.2, Report 7.4).

Draws one textured full-screen quad per frame. The warp model's 12
polynomial coefficients, homography and target map are shader uniforms, so
a new calibration is applied by uploading 48 bytes, not by rebuilding a
lookup texture. The source frame is uploaded as one RGB texture per frame.

Two ways to get a GL context:
  - WindowRenderer: SDL2 full-screen window (KMSDRM on the ROCK 5B with no
    desktop, or a normal window on a laptop). Needs PySDL2.
  - OffscreenRenderer: EGL standalone context, renders to a framebuffer and
    reads pixels back. Used by tests and by tools/benchmark_frame.py.

Both share GLWarp, which owns the program, quad and texture.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from ..calibration.solve import WarpModel

SHADER_DIR = Path(__file__).parent / "shaders"


def _load(name: str) -> str:
    return (SHADER_DIR / name).read_text(encoding="utf-8")


class GLWarp:
    """Program, quad and source texture on an existing moderngl context."""

    def __init__(self, ctx, panel_size: tuple[int, int]):
        import moderngl
        self.ctx = ctx
        self.panel_size = panel_size
        w, h = panel_size
        self.program = ctx.program(vertex_shader=_load("warp.vert"), fragment_shader=_load("warp.frag"))
        quad = np.array([-1, -1, 1, -1, -1, 1, 1, 1], dtype="f4")
        self.vbo = ctx.buffer(quad.tobytes())
        self.vao = ctx.vertex_array(self.program, [(self.vbo, "2f", "in_pos")])
        self.texture = ctx.texture((w, h), 3, dtype="f1")
        self.texture.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.texture.repeat_x = self.texture.repeat_y = False
        self.texture.use(0)
        self.program["u_source"].value = 0
        self.program["u_panel_size"].value = (float(w), float(h))
        self.flip = False
        self.set_model(None)

    # ---- state -------------------------------------------------------------

    def set_model(self, model: WarpModel | None) -> None:
        """Upload a calibration, or switch to passthrough when None."""
        p = self.program
        if model is None:
            p["u_passthrough"].value = 1
            p["u_homography"].write(np.eye(3, dtype="f4").T.tobytes())
            p["u_coeff_u"].value = [0.0] * 6
            p["u_coeff_v"].value = [0.0] * 6
            p["u_target_scale"].value = 1.0
            p["u_target_offset"].value = (0.0, 0.0)
            return
        if tuple(model.panel_size) != tuple(self.panel_size):
            raise ValueError("model panel size does not match the renderer")
        p["u_passthrough"].value = 0
        # GLSL mat3 is column-major; numpy is row-major, so transpose.
        p["u_homography"].write(np.asarray(model.homography, dtype="f4").T.tobytes())
        p["u_coeff_u"].value = [float(c) for c in model.coeff_u]
        p["u_coeff_v"].value = [float(c) for c in model.coeff_v]
        p["u_target_scale"].value = float(model.target_scale)
        p["u_target_offset"].value = (float(model.target_offset[0]), float(model.target_offset[1]))

    def set_flip(self, flip: bool) -> None:
        self.flip = bool(flip)
        self.program["u_flip"].value = 1 if flip else 0

    # ---- per frame ---------------------------------------------------------

    def upload(self, frame_rgb: np.ndarray) -> None:
        """frame_rgb: (H, W, 3) uint8, panel-sized, RGB order."""
        h, w = frame_rgb.shape[:2]
        if (w, h) != tuple(self.panel_size):
            raise ValueError(f"frame is {w}x{h}, renderer expects {self.panel_size}")
        self.texture.write(np.ascontiguousarray(frame_rgb).tobytes())

    def draw(self) -> None:
        import moderngl
        self.ctx.clear(0.0, 0.0, 0.0)
        self.vao.render(moderngl.TRIANGLE_STRIP)


class OffscreenRenderer:
    """Headless renderer: EGL context + framebuffer. render() returns an RGB array."""

    def __init__(self, panel_size: tuple[int, int]):
        import moderngl
        self.ctx = moderngl.create_standalone_context(backend="egl")
        w, h = panel_size
        self.fbo = self.ctx.simple_framebuffer((w, h), components=3)
        self.fbo.use()
        self.warp = GLWarp(self.ctx, panel_size)
        self.panel_size = panel_size

    def render(self, frame_rgb: np.ndarray) -> np.ndarray:
        self.warp.upload(frame_rgb)
        self.warp.draw()
        self.ctx.finish()
        w, h = self.panel_size
        data = self.fbo.read(components=3, alignment=1)
        # GL returns the bottom row first; flip so row 0 is the top, as on the panel.
        return np.frombuffer(data, dtype=np.uint8).reshape(h, w, 3)[::-1].copy()

    def release(self) -> None:
        self.ctx.release()


class WindowRenderer:
    """Full-screen window on the panel through SDL2 (KMSDRM when there is no desktop)."""

    def __init__(self, panel_size: tuple[int, int], fullscreen: bool = True,
                 display_index: int = 0, vsync: bool = True):
        import moderngl
        import sdl2
        if sdl2.SDL_Init(sdl2.SDL_INIT_VIDEO) != 0:
            raise RuntimeError(f"SDL_Init failed: {sdl2.SDL_GetError().decode()}")
        sdl2.SDL_GL_SetAttribute(sdl2.SDL_GL_CONTEXT_PROFILE_MASK, sdl2.SDL_GL_CONTEXT_PROFILE_ES)
        sdl2.SDL_GL_SetAttribute(sdl2.SDL_GL_CONTEXT_MAJOR_VERSION, 3)
        sdl2.SDL_GL_SetAttribute(sdl2.SDL_GL_CONTEXT_MINOR_VERSION, 0)
        sdl2.SDL_GL_SetAttribute(sdl2.SDL_GL_DOUBLEBUFFER, 1)
        w, h = panel_size
        flags = sdl2.SDL_WINDOW_OPENGL | (sdl2.SDL_WINDOW_FULLSCREEN if fullscreen else 0)
        x = sdl2.SDL_WINDOWPOS_CENTERED_DISPLAY(display_index)
        self.window = sdl2.SDL_CreateWindow(b"warpei", x, x, w, h, flags)
        if not self.window:
            raise RuntimeError(f"SDL_CreateWindow failed: {sdl2.SDL_GetError().decode()}")
        self.gl = sdl2.SDL_GL_CreateContext(self.window)
        sdl2.SDL_GL_SetSwapInterval(1 if vsync else 0)
        sdl2.SDL_ShowCursor(sdl2.SDL_DISABLE)
        self.ctx = moderngl.create_context()
        self.ctx.viewport = (0, 0, w, h)
        self.warp = GLWarp(self.ctx, panel_size)
        self.panel_size = panel_size
        self._sdl = sdl2

    def render(self, frame_rgb: np.ndarray) -> None:
        self.warp.upload(frame_rgb)
        self.warp.draw()
        self._sdl.SDL_GL_SwapWindow(self.window)

    def poll_quit(self) -> bool:
        """True if the window was asked to close or Q/Esc was pressed."""
        sdl2 = self._sdl
        event = sdl2.SDL_Event()
        while sdl2.SDL_PollEvent(event):
            if event.type == sdl2.SDL_QUIT:
                return True
            if event.type == sdl2.SDL_KEYDOWN and event.key.keysym.sym in (sdl2.SDLK_q, sdl2.SDLK_ESCAPE):
                return True
        return False

    def release(self) -> None:
        self._sdl.SDL_GL_DeleteContext(self.gl)
        self._sdl.SDL_DestroyWindow(self.window)
        self._sdl.SDL_Quit()


def gl_info(ctx) -> dict:
    return {k: ctx.info.get(k) for k in ("GL_VENDOR", "GL_RENDERER", "GL_VERSION")}
