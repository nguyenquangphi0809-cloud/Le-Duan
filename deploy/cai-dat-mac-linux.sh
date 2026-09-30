#!/usr/bin/env bash
# Cài đặt automaton51 trên macOS hoặc Linux:  bash deploy/cai-dat-mac-linux.sh
# Tạo môi trường Python riêng (.venv) rồi chạy trình cài đặt. Chạy lại để đổi thông tin.
set -e
cd "$(dirname "$0")/.."
if ! command -v python3 >/dev/null 2>&1; then
  echo "Chưa có Python 3."
  echo "  macOS: tải tại https://www.python.org/downloads/macos/ rồi chạy lại lệnh này."
  echo "  Ubuntu/Debian: sudo apt install -y python3 python3-venv  rồi chạy lại."
  exit 1
fi
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv || { echo "Thiếu gói venv. Ubuntu/Debian: sudo apt install -y python3-venv"; exit 1; }
fi
exec .venv/bin/python -m automaton51 --state state install
