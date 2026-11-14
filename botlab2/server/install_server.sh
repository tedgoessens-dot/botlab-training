#!/usr/bin/env bash
# Botlab op een Ubuntu/Debian-server zetten.
#   sudo bash install_server.sh tailscale              (aanbevolen: alleen bereikbaar via jouw Tailscale-netwerk)
#   sudo bash install_server.sh caddy botlab.jouwdomein.nl   (via internet met automatisch HTTPS-certificaat)
set -euo pipefail
cd "$(dirname "$0")"
MODE="${1:-}"; DOMEIN="${2:-}"
APP=/opt/botlab; DATA=/var/lib/botlab; CFG="$DATA/botlab_config.json"

if [ "$(id -u)" -ne 0 ]; then echo "Start dit script met sudo."; exit 1; fi
if [ "$MODE" != "tailscale" ] && [ "$MODE" != "caddy" ]; then
  echo "Gebruik: sudo bash install_server.sh tailscale"
  echo "     of: sudo bash install_server.sh caddy botlab.jouwdomein.nl"; exit 1
fi
if [ "$MODE" = "caddy" ] && [ -z "$DOMEIN" ]; then echo "Geef een domeinnaam mee, bijv. botlab.jouwdomein.nl"; exit 1; fi

echo "== Pakketten installeren"
apt-get update -y
apt-get install -y python3 ca-certificates curl

echo "== Gebruiker en mappen"
id botlab >/dev/null 2>&1 || useradd --system --home "$DATA" --shell /usr/sbin/nologin botlab
mkdir -p "$APP" "$DATA"
cp ../botlab.py ../dashboard.html "$APP"/
chmod 644 "$APP"/*

if [ "$MODE" = "tailscale" ]; then
  echo "== Tailscale"
  command -v tailscale >/dev/null 2>&1 || curl -fsSL https://tailscale.com/install.sh | sh
  tailscale status >/dev/null 2>&1 || tailscale up
  IP="$(tailscale ip -4 | head -n1)"
  LISTEN="$IP"; PUBLIC="http://$IP:8765"
else
  echo "== Caddy (HTTPS)"
  apt-get install -y caddy
  cat > /etc/caddy/Caddyfile <<CADDY
$DOMEIN {
  encode gzip
  reverse_proxy 127.0.0.1:8765
}
CADDY
  systemctl reload caddy || systemctl restart caddy
  LISTEN="127.0.0.1"; PUBLIC="https://$DOMEIN"
fi

echo "== Configuratie"
python3 - "$CFG" "$LISTEN" "$PUBLIC" <<'PY'
import json, os, sys, secrets
path, listen, public = sys.argv[1:4]
cfg = {}
if os.path.exists(path):
    with open(path, encoding="utf-8-sig") as f:
        cfg = json.load(f)
cfg.setdefault("beurs", "kraken"); cfg.setdefault("api_key", ""); cfg.setdefault("api_secret", "")
cfg.update({"server_modus": True, "telefoon_toegang": True, "luister_adres": listen, "publiek_adres": public})
if len(str(cfg.get("pincode", ""))) < 6:
    cfg["pincode"] = "".join(secrets.choice("0123456789") for _ in range(8))
with open(path, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2)
print("Pincode:", cfg["pincode"])
PY
chown -R botlab:botlab "$DATA"; chmod 700 "$DATA"; chmod 600 "$CFG"

echo "== Service starten"
cp botlab.service /etc/systemd/system/botlab.service
systemctl daemon-reload
systemctl enable --now botlab
systemctl restart botlab
sleep 4
journalctl -u botlab -n 15 --no-pager || true
echo
echo "Klaar. Open op je iPhone: $PUBLIC"
echo "Pincode staat hierboven en in $CFG"
echo "API-sleutel invullen: sudo nano $CFG   daarna: sudo systemctl restart botlab"
