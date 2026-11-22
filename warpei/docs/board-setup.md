# ROCK 5B board setup (task 4.1)

## Image

1. Download the current Radxa OS Debian 12 (Bookworm) image for ROCK 5B from
   the `radxa-build/rock-5b` releases page and flash it to the eMMC or an
   SD card with balenaEtcher or `dd`.
2. First boot: log in as `rock`, set a password, connect to the network.
3. Clone the repository with Git LFS installed, then:

       sudo bash warpei/sbc/deploy/setup.sh

   The script installs packages, creates `~/.warpei/venv`, copies
   `configs/warpei_panel.json` to `~/.warpei/config.json`, installs the
   `warpei` systemd service, and appends a "Board state" block to the end
   of this file with the kernel, Python, OpenCV and GL driver versions.

## Checks after setup

| Check | Command | Expect |
| --- | --- | --- |
| Tests | `cd warpei/sbc && ~/.warpei/venv/bin/pytest` | all pass; the renderer tests must not skip |
| GL driver | see the Board state block below | Mali-G610 renderer, OpenGL ES 3.x |
| Panel | `~/.warpei/venv/bin/python -m warpei.main --no-uart` | test card on the panel |
| Capture dongle | `v4l2-ctl --list-devices` | the UVC dongle listed; note its `/dev/videoN` |
| Camera | same list | Arducam listed |
| UART | `ls -l /dev/ttyS2` and group `dialout` | present, user in group |
| Frame timing | `~/.warpei/venv/bin/python tools/benchmark_frame.py --frames 600 --source N` | gpu_total mean under 33 ms |
| Boot | `sudo systemctl start warpei; journalctl -u warpei -f` | warped image or status card with no keyboard |

Set `--video-source` and the camera index in the service file and config
once the `/dev/videoN` numbers are known; they depend on USB enumeration
order, so prefer the `/dev/v4l/by-id/...` paths for both.

## If the panel does not light

- `SDL_VIDEODRIVER=kmsdrm` requires no desktop session to own the display.
  Disable any display manager: `sudo systemctl disable --now lightdm` (or gdm).
- Check that `/dev/dri/card0` exists and the user is in the `video` and `render` groups.
- Try `--windowed` under a desktop session first to separate panel problems from GL problems.

## Board state

(appended by `setup.sh` on each run)
