#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Botlab 2 – tradingbots op steun en weerstand, gekoppeld aan Kraken of Bitvavo.
Opdracht: handelen met zo weinig mogelijk risico.

Strategieen:
  - Steunkoper:        koopt net BOVEN een steunlijn, verkoopt net ONDER de weerstand.
  - Weerstandverkoper: shortt net ONDER een weerstand, sluit net BOVEN de steun (alleen papier).
  - Uitbraak omhoog:   koopt als een candle met volume BOVEN een sterke lijn sluit.
  - Uitbraak omlaag:   shortt als een candle met volume ONDER een sterke lijn sluit (alleen papier).
  - Toeval:            controlegroep (alleen papier).

Risico: elke trade heeft vooraf een stop; de positie is zo groot dat de stop (incl. kosten)
precies risico_pct van de bot kost. Handelsstijl uur/dag/week/maand en een marktkompas
(trend, Bitcoin-cyclus, economie, angst-en-hebzucht) bepalen wanneer en met welke inzet.

Standaard PAPIERMODUS. In ECHT-modus doen de long-bots voorstellen en moet je
ELKE order goedkeuren in het dashboard (http://127.0.0.1:8765).
Alleen standaard-Python nodig (3.9+).
"""
import csv, io, json, time, hmac, socket, http.cookies, hashlib, base64, threading, math, random, os, sys, uuid, secrets
import webbrowser, urllib.request, urllib.error, urllib.parse, traceback
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from collections import deque

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("BOTLAB_DATA", HERE)   # map voor config en stand (op een server bijv. /var/lib/botlab)
CFG_PATH = os.path.join(DATA, "botlab_config.json")
STATE_PATH = os.path.join(DATA, "botlab_state.json")
LOG_PATH = os.path.join(DATA, "botlab_logboek.csv")       # volledig logboek van alles wat er gebeurt
TAX_PATH = os.path.join(DATA, "botlab_belasting.json")    # peildatum-waarden per jaar (box 3)
PAGE_PATH = os.path.join(HERE, "dashboard.html")
MOCK = os.environ.get("BOTLAB_MOCK") == "1"   # alleen voor testen: nagebootste beurs

YEAR, DAY, HOUR = 31536000, 86400, 3600
VOL = 0.6  # aangenomen jaarvolatiliteit BTC, om trends te normaliseren

DEFAULT_CFG = {
    "beurs": "kraken",            # "kraken" of "bitvavo"
    "api_key": "",
    "api_secret": "",
    "bitvavo_operator_id": 1001,
    "start_eur": 50,
    "doel_eur": 75,
    "noodrem_eur": 35,
    "fee_pct": 0.40,              # kosten per order: Kraken Pro taker 0,40%; Bitvavo ca. 0,25%
    "risico_pct": 1.0,            # max verlies per trade (incl. kosten) als % van de bot; ook instelbaar in het dashboard
    "handelsstijl": "dag",        # "uur", "dag", "week" of "maand"; ook instelbaar in het dashboard
    "economie": "neutraal",       # "gunstig", "neutraal" of "ongunstig" (jouw inschatting); ook in het dashboard
    "volume_factor": 1.5,         # uitbraak-candle moet 1,5x het gemiddelde volume hebben
    "ema_filter": True,           # bots handelen alleen mee met de EMA-trend (9/20 momentum, 200 trend)
    "max_echt_per_bot_eur": 50,
    "max_echt_totaal_eur": 100,
    "akkoord_geldig_sec": 180,
    "poort": 8765,
    "telefoon_toegang": False,    # true = ook bereikbaar vanaf je iPhone (zelfde wifi of via Tailscale)
    "pincode": "",                # wordt automatisch gemaakt als dit leeg is
    "ntfy_onderwerp": "",         # optioneel: pushmelding via de ntfy-app bij "akkoord nodig"
    "server_modus": False,        # true op een server: iedereen moet inloggen, ook vanaf de server zelf
    "luister_adres": "",          # leeg = automatisch; op een server met Caddy: "127.0.0.1"
    "publiek_adres": "",          # adres voor je iPhone, bijv. http://100.64.1.5:8765 of https://botlab.jouwdomein.nl
}


def load_cfg():
    if not os.path.exists(CFG_PATH):
        with open(CFG_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CFG, f, indent=2)
    with open(CFG_PATH, encoding="utf-8-sig") as f:  # -sig: Kladblok kan een BOM toevoegen
        cfg = json.load(f)
    for k, v in DEFAULT_CFG.items():
        cfg.setdefault(k, v)
    cfg["beurs"] = str(cfg["beurs"]).lower().strip()
    if cfg.get("server_modus"):
        cfg["telefoon_toegang"] = True
    if cfg.get("telefoon_toegang") and len(str(cfg.get("pincode", "")).strip()) < 6:
        cfg["pincode"] = "".join(secrets.choice("0123456789") for _ in range(8))
        with open(CFG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    return cfg


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))   # stuurt niets, kiest alleen het netwerk
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def notify(cfg, title, msg, click=None):
    """Pushmelding via ntfy.sh (gratis app voor iPhone). Alleen als ntfy_onderwerp is ingevuld."""
    topic = str(cfg.get("ntfy_onderwerp", "")).strip()
    if not topic:
        return
    def go():
        try:
            h = {"Title": title.encode("utf-8").decode("latin-1", "ignore"), "Priority": "high", "Tags": "chart_with_upwards_trend"}
            if click:
                h["Click"] = click
            req = urllib.request.Request("https://ntfy.sh/" + urllib.parse.quote(topic), data=msg.encode("utf-8"), headers=h, method="POST")
            urllib.request.urlopen(req, timeout=10).read()
        except Exception as e:
            print("Pushmelding mislukt:", e)
    threading.Thread(target=go, daemon=True).start()


class ExchangeError(Exception):
    pass


def http_json(req):
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        txt = e.read().decode(errors="replace")[:300]
        raise ExchangeError(f"HTTP {e.code} – {txt}")
    except urllib.error.URLError as e:
        raise ExchangeError(f"Geen verbinding ({e.reason})")


# =====================================================================
#  Beurskoppelingen. Alle candles: {"t","o","h","l","c","v"} oplopend in tijd.
# =====================================================================
class Kraken:
    NAME, MARKET, LIMIT = "Kraken", "BTC/EUR", 720
    URL, PAIR = "https://api.kraken.com", "XBTEUR"
    IV = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "1d": 1440}

    def __init__(self, key, secret):
        self.key, self.secret = key.strip(), secret.strip()
        self._nonce = 0

    @property
    def has_keys(self):
        return bool(self.key and self.secret)

    def _pub(self, path, params):
        req = urllib.request.Request(f"{self.URL}/0/public/{path}?{urllib.parse.urlencode(params)}",
                                     headers={"User-Agent": "botlab/2.0"})
        j = http_json(req)
        if j.get("error"):
            raise ExchangeError("Kraken: " + ", ".join(j["error"]))
        return j["result"]

    def _priv(self, path, data=None):
        if not self.has_keys:
            raise ExchangeError("Geen API-sleutel ingesteld in botlab_config.json")
        self._nonce = max(self._nonce + 1, int(time.time() * 1000))
        data = dict(data or {}, nonce=str(self._nonce))
        post = urllib.parse.urlencode(data)
        urlpath = f"/0/private/{path}"
        sha = hashlib.sha256((data["nonce"] + post).encode()).digest()
        sig = base64.b64encode(hmac.new(base64.b64decode(self.secret), urlpath.encode() + sha, hashlib.sha512).digest()).decode()
        req = urllib.request.Request(self.URL + urlpath, data=post.encode(), method="POST",
                                     headers={"API-Key": self.key, "API-Sign": sig, "User-Agent": "botlab/2.0",
                                              "Content-Type": "application/x-www-form-urlencoded"})
        j = http_json(req)
        if j.get("error"):
            raise ExchangeError("Kraken: " + ", ".join(j["error"]))
        return j["result"]

    @staticmethod
    def _first(res):
        return next(v for k, v in res.items() if k != "last")

    def price(self):
        return float(self._first(self._pub("Ticker", {"pair": self.PAIR}))["c"][0])

    def candles(self, interval, limit):
        rows = self._first(self._pub("OHLC", {"pair": self.PAIR, "interval": self.IV[interval]}))
        out = [{"t": int(r[0]), "o": float(r[1]), "h": float(r[2]), "l": float(r[3]), "c": float(r[4]), "v": float(r[6])} for r in rows]
        return out[-limit:]

    def market_info(self):
        m = self._first(self._pub("AssetPairs", {"pair": self.PAIR}))
        return {"decimals": int(m.get("lot_decimals", 8)), "min_base": float(m.get("ordermin", 0.00005)),
                "min_quote": float(m.get("costmin", 0.5) or 0.5)}

    def balances(self):
        b = self._priv("Balance")
        return {"EUR": float(b.get("ZEUR", 0)), "BTC": float(b.get("XXBT", b.get("XBT", 0)))}

    def _order(self, side, volume, validate=False):
        d = {"pair": self.PAIR, "type": side, "ordertype": "market", "volume": volume}
        if validate:
            d["validate"] = "true"
        res = self._priv("AddOrder", d)
        if validate:
            return {"validate": True, "descr": res.get("descr", {})}
        txid = res["txid"][0]
        o = {}
        for _ in range(8):
            time.sleep(1)
            o = self._priv("QueryOrders", {"txid": txid})[txid]
            if o.get("status") in ("closed", "canceled", "expired"):
                break
        vol = float(o.get("vol_exec", 0) or 0)
        return {"id": txid, "status": o.get("status"), "qty": vol, "quote": float(o.get("cost", 0) or 0),
                "fee": float(o.get("fee", 0) or 0)}

    def buy_quote(self, eur, price, info):
        vol = math.floor(eur / price * 10 ** info["decimals"]) / 10 ** info["decimals"]
        if vol < info["min_base"]:
            raise ExchangeError(f"Bedrag te klein: minimaal {info['min_base']} BTC")
        return self._order("buy", f"{vol:.{info['decimals']}f}")

    def sell_base(self, amount_str):
        return self._order("sell", amount_str)

    def test_order(self, price, info):
        return self._order("buy", f"{info['min_base']:.{info['decimals']}f}", validate=True)


class Bitvavo:
    NAME, MARKET, LIMIT = "Bitvavo", "BTC-EUR", 1440
    URL = "https://api.bitvavo.com/v2"

    def __init__(self, key, secret, operator_id):
        self.key, self.secret, self.operator_id = key.strip(), secret.strip(), int(operator_id)

    @property
    def has_keys(self):
        return bool(self.key and self.secret)

    def _req(self, method, path, params=None, body=None, auth=False):
        q = ("?" + urllib.parse.urlencode(params)) if params else ""
        data = json.dumps(body, separators=(",", ":")) if body is not None else ""
        headers = {"Content-Type": "application/json", "User-Agent": "botlab/2.0"}
        if auth:
            if not self.has_keys:
                raise ExchangeError("Geen API-sleutel ingesteld in botlab_config.json")
            ts = str(int(time.time() * 1000))
            sig = hmac.new(self.secret.encode(), (ts + method + "/v2" + path + q + data).encode(), hashlib.sha256).hexdigest()
            headers.update({"Bitvavo-Access-Key": self.key, "Bitvavo-Access-Signature": sig,
                            "Bitvavo-Access-Timestamp": ts, "Bitvavo-Access-Window": "10000"})
        req = urllib.request.Request(self.URL + path + q, data=data.encode() if data else None, method=method, headers=headers)
        try:
            return http_json(req)
        except ExchangeError as e:
            raise ExchangeError("Bitvavo: " + str(e))

    def price(self):
        return float(self._req("GET", "/ticker/price", {"market": self.MARKET})["price"])

    def candles(self, interval, limit):
        rows = self._req("GET", f"/{self.MARKET}/candles", {"interval": interval, "limit": min(limit, 1440)})
        out = [{"t": int(r[0]) // 1000, "o": float(r[1]), "h": float(r[2]), "l": float(r[3]), "c": float(r[4]), "v": float(r[5])} for r in rows]
        out.sort(key=lambda k: k["t"])
        return out

    def market_info(self):
        m = self._req("GET", "/markets", {"market": self.MARKET})
        m = m[0] if isinstance(m, list) else m
        return {"decimals": int(m.get("quantityDecimals", 8)), "min_base": float(m.get("minOrderInBaseAsset", 0) or 0),
                "min_quote": float(m.get("minOrderInQuoteAsset", 5) or 5)}

    def balances(self):
        return {r["symbol"]: float(r.get("available", 0)) for r in self._req("GET", "/balance", auth=True)}

    def _order(self, body):
        body.update({"market": self.MARKET, "orderType": "market", "operatorId": self.operator_id, "clientOrderId": str(uuid.uuid4())})
        o = self._req("POST", "/order", body=body, auth=True)
        for _ in range(6):
            if o.get("status") in ("filled", "canceled", "rejected", "expired"):
                break
            time.sleep(1)
            o = self._req("GET", "/order", {"market": self.MARKET, "orderId": o["orderId"]}, auth=True)
        qty, quote = float(o.get("filledAmount", 0) or 0), float(o.get("filledAmountQuote", 0) or 0)
        fee = float(o.get("feePaid", 0) or 0)
        if o.get("feeCurrency", "EUR") != "EUR" and qty:
            fee *= quote / qty
        return {"id": o.get("orderId"), "status": o.get("status"), "qty": qty, "quote": quote, "fee": fee}

    def buy_quote(self, eur, price, info):
        return self._order({"side": "buy", "amountQuote": f"{eur:.2f}"})

    def sell_base(self, amount_str):
        return self._order({"side": "sell", "amount": amount_str})

    def test_order(self, price, info):
        return None  # Bitvavo kent geen testorder; alleen saldo-check


class FakeExchange:
    """Nagebootste beurs voor testen (BOTLAB_MOCK=1). Doet nooit echte verzoeken."""
    SECS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "1d": 86400}

    def __init__(self, name="Kraken"):
        self.NAME, self.MARKET, self.LIMIT = name + " (test)", "BTC-EUR", 720
        self.rng = random.Random(7)
        self.p, self.t = 62000.0, time.time()
        self.eur, self.btc = 500.0, 0.0
        self.cache = {}
        self.key = "mock"

    has_keys = True

    def _adv(self):
        now = time.time(); dt = max(1e-6, now - self.t); self.t = now
        self.p *= math.exp(VOL / math.sqrt(YEAR) * math.sqrt(dt) * 25 * self.rng.gauss(0, 1))

    def price(self):
        self._adv(); return self.p

    def candles(self, interval, limit):
        sec = self.SECS[interval]; now = int(time.time() // sec * sec)
        if interval not in self.cache:
            sig = VOL * math.sqrt(sec / YEAR) * 1.5; p = self.p; out = []
            center = self.p
            for i in range(limit):  # licht terugtrekkend naar een middenkoers: geeft herkenbare steun/weerstand
                o = p * math.exp(-self.rng.gauss(0, sig) - min(0.5, 0.08 * (sec / 3600) ** 0.3) * math.log(p / center))
                out.append({"t": now - i * sec, "o": o, "h": max(o, p) * (1 + abs(self.rng.gauss(0, sig / 3))),
                            "l": min(o, p) * (1 - abs(self.rng.gauss(0, sig / 3))), "c": p, "v": abs(self.rng.gauss(10, 4))})
                p = o
            self.cache[interval] = out[::-1]
        cs = self.cache[interval]
        while cs[-1]["t"] + sec <= now:
            cs.append({"t": cs[-1]["t"] + sec, "o": self.p, "h": self.p, "l": self.p, "c": self.p, "v": abs(self.rng.gauss(10, 4))})
        return [dict(k) for k in cs[-limit:]]

    def market_info(self):
        return {"decimals": 8, "min_base": 0.00005, "min_quote": 5.0}

    def balances(self):
        return {"EUR": self.eur, "BTC": self.btc}

    def buy_quote(self, q, price, info):
        qty = q / self.p; fee = q * 0.004
        self.eur -= q + fee; self.btc += qty
        return {"id": str(uuid.uuid4()), "status": "closed", "qty": qty, "quote": q, "fee": fee}

    def sell_base(self, a):
        a = float(a); q = a * self.p; fee = q * 0.004
        self.btc -= a; self.eur += q - fee
        return {"id": str(uuid.uuid4()), "status": "closed", "qty": a, "quote": q, "fee": fee}

    def test_order(self, price, info):
        return {"validate": True, "descr": {"order": "buy 0.00005000 XBTEUR @ market"}}


# =====================================================================
#  Marktdata + steun/weerstand
# =====================================================================
INTERVALS = {"1m": (60, 60), "5m": (300, 60), "15m": (900, 60), "1h": (3600, 600), "1d": (86400, 3600)}  # (seconden, verversen)

# Handelsstijlen. mom: candles voor momentum (9/20 EMA) en trend (200 EMA op de tweede).
# lv: candles voor steun/weerstand (periode, gewicht, geheugen, aantal). bar: candle voor uitbraken.
# higher: hogere trend voor het marktkompas. period: verlieslimiet per dag/week/maand.
HZ = {
    "uur":   dict(naam="Uur-traden", uitleg="Snelle trades van minuten tot een paar uur, op 1m- en 5m-candles.",
                  mom=(60, 300), lv=((900, 1.0, 2 * DAY, 192), (300, .6, 12 * HOUR, 144)), bar=300, cool=300,
                  zone=.15, buf=.10, stop=.25, min_range=1.5, dev=.2, rnd=(.006, 600, HOUR),
                  higher=DAY, higher_naam="dag", period=DAY, period_naam="dag", cyc=False),
    "dag":   dict(naam="Dag-traden", uitleg="Trades van een uur tot een dag, op 5m-, 15m- en 1u-candles.",
                  mom=(60, 300), lv=((3600, 1.0, 30 * DAY, 720), (900, .6, 2 * DAY, 192)), bar=900, cool=900,
                  zone=.30, buf=.20, stop=.40, min_range=2.5, dev=.4, rnd=(.015, 900, 4 * HOUR),
                  higher=7 * DAY, higher_naam="week", period=DAY, period_naam="dag", cyc=False),
    "week":  dict(naam="Week-traden", uitleg="Swingtrades van een paar dagen tot een paar weken, op 1u-, 4u- en dagcandles.",
                  mom=(900, 3600), lv=((14400, 1.0, 90 * DAY, 180), (3600, .6, 10 * DAY, 240)), bar=14400, cool=14400,
                  zone=1.0, buf=.5, stop=1.5, min_range=6.0, dev=1.5, rnd=(.05, DAY, 3 * DAY),
                  higher=30 * DAY, higher_naam="maand", period=7 * DAY, period_naam="week", cyc=True),
    "maand": dict(naam="Maand-traden", uitleg="Lange posities van weken tot maanden, op 4u- en dagcandles.",
                  mom=(14400, DAY), lv=((DAY, 1.0, 365 * DAY, 365), (14400, .6, 60 * DAY, 180)), bar=DAY, cool=DAY,
                  zone=2.5, buf=1.0, stop=4.0, min_range=15.0, dev=4.0, rnd=(.12, 3 * DAY, 10 * DAY),
                  higher=YEAR, higher_naam="jaar", period=30 * DAY, period_naam="maand", cyc=True),
}
LBL = {60: "1m", 300: "5m", 900: "15m", 3600: "1u", 14400: "4u", 86400: "1d"}
TFKEY = {60: "1m", 300: "5m", 900: "15m", 3600: "1h", 86400: "1d"}
ECONOMIE = {"gunstig": "Gunstig", "neutraal": "Neutraal", "ongunstig": "Ongunstig"}


def agg(src, B):
    """Candles samenvoegen tot een grotere periode (bijv. 1u -> 4u)."""
    out = []
    for k in src:
        bt = k["t"] // B * B
        if not out or out[-1]["t"] != bt:
            out.append({"t": bt, "o": k["o"], "h": k["h"], "l": k["l"], "c": k["c"], "v": k.get("v", 0)})
        else:
            c = out[-1]
            c["h"] = max(c["h"], k["h"]); c["l"] = min(c["l"], k["l"]); c["c"] = k["c"]; c["v"] += k.get("v", 0)
    return out


def dur(s):
    if s < HOUR:
        return f"{round(s / 60)} min"
    if s < DAY:
        return nl(s / HOUR, 1).replace(",0", "") + " uur"
    return nl(s / DAY, 1).replace(",0", "") + " dagen"


# Angst-en-hebzuchtindex (alternative.me): gratis, zonder sleutel. Valt stil weg als hij niet bereikbaar is.
FNG = {"v": None, "err": False}


def fng_loop():
    while True:
        try:
            req = urllib.request.Request("https://api.alternative.me/fng/?limit=1", headers={"User-Agent": "botlab/2.0"})
            d = http_json(req)["data"][0]
            FNG.update(v=int(d["value"]), err=False)
        except Exception:
            if FNG["v"] is None:
                FNG["err"] = True
        time.sleep(HOUR)


HALVINGS = [1354060800, 1468022400, 1589155200, 1713571200]  # 28-11-2012, 09-07-2016, 11-05-2020, 20-04-2024


def halving_phase(t):
    h0 = max(x for x in HALVINGS if x <= t)
    d = (t - h0) / DAY
    if d < 365:
        return dict(d=d, naam="Opbouw na de halvering", hist="historisch vaak voorzichtig stijgend", long=1.0, short=.5)
    if d < 550:
        return dict(d=d, naam="Stijgfase richting de top", hist="historisch de sterkste stijging van de cyclus", long=1.0, short=.5)
    if d < 900:
        return dict(d=d, naam="Daling na de top", hist="historisch vaak een dalende markt", long=.5, short=1.0)
    return dict(d=d, naam="Bodem en opbouw", hist="historisch vaak zijwaarts tot de volgende halvering", long=1.0, short=1.0)


def compass(m, h, economie):
    """Marktkompas: bepaalt per richting volle inzet (1), halve inzet (0,5) of geen trade (0)."""
    L = Sh = 1.0
    items = []
    z = m.z(h["higher"])
    pa = m.price_at(time.time() - h["higher"])
    ch = (m.price / pa - 1) if pa and m.price else 0.0
    if z > 1.5:
        t, Sh, ef = "Sterk stijgend", 0.0, "geen shorts"
    elif z > .5:
        t, ef = "Stijgend", "short: halve inzet"; Sh *= .5
    elif z < -1.5:
        t, L, ef = "Sterk dalend", 0.0, "geen longs"
    elif z < -.5:
        t, ef = "Dalend", "long: halve inzet"; L *= .5
    else:
        t, ef = "Zijwaarts", ""
    items.append([f"Trend (afgelopen {h['higher_naam']})", f"{t} ({pct(ch, 1)})", ef])
    ph = halving_phase(time.time())
    if h["cyc"]:
        L *= ph["long"]; Sh *= ph["short"]
        ef = "long: halve inzet" if ph["long"] < 1 else "short: halve inzet" if ph["short"] < 1 else ""
    else:
        ef = "telt mee bij week- en maandtraden"
    items.append(["Bitcoin-cyclus (4 jaar)", f"{ph['naam']}, dag {round(ph['d'])} na de halvering: {ph['hist']}", ef])
    if economie == "gunstig":
        Sh *= .5; ef = "short: halve inzet"
    elif economie == "ongunstig":
        L *= .5; ef = "long: halve inzet"
    else:
        ef = ""
    items.append(["Economie (jouw inschatting)", ECONOMIE.get(economie, "Neutraal"), ef])
    v = FNG["v"]
    if v is not None:
        c = "extreme angst" if v < 25 else "angst" if v < 45 else "neutraal" if v <= 55 else "hebzucht" if v <= 75 else "extreme hebzucht"
        if v > 75:
            L *= .5; ef = "long: halve inzet (veel hebzucht = vaak dicht bij een top)"
        elif v < 25:
            Sh *= .5; ef = "short: halve inzet (veel angst = vaak dicht bij een bodem)"
        else:
            ef = ""
        items.append(["Angst & hebzucht", f"{v} van 100 · {c}", ef])
    else:
        items.append(["Angst & hebzucht", "niet bereikbaar" if FNG["err"] else "laden…", ""])
    return {"long": L if L >= .25 else 0.0, "short": Sh if Sh >= .25 else 0.0, "items": items}


def rsi(closes, n=14):
    if len(closes) < n + 1:
        return 50.0
    g = l = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]; g += max(d, 0); l += max(-d, 0)
    g /= n; l /= n
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        g = (g * (n - 1) + max(d, 0)) / n; l = (l * (n - 1) + max(-d, 0)) / n
    return 100.0 if l == 0 else 100 - 100 / (1 + g / l)


def ema(vals, n):
    """Exponential Moving Average; begint met het gemiddelde van de eerste n waarden."""
    if len(vals) < n:
        return [None] * len(vals)
    k, out = 2 / (n + 1), [None] * (n - 1)
    e = sum(vals[:n]) / n
    out.append(e)
    for v in vals[n:]:
        e = v * k + e * (1 - k)
        out.append(e)
    return out


def ema_signal(m, h):
    """Signaal: 9/20 EMA voor momentum, 200 EMA voor de trend en een cyclusmeter, op de candles van de handelsstijl."""
    p, zone = m.price, h["zone"]
    L1, L2 = LBL[h["mom"][0]], LBL[h["mom"][1]]
    A = [x["c"] for x in m.candles(h["mom"][0])[-300:]]
    Bc = m.candles(h["mom"][1])[-300:]
    B = [x["c"] for x in Bc]
    ef = {9: ema(A, 9)[-1] if A else None, 20: ema(A, 20)[-1] if A else None}
    es = {9: ema(B, 9)[-1] if B else None, 20: ema(B, 20)[-1] if B else None, 200: ema(B, 200)[-1] if B else None}
    upF = ef[9] is not None and ef[20] is not None and ef[9] > ef[20]
    upS = es[9] is not None and es[20] is not None and es[9] > es[20]
    trend = None if es[200] is None else (1 if p > es[200] else -1)
    d20 = (p / es[20] - 1) * 100 if es[20] else 0.0
    win = Bc[-50:]
    lo, hi = (min(x["l"] for x in win), max(x["h"] for x in win)) if win else (p, p)
    cyc = min(100.0, max(0.0, (p - lo) / (hi - lo) * 100)) if hi > lo else 50.0
    ds = (p / m.sup["p"] - 1) * 100 if m.sup else None
    dr = (m.res["p"] / p - 1) * 100 if m.res else None
    near_sup = ds is not None and -0.1 <= ds <= zone
    near_res = dr is not None and -0.1 <= dr <= zone
    low, high = near_sup or d20 <= -h["dev"] or cyc <= 10, near_res or d20 >= h["dev"] or cyc >= 90
    act = "KOPEN" if (low and not high and trend == 1) else "VERKOPEN" if (high and not low) else "HOUDEN"
    why = [
        (f"Laagpunt: koers vlak boven steun {num(m.sup['p'])}" if near_sup else
         f"Laagpunt: koers {nl(-d20)}% onder de 20 EMA ({L2})" if d20 <= -h["dev"] else
         "Geen laagpunt: niet bij steun en niet ver onder de 20 EMA"),
        (f"Hoogtepunt: koers vlak onder weerstand {num(m.res['p'])}" if near_res else
         f"Hoogtepunt: koers {nl(d20)}% boven de 20 EMA ({L2})" if d20 >= h["dev"] else
         "Geen hoogtepunt: niet bij weerstand en niet ver boven de 20 EMA"),
        f"Cyclus: koers staat op {round(cyc)}% van de bandbreedte van de laatste 50 × {L2}-candles (0% = bodem, 100% = top)",
        (f"Nog te weinig {L2}-data voor de 200 EMA" if trend is None else
         f"Trend: koers {'boven' if trend == 1 else 'onder'} de 200 EMA ({L2}) {num(es[200])}"
         + (" → laagpunt, maar tegen de trend in: niet kopen" if low and trend != 1 else "")),
        f"Momentum: 9 EMA {'boven' if upS else 'onder'} 20 EMA ({L2}), {'boven' if upF else 'onder'} ({L1})",
    ]
    return {"actie": act, "trend": trend, "upF": upF, "upS": upS, "ema": {L1: ef, L2: es}, "why": why, "cyc": cyc}


def find_levels(m, h, price, k=3):
    """Steun/weerstand uit swing-toppen en -bodems (pivots) op de candles van de handelsstijl.
       Sterkte = aantal aanrakingen, met extra gewicht voor recente pivots en de grotere tijdschaal."""
    pts, now = [], time.time()
    tol, far = max(0.35, h["zone"] * 1.2), max(0.10, h["min_range"] * 3 / 100)
    for B, w, span, n in h["lv"]:
        cs = m.candles(B)[-n:]
        for i in range(k, len(cs) - k):
            win = cs[i - k:i + k + 1]
            rec = 0.5 + 0.5 * max(0.0, 1 - (now - cs[i]["t"]) / span)
            if cs[i]["h"] >= max(x["h"] for x in win):
                pts.append((cs[i]["h"], w * rec, cs[i]["t"]))
            if cs[i]["l"] <= min(x["l"] for x in win):
                pts.append((cs[i]["l"], w * rec, cs[i]["t"]))
    pts.sort()
    clusters = []
    for p, w, t in pts:
        if clusters and abs(p / clusters[-1]["p"] - 1) * 100 <= tol:
            c = clusters[-1]
            c["p"] = (c["p"] * c["w"] + p * w) / (c["w"] + w); c["w"] += w; c["n"] += 1; c["t"] = max(c["t"], t)
        else:
            clusters.append({"p": p, "w": w, "n": 1, "t": t})
    lv = [c for c in clusters if c["n"] >= 2 and abs(c["p"] / price - 1) < far]
    for c in lv:
        c["kind"] = "steun" if c["p"] < price else "weerstand"
        c["dist"] = c["p"] / price - 1
    lv.sort(key=lambda c: abs(c["dist"]))
    sup = next((c for c in lv if c["kind"] == "steun" and c["w"] >= 1.5), None)
    res = next((c for c in lv if c["kind"] == "weerstand" and c["w"] >= 1.5), None)
    return lv[:12], sup, res


class Market:
    def __init__(self, ex):
        self.ex = ex
        self.ticks = deque(maxlen=900)
        self.c = {k: [] for k in INTERVALS}
        self.last_fetch, self.closed, self.events = {}, {}, set()
        self.price = self.err = None
        self.last_ok = 0
        self.rsi = 50.0
        self.levels, self.sup, self.res = [], None, None
        self.vol_avg = 0
        self.signal = {"actie": "HOUDEN", "trend": None, "upF": False, "upS": False, "ema": {}, "why": [], "cyc": 50}
        self.info = {"decimals": 8, "min_base": 0.00005, "min_quote": 5.0}
        self.hz = "dag"         # handelsstijl, wordt door de Engine gezet
        self.cb = None          # afgesloten candles van de uitbraak-periode
        self.new_bar = False    # True in de ronde waarin een uitbraak-candle net is afgesloten

    def candles(self, B):
        """Candles van B seconden; 4u wordt opgebouwd uit 1u-candles."""
        if B == 14400:
            return agg(self.c["1h"], 14400)
        return self.c[TFKEY[B]]

    def closed_bars(self, B, n):
        now = time.time()
        return [x for x in self.candles(B)[-(n + 3):] if x["t"] + B <= now][-n:]

    def bar_event(self, B):
        if B == 14400:
            cs = self.c["1h"]
            return "1h" in self.events and len(cs) >= 2 and (cs[-2]["t"] + 3600) % 14400 == 0
        return TFKEY[B] in self.events

    def reset_analysis(self):
        self.levels, self.sup, self.res, self.cb = [], None, None, None

    @property
    def ready(self):
        return self.price is not None and all(self.c[k] for k in INTERVALS)

    def update(self):
        now = time.time()
        p = self.ex.price()
        self.price = p
        self.ticks.append((now, p))
        if "info" not in self.last_fetch:
            try:
                self.info = self.ex.market_info(); self.last_fetch["info"] = now
            except Exception:
                pass
        for k, (sec, ref) in INTERVALS.items():
            lf = self.last_fetch.get(k, 0)
            # ververs op vaste momenten, en ook kort na elke candle-grens, zodat een afgesloten candle volledig is
            if now - lf >= ref or (int(now // sec) != int(lf // sec) and now % sec >= 3):
                self.c[k] = self.ex.candles(k, self.ex.LIMIT)
                self.last_fetch[k] = now
        self._patch(now, p)
        self.events = set()
        for k in INTERVALS:
            cs = self.c[k]
            if len(cs) >= 2 and self.closed.get(k) != cs[-2]["t"] and self.last_fetch.get(k, 0) >= cs[-1]["t"] + 3:
                self.closed[k] = cs[-2]["t"]
                self.events.add(k)
        h = HZ[self.hz]
        self.new_bar = self.bar_event(h["bar"])
        if "15m" in self.events or not self.levels:
            self.rsi = rsi([x["c"] for x in self.c["15m"][:-1][-200:]])
        if self.new_bar or self.cb is None:
            self.cb = self.closed_bars(h["bar"], 24)
            vols = [x.get("v", 0) for x in self.cb[-21:-1]]
            self.vol_avg = sum(vols) / len(vols) if vols else 0
        if self.new_bar or "1h" in self.events or not self.levels or int(now) % 30 == 0:
            self.levels, self.sup, self.res = find_levels(self, h, p)
        self.signal = ema_signal(self, h)
        self.err = None
        self.last_ok = now

    def _patch(self, now, p):
        for k, (sec, _) in INTERVALS.items():
            cs = self.c[k]
            if not cs:
                continue
            last = cs[-1]
            if now < last["t"] + sec:
                last["h"] = max(last["h"], p); last["l"] = min(last["l"], p); last["c"] = p
            else:
                cs.append({"t": int(now // sec * sec), "o": p, "h": p, "l": p, "c": p, "v": 0})
                if len(cs) > self.ex.LIMIT + 50:
                    del cs[0]

    def price_at(self, ts):
        now = time.time()
        if ts >= now or self.price is None:
            return self.price
        if self.ticks and ts >= self.ticks[0][0]:
            for t, p in reversed(self.ticks):
                if t <= ts:
                    return p
            return self.ticks[0][1]
        for k in ("1m", "5m", "15m", "1h", "1d"):
            cs = self.c[k]
            if cs and ts >= cs[0]["t"]:
                lo, hi = 0, len(cs) - 1
                while lo < hi:
                    mid = (lo + hi + 1) // 2
                    if cs[mid]["t"] <= ts:
                        lo = mid
                    else:
                        hi = mid - 1
                return cs[lo]["c"]
        cs = self.c["1d"]
        return cs[0]["o"] if cs else self.price

    def z(self, secs):
        pa = self.price_at(time.time() - secs)
        if not pa or not self.price:
            return 0.0
        return math.log(self.price / pa) / (VOL * math.sqrt(secs / YEAR))


# =====================================================================
#  Bots
# =====================================================================
DEFS = [
    {"id": "steun", "naam": "Steunkoper", "kleur": "#22c55e", "long": True,
     "uitleg": "Koopt net boven een steunlijn en verkoopt net onder de weerstand. Stop net onder de steun."},
    {"id": "weerstand", "naam": "Weerstandverkoper", "kleur": "#ef4444", "long": False,
     "uitleg": "Shortt net onder een weerstandlijn en sluit net boven de steun. Stop net boven de weerstand. Alleen papier."},
    {"id": "bo_up", "naam": "Uitbraak omhoog", "kleur": "#38bdf8", "long": True,
     "uitleg": "Koopt als een {bar}-candle met extra volume boven een sterke lijn sluit. Doel: de breedte van de range erbij."},
    {"id": "bo_down", "naam": "Uitbraak omlaag", "kleur": "#a78bfa", "long": False,
     "uitleg": "Shortt als een {bar}-candle met extra volume onder een sterke lijn sluit. Alleen papier."},
    {"id": "rnd", "naam": "Toeval", "kleur": "#f472b6", "long": False,
     "uitleg": "Gooit een munt. Controlegroep: een slimme bot moet deze verslaan. Alleen papier."},
]
DEF = {d["id"]: d for d in DEFS}
PERIODS = [("uur", HOUR), ("dag", DAY), ("week", 7 * DAY), ("maand", 30 * DAY), ("jaar", YEAR)]
SCALES = [("Seconde", 10, "10 s"), ("Uur", HOUR, ""), ("Dag", DAY, ""), ("Week", 7 * DAY, ""), ("Maand", 30 * DAY, ""), ("Jaar", YEAR, "")]


def eur(x):
    return ("€ {:,.2f}".format(x)).replace(",", "X").replace(".", ",").replace("X", ".")


def num(x):
    return "{:,.0f}".format(x).replace(",", ".")


def nl(x, d=2):
    return f"{x:.{d}f}".replace(".", ",")


def pct(x, d=2):
    return ("+" if x >= 0 else "−") + f"{abs(x) * 100:.{d}f}".replace(".", ",") + "%"


LOG_COLS = ["datum_tijd", "bot", "modus", "actie", "koers_eur", "aantal_btc", "bedrag_eur", "kosten_eur", "resultaat_eur", "toelichting", "order_id"]
LOG_LOCK = threading.Lock()


def dec(x, d=2):
    """Getal met decimale komma (voor Excel in het Nederlands)."""
    return "" if x is None else f"{x:.{d}f}".replace(".", ",")


def undec(x):
    try:
        return float(str(x).replace(",", ".")) if str(x).strip() != "" else None
    except ValueError:
        return None


def logboek_write(row):
    """Elke gebeurtenis komt in botlab_logboek.csv (puntkomma-gescheiden, opent direct in Excel)."""
    with LOG_LOCK:
        new = not os.path.exists(LOG_PATH)
        with open(LOG_PATH, "a", encoding="utf-8-sig" if new else "utf-8", newline="") as f:
            w = csv.writer(f, delimiter=";")
            if new:
                w.writerow(LOG_COLS)
            w.writerow([row.get(k, "") for k in LOG_COLS])


def logboek_read(limit=None):
    if not os.path.exists(LOG_PATH):
        return []
    with LOG_LOCK, open(LOG_PATH, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    return rows[-limit:] if limit else rows


def jan1(year):
    return time.mktime((year, 1, 1, 0, 0, 0, 0, 0, -1))  # 1 januari 00:00 lokale tijd


class Engine:
    def __init__(self, cfg, ex, market):
        self.cfg, self.ex, self.m = cfg, ex, market
        self.lock = threading.RLock()
        self.mode = "papier"
        self.bots, self.trades, self.marks, self.pending = [], [], [], []
        self.rng = random.Random()
        self.last_sample = self.last_save = 0
        self.last_step = time.time()
        hz = str(cfg.get("handelsstijl", "dag")).lower()
        self.settings = {"risico_pct": float(cfg.get("risico_pct", 1.0)), "handelsstijl": hz if hz in HZ else "dag",
                         "economie": str(cfg.get("economie", "neutraal")).lower()}
        self.kompas = {"long": 1.0, "short": 1.0, "items": []}
        self.tax = self.load_tax()
        self.tax_busy = False
        if not self.load():
            self.reset_bots()
        self.apply_market()

    # ---------- instellingen ----------
    @property
    def h(self):
        return HZ[self.settings["handelsstijl"]]

    @property
    def fee(self):
        return self.cfg["fee_pct"] / 100

    def apply_market(self):
        self.m.hz = self.settings["handelsstijl"]
        self.m.reset_analysis()

    def rr_min(self):
        r = self.settings["risico_pct"]
        return 2.5 if r <= 0.5 else 2.0 if r <= 1 else 1.75 if r <= 2 else 1.5

    def rr_net(self, tp, sl):
        """Winst/risico na aftrek van de kosten voor kopen en verkopen."""
        p = self.m.price
        c = 2 * self.fee * p
        return (abs(tp - p) - c) / (abs(p - sl) + c)

    def set_settings(self, body):
        st, changed = dict(self.settings), []
        if "risico_pct" in body:
            try:
                r = round(min(5.0, max(0.25, float(body["risico_pct"]))) * 4) / 4
            except (TypeError, ValueError):
                return False, "Ongeldig risico."
            if r != st["risico_pct"]:
                st["risico_pct"] = r; changed.append(f"risico {nl(r)}%")
        if "economie" in body:
            e = str(body["economie"]).lower()
            if e not in ECONOMIE:
                return False, "Ongeldige keuze voor economie."
            if e != st["economie"]:
                st["economie"] = e; changed.append(f"economie {ECONOMIE[e].lower()}")
        new_hz = False
        if "handelsstijl" in body:
            hz = str(body["handelsstijl"]).lower()
            if hz not in HZ:
                return False, "Ongeldige handelsstijl."
            if hz != st["handelsstijl"]:
                if any(b["live"] and b["pos"] for b in self.bots) or self.pending:
                    return False, "Er staan nog echte posities of voorstellen open. Sluit die eerst af voordat je de handelsstijl wijzigt."
                st["handelsstijl"] = hz; new_hz = True; changed.append(HZ[hz]["naam"].lower())
        if not changed:
            return True, "Niets gewijzigd."
        self.settings = st
        self.log(None, "Instelling gewijzigd", ", ".join(changed), None, None, False)
        if new_hz:
            self.apply_market()
            self.reset_bots()
        self.kompas = compass(self.m, self.h, self.settings["economie"]) if self.m.ready else self.kompas
        self.save()
        return True, "Opgeslagen: " + ", ".join(changed) + (". Bots opnieuw gestart." if new_hz else ".")

    # ---------- opslag ----------
    def load(self):
        try:
            with open(STATE_PATH, encoding="utf-8") as f:
                s = json.load(f)
            if s.get("versie") != 2 or s.get("beurs") != self.ex.NAME:
                return False
            self.mode, self.bots, self.trades, self.marks = s["mode"], s["bots"], s["trades"], s["marks"]
            self.settings.update({k: v for k, v in s.get("settings", {}).items() if k in self.settings})
            if self.settings["handelsstijl"] not in HZ:
                self.settings["handelsstijl"] = "dag"
            for b in self.bots:  # oudere stand: nieuwe velden aanvullen
                b.setdefault("streak", 0); b.setdefault("pauze", False)
                b.setdefault("per_key", int(time.time() // self.h["period"])); b.setdefault("per_start", b["cash"])
            return True
        except FileNotFoundError:
            return False
        except Exception as e:
            print("Kon opgeslagen staat niet lezen, start opnieuw:", e)
            return False

    def save(self):
        tmp = STATE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"versie": 2, "beurs": self.ex.NAME, "mode": self.mode, "settings": self.settings, "bots": self.bots,
                       "trades": self.trades[:200], "marks": self.marks[-400:]}, f)
        os.replace(tmp, STATE_PATH)

    # ---------- bots ----------
    def next_rnd(self, now):
        r = self.h["rnd"]
        return now + r[1] + self.rng.random() * (r[2] - r[1])

    def make_bot(self, d, live, start):
        c, now = self.cfg, time.time()
        r = start / c["start_eur"]
        return {"id": d["id"], "live": live, "start": start, "doel": round(c["doel_eur"] * r, 2), "rem": round(c["noodrem_eur"] * r, 2),
                "cash": start, "pos": None, "n": 0, "closed": 0, "wins": 0, "eq": [[now, start]], "peak": start, "maxdd": 0.0,
                "status": "actief", "thought": "Opstarten: koersdata en lijnen verzamelen…", "cool": 0,
                "next": self.next_rnd(now), "snooze": 0, "streak": 0, "pauze": False,
                "per_key": int(now // self.h["period"]), "per_start": start}

    def reset_bots(self):
        c = self.cfg
        self.bots = []
        for d in DEFS:
            live = self.mode == "echt" and d["long"]
            start = min(c["start_eur"], c["max_echt_per_bot_eur"]) if live else c["start_eur"]
            self.bots.append(self.make_bot(d, live, start))
        self.marks, self.pending = [], []
        self.log(None, "Bots gestart", f"Beurs: {self.ex.NAME} · modus: {self.mode.upper()} · {self.h['naam']} · "
                                       f"risico {nl(self.settings['risico_pct'])}% per trade", None, None, False)

    def equity(self, b):
        P, p = b["pos"], self.m.price
        if not P or not p:
            return b["cash"]
        return b["cash"] + P["qty"] * p if P["side"] == 1 else b["cash"] + (P["entry"] - p) * P["qty"]

    def log(self, b, actie, why, pnl, ret, echt, qty=None, quote=None, fee=None, order=None, price=None):
        now, p = time.time(), price if price is not None else self.m.price
        self.trades.insert(0, {"t": now, "bot": b["id"] if b else None, "actie": actie, "p": p, "why": why, "pnl": pnl, "ret": ret,
                               "echt": echt, "qty": qty, "quote": quote, "fee": fee, "order": order})
        del self.trades[300:]
        try:
            logboek_write({"datum_tijd": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
                           "bot": DEF[b["id"]]["naam"] if b else "Systeem", "modus": "echt" if echt else self.mode if not b else "papier",
                           "actie": actie, "koers_eur": dec(p, 2), "aantal_btc": dec(qty, 8), "bedrag_eur": dec(quote, 2),
                           "kosten_eur": dec(fee, 2), "resultaat_eur": dec(pnl, 2), "toelichting": why, "order_id": order or ""})
        except Exception as e:
            print("Logboek schrijven mislukt:", e)

    def mark(self, b, side, kind, p):
        self.marks.append({"t": time.time(), "p": p, "side": side, "kind": kind, "c": DEF[b["id"]]["kleur"]})
        del self.marks[:-400]

    def has_pending(self, b):
        return any(x["bot"] == b["id"] for x in self.pending)

    # ---------- positiegrootte op risico ----------
    def size_for(self, b, side, sl):
        """Zo groot dat het verlies bij de stop, inclusief kosten, precies het gekozen risico is (x ruimte van het kompas).
           Nooit groter dan het eigen geld van de bot: geen hefboom."""
        p, fee = self.m.price, self.fee
        mult = self.kompas["long"] if side == 1 else self.kompas["short"]
        risk_eur = self.equity(b) * self.settings["risico_pct"] / 100 * mult
        per = max(abs(p - sl), p * 0.0005) + 2 * fee * p
        cap = b["cash"] * 0.95
        if b["live"]:
            cap = min(cap, self.cfg["max_echt_per_bot_eur"] * 0.97)
        qty = max(0.0, min(risk_eur / per, cap / p / (1 + fee)))
        return qty, min(risk_eur, qty * per), mult

    # ---------- openen / sluiten ----------
    def open(self, b, side, why, tp, sl, trail=None):
        """tp en sl zijn absolute koersen; trail = meeschuivende stop als fractie."""
        now, p = time.time(), self.m.price
        mult = self.kompas["long"] if side == 1 else self.kompas["short"]
        if mult <= 0:
            b["thought"] = f"Kans op {'kopen' if side == 1 else 'shorten'}, maar het marktkompas staat nu geen {'long' if side == 1 else 'short'} toe. Veiligheid eerst: wacht."
            b["cool"] = now + self.h["cool"]
            return
        qty, risk, mult = self.size_for(b, side, sl)
        opts = {"tpP": tp, "slP": sl, "trail": trail, "risk": risk}
        extra = f". Max verlies {eur(risk)} ({nl(self.settings['risico_pct'])}% risico{', halve inzet door marktkompas' if mult < 1 else ''})"
        if b["live"]:
            q = math.floor(qty * p * 100) / 100
            if q < self.m.info["min_quote"]:
                b["thought"] = (f"Kans gezien, maar bij {nl(self.settings['risico_pct'])}% risico wordt de order maar {eur(q)}. "
                                f"{self.ex.NAME} vraagt minimaal {eur(self.m.info['min_quote'])}. Overgeslagen.")
                b["cool"] = now + self.h["cool"]
                return
            self.propose(b, "buy", why + extra, amount_quote=q, opts=opts)
            return
        if qty * p < 1:
            b["thought"] = f"Positie zou kleiner zijn dan €1 bij {nl(self.settings['risico_pct'])}% risico. Overgeslagen."
            b["cool"] = now + self.h["cool"]
            return
        notional = qty * p
        f = notional * self.fee
        b["cash"] -= (notional + f) if side == 1 else f
        b["pos"] = dict(side=side, qty=qty, entry=p, t=now, fee=f, ext=p, borrow=0.0, **opts)
        b["n"] += 1
        self.log(b, "Open long" if side == 1 else "Open short", why + extra, None, None, False, qty=qty, quote=notional, fee=f)
        self.mark(b, side, "open", p)
        b["thought"] = f"{'Long' if side == 1 else 'Short'} geopend (papier) voor {eur(notional)}. Doel {num(tp)}, stop {num(sl)}. Max verlies {eur(risk)}."

    def close(self, b, why, final=None):
        if b["live"]:
            if time.time() < b.get("snooze", 0) and not final:
                b["thought"] = f"Wil verkopen ({why}), maar je wees dit kort geleden af."
                return
            self.propose(b, "sell", why, final=final)
            return
        P, p = b["pos"], self.m.price
        exit_fee = P["qty"] * p * self.fee
        if P["side"] == 1:
            b["cash"] += P["qty"] * p - exit_fee
            pnl = P["qty"] * (p - P["entry"]) - P["fee"] - exit_fee
        else:
            b["cash"] += (P["entry"] - p) * P["qty"] - exit_fee
            pnl = (P["entry"] - p) * P["qty"] - P["fee"] - exit_fee - P["borrow"]
        self.finish_close(b, P, why, pnl, p, False, final, qty=P["qty"], quote=P["qty"] * p, fee=exit_fee)

    def finish_close(self, b, P, why, pnl, p, echt, final, qty=None, quote=None, fee=None, order=None):
        now, h = time.time(), self.h
        b["closed"] += 1
        b["pos"] = None
        b["cool"] = now + h["cool"]
        b["next"] = self.next_rnd(now)
        if pnl > 0:
            b["wins"] += 1; b["streak"] = 0
        else:
            b["streak"] = b.get("streak", 0) + 1
            if b["streak"] >= 2:
                b["streak"], b["pauze"], b["cool"] = 0, True, now + h["cool"] * 4
        self.log(b, "Sluit long" if P["side"] == 1 else "Sluit short", why, pnl, pnl / (P["qty"] * P["entry"]), echt,
                 qty=qty, quote=quote, fee=fee, order=order, price=p)
        self.mark(b, P["side"], "close", p)
        if final:
            notify(self.cfg, "Botlab: " + ("doel gehaald" if final == "doel" else "noodrem"), f"{DEF[b['id']]['naam']}: {eur(b['cash'])}", PHONE_URL)
            b["status"] = final
            b["thought"] = (f"Doel gehaald: {eur(b['cash'])}. Bot staat stil." if final == "doel"
                            else f"Noodrem geraakt bij {eur(b['cash'])}. Bot staat stil.")

    # ---------- akkoord ----------
    def propose(self, b, kind, why, amount_quote=None, opts=None, final=None):
        if self.has_pending(b):
            return
        now = time.time()
        pr = {"id": uuid.uuid4().hex[:12], "bot": b["id"], "kind": kind, "why": why, "created": now,
              "expires": now + self.cfg["akkoord_geldig_sec"], "price": self.m.price, "final": final}
        if kind == "buy":
            pr.update(amount_quote=amount_quote, opts=opts or {})
        else:
            pr.update(qty=b["pos"]["qty"], entry=b["pos"]["entry"])
        self.pending.append(pr)
        b["thought"] = f"Wacht op jouw akkoord: {'kopen' if kind == 'buy' else 'verkopen'}. {why}"
        self.log(b, "Voorstel " + ("kopen" if kind == "buy" else "verkopen"), why, None, None, True,
                 quote=amount_quote if kind == "buy" else None, qty=None if kind == "buy" else b["pos"]["qty"])
        print(f"[AKKOORD NODIG] {DEF[b['id']]['naam']}: {kind} – {why}")
        notify(self.cfg, f"Botlab: akkoord nodig ({'KOPEN' if kind == 'buy' else 'VERKOPEN'})",
               f"{DEF[b['id']]['naam']} wil {'kopen voor ' + eur(amount_quote) if kind == 'buy' else 'verkopen'}. {why}", PHONE_URL)

    def _bot(self, bid):
        return next(b for b in self.bots if b["id"] == bid)

    def reject(self, pid, reason="Afgewezen door jou"):
        pr = next((x for x in self.pending if x["id"] == pid), None)
        if not pr:
            return False, "Voorstel bestaat niet meer."
        self.pending.remove(pr)
        b = self._bot(pr["bot"])
        if pr["kind"] == "buy":
            b["cool"] = time.time() + self.h["cool"]
        else:
            b["snooze"] = time.time() + self.h["cool"]
        b["thought"] = f"{reason}: {'koop' if pr['kind'] == 'buy' else 'verkoop'} niet uitgevoerd."
        self.log(b, "Voorstel " + ("verlopen" if "Verlopen" in reason else "afgewezen"),
                 f"{'Kopen' if pr['kind'] == 'buy' else 'Verkopen'}: {pr['why']}", None, None, True)
        return True, "Afgewezen."

    def approve(self, pid):
        pr = next((x for x in self.pending if x["id"] == pid), None)
        if not pr:
            return False, "Voorstel bestaat niet meer (verlopen?)."
        if time.time() > pr["expires"]:
            self.reject(pid, "Verlopen")
            return False, "Voorstel was verlopen."
        self.pending.remove(pr)
        b = self._bot(pr["bot"])
        try:
            if pr["kind"] == "buy":
                o = self.ex.buy_quote(pr["amount_quote"], self.m.price, self.m.info)
                if o["qty"] <= 0:
                    raise ExchangeError(f"Order niet gevuld (status {o.get('status')})")
                px = o["quote"] / o["qty"]
                b["cash"] -= o["quote"] + o["fee"]
                b["pos"] = dict(side=1, qty=o["qty"], entry=px, t=time.time(), fee=o["fee"], ext=px, borrow=0.0, order=o["id"], **pr["opts"])
                b["n"] += 1
                self.log(b, "Open long", f"ECHT gekocht voor {eur(o['quote'])} (kosten {eur(o['fee'])}). {pr['why']}", None, None, True,
                         qty=o["qty"], quote=o["quote"], fee=o["fee"], order=o["id"], price=px)
                self.mark(b, 1, "open", px)
                b["thought"] = f"Gekocht met echt geld. Doel {num(pr['opts']['tpP'])}, stop {num(pr['opts']['slP'])}."
            else:
                P, dc = b["pos"], self.m.info["decimals"]
                try:
                    avail = self.ex.balances().get("BTC", P["qty"])
                except Exception:
                    avail = P["qty"]
                amt = math.floor(min(P["qty"], avail) * 10 ** dc) / 10 ** dc
                if amt <= 0:
                    raise ExchangeError("Geen BTC beschikbaar om te verkopen")
                o = self.ex.sell_base(f"{amt:.{dc}f}")
                if o["qty"] <= 0:
                    raise ExchangeError(f"Order niet gevuld (status {o.get('status')})")
                b["cash"] += o["quote"] - o["fee"]
                pnl = o["quote"] - o["fee"] - o["qty"] * P["entry"] - P["fee"] * (o["qty"] / P["qty"])
                self.finish_close(b, P, f"ECHT verkocht voor {eur(o['quote'])}. {pr['why']}", pnl, o["quote"] / o["qty"], True, pr["final"],
                                  qty=o["qty"], quote=o["quote"], fee=o["fee"], order=o["id"])
            self.save()
            return True, "Order uitgevoerd."
        except Exception as e:
            self.log(b, "Order mislukt", str(e), None, None, True)
            b["thought"] = f"Order mislukt: {e}"
            b["cool"] = time.time() + 600
            return False, f"Order mislukt: {e}"

    # ---------- modus ----------
    def live_need(self):
        return min(self.cfg["start_eur"], self.cfg["max_echt_per_bot_eur"]) * sum(1 for d in DEFS if d["long"])

    def set_mode(self, mode):
        if mode == self.mode:
            return True, f"Modus was al {mode}."
        if any(b["live"] and b["pos"] for b in self.bots):
            return False, "Er staan nog echte posities open. Verkoop die eerst (of gebruik Noodstop)."
        if mode == "echt":
            if not self.ex.has_keys:
                return False, "Vul eerst je API-sleutel en geheim in botlab_config.json in en herstart."
            need = self.live_need()
            if need > self.cfg["max_echt_totaal_eur"]:
                return False, f"Budget {eur(need)} is hoger dan max_echt_totaal_eur ({eur(self.cfg['max_echt_totaal_eur'])})."
            try:
                bal = self.ex.balances()
            except Exception as e:
                return False, f"Verbindingstest mislukt: {e}"
            if bal.get("EUR", 0) < need:
                return False, f"Te weinig euro op {self.ex.NAME}: {eur(bal.get('EUR', 0))} beschikbaar, {eur(need)} nodig."
        self.mode = mode
        self.log(None, "Modus gewijzigd", "ECHT GELD aangezet door jou" if mode == "echt" else "Terug naar papier", None, None, mode == "echt")
        self.reset_bots()
        self.save()
        return True, ("ECHT handelen staat aan. Elke order vraagt jouw akkoord." if mode == "echt" else "Terug naar papiermodus.")

    def noodstop(self):
        msgs = []
        self.log(None, "Noodstop", "Noodstop ingedrukt door jou", None, None, self.mode == "echt")
        for b in self.bots:
            self.pending = [x for x in self.pending if x["bot"] != b["id"]]
            if b["live"] and b["pos"]:
                self.propose(b, "sell", "Noodstop door jou", final="rem")
                ok, msg = self.approve(self.pending[-1]["id"])
                msgs.append(f"{DEF[b['id']]['naam']}: {msg}")
            if b["status"] == "actief":
                if b["pos"] and not b["live"]:
                    self.close(b, "Noodstop door jou")
                b["status"] = "rem"
                b["thought"] = "Gestopt met noodstop."
        self.save()
        return True, " ".join(msgs) or "Alle bots gestopt."

    # ---------- hoofdlus ----------
    def step(self):
        now = time.time()
        dt, self.last_step = now - self.last_step, now
        self.kompas = compass(self.m, self.h, self.settings["economie"])
        for pr in list(self.pending):
            if now > pr["expires"]:
                self.reject(pr["id"], "Verlopen")
        for b in self.bots:
            try:
                self.bot_tick(b, now, dt)
            except Exception:
                traceback.print_exc()
        if now - self.last_sample >= 30:
            self.last_sample = now
            for b in self.bots:
                e = self.equity(b) if b["status"] == "actief" else b["cash"]
                b["eq"].append([now, e])
                b["peak"] = max(b["peak"], e)
                b["maxdd"] = max(b["maxdd"], 1 - e / b["peak"])
                if len(b["eq"]) > 4000:
                    b["eq"] = b["eq"][::2] + ([b["eq"][-1]] if len(b["eq"]) % 2 == 0 else [])
        if now - self.last_save >= 15:
            self.last_save = now
            self.save()
        self.check_peildatum(now)

    def bot_tick(self, b, now, dt):
        if b["status"] != "actief" or self.has_pending(b):
            return
        p, P, h = self.m.price, b["pos"], self.h
        if P:
            if P["side"] == -1:
                bf = P["qty"] * p * 0.0003 / DAY * dt  # leenkosten short ca. 0,03%/dag
                b["cash"] -= bf; P["borrow"] += bf
            s = P["side"]
            P["ext"] = max(P["ext"], p) if s == 1 else min(P["ext"], p)
            reason = None
            if s * (p - P["tpP"]) >= 0:
                reason = f"Doel {num(P['tpP'])} geraakt"
            elif s * (p - P["slP"]) <= 0:
                reason = f"Stop {num(P['slP'])} geraakt"
            elif P.get("trail") and s * (P["ext"] / P["entry"] - 1) > P["trail"] * 0.7:
                back = 1 - p / P["ext"] if s == 1 else p / P["ext"] - 1
                if back >= P["trail"]:
                    reason = f"Meeschuivende stop: {pct(P['trail'], 1)} terug van {'top' if s == 1 else 'bodem'} {num(P['ext'])}"
            if reason:
                self.close(b, reason)
                return
            risk = f" Max verlies {eur(P['risk'])}." if P.get("risk") else ""
            b["thought"] = (f"Rijdt mee met de uitbraak. Doel {num(P['tpP'])}, stop {num(P['slP'])} (+ meeschuivende stop).{risk}"
                            if b["id"] in ("bo_up", "bo_down") else
                            f"{'Long' if s == 1 else 'Short'} @ {num(P['entry'])}. Doel {num(P['tpP'])}, stop {num(P['slP'])}.{risk}")
        e = self.equity(b)
        if e >= b["doel"] or e <= b["rem"]:
            final = "doel" if e >= b["doel"] else "rem"
            if b["pos"]:
                self.close(b, "Doel bereikt, alles verkopen" if final == "doel" else "Noodrem: verlieslimiet bereikt", final=final)
            else:
                b["status"] = final
            return
        if b["pos"]:
            return
        # Veiligheidsregels
        r = self.settings["risico_pct"]
        if e < b["peak"] * (1 - 10 * r / 100):
            b["status"] = "rem"
            b["thought"] = f"Gestopt: {nl(10 * r, 1)}% gedaald vanaf de top ({eur(b['peak'])} → {eur(e)}). Kapitaal beschermd."
            self.log(b, "Gestopt (max daling)", b["thought"], None, None, b["live"])
            notify(self.cfg, "Botlab: bot gestopt", f"{DEF[b['id']]['naam']}: {nl(10 * r, 1)}% daling vanaf de top", PHONE_URL)
            return
        key = int(now // h["period"])
        if key != b.get("per_key"):
            b["per_key"], b["per_start"] = key, e
        if b.get("pauze"):
            if now < b["cool"]:
                b["thought"] = f"Pauze na 2 verliezen op rij, tot {time.strftime('%d-%m %H:%M', time.localtime(b['cool']))}."
                return
            b["pauze"] = False
        if e < b["per_start"] * (1 - 3 * r / 100):
            b["thought"] = (f"Verlieslimiet voor deze {h['period_naam']} bereikt (3 × {nl(r)}% = {eur(b['per_start'] - e)} verlies). "
                            f"Geen nieuwe trades tot de volgende {h['period_naam']}.")
            return
        getattr(self, "s_" + b["id"])(b, now)

    # ---------- strategieën ----------
    def _range(self, side=1):
        """Instaplijn = dichtstbijzijnde sterke lijn; doel = eerste sterke lijn aan de andere kant
           die minstens min_range verder ligt (anders blijft na kosten niets over)."""
        m, mr = self.m, self.h["min_range"]
        strong = [x for x in m.levels if x["w"] >= 1.5]
        if side == 1:
            S = m.sup
            if not S:
                return None, None, None
            far = sorted([x for x in strong if x["p"] > S["p"] and (x["p"] - S["p"]) / S["p"] * 100 >= mr], key=lambda x: x["p"])
            R = far[0] if far else m.res
        else:
            R = m.res
            if not R:
                return None, None, None
            far = sorted([x for x in strong if x["p"] < R["p"] and (R["p"] - x["p"]) / x["p"] * 100 >= mr], key=lambda x: -x["p"])
            S = far[0] if far else m.sup
        if not S or not R:
            return None, None, None
        return S["p"], R["p"], (R["p"] - S["p"]) / S["p"] * 100

    def _when(self, t):
        return time.strftime("%H:%M" if t - time.time() < DAY else "%d-%m %H:%M", time.localtime(t))

    def s_steun(self, b, now):
        h, p, L = self.h, self.m.price, LBL[self.h["bar"]]
        S, R, width = self._range()
        if S is None:
            b["thought"] = "Geen duidelijke steun en weerstand gevonden. Wacht."
            return
        gap = (p / S - 1) * 100
        if now < b["cool"]:
            b["thought"] = f"Even afkoelen tot {self._when(b['cool'])}. Steun {num(S)}, koers {pct(gap / 100)} erboven."
            return
        if width < h["min_range"]:
            b["thought"] = f"Range {num(S)}–{num(R)} is maar {nl(width)}%. Te smal na kosten, wacht."
            return
        if self.cfg["ema_filter"] and self.m.signal["trend"] == -1:
            b["thought"] = f"Steun {num(S)} · weerstand {num(R)}. Koers onder de 200 EMA ({LBL[h['mom'][1]]}): geen long tegen de trend in."
            return
        if not self.m.cb:
            b["thought"] = f"Wacht op {L}-candles."
            return
        last = self.m.cb[-1]
        tp, sl = R * (1 - 0.002), S * (1 - h["stop"] / 100)
        rr, need = self.rr_net(tp, sl), self.rr_min()
        if 0.05 <= gap <= h["zone"] and last["c"] > S and rr >= need:
            self.open(b, 1, f"Net boven steun {num(S)} ({self.m.sup['n']}× getest). Doel net onder weerstand {num(R)}, "
                            f"winst/risico na kosten {nl(rr, 1)}", tp, sl)
        else:
            why = (f"vorige {L}-candle sloot onder de steun" if last["c"] <= S else
                   f"winst/risico na kosten {nl(rr, 1)} is lager dan {nl(need, 2).rstrip('0').rstrip(',')}" if 0.05 <= gap <= h["zone"] else
                   f"koopt pas binnen +{nl(h['zone'])}% boven de steun")
            b["thought"] = f"Steun {num(S)} · doel {num(R)}. Koers {pct(gap / 100)} boven steun: {why}."

    def s_weerstand(self, b, now):
        h, p, L = self.h, self.m.price, LBL[self.h["bar"]]
        S, R, width = self._range(-1)
        if S is None:
            b["thought"] = "Geen duidelijke steun en weerstand gevonden. Wacht."
            return
        gap = (R / p - 1) * 100
        if now < b["cool"]:
            b["thought"] = f"Even afkoelen tot {self._when(b['cool'])}. Weerstand {num(R)}, koers {nl(gap)}% eronder."
            return
        if width < h["min_range"]:
            b["thought"] = f"Range {num(S)}–{num(R)} te smal na kosten. Wacht."
            return
        if self.cfg["ema_filter"] and self.m.signal["trend"] == 1:
            b["thought"] = f"Weerstand {num(R)} · steun {num(S)}. Koers boven de 200 EMA ({LBL[h['mom'][1]]}): geen short tegen de trend in."
            return
        if not self.m.cb:
            b["thought"] = f"Wacht op {L}-candles."
            return
        last = self.m.cb[-1]
        tp, sl = S * (1 + 0.002), R * (1 + h["stop"] / 100)
        rr, need = self.rr_net(tp, sl), self.rr_min()
        if 0.05 <= gap <= h["zone"] and last["c"] < R and rr >= need:
            self.open(b, -1, f"Net onder weerstand {num(R)} ({self.m.res['n']}× getest). Doel net boven steun {num(S)}, "
                             f"winst/risico na kosten {nl(rr, 1)}", tp, sl)
        else:
            why = (f"vorige {L}-candle sloot boven de weerstand" if last["c"] >= R else
                   f"winst/risico na kosten {nl(rr, 1)} is lager dan {nl(need, 2).rstrip('0').rstrip(',')}" if 0.05 <= gap <= h["zone"] else
                   f"shortt pas binnen −{nl(h['zone'])}% onder de weerstand")
            b["thought"] = f"Weerstand {num(R)} · doel {num(S)}. Koers {nl(gap)}% onder weerstand: {why}."

    def _breakout(self, b, now, up):
        m, c, h = self.m, self.cfg, self.h
        L = LBL[h["bar"]]
        if not m.new_bar and not b["thought"].startswith("Opstarten"):
            return
        cs = m.cb or []
        if len(cs) < 2:
            b["thought"] = f"Wacht op {L}-candles."
            return
        prev, cur = cs[-2], cs[-1]  # laatste twee AFGESLOTEN candles
        buf = h["buf"] / 100
        # Welke sterke lijn is door de laatste candle doorbroken? Na de uitbraak heet een oude weerstand al 'steun',
        # daarom kijken we naar alle sterke lijnen en niet alleen naar de huidige steun/weerstand.
        strong = [x for x in m.levels if x["w"] >= 1.5]
        hit = [x for x in strong if ((prev["c"] <= x["p"] and cur["c"] > x["p"] * (1 + buf)) if up else
                                     (prev["c"] >= x["p"] and cur["c"] < x["p"] * (1 - buf)))]
        hit.sort(key=lambda x: -x["p"] if up else x["p"])
        crossed = bool(hit)
        lvl = hit[0]["p"] if hit else ((m.res and m.res["p"]) if up else (m.sup and m.sup["p"]))
        if lvl is None:
            b["thought"] = "Geen duidelijke lijn om doorheen te breken. Wacht."
            return
        other = [x for x in strong if (x["p"] > lvl * (1 + h["min_range"] / 100) if up else x["p"] < lvl * (1 - h["min_range"] / 100))]
        other.sort(key=lambda x: x["p"] if up else -x["p"])
        rng = abs(other[0]["p"] - lvl) if other else lvl * h["min_range"] / 100
        vol_ok = m.vol_avg > 0 and cur.get("v", 0) >= c["volume_factor"] * m.vol_avg
        vr = cur.get("v", 0) / m.vol_avg if m.vol_avg else 0
        if now < b["cool"]:
            b["thought"] = f"Even afkoelen tot {self._when(b['cool'])}. Let op {'weerstand' if up else 'steun'} {num(lvl)}."
            return
        tp = lvl + rng if up else lvl - rng
        sl = lvl * (1 - h["stop"] / 100) if up else lvl * (1 + h["stop"] / 100)
        rr = self.rr_net(tp, sl)
        ema_ok = (not c["ema_filter"]) or (m.signal["upS"] if up else not m.signal["upS"])
        if crossed and vol_ok and not ema_ok:
            b["thought"] = f"Uitbraak door {num(lvl)} met volume, maar 9 EMA staat {'onder' if up else 'boven'} 20 EMA ({LBL[h['mom'][1]]}): momentum bevestigt niet."
        elif crossed and vol_ok and rr < self.rr_min():
            b["thought"] = f"Uitbraak door {num(lvl)}, maar winst/risico na kosten {nl(rr, 1)} is te laag bij {nl(self.settings['risico_pct'])}% risico."
        elif crossed and vol_ok:
            self.open(b, 1 if up else -1, f"Uitbraak {'omhoog' if up else 'omlaag'}: {L}-slot {num(cur['c'])} {'boven weerstand' if up else 'onder steun'} "
                                         f"{num(lvl)} met {nl(vr, 1)}× volume", tp, sl, trail=max(0.015, h["stop"] * 3 / 100))
            b["cool"] = now + h["bar"] * 4
        elif crossed:
            b["thought"] = f"Door {'weerstand' if up else 'steun'} {num(lvl)} maar volume maar {nl(vr, 1)}×: mogelijke valse uitbraak, geen trade."
        else:
            d = (lvl / m.price - 1) * 100
            b["thought"] = (f"Wacht op {L}-slot {'boven' if up else 'onder'} {num(lvl)} ({'+' if up else '−'}{nl(h['buf'])}% buffer, "
                            f"{nl(c['volume_factor'], 1)}× volume). Nu {nl(abs(d))}% {'eronder' if up else 'erboven'}.")

    def s_bo_up(self, b, now):
        self._breakout(b, now, True)

    def s_bo_down(self, b, now):
        self._breakout(b, now, False)

    def s_rnd(self, b, now):
        if now < b["next"]:
            b["thought"] = "Volgende muntworp om " + self._when(b["next"]) + "."
            return
        d, side, p = self.h["rnd"][0], (1 if self.rng.random() < 0.5 else -1), self.m.price
        self.open(b, side, "Muntworp: " + ("kop → long" if side == 1 else "munt → short"), p * (1 + d * side), p * (1 - d * side))
        b["next"] = self.next_rnd(now)

    # ---------- verdiend per periode ----------
    def verdiend(self):
        now = time.time()
        if not self.bots:
            return {"rows": [], "elapsed": 0}
        t0 = min(b["eq"][0][0] for b in self.bots)
        el = max(1, now - t0)

        def eq_at(b, ts):
            eq = b["eq"]
            lo, hi = 0, len(eq) - 1
            if ts < eq[0][0]:
                return eq[0][1]
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if eq[mid][0] <= ts:
                    lo = mid
                else:
                    hi = mid - 1
            return eq[lo][1]

        rows = []
        for naam, kleur, group, tot in [("Alle bots samen", None, self.bots, True)] + [(DEF[b["id"]]["naam"], DEF[b["id"]]["kleur"], [b], False) for b in self.bots]:
            nowv = sum(self.equity(b) if b["status"] == "actief" else b["cash"] for b in group)
            cells = []
            for pn, P in PERIODS:
                full = el >= P
                frm = now - P if full else t0
                base = sum(eq_at(b, frm) for b in group)
                cells.append({"d": nowv - base, "r": (nowv - base) / base if base else 0, "full": full})
            rows.append({"naam": naam, "kleur": kleur, "tot": tot, "echt": any(b["live"] for b in group), "cells": cells})
        return {"rows": rows, "elapsed": el, "periods": [p for p, _ in PERIODS]}

    # ---------- belasting ----------
    def load_tax(self):
        try:
            with open(TAX_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def save_tax(self):
        with open(TAX_PATH, "w", encoding="utf-8") as f:
            json.dump(self.tax, f, indent=2)

    def check_peildatum(self, now):
        """Legt per jaar de waarde op 1 januari 00:00 vast (peildatum box 3). Alleen met een API-sleutel."""
        year = time.localtime(now).tm_year
        if str(year) in self.tax or not self.ex.has_keys or self.tax_busy or not self.m.ready:
            return
        self.tax_busy = True
        threading.Thread(target=self._measure_peildatum, args=(year,), daemon=True).start()

    def _measure_peildatum(self, year):
        try:
            t1 = jan1(year)
            bal = self.ex.balances()
            btc_now, eur_now = bal.get("BTC", 0.0), bal.get("EUR", 0.0)
            koers, bron = None, ""
            for k in self.m.c["1h"]:
                if k["t"] == int(t1):
                    koers, bron = k["o"], f"opening 1u-candle {self.ex.NAME} op 1 januari 00:00"
                    break
            if koers is None and time.time() - t1 < 2 * HOUR:
                koers, bron = self.m.price, "koers bij meting kort na middernacht"
            if koers is None:  # terugvallen op de dagcandle van 1 januari (UTC, opent 01:00 Nederlandse tijd)
                d1 = int(t1 // DAY * DAY + DAY) if t1 % DAY else int(t1)
                for k in self.m.c["1d"]:
                    if k["t"] in (d1, d1 - DAY) and time.gmtime(k["t"]).tm_mon == 1 and time.gmtime(k["t"]).tm_mday == 1:
                        koers, bron = k["o"], f"opening dagcandle {self.ex.NAME} op 1 januari (UTC)"
                        break
            # Saldo op 1 januari terugrekenen met de echte trades sinds 1 januari (stortingen/opnames niet meegerekend).
            bought = sold = spent = received = 0.0
            for r in logboek_read():
                try:
                    ts = time.mktime(time.strptime(r["datum_tijd"], "%Y-%m-%d %H:%M:%S"))
                except Exception:
                    continue
                if ts < t1 or r["modus"] != "echt":
                    continue
                q, a, f = undec(r["aantal_btc"]) or 0, undec(r["bedrag_eur"]) or 0, undec(r["kosten_eur"]) or 0
                if r["actie"] == "Open long":
                    bought += q; spent += a + f
                elif r["actie"] == "Sluit long":
                    sold += q; received += a - f
            btc = max(0.0, btc_now - bought + sold)
            eurv = max(0.0, eur_now + spent - received)
            self.tax[str(year)] = {"gemeten": time.time(), "btc": btc, "eur": eurv, "koers": koers, "bron_koers": bron,
                                   "waarde_btc": btc * koers if koers else None, "beurs": self.ex.NAME,
                                   "methode": "gemeten" if time.time() - t1 < 2 * HOUR else "teruggerekend met echte trades sinds 1 januari"}
            self.save_tax()
            self.log(None, "Peildatum vastgelegd", f"1 januari {year}: {btc:.8f} BTC en {eur(eurv)} op {self.ex.NAME}"
                                                   + (f", BTC-koers {num(koers)}" if koers else ", koers niet beschikbaar"), None, None, False)
        except Exception as e:
            print("Peildatum vastleggen mislukt:", e)
        finally:
            self.tax_busy = False

    def belasting(self):
        rows = [r for r in logboek_read() if r.get("modus") == "echt" and r.get("actie") in ("Open long", "Sluit long")]
        years = {}
        for r in rows:
            y = r["datum_tijd"][:4]
            d = years.setdefault(y, {"jaar": y, "aankopen": 0, "verkopen": 0, "gekocht_eur": 0.0, "verkocht_eur": 0.0,
                                     "kosten_eur": 0.0, "resultaat_eur": 0.0})
            a, f, res = undec(r["bedrag_eur"]) or 0, undec(r["kosten_eur"]) or 0, undec(r["resultaat_eur"]) or 0
            d["kosten_eur"] += f
            if r["actie"] == "Open long":
                d["aankopen"] += 1; d["gekocht_eur"] += a
            else:
                d["verkopen"] += 1; d["verkocht_eur"] += a; d["resultaat_eur"] += res
        for y, t in self.tax.items():
            years.setdefault(y, {"jaar": y, "aankopen": 0, "verkopen": 0, "gekocht_eur": 0.0, "verkocht_eur": 0.0,
                                 "kosten_eur": 0.0, "resultaat_eur": 0.0})["peildatum"] = t
        return sorted(years.values(), key=lambda d: d["jaar"], reverse=True)

    # ---------- snapshot ----------
    def snapshot(self, tf, local=False):
        m, now, h = self.m, time.time(), self.h
        B = {"1m": 60, "5m": 300, "15m": 900, "1u": 3600, "4u": 14400, "1d": 86400}.get(tf, 900)
        full = m.candles(B)
        cs = full[-150:]
        closes = [x["c"] for x in full]
        emas = {str(n): ema(closes, n)[-150:] for n in (9, 20, 200)}
        trends = []
        if m.ready:
            for name, s, sub in SCALES:
                pa = m.price_at(now - s)
                trends.append({"k": name, "sub": sub, "ch": m.price / pa - 1 if pa else 0, "z": m.z(s),
                               "spark": [m.price_at(now - s + s * j / 39) for j in range(40)]})
        bots = []
        for b in self.bots:
            e = self.equity(b) if b["status"] == "actief" else b["cash"]
            P, eq = b["pos"], b["eq"]
            bots.append({**{k: b[k] for k in ("id", "live", "start", "doel", "rem", "status", "thought", "n", "closed", "wins", "maxdd")},
                         **{k: DEF[b["id"]][k] for k in ("naam", "kleur")}, "uitleg": DEF[b["id"]]["uitleg"].replace("{bar}", LBL[h["bar"]]),
                         "e": e, "eq": eq[::max(1, len(eq) // 300)] + [[now, e]],
                         "pos": None if not P else {"side": P["side"], "qty": P["qty"], "entry": P["entry"], "tp": P["tpP"], "sl": P["slP"],
                                                    "risk": P.get("risk"), "t": P.get("t"),
                                                    "r": P["side"] * (m.price / P["entry"] - 1) if m.price else 0}})
        lv = lambda c: c and {"p": c["p"], "n": c["n"], "w": round(c["w"], 2), "kind": c["kind"], "dist": c["dist"]}
        r = self.settings["risico_pct"]
        rules = [
            f"Elke trade heeft vooraf een stop en riskeert maximaal <b>{nl(r)}%</b> van de bot ({eur(self.cfg['start_eur'] * r / 100)} bij de start), kosten inbegrepen.",
            f"Alleen trades waarbij de mogelijke winst na kosten minstens <b>{nl(self.rr_min(), 2).rstrip('0').rstrip(',')}×</b> zo groot is als het risico.",
            "Niet tegen de trend in: geen long onder de 200 EMA, geen short erboven.",
            "Halve inzet of geen trade als het marktkompas tegenzit (trend, cyclus, economie, sentiment).",
            f"Na 2 verliezen op rij een pauze van {dur(h['cool'] * 4)}.",
            f"Verlieslimiet: geen nieuwe trades meer deze {h['period_naam']} na {nl(3 * r)}% verlies.",
            f"Een bot stopt helemaal na {nl(10 * r, 1)}% daling vanaf zijn hoogste stand, en altijd bij de noodrem.",
            "Geen hefboom: een positie is nooit groter dan het eigen geld van de bot. Echte orders: alleen long, elke order met jouw akkoord.",
        ]
        return {"now": now, "price": m.price, "ready": m.ready, "err": m.err, "last_ok": m.last_ok, "beurs": self.ex.NAME, "market": self.ex.MARKET,
                "chg24": (m.price / m.price_at(now - DAY) - 1) if m.ready else 0,
                "candles": cs, "tf": tf, "marks": [x for x in self.marks if cs and x["t"] >= cs[0]["t"]],
                "levels": [lv(c) for c in m.levels], "sup": lv(m.sup), "res": lv(m.res), "rsi": m.rsi, "vol_avg": m.vol_avg,
                "trends": trends, "bots": bots, "emas": emas,
                "signal": {k: m.signal.get(k) for k in ("actie", "trend", "upF", "upS", "why", "cyc")},
                "ema_now": {tfk: {str(n): v for n, v in d.items()} for tfk, d in m.signal.get("ema", {}).items()},
                "pending": [{**x, "naam": DEF[x["bot"]]["naam"], "kleur": DEF[x["bot"]]["kleur"]} for x in self.pending],
                "trades": [{**t, "naam": DEF[t["bot"]]["naam"] if t["bot"] else "Systeem",
                            "kleur": DEF[t["bot"]]["kleur"] if t["bot"] else "#64748b"} for t in self.trades[:80]],
                "mode": self.mode, "keys": self.ex.has_keys, "mock": MOCK,
                "settings": self.settings, "hz": {"naam": h["naam"], "uitleg": h["uitleg"], "min_range": h["min_range"],
                                                  "bar": LBL[h["bar"]], "lv": " + ".join(LBL[x[0]] for x in h["lv"]), "zone": h["zone"]},
                "kompas": self.kompas, "rules": rules, "verdiend": self.verdiend(),
                "phone": ({"on": bool(self.cfg.get("telefoon_toegang")), "url": PHONE_URL, "pin": self.cfg.get("pincode", ""),
                           "ntfy": bool(str(self.cfg.get("ntfy_onderwerp", "")).strip())} if local else None),
                "cfg": {k: self.cfg[k] for k in DEFAULT_CFG if k not in ("api_key", "api_secret", "pincode")}}


# =====================================================================
#  Webserver (alleen op deze computer bereikbaar)
# =====================================================================
TOKEN = secrets.token_hex(16)
E = None
CFG = {}
PHONE_URL = None
SESSIONS = set()
SESS_PATH = os.path.join(DATA, "botlab_sessies.json")


def load_sessions():
    try:
        with open(SESS_PATH, encoding="utf-8") as f:
            SESSIONS.update(json.load(f))
    except Exception:
        pass


def save_sessions():
    try:
        with open(SESS_PATH, "w", encoding="utf-8") as f:
            json.dump(sorted(SESSIONS)[-50:], f)
    except Exception:
        pass
FAILS = {}
ICON_PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAALQAAAC0CAIAAACyr5FlAAAEcUlEQVR4Xu3dMY7bVhQFUE2QyoUBN4aRxkD6VKmyA7vNhrKjtPYOvAD3BtIE7rKFABEwESRSw/f5Hv+neE49I1Hk1X2f1Ijz9Or12xNM+cFuYY5wIBzEaQ40B3GaA81BnOZAcxCnOdAcxGkONAdxP8Z/Jdm7Tx+SH/GBfP/4ueOreerykb1ANNg+KJuGQyZSbJaSLcIhE0WqU1J+tiIZdar3bWFzLNz0f37/Urf79u7Nn78teQlFFVIVjvvJEIgG94NSkY/8cIhFqS0jkhyOuWSoinRzKUmskMwFqWRsae79tnCpt0Rac0xuk8LYwGSFpPRHTnNIRkeT78CU/kgIh2R0V5SPteGQjEFU5GNtOG5ZZ/SSvudXheO2NtK3j5Db/b9m8dEeDskYU2I+2sNxRWeMI+tYNIZjTVmxvbbj1RIOA2V8KcOlJRwGyi6sHy4J4eBRhcPRNr0YQfTYhcNhpuzIysmyNhw8sFg4rnppZTDZwNUxCk2WWDg4lP5fh2TO5V/xdClpzcGsQDgsOHaqedkRCAdHIxxkjBWOpvBs5dsv74+2N5P98ff/D3h3Z/789a/kp/6PsYKxQlzhWCnquuNwEYxxWXNgzUGc5mBW4YKUhZbc+GvyZ6o/qhWOtbqfU9QxVrAgJU5zoDmI0xxoDuI0B5qDOM3BrLGukD7w1cY90hxYcxCnOdjJmmNkw36wXkdzYM1BnOZAcxCnOdAcxGkONAdxmoNZfT6VPeDVxj3qE47tXd5myL0hFjJWsCAlTnOgOYg7yoJ0ZHN3Uuj+F7XGCsYKcZoDzUGc5kBzEKc50BzEPdpFsCX/5GXyZ3xUe8tYwVghTnOgOYh7tAXpI6m+7/2LjBWMFeI0B5qDOM2B5iBOc6A5iNMcaA7i+lw+H/ZrPFwyVjBWiNMcaA7iNAeagzjNwaw+1zn26IDXZjQHh2mOuS+uuQ9pA82BsxXiNAc7WXN0/xoPlzQHPZpjyf/N2MyvF8/05vRT0fP2eslFjas5cLZCXOHl86Kua1N3Eaz7HcrrGCsYK8QVjpWDGGp65jJW6HGdYyhuM9pAc2BBSlygOb5//Hz5+L0uFRN1daSujuMdgXBwNMKBNQdxseaw7Nid5gXH6RQMB4cSa45bzllGtvLohMOx/ESI0USPXTgcHEdCOFZ2F0XWH5eWcNy20/rtINftEYnOlPazlYZnoqO249XSHJOUxziyjkV7OAyXMaUMlLP2cJxO8jGcxGSsDYf5MpSsafJsVXNMlsfplL+VvGgyGW3r0LRwyMcIKpKRNlYmE5reciyf4ys74+zp1eu3WTv93acPkw/1wN/s6Gvu7ZeSjLTmOJvbJhVSoToZyc1xNtcfZ1pkpfvvtKzOyB8rl0Qk3ZaxqA3HixXyTJfcsXAi5xbGs8wF6aT7FcJKRbE4W3sR7EWlW39w1fu2vDmWL0RYqDoT240VsybLZpnoHA51stD2gbi06VhhX8oXpOyXcDBLOBAO4jQHmoM4zYHmIE5zoDmI0xxoDuL+BRVgNp+8wTd2AAAAAElFTkSuQmCC")
MANIFEST = json.dumps({"name": "Botlab", "short_name": "Botlab", "start_url": "/", "display": "standalone",
                       "background_color": "#0a0e16", "theme_color": "#0a0e16",
                       "icons": [{"src": "/icon.png", "sizes": "180x180", "type": "image/png"}]})
LOGIN_HTML = """<!DOCTYPE html><html lang="nl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Botlab"><link rel="apple-touch-icon" href="/icon.png"><link rel="manifest" href="/manifest.json">
<title>Botlab – inloggen</title><style>*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0a0e16;color:#e7ecf6;font:16px -apple-system,Segoe UI,sans-serif;padding:env(safe-area-inset-top) 16px env(safe-area-inset-bottom)}
form{background:#111725;border:1px solid #222b3d;border-radius:18px;padding:24px;width:min(340px,100%);display:grid;gap:14px}
h1{margin:0;font-size:22px}p{margin:0;color:#8792a8;font-size:14px}
input{font:600 24px ui-monospace,Consolas,monospace;letter-spacing:.25em;text-align:center;background:#0c1220;color:#fff;border:1px solid #2b3650;border-radius:12px;padding:14px}
button{font:700 16px inherit;background:#16a34a;color:#fff;border:0;border-radius:12px;padding:14px}.e{color:#fca5a5}</style></head>
<body><form method="post" action="/login"><h1>⚡ Botlab</h1><p>Vul de pincode in die op je pc staat (in het zwarte venster en in het dashboard).</p>
<input name="pin" inputmode="numeric" autocomplete="one-time-code" autofocus placeholder="pincode">__ERR__<button>Inloggen</button></form></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _local(self):
        """Alleen een verzoek van deze pc zelf, zonder proxy ertussen, hoeft niet in te loggen.
           In servermodus moet iedereen inloggen."""
        if CFG.get("server_modus"):
            return False
        if self.headers.get("X-Forwarded-For") or self.headers.get("Forwarded"):
            return False
        return self.client_address[0] in ("127.0.0.1", "::1")

    def _host_ok(self):
        if CFG.get("telefoon_toegang"):
            return True
        return self.headers.get("Host", "").split(":")[0] in ("127.0.0.1", "localhost")

    def _authed(self):
        if self._local():
            return True
        c = http.cookies.SimpleCookie(self.headers.get("Cookie", ""))
        return "bl" in c and c["bl"].value in SESSIONS

    def _redirect(self, to, cookie=None):
        self.send_response(303)
        self.send_header("Location", to)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {"ok": False})
        u = urllib.parse.urlparse(self.path)
        if u.path == "/icon.png":
            return self._send(200, ICON_PNG, "image/png")
        if u.path == "/manifest.json":
            return self._send(200, MANIFEST.encode(), "application/manifest+json")
        if u.path == "/logout":
            c = http.cookies.SimpleCookie(self.headers.get("Cookie", ""))
            if "bl" in c:
                SESSIONS.discard(c["bl"].value); save_sessions()
            return self._redirect("/", "bl=; Path=/; Max-Age=0")
        if not self._authed():
            if u.path == "/":
                return self._send(200, LOGIN_HTML.replace("__ERR__", "").encode(), "text/html")
            return self._send(401, {"ok": False, "msg": "Log opnieuw in"})
        if u.path == "/":
            with open(PAGE_PATH, encoding="utf-8") as f:
                return self._send(200, f.read().replace("__TOKEN__", TOKEN).encode(), "text/html")
        q = urllib.parse.parse_qs(u.query)
        if u.path == "/api/state":
            tf = q.get("tf", ["15m"])[0]
            with E.lock:
                return self._send(200, E.snapshot(tf, self._local()))
        if u.path == "/api/logboek":
            try:
                n = max(1, min(2000, int(q.get("n", ["300"])[0])))
            except ValueError:
                n = 300
            return self._send(200, {"ok": True, "rows": logboek_read(n)[::-1]})
        if u.path == "/api/logboek.csv":
            data = b""
            if os.path.exists(LOG_PATH):
                with LOG_LOCK, open(LOG_PATH, "rb") as f:
                    data = f.read()
            return self._download(data, "botlab_logboek.csv")
        if u.path == "/api/belasting":
            with E.lock:
                return self._send(200, {"ok": True, "jaren": E.belasting(), "keys": E.ex.has_keys, "beurs": E.ex.NAME})
        if u.path == "/api/belasting.csv":
            jaar = q.get("jaar", [time.strftime("%Y")])[0][:4]
            with E.lock:
                y = next((d for d in E.belasting() if d["jaar"] == jaar), None)
            out = io.StringIO()
            w = csv.writer(out, delimiter=";")
            w.writerow([f"Botlab – overzicht voor de belastingaangifte {jaar}", f"beurs: {E.ex.NAME}", "geen belastingadvies"])
            w.writerow([])
            pd = (y or {}).get("peildatum")
            w.writerow(["Peildatum 1 januari (box 3)", "BTC", "EUR", "BTC-koers", "waarde BTC in EUR", "methode", "bron koers"])
            w.writerow(["" if not pd else f"1-1-{jaar}", dec(pd["btc"], 8) if pd else "", dec(pd["eur"]) if pd else "",
                        dec(pd["koers"]) if pd and pd.get("koers") else "", dec(pd["waarde_btc"]) if pd and pd.get("waarde_btc") else "",
                        pd["methode"] if pd else "niet vastgelegd: zie het jaaroverzicht van je beurs", pd.get("bron_koers", "") if pd else ""])
            w.writerow([])
            w.writerow(["Echte trades in " + jaar, "aankopen", "verkopen", "gekocht EUR", "verkocht EUR", "kosten EUR", "gerealiseerd resultaat EUR"])
            if y:
                w.writerow(["", y["aankopen"], y["verkopen"], dec(y["gekocht_eur"]), dec(y["verkocht_eur"]), dec(y["kosten_eur"]), dec(y["resultaat_eur"])])
            w.writerow([])
            w.writerow(LOG_COLS)
            for r in logboek_read():
                if r.get("modus") == "echt" and r.get("datum_tijd", "").startswith(jaar):
                    w.writerow([r.get(k, "") for k in LOG_COLS])
            return self._download(("\ufeff" + out.getvalue()).encode("utf-8"), f"botlab_belasting_{jaar}.csv")
        self._send(404, {"ok": False})

    def _download(self, data, name):
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{name}"')
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path == "/login" and CFG.get("telefoon_toegang"):
            ip, now = self.client_address[0], time.time()
            if ip in ("127.0.0.1", "::1") and self.headers.get("X-Forwarded-For"):  # alleen een lokale proxy (Caddy) vertrouwen
                ip = self.headers["X-Forwarded-For"].split(",")[0].strip()
            fails = [t for t in FAILS.get(ip, []) if now - t < 300]
            n = int(self.headers.get("Content-Length", 0) or 0)
            pin = urllib.parse.parse_qs(self.rfile.read(n).decode()).get("pin", [""])[0].strip()
            if len(fails) >= 5:
                return self._send(429, LOGIN_HTML.replace("__ERR__", '<p class="e">Te vaak fout. Probeer het over 5 minuten opnieuw.</p>').encode(), "text/html")
            if pin and hmac.compare_digest(pin, str(CFG.get("pincode", ""))):
                sid = secrets.token_hex(24)
                SESSIONS.add(sid)
                save_sessions()
                secure = "; Secure" if self.headers.get("X-Forwarded-Proto", "").lower() == "https" else ""
                return self._redirect("/", f"bl={sid}; Path=/; Max-Age=2592000; HttpOnly; SameSite=Strict{secure}")
            FAILS[ip] = fails + [now]
            return self._send(401, LOGIN_HTML.replace("__ERR__", '<p class="e">Onjuiste pincode.</p>').encode(), "text/html")
        if not self._host_ok() or not self._authed() or self.headers.get("X-Token") != TOKEN:
            return self._send(403, {"ok": False, "msg": "Niet toegestaan"})
        n = int(self.headers.get("Content-Length", 0) or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            body = {}
        path = urllib.parse.urlparse(self.path).path
        with E.lock:
            if path == "/api/approve":
                ok, msg = E.approve(body.get("id"))
            elif path == "/api/reject":
                ok, msg = E.reject(body.get("id"))
            elif path == "/api/mode":
                if body.get("mode") == "echt" and body.get("confirm") != "ECHT":
                    ok, msg = False, "Typ ECHT om te bevestigen."
                else:
                    ok, msg = E.set_mode(body.get("mode"))
            elif path == "/api/test":
                try:
                    bal = E.ex.balances()
                    msg = f"Verbinding met {E.ex.NAME} werkt. Beschikbaar: {eur(bal.get('EUR', 0))} en {bal.get('BTC', 0):.8f} BTC."
                    t = E.ex.test_order(E.m.price, E.m.info)
                    if t:
                        msg += " Testorder (niet uitgevoerd) goedgekeurd: " + str(t.get("descr", {}).get("order", "ok")) + "."
                    ok = True
                except Exception as e:
                    ok, msg = False, str(e)
            elif path == "/api/restart":
                if any(b["live"] and b["pos"] for b in E.bots):
                    ok, msg = False, "Er staan nog echte posities open."
                else:
                    E.reset_bots(); E.save(); ok, msg = True, "Bots opnieuw gestart."
            elif path == "/api/noodstop":
                ok, msg = E.noodstop()
            elif path == "/api/settings":
                ok, msg = E.set_settings(body)
            elif path == "/api/debug_signal" and MOCK:
                b, p = E._bot(body.get("bot", "steun")), E.m.price
                E.open(b, 1, "Testsignaal (alleen in testmodus)", p * 1.02, p * 0.99); ok, msg = True, "ok"
            elif path == "/api/debug_sell" and MOCK:
                E.close(E._bot(body.get("bot", "steun")), "Testverkoop (alleen in testmodus)"); ok, msg = True, "ok"
            else:
                return self._send(404, {"ok": False, "msg": "Onbekend"})
        self._send(200, {"ok": ok, "msg": msg})


def loop(market, engine):
    while True:
        try:
            market.update()
            if market.ready:
                with engine.lock:
                    engine.step()
        except Exception as e:
            market.err = str(e)
            print("Fout:", e)
        time.sleep(2)


def main():
    global E, CFG, PHONE_URL
    cfg = load_cfg()
    CFG = cfg
    if MOCK:
        ex = FakeExchange("Bitvavo" if cfg["beurs"] == "bitvavo" else "Kraken")
    elif cfg["beurs"] == "bitvavo":
        ex = Bitvavo(cfg["api_key"], cfg["api_secret"], cfg["bitvavo_operator_id"])
    elif cfg["beurs"] == "kraken":
        ex = Kraken(cfg["api_key"], cfg["api_secret"])
    else:
        print('Onbekende beurs in botlab_config.json. Gebruik "kraken" of "bitvavo".'); return
    market = Market(ex)
    E = Engine(cfg, ex, market)
    threading.Thread(target=loop, args=(market, E), daemon=True).start()
    threading.Thread(target=fng_loop, daemon=True).start()
    port = int(cfg["poort"])
    phone = bool(cfg.get("telefoon_toegang"))
    host = str(cfg.get("luister_adres", "")).strip() or ("0.0.0.0" if phone else "127.0.0.1")
    load_sessions()
    srv = ThreadingHTTPServer((host, port), Handler)
    url = f"http://127.0.0.1:{port}"
    PHONE_URL = (str(cfg.get("publiek_adres", "")).strip().rstrip("/") or f"http://{lan_ip()}:{port}") if phone else None
    print("=" * 62)
    print(f" Botlab 2 draait · beurs: {ex.NAME}" + ("  [TESTMODUS]" if MOCK else ""))
    print(f" Dashboard: {url}")
    print(f" Modus: {E.mode.upper()}   API-sleutel: {'ingesteld' if ex.has_keys else 'niet ingesteld (alleen papier)'}")
    if cfg.get("server_modus"):
        print(f" SERVERMODUS · luistert op {host}:{port} · iPhone: {PHONE_URL}   pincode: {cfg['pincode']}")
    elif phone:
        print(f" iPhone (zelfde wifi): {PHONE_URL}   pincode: {cfg['pincode']}")
        print(" Windows vraagt misschien om toegang: kies 'Privenetwerken' en klik Toestaan.")
    print(" Laat dit venster open. Sluiten = bots stoppen.")
    print("=" * 62)
    if os.environ.get("BOTLAB_NOBROWSER") != "1" and not cfg.get("server_modus"):
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        with E.lock:
            E.save()
        print("Gestopt. Stand opgeslagen.")


if __name__ == "__main__":
    main()
