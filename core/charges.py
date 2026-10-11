"""
Trading charges.

What a trade actually costs, on top of the price difference. For option
buying on a small premium these charges are not a rounding error — on a
₹20,000 premium round trip they can run to a couple of hundred rupees,
which is a real part of whether a strategy makes money.

Every rate below is a SETTING, not a constant. Rates change with budgets
and exchange circulars, and the defaults carry the date they were last
checked so nobody trusts a stale number by accident. The one thing that
settles an argument is the contract note: if the app and the broker
disagree, the broker is right and the rates here should be corrected.

How an option trade is charged
------------------------------
  Brokerage        per executed order. Dhan is a flat 20 rupees on F&O.
  STT              sell side only, on the premium.
  Exchange charge  both sides, on the premium. Differs NSE vs BSE.
  SEBI turnover    both sides, 10 rupees per crore.
  Stamp duty       buy side only, on the premium.
  GST              18% on brokerage + exchange + SEBI + IPFT.
                   NOT on STT and NOT on stamp duty — those are taxes,
                   not payment for a service.
"""

from dataclasses import dataclass, asdict, field

RATES_CHECKED = "2026-10-11"

# Where the defaults came from, so they can be re-checked later.
SOURCES = (
    "Brokerage: Dhan published rate card, flat Rs 20 per executed F&O order. "
    "STT on options: 0.15% of the sell-side premium (raised from 0.10% in "
    "the 2026 budget). Exchange transaction charge NSE: 0.03503% of premium. "
    "SEBI turnover fee: 0.0001% (Rs 10 per crore), both sides. Stamp duty: "
    "0.003% of premium, buy side only. GST: 18% on brokerage plus exchange "
    "plus SEBI."
)

# The BSE option transaction charge is the one number the public sources
# disagree on, so it is flagged rather than quietly assumed correct.
UNVERIFIED = ("exchange_bse",)


@dataclass
class ChargeRates:
    # brokerage, per executed order
    brokerage_flat: float = 20.0        # rupees per order
    brokerage_pct: float = 0.0          # percent of turnover, if used
    brokerage_cap: float = 20.0         # 0 means no cap

    # statutory, all percentages of the premium turnover
    stt_sell: float = 0.15              # sell side only
    exchange_nse: float = 0.03503       # both sides
    exchange_bse: float = 0.0325        # both sides -- verify this one
    sebi: float = 0.0001                # both sides, Rs 10 per crore
    stamp_buy: float = 0.003            # buy side only
    ipft: float = 0.0                   # investor protection fund, if any
    gst: float = 18.0                   # on brokerage + exchange + sebi + ipft

    checked: str = RATES_CHECKED

    def to_dict(self):
        return asdict(self)

    @staticmethod
    def from_dict(d):
        if not d:
            return ChargeRates()
        known = {f for f in ChargeRates.__dataclass_fields__}
        return ChargeRates(**{k: v for k, v in d.items() if k in known})


DEFAULTS = ChargeRates()

LABELS = {
    "brokerage": "Brokerage",
    "stt": "STT",
    "exchange": "Exchange charge",
    "sebi": "SEBI turnover fee",
    "stamp": "Stamp duty",
    "ipft": "IPFT",
    "gst": "GST",
}


def _brokerage(turnover, rates: ChargeRates):
    value = rates.brokerage_flat + turnover * rates.brokerage_pct / 100.0
    if rates.brokerage_cap:
        value = min(value, rates.brokerage_cap)
    return value


def leg(turnover, side, exchange="NSE", rates: ChargeRates = None):
    """
    Charges for one executed order. `turnover` is premium x quantity.
    Returns every line separately so the user can see where it went.
    """
    rates = rates or DEFAULTS
    side = (side or "BUY").upper()
    turnover = max(float(turnover or 0.0), 0.0)

    exchange_pct = (rates.exchange_bse if str(exchange).upper() == "BSE"
                    else rates.exchange_nse)

    brokerage = _brokerage(turnover, rates)
    exch = turnover * exchange_pct / 100.0
    sebi = turnover * rates.sebi / 100.0
    ipft = turnover * rates.ipft / 100.0
    stt = turnover * rates.stt_sell / 100.0 if side == "SELL" else 0.0
    stamp = turnover * rates.stamp_buy / 100.0 if side == "BUY" else 0.0
    gst = (brokerage + exch + sebi + ipft) * rates.gst / 100.0

    lines = {"brokerage": brokerage, "stt": stt, "exchange": exch,
             "sebi": sebi, "stamp": stamp, "ipft": ipft, "gst": gst}
    return {"lines": lines, "total": sum(lines.values()),
            "turnover": turnover, "side": side}


def round_trip(entry_price, exit_price, qty, exchange="NSE",
               rates: ChargeRates = None):
    """
    A complete buy-then-sell option trade. Returns the gross profit, every
    charge line added across both legs, and what is actually left.
    """
    rates = rates or DEFAULTS
    buy = leg(entry_price * qty, "BUY", exchange, rates)
    sell = leg(exit_price * qty, "SELL", exchange, rates)

    lines = {key: buy["lines"].get(key, 0.0) + sell["lines"].get(key, 0.0)
             for key in LABELS}
    total = buy["total"] + sell["total"]
    gross = (exit_price - entry_price) * qty
    return {"buy": buy, "sell": sell, "lines": lines, "total": total,
            "gross": gross, "net": gross - total,
            "breakeven_move": (total / qty) if qty else 0.0}


def estimate_open(entry_price, qty, exchange="NSE", rates: ChargeRates = None):
    """
    What an open position has already cost, plus what the exit will cost
    if it closes near here. Shown live so the user is never surprised at
    the end of the day.
    """
    rates = rates or DEFAULTS
    buy = leg(entry_price * qty, "BUY", exchange, rates)
    sell = leg(entry_price * qty, "SELL", exchange, rates)
    return {"paid": buy["total"], "expected_exit": sell["total"],
            "round_trip": buy["total"] + sell["total"]}


def describe(rates: ChargeRates = None):
    """Rows for the settings screen."""
    rates = rates or DEFAULTS
    return [
        ("brokerage_flat", "Brokerage per order (Rs)", rates.brokerage_flat),
        ("brokerage_pct", "Brokerage percent of turnover", rates.brokerage_pct),
        ("brokerage_cap", "Brokerage cap per order (Rs)", rates.brokerage_cap),
        ("stt_sell", "STT, sell side (%)", rates.stt_sell),
        ("exchange_nse", "Exchange charge NSE (%)", rates.exchange_nse),
        ("exchange_bse", "Exchange charge BSE (%)", rates.exchange_bse),
        ("sebi", "SEBI turnover fee (%)", rates.sebi),
        ("stamp_buy", "Stamp duty, buy side (%)", rates.stamp_buy),
        ("ipft", "IPFT (%)", rates.ipft),
        ("gst", "GST (%)", rates.gst),
    ]
