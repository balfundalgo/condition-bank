"""
The candidate universe: which strikes are being watched right now.

This never polls the option chain. That endpoint is limited to roughly one
call every three seconds and could not keep up with a list that moves with
the market. Instead:

    the scrip master gives every strike and its security id, once
    the index spot arrives on the WebSocket, tick by tick
    the ITM/OTM band is recomputed from that spot, immediately

So the list is live at no API cost at all.
"""

import logging
from datetime import datetime

from . import dhan

log = logging.getLogger("universe")

INDEX_SPOT = {
    "NIFTY": {"security_id": "13", "segment": "IDX_I", "fno": "NSE_FNO"},
    "BANKNIFTY": {"security_id": "25", "segment": "IDX_I", "fno": "NSE_FNO"},
    "FINNIFTY": {"security_id": "27", "segment": "IDX_I", "fno": "NSE_FNO"},
    "SENSEX": {"security_id": "51", "segment": "IDX_I", "fno": "BSE_FNO"},
}


class StrikeLadder:
    """Every option row for one underlying and one expiry, sorted."""

    def __init__(self, underlying, expiry, rows):
        self.underlying = underlying
        self.expiry = expiry
        self.calls = sorted((r for r in rows if r["option_type"] == "CE"),
                            key=lambda r: r["strike"])
        self.puts = sorted((r for r in rows if r["option_type"] == "PE"),
                           key=lambda r: r["strike"])
        self.lot = next((r["lot"] for r in rows if r["lot"] > 0), 0)

    @property
    def strikes(self):
        return sorted({r["strike"] for r in self.calls})

    def step(self):
        strikes = self.strikes
        if len(strikes) < 2:
            return 0
        gaps = [round(b - a, 2) for a, b in zip(strikes, strikes[1:])]
        return min(g for g in gaps if g > 0) if any(g > 0 for g in gaps) else 0


def build_ladders(rows, underlying, expiry=None, min_days=1):
    """
    Pick the expiry by the agreed rule — current until one day before,
    next week on expiry day — and return the ladder for it.
    """
    options = [r for r in rows
               if r["instrument"] in ("OPTIDX", "OPTSTK")
               and (r["underlying"] == underlying
                    or r["symbol"].startswith(underlying))
               and r["option_type"] in ("CE", "PE")
               and r["expiry"]]
    if not options:
        return None

    if expiry is None:
        expiries = sorted({r["expiry"] for r in options})
        expiry = dhan.DhanClient.choose_expiry(expiries, min_days=min_days)
    if not expiry:
        return None
    return StrikeLadder(underlying, expiry,
                        [r for r in options if r["expiry"] == expiry])


class UniverseFilter:
    """
    The user's strike settings. Mirrors Method 1 in the specification:
    option type, moneyness, a percentage band around the underlying, a
    strike step factor and a premium range.
    """

    def __init__(self, option_type="All", moneyness="All",
                 allow_pct=0.80, ignore_pct=0.0, step=1,
                 premium_low=None, premium_high=None):
        self.option_type = option_type        # All | Call | Put
        self.moneyness = moneyness            # All | ITM | OTM
        self.allow_pct = float(allow_pct)
        self.ignore_pct = float(ignore_pct)
        self.step = max(1, int(step))
        self.premium_low = premium_low
        self.premium_high = premium_high

    def contains_other(self, other_low, other_high):
        """True when this premium range makes the other one pointless."""
        if None in (self.premium_low, self.premium_high,
                    other_low, other_high):
            return False
        return (other_low <= self.premium_low
                and other_high >= self.premium_high)

    # ----------------------------------------------------------- select
    def select(self, ladder: StrikeLadder, spot: float):
        """Which strikes of this ladder are inside the band right now."""
        if not ladder or not spot:
            return []
        near = spot * self.allow_pct / 100.0
        far = spot * self.ignore_pct / 100.0
        picked = []

        for side, rows in (("CE", ladder.calls), ("PE", ladder.puts)):
            if self.option_type == "Call" and side != "CE":
                continue
            if self.option_type == "Put" and side != "PE":
                continue

            inside = []
            for row in rows:
                distance = abs(row["strike"] - spot)
                if distance > near or distance < far:
                    continue
                if self.moneyness == "ITM":
                    itm = (row["strike"] < spot if side == "CE"
                           else row["strike"] > spot)
                    if not itm:
                        continue
                elif self.moneyness == "OTM":
                    otm = (row["strike"] > spot if side == "CE"
                           else row["strike"] < spot)
                    if not otm:
                        continue
                inside.append(row)

            inside.sort(key=lambda r: abs(r["strike"] - spot))
            picked.extend(inside[::self.step])

        return picked


class Universe:
    """
    Keeps the live set of strikes for one strategy and reports what
    changed so the feed pool can be told the difference.
    """

    def __init__(self, underlying, rows, filt: UniverseFilter,
                 segment=None, min_days=1):
        self.underlying = underlying
        self.filter = filt
        self.ladder = build_ladders(rows, underlying, min_days=min_days)
        spot_cfg = INDEX_SPOT.get(underlying, {})
        self.spot_security_id = spot_cfg.get("security_id")
        self.spot_segment = spot_cfg.get("segment", "IDX_I")
        self.segment = segment or spot_cfg.get("fno", "NSE_FNO")
        self.spot = None
        self.current = {}                 # security_id -> row
        self.premium = {}                 # security_id -> last seen ltp

    @property
    def expiry(self):
        return self.ladder.expiry if self.ladder else None

    @property
    def lot_size(self):
        return self.ladder.lot if self.ladder else 0

    def on_spot(self, price):
        """New index price. Returns (added, removed) as lists of rows."""
        self.spot = price
        if not self.ladder:
            return [], []

        wanted = {r["security_id"]: r
                  for r in self.filter.select(self.ladder, price)}

        # The premium filter only applies once a price has been seen. A
        # strike with no quote yet is kept rather than dropped, otherwise
        # nothing could ever warm up.
        low, high = self.filter.premium_low, self.filter.premium_high
        if low is not None and high is not None:
            for sid in list(wanted):
                ltp = self.premium.get(sid)
                if ltp is not None and not (low <= ltp <= high):
                    wanted.pop(sid)

        added = [r for sid, r in wanted.items() if sid not in self.current]
        removed = [r for sid, r in self.current.items() if sid not in wanted]
        self.current = wanted
        return added, removed

    def on_premium(self, security_id, ltp):
        self.premium[str(security_id)] = ltp

    def instruments(self):
        """What to hand the feed pool, index spot included."""
        out = [{"security_id": sid, "segment": self.segment}
               for sid in self.current]
        if self.spot_security_id:
            out.append({"security_id": self.spot_security_id,
                        "segment": self.spot_segment})
        return out

    def label(self, security_id):
        row = self.current.get(str(security_id))
        if not row:
            return str(security_id)
        return (f"{row['underlying'] or self.underlying} "
                f"{int(row['strike'])} {row['option_type']}")

    def describe(self):
        return {"underlying": self.underlying,
                "expiry": self.expiry,
                "spot": self.spot,
                "strikes": len(self.current),
                "lot": self.lot_size}


def days_to_expiry(expiry):
    try:
        d = datetime.strptime(expiry, "%Y-%m-%d").date()
        return (d - dhan.now_ist().date()).days
    except (ValueError, TypeError):
        return None
