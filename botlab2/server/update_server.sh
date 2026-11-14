#!/usr/bin/env bash
# Nieuwe versie van botlab.py / dashboard.html plaatsen. Config en stand blijven staan.
set -euo pipefail
cd "$(dirname "$0")"
if [ "$(id -u)" -ne 0 ]; then echo "Start dit script met sudo."; exit 1; fi
cp ../botlab.py ../dashboard.html /opt/botlab/
chmod 644 /opt/botlab/*
systemctl restart botlab
sleep 3
journalctl -u botlab -n 10 --no-pager || true
