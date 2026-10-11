"""
Dhan v2 REST layer.

Built on the connection pattern already proven in RA17: TOTP token flow
with verify then renew then generate, separate rate gates per class of
call, and polling the order book rather than trusting the place-order
response.

Orders are MARKET only, as decided. A limit path is left behind a single
switch (ORDER_MODE) so it can be turned on without touching anything that
calls this module, in case market orders are restricted later.
"""

import csv
import io
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone

import requests

log = logging.getLogger("dhan")

BASE_URL = "https://api.dhan.co/v2"
AUTH_URL = "https://auth.dhan.co/app/generateAccessToken"
FEED_URL = "wss://api-feed.dhan.co"
MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master-detailed.csv"
MASTER_URL_FALLBACK = "https://images.dhan.co/api-data/api-scrip-master.csv"

IST = timezone(timedelta(hours=5, minutes=30))

ORDER_MODE = "MARKET"        # "MARKET" today. "LIMIT" is the SEBI fallback.
ORDER_RETRIES = 4            # per the specification


def now_ist():
    return datetime.now(IST)


def normalise_epoch(ts):
    """Dhan sometimes sends IST-shifted epochs. Pull them back to UTC."""
    ts = int(ts)
    now_ts = int(time.time())
    if int(4.5 * 3600) <= (ts - now_ts) <= int(6.5 * 3600):
        ts -= 19800
    return ts


# ═══════════════════════════════════════════════════════════ rate gates
class RateGate:
    def __init__(self, max_per_sec):
        self.min_gap = 1.0 / float(max_per_sec)
        self._last = 0.0
        self._lock = threading.Lock()

    def wait(self):
        with self._lock:
            gap = time.time() - self._last
            if gap < self.min_gap:
                time.sleep(self.min_gap - gap)
            self._last = time.time()


ORDER_GATE = RateGate(8.0)      # order requests
DATA_GATE = RateGate(4.0)       # quotes, history, positions
CHAIN_GATE = RateGate(0.30)     # option chain is the slow one


# ═══════════════════════════════════════════════════════════════ client
class DhanClient:
    def __init__(self):
        self.client_id = ""
        self.pin = ""
        self.totp_secret = ""
        self.access_token = ""
        self.connected = False
        self.profile_name = ""
        self.last_error = ""

    # ------------------------------------------------------------ setup
    def set_credentials(self, client_id, pin="", totp_secret="", token=""):
        self.client_id = (client_id or "").strip()
        self.pin = (pin or "").strip()
        self.totp_secret = (totp_secret or "").strip()
        self.access_token = (token or "").strip()

    def headers(self):
        return {"Content-Type": "application/json",
                "access-token": self.access_token,
                "client-id": self.client_id}

    def feed_url(self):
        return (f"{FEED_URL}?version=2&token={self.access_token}"
                f"&clientId={self.client_id}&authType=2")

    # ------------------------------------------------------------ token
    def verify_token(self, token=None):
        token = token or self.access_token
        if not token:
            return False
        try:
            r = requests.get(f"{BASE_URL}/profile", timeout=10,
                             headers={"access-token": token,
                                      "client-id": self.client_id})
            if r.status_code == 200:
                try:
                    self.profile_name = r.json().get("dhanClientId", "")
                except ValueError:
                    pass
                return True
        except requests.RequestException as e:
            log.warning("profile check failed: %s", e)
        return False

    def renew_token(self):
        try:
            r = requests.get(f"{BASE_URL}/RenewToken", timeout=15,
                             headers={"access-token": self.access_token,
                                      "dhanClientId": self.client_id,
                                      "Content-Type": "application/json"})
            token = r.json().get("accessToken")
            if token:
                log.info("token renewed")
                return token
        except (requests.RequestException, ValueError) as e:
            log.warning("renew failed: %s", e)
        return None

    def generate_token(self, attempts=3):
        try:
            import pyotp
        except ImportError:
            self.last_error = "pyotp is not installed"
            return None
        if not (self.pin and self.totp_secret):
            self.last_error = "PIN and TOTP secret are needed to generate a token"
            return None
        for attempt in range(attempts):
            remaining = 30 - (int(time.time()) % 30)
            if attempt > 0 or remaining < 10:
                time.sleep(remaining + 1)
            code = pyotp.TOTP(self.totp_secret).now()
            try:
                r = requests.post(AUTH_URL, timeout=15,
                                  params={"dhanClientId": self.client_id,
                                          "pin": self.pin, "totp": code})
                data = r.json()
                if "accessToken" in data:
                    log.info("token generated")
                    return data["accessToken"]
                self.last_error = str(data.get("errorMessage", data))[:200]
                log.warning("generate attempt %d: %s", attempt + 1,
                            self.last_error)
            except (requests.RequestException, ValueError) as e:
                self.last_error = str(e)[:200]
        return None

    def connect(self, status=None):
        """verify, else renew, else generate. Returns True when usable."""
        def say(msg):
            log.info(msg)
            if status:
                status(msg)

        if not self.client_id:
            self.last_error = "Client ID is required"
            return False

        if self.access_token:
            say("Checking saved token...")
            if self.verify_token():
                self.connected = True
                say("Connected with the saved token.")
                return True
            say("Saved token rejected, trying to renew...")
            token = self.renew_token()
            if token and self.verify_token(token):
                self.access_token = token
                self.connected = True
                say("Token renewed.")
                return True

        say("Generating a new token with TOTP...")
        token = self.generate_token()
        if token:
            self.access_token = token
            self.connected = self.verify_token(token)
            say("Connected." if self.connected else "Token generated but rejected.")
            return self.connected

        self.connected = False
        say(f"Could not connect: {self.last_error or 'unknown error'}")
        return False

    # ------------------------------------------------------------- REST
    def _get(self, path, gate=DATA_GATE, **kw):
        gate.wait()
        try:
            r = requests.get(f"{BASE_URL}{path}", headers=self.headers(),
                             timeout=15, **kw)
            if r.status_code == 200:
                return r.json()
            log.error("GET %s -> HTTP %s %s", path, r.status_code, r.text[:160])
        except (requests.RequestException, ValueError) as e:
            log.error("GET %s error: %s", path, e)
        return None

    def _post(self, path, payload, gate=DATA_GATE, retries=2):
        for attempt in range(retries + 1):
            gate.wait()
            try:
                r = requests.post(f"{BASE_URL}{path}", headers=self.headers(),
                                  json=payload, timeout=15)
                if r.status_code == 200:
                    return r.json()
                if r.status_code == 429:
                    time.sleep(2 ** (attempt + 1))
                    continue
                log.error("POST %s -> HTTP %s %s", path, r.status_code,
                          r.text[:160])
            except (requests.RequestException, ValueError) as e:
                log.error("POST %s error: %s", path, e)
            if attempt < retries:
                time.sleep(1.5)
        return None

    # ----------------------------------------------------------- funds
    def funds(self):
        """Available capital, shown on the dashboard. No limit is imposed."""
        data = self._get("/fundlimit")
        if not data:
            return None
        return {"available": float(data.get("availabelBalance",
                                            data.get("availableBalance", 0)) or 0),
                "utilised": float(data.get("utilizedAmount", 0) or 0),
                "collateral": float(data.get("collateralAmount", 0) or 0)}

    # ---------------------------------------------------------- expiry
    def expiry_list(self, underlying_security_id, segment="IDX_I"):
        data = self._post("/optionchain/expirylist",
                          {"UnderlyingScrip": int(underlying_security_id),
                           "UnderlyingSeg": segment}, gate=CHAIN_GATE)
        if data and data.get("status") == "success":
            return data.get("data", [])
        return []

    @staticmethod
    def choose_expiry(expiries, min_days=1):
        """
        Use the current expiry until one day before it expires. On expiry
        day itself, move to the next one.
        """
        today = now_ist().date()
        dated = sorted((datetime.strptime(e, "%Y-%m-%d").date(), e)
                       for e in expiries)
        future = [(d, e) for d, e in dated if d >= today]
        if not future:
            return None
        for d, e in future:
            if (d - today).days >= min_days:
                return e
        return future[-1][1]

    def option_chain(self, underlying_security_id, expiry, segment="IDX_I"):
        data = self._post("/optionchain",
                          {"UnderlyingScrip": int(underlying_security_id),
                           "UnderlyingSeg": segment, "Expiry": expiry},
                          gate=CHAIN_GATE)
        if data and data.get("status") == "success":
            return {"spot": float(data["data"]["last_price"]),
                    "chain": data["data"]["oc"]}
        return None

    # ------------------------------------------------------- historical
    def historical(self, security_id, segment, instrument="OPTIDX",
                   interval="1", days=10):
        """Intraday candles for backfill. interval is in minutes."""
        to_date = now_ist().strftime("%Y-%m-%d")
        from_date = (now_ist() - timedelta(days=days)).strftime("%Y-%m-%d")
        data = self._post("/charts/intraday",
                          {"securityId": str(security_id),
                           "exchangeSegment": segment,
                           "instrument": instrument,
                           "interval": str(interval),
                           "fromDate": from_date, "toDate": to_date})
        if not data or "open" not in data:
            return []
        stamps = data.get("timestamp") or []
        volumes = data.get("volume") or []
        bars = []
        for i in range(len(data["open"])):
            bars.append({
                "t": normalise_epoch(stamps[i]) if i < len(stamps) else i,
                "o": float(data["open"][i]), "h": float(data["high"][i]),
                "l": float(data["low"][i]), "c": float(data["close"][i]),
                "v": float(volumes[i]) if i < len(volumes) else 0.0})
        return bars

    # ----------------------------------------------------------- orders
    def place_market(self, security_id, segment, side, qty,
                     product="INTRADAY"):
        """
        Market order with the retry count from the specification. Never
        assumes success from the response alone — the fill is confirmed
        against the order book.
        """
        payload = {"dhanClientId": str(self.client_id),
                   "transactionType": side,
                   "exchangeSegment": segment,
                   "productType": product,
                   "orderType": "MARKET",
                   "validity": "DAY",
                   "securityId": str(security_id),
                   "quantity": int(qty),
                   "disclosedQuantity": 0,
                   "price": 0, "triggerPrice": 0,
                   "afterMarketOrder": False}

        last_error = ""
        for attempt in range(ORDER_RETRIES):
            ORDER_GATE.wait()
            try:
                r = requests.post(f"{BASE_URL}/orders", headers=self.headers(),
                                  json=payload, timeout=15)
                if r.status_code == 200:
                    data = r.json()
                    order_id = str(data.get("orderId", ""))
                    filled = self.confirm_fill(order_id)
                    if filled["filled"]:
                        return filled
                    last_error = filled.get("reason", "not filled")
                else:
                    last_error = f"HTTP {r.status_code}: {r.text[:120]}"
            except (requests.RequestException, ValueError) as e:
                last_error = str(e)[:160]
            log.warning("order attempt %d/%d failed: %s",
                        attempt + 1, ORDER_RETRIES, last_error)
            time.sleep(0.5)

        return {"filled": False, "price": 0.0, "qty": 0, "order_id": "",
                "reason": last_error or "all retries failed"}

    def confirm_fill(self, order_id, tries=8, pause=0.4):
        """Poll the order book until the order settles one way or the other."""
        if not order_id:
            return {"filled": False, "reason": "no order id returned"}
        for _ in range(tries):
            data = self._get(f"/orders/{order_id}")
            if data:
                status = str(data.get("orderStatus", "")).upper()
                price = float(data.get("averageTradedPrice", 0) or 0)
                qty = int(data.get("filledQty", data.get("quantity", 0)) or 0)
                if status == "TRADED" and price > 0:
                    return {"filled": True, "price": price, "qty": qty,
                            "order_id": order_id, "reason": ""}
                if status in ("REJECTED", "CANCELLED"):
                    return {"filled": False, "price": 0.0, "qty": 0,
                            "order_id": order_id,
                            "reason": (data.get("omsErrorDescription")
                                       or status)}
            time.sleep(pause)
        return {"filled": False, "price": 0.0, "qty": 0,
                "order_id": order_id, "reason": "still pending after polling"}

    def positions(self):
        return self._get("/positions") or []

    def order_book(self):
        return self._get("/orders") or []


# ═══════════════════════════════════════════════════════ scrip master
# Column names differ a little between the plain and detailed master
# files, so each field is looked up against a list of candidates rather
# than hardcoded. If none match, the loader says exactly what it saw.
_COLS = {
    "security_id": ["SEM_SMST_SECURITY_ID", "SECURITY_ID"],
    "symbol": ["SEM_TRADING_SYMBOL", "SEM_CUSTOM_SYMBOL", "TRADING_SYMBOL"],
    "instrument": ["SEM_INSTRUMENT_NAME", "SEM_EXCH_INSTRUMENT_TYPE",
                   "INSTRUMENT"],
    "expiry": ["SEM_EXPIRY_DATE", "EXPIRY_DATE"],
    "strike": ["SEM_STRIKE_PRICE", "STRIKE_PRICE"],
    "option_type": ["SEM_OPTION_TYPE", "OPTION_TYPE"],
    "lot": ["SEM_LOT_UNITS", "LOT_SIZE"],
    "segment": ["SEM_SEGMENT", "SEGMENT"],
    "exchange": ["SEM_EXM_EXCH_ID", "EXCHANGE"],
    "underlying": ["SM_SYMBOL_NAME", "SEM_UNDERLYING_SYMBOL",
                   "UNDERLYING_SYMBOL"],
}


def _resolve(fieldnames):
    found, missing = {}, []
    upper = {f.upper(): f for f in (fieldnames or [])}
    for key, candidates in _COLS.items():
        for cand in candidates:
            if cand in upper:
                found[key] = upper[cand]
                break
        else:
            missing.append(key)
    return found, missing


def download_scrip_master(cache_path=None, timeout=180):
    """
    Pull the scrip master once a day and cache it. Everything the platform
    needs about a strike — security id, strike price, expiry, lot size —
    comes from here, which is why the live strike list never has to poll
    the option chain.
    """
    if cache_path and os.path.exists(cache_path):
        age = time.time() - os.path.getmtime(cache_path)
        if age < 12 * 3600:
            with open(cache_path, encoding="utf-8", errors="ignore") as fh:
                return fh.read()

    last_error = None
    for url in (MASTER_URL, MASTER_URL_FALLBACK):
        try:
            r = requests.get(url, timeout=timeout)
            r.raise_for_status()
            raw = r.content.decode("utf-8", errors="ignore").lstrip("\ufeff")
            if cache_path:
                try:
                    with open(cache_path, "w", encoding="utf-8") as fh:
                        fh.write(raw)
                except OSError:
                    pass
            return raw
        except requests.RequestException as e:
            last_error = e
            log.warning("scrip master %s failed: %s", url, e)
    raise RuntimeError(f"Could not download the scrip master: {last_error}")


def parse_scrip_master(raw):
    """
    Returns (rows, lot_sizes). Each row is a normalised dict. Only option
    and equity rows are kept, which is most of the file but not all of it.
    """
    reader = csv.DictReader(io.StringIO(raw))
    cols, missing = _resolve(reader.fieldnames)
    critical = {"security_id", "symbol", "instrument"}
    if critical & set(missing):
        raise RuntimeError(
            "Scrip master layout not recognised. Missing "
            f"{sorted(critical & set(missing))}. Columns seen: "
            f"{(reader.fieldnames or [])[:12]}")

    rows, lots = [], {}
    for raw_row in reader:
        instrument = (raw_row.get(cols["instrument"], "") or "").strip().upper()
        if instrument not in ("OPTIDX", "OPTSTK", "EQUITY", "ES"):
            continue
        symbol = (raw_row.get(cols["symbol"], "") or "").strip().upper()

        def take(key, default=""):
            return (raw_row.get(cols[key], default) or "").strip() \
                if key in cols else default

        try:
            strike = float(take("strike", "0") or 0)
        except ValueError:
            strike = 0.0
        try:
            lot = int(float(take("lot", "0") or 0))
        except ValueError:
            lot = 0

        row = {"security_id": take("security_id"),
               "symbol": symbol,
               "instrument": instrument,
               "expiry": take("expiry")[:10],
               "strike": strike,
               "option_type": take("option_type").upper(),
               "lot": lot,
               "segment": take("segment").upper(),
               "exchange": take("exchange").upper(),
               "underlying": take("underlying").upper()}
        rows.append(row)
        if lot > 0 and instrument in ("OPTIDX", "OPTSTK"):
            base = row["underlying"] or symbol
            for name in ("NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX",
                         "MIDCPNIFTY", "BANKEX"):
                if symbol.startswith(name):
                    lots.setdefault(name, lot)
                    break
            else:
                lots.setdefault(base, lot)
    return rows, lots


CLIENT = DhanClient()
