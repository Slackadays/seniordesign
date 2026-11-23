#!/usr/bin/env bash
# Warpei ROCK 5B setup (task 4.1). Run once on a fresh Radxa OS (Debian 12) image:
#     sudo bash sbc/deploy/setup.sh
# Installs system packages, creates the Python environment, installs the
# application, records the board state in docs/board-setup.md, and installs
# the systemd service. Safe to rerun.
set -euo pipefail

APP_USER="${SUDO_USER:-rock}"
REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"     # .../warpei
SBC_DIR="$REPO_DIR/sbc"
VENV="/home/$APP_USER/.warpei/venv"
CONF_DIR="/home/$APP_USER/.warpei"

echo "== apt packages"
apt-get update
apt-get install -y --no-install-recommends \
    python3 python3-venv python3-dev python3-opencv python3-numpy \
    libsdl2-2.0-0 libegl1 libgles2 libgbm1 libdrm2 \
    v4l-utils git git-lfs

echo "== device permissions for $APP_USER (video, serial, render nodes)"
usermod -aG video,render,dialout,input "$APP_USER" || true

echo "== python environment at $VENV"
mkdir -p "$CONF_DIR"
chown "$APP_USER":"$APP_USER" "$CONF_DIR"
sudo -u "$APP_USER" python3 -m venv --system-site-packages "$VENV"
sudo -u "$APP_USER" "$VENV/bin/pip" install --upgrade pip
sudo -u "$APP_USER" "$VENV/bin/pip" install -e "$SBC_DIR[dev,board]"

echo "== default config"
if [ ! -f "$CONF_DIR/config.json" ]; then
    sudo -u "$APP_USER" cp "$SBC_DIR/configs/warpei_panel.json" "$CONF_DIR/config.json"
    echo "wrote $CONF_DIR/config.json from configs/warpei_panel.json"
fi

echo "== record board state"
{
    echo "## Board state recorded $(date -Is)"
    echo '```'
    echo "image:   $(grep PRETTY_NAME /etc/os-release | cut -d= -f2)"
    echo "kernel:  $(uname -r)"
    echo "python:  $(sudo -u "$APP_USER" "$VENV/bin/python" --version)"
    echo "opencv:  $(sudo -u "$APP_USER" "$VENV/bin/python" -c 'import cv2; print(cv2.__version__)')"
    echo "numpy:   $(sudo -u "$APP_USER" "$VENV/bin/python" -c 'import numpy; print(numpy.__version__)')"
    echo "moderngl:$(sudo -u "$APP_USER" "$VENV/bin/python" -c 'import moderngl; print(moderngl.__version__)' 2>/dev/null || echo ' not installed')"
    echo "GL:      $(sudo -u "$APP_USER" "$VENV/bin/python" -c 'import moderngl; c=moderngl.create_standalone_context(backend="egl"); print(c.info["GL_RENDERER"], c.info["GL_VERSION"])' 2>&1 | tail -1)"
    echo "video devices:"; v4l2-ctl --list-devices 2>/dev/null || true
    echo "serial:  $(ls /dev/ttyS* /dev/ttyUSB* 2>/dev/null | tr '\n' ' ')"
    echo '```'
} >> "$REPO_DIR/docs/board-setup.md"

echo "== systemd service"
install -m 644 "$SBC_DIR/deploy/warpei.service" /etc/systemd/system/warpei.service
sed -i "s|@USER@|$APP_USER|g; s|@SBC_DIR@|$SBC_DIR|g; s|@VENV@|$VENV|g" /etc/systemd/system/warpei.service
systemctl daemon-reload
systemctl enable warpei.service
echo "service installed; start with: sudo systemctl start warpei"
echo "logs:                          journalctl -u warpei -f"
echo
echo "== run the tests as $APP_USER:"
echo "   cd $SBC_DIR && $VENV/bin/pytest"
