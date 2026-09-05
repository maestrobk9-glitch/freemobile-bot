#!/usr/bin/env bash
set -e
export DISPLAY=:99
Xvfb :99 -screen 0 390x844x24 -ac +extension RANDR >/tmp/xvfb.log 2>&1 &
sleep 1
fluxbox >/tmp/fluxbox.log 2>&1 &
sleep 1
exec python /app/vip_webrtc.py
