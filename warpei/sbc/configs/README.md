# Config files

Pass one with `--config` to `warpei.app`, `tools/demo.py`, or
`testing/scripts/run_trials.py`. Any key may be left out; the defaults in
`warpei/config.py` fill it in.

| File | Use |
| --- | --- |
| `demo_projector_1080p.json` | A consumer 1080p projector on a laptop's second display. Set `display_offset_x` to the laptop screen's width so the full-screen window lands on the projector. |
| `warpei_panel.json` | The 1440 x 2560 portrait panel on the ROCK 5B. Source content is rotated 90 degrees. |

Orientation keys (settle on bench):

- `source_rotation`: 0, 90, 180 or 270 degrees clockwise, applied to video content only. The calibration pattern is always generated in panel orientation.
- `source_flip_horizontal` / `source_flip_vertical`: set if the fold mirror or lens leaves the content mirrored.
- `display_offset_x` / `display_offset_y`: where the output window opens; on the ROCK 5B with a single display both are 0.
