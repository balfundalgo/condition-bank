"""
Condition evaluator.

This is where the condition bank stops being a description and becomes
arithmetic. Every condition in core/conditions.py has an entry here with
two parts:

    requires(params)   which indicators this condition needs, so the engine
                       builds only what is actually used
    check(ctx, params) True, False, or None when there is not enough data

Returning None rather than False matters. A strike that has not warmed up
has not failed the condition — it simply cannot be judged yet, and the
strategy must be skipped rather than counted as a miss.

Bar offsets follow the specification: 0 is the live bar, -1 the last
completed bar, -2 the one before that.
"""

from . import conditions as C


class Ctx:
    """What a condition is allowed to look at."""

    def __init__(self, strike, ltp=None, signal_price=None):
        self.strike = strike
        self.ltp = ltp if ltp is not None else strike.ltp
        self.signal_price = signal_price

    def series(self, params):
        return self.strike.series.get(str(params.get("timeframe", "5m")))


# ──────────────────────────────────────────────────── parameter helpers
def _i(params, key, default):
    try:
        return int(float(params.get(key, default)))
    except (TypeError, ValueError):
        return int(default)


def _f(params, key, default):
    try:
        return float(params.get(key, default))
    except (TypeError, ValueError):
        return float(default)


def _bb_spec(p):
    return ("bb", _i(p, "bb_period", 20), _f(p, "bb_stdev", 2.0))


def _rsi_spec(p):
    return ("rsi", _i(p, "rsi_period", 14))


def _dmi_spec(p, key="adx_period"):
    return ("dmi", _i(p, key, 14))


# ────────────────────────────────────────────────────── small utilities
def _upper(series, spec, offset):
    band = series.value(spec, offset)
    return band["upper"] if band else None


def _strictly_rising(values):
    """values[0] is the newest. True only if each is above the one before."""
    if any(v is None for v in values):
        return None
    return all(values[i] > values[i + 1] for i in range(len(values) - 1))


def _bars_back(series, first, count, key):
    """count bars ending at offset `first` and going further back."""
    out = []
    for k in range(count):
        bar = series.bar(first - k)
        if bar is None:
            return None
        out.append(bar[key])
    return out


# ═══════════════════════════════════════════════════ ENTRY CONDITIONS
def _c0(ctx, p):
    s = ctx.series(p)
    spec = _bb_spec(p)
    b1, b2 = s.bar(-1), s.bar(-2)
    u1, u2 = _upper(s, spec, -1), _upper(s, spec, -2)
    if None in (b1, b2, u1, u2):
        return None
    return (b1["o"] < u1 and b1["c"] > u1
            and b2["o"] < u2 and b2["c"] < u2)


def _c1(ctx, p):
    s = ctx.series(p)
    spec = _rsi_spec(p)
    level = _f(p, "level", 70)
    prev, last = s.value(spec, -2), s.value(spec, -1)
    if prev is None or last is None:
        return None
    return prev < level <= last


def _c2(ctx, p):
    s = ctx.series(p)
    spec = _rsi_spec(p)
    level = _f(p, "level", 70)
    prev, now = s.value(spec, -1), s.value(spec, 0)
    if prev is None or now is None:
        return None
    return prev < level <= now


def _c3(ctx, p):
    s = ctx.series(p)
    n = _i(p, "n", 10)
    last = s.bar(-1)
    window = _bars_back(s, -2, n, "v")
    if last is None or window is None:
        return None
    return last["v"] > max(window)


def _c4(ctx, p):
    s = ctx.series(p)
    upper = _upper(s, _bb_spec(p), 0)
    if upper is None or ctx.ltp is None:
        return None
    return ctx.ltp > upper


def _c5(ctx, p):
    s = ctx.series(p)
    spec = _dmi_spec(p)
    n = _i(p, "n", 3)
    values = []
    for k in range(n + 1):
        v = s.value(spec, -k if k else 0)
        values.append(v["adx"] if v else None)
    return _strictly_rising(values)


def _c6(ctx, p):
    s = ctx.series(p)
    spec = ("st", _i(p, "atr_period", 10), _f(p, "multiplier", 3.0))
    prev, now = s.value(spec, -1), s.value(spec, 0)
    if prev is None or now is None:
        return None
    return prev[0] == -1 and now[0] == 1


def _c7(ctx, p):
    s = ctx.series(p)
    v = s.value(_dmi_spec(p, "di_period"), -1)
    if not v or v["plus_di"] is None:
        return None
    return v["plus_di"] > _f(p, "level", 23)


def _c8(ctx, p):
    s = ctx.series(p)
    v = s.value(_dmi_spec(p, "di_period"), -1)
    if not v or v["minus_di"] is None:
        return None
    return v["minus_di"] < _f(p, "level", 23)


def _c9(ctx, p):
    s = ctx.series(p)
    v = s.value(_rsi_spec(p), -1)
    if v is None:
        return None
    return _f(p, "lower", 70) <= v <= _f(p, "upper", 80)


def _c10(ctx, p):
    s = ctx.series(p)
    spec = _dmi_spec(p)
    n = _i(p, "n", 3)
    values = []
    for k in range(n + 1):
        v = s.value(spec, -1 - k)
        values.append(v["adx"] if v else None)
    return _strictly_rising(values)


def _c11(ctx, p):
    s = ctx.series(p)
    n = _i(p, "n", 4)
    window = _bars_back(s, -1, n, "h")
    if window is None or ctx.ltp is None:
        return None
    return ctx.ltp > max(window)


def _cross(series, spec, n, line, upward):
    """Did `line` cross the ADX in the last n bars, live bar included?"""
    for k in range(n):
        now = series.value(spec, -k if k else 0)
        before = series.value(spec, -k - 1)
        if not now or not before:
            return None
        if None in (now[line], now["adx"], before[line], before["adx"]):
            return None
        if upward:
            if before[line] <= before["adx"] and now[line] > now["adx"]:
                return True
        else:
            if before[line] >= before["adx"] and now[line] < now["adx"]:
                return True
    return False


def _c12(ctx, p):
    return _cross(ctx.series(p), _dmi_spec(p), _i(p, "n", 5),
                  "plus_di", True)


def _c13(ctx, p):
    return _cross(ctx.series(p), _dmi_spec(p), _i(p, "n", 5),
                  "minus_di", False)


def _c14(ctx, p):
    if ctx.ltp is None:
        return None
    return _f(p, "lower", 90) <= ctx.ltp <= _f(p, "upper", 300)


def _c15(ctx, p):
    s = ctx.series(p)
    spec = _bb_spec(p)
    b1, b2 = s.bar(-1), s.bar(-2)
    u1, u2 = _upper(s, spec, -1), _upper(s, spec, -2)
    if None in (b1, b2, u1, u2):
        return None
    return (b1["o"] < u1 and b1["c"] > u1
            and b2["o"] > u2 and b2["c"] > u2)


def _c16(ctx, p):
    s = ctx.series(p)
    spec = _rsi_spec(p)
    level = _f(p, "level", 40)
    offset = _i(p, "offset", 5)
    width = _i(p, "width", 5)
    for k in range(width):
        v = s.value(spec, -offset - k)
        if v is None:
            return None
        if v >= level:
            return False
    return True


# ════════════════════════════════════════════════════ EXIT CONDITIONS
def _x0(ctx, p):
    s = ctx.series(p)
    fast = s.value(("ema", _i(p, "fast", 5)), 0)
    slow = s.value(("ema", _i(p, "slow", 21)), 0)
    if fast is None or slow is None:
        return None
    return fast < slow


def _x1(ctx, p):
    s = ctx.series(p)
    fast = s.value(("ema", _i(p, "fast", 5)), -1)
    mid = s.value(("ema", _i(p, "mid", 8)), -1)
    slow = s.value(("ema", _i(p, "slow", 21)), -1)
    if None in (fast, mid, slow):
        return None
    return fast < slow and mid < slow


def _x2(ctx, p):
    s = ctx.series(p)
    bar = s.bar(-1)
    mid = s.value(("ema", _i(p, "mid", 8)), -1)
    if bar is None or mid is None:
        return None
    return bar["l"] < mid


# ══════════════════════════════════════════════ LATE ENTRY CONDITIONS
def _l0(ctx, p):
    v = ctx.series(p).value(_rsi_spec(p), 0)
    if v is None:
        return None
    return v > _f(p, "level", 70)


def _l1(ctx, p):
    s = ctx.series(p)
    spec = _dmi_spec(p, "di_period")
    n = _i(p, "n", 3)
    values = []
    for k in range(n + 1):
        v = s.value(spec, -k if k else 0)
        values.append(v["plus_di"] if v else None)
    return _strictly_rising(values)


def _l2(ctx, p):
    if ctx.ltp is None or ctx.signal_price in (None, 0):
        return None
    return ctx.ltp >= ctx.signal_price * (1.0 + _f(p, "percent", 2.0) / 100.0)


# ═════════════════════════════════════════════════════════ the register
def _req_bb(p):
    return [_bb_spec(p)]


def _req_rsi(p):
    return [_rsi_spec(p)]


def _req_adx(p):
    return [_dmi_spec(p)]


def _req_di(p):
    return [_dmi_spec(p, "di_period")]


def _req_none(p):
    return []


CHECKS = {
    "C0":  (_c0,  _req_bb),
    "C1":  (_c1,  _req_rsi),
    "C2":  (_c2,  _req_rsi),
    "C3":  (_c3,  _req_none),
    "C4":  (_c4,  _req_bb),
    "C5":  (_c5,  _req_adx),
    "C6":  (_c6,  lambda p: [("st", _i(p, "atr_period", 10),
                              _f(p, "multiplier", 3.0))]),
    "C7":  (_c7,  _req_di),
    "C8":  (_c8,  _req_di),
    "C9":  (_c9,  _req_rsi),
    "C10": (_c10, _req_adx),
    "C11": (_c11, _req_none),
    "C12": (_c12, _req_adx),
    "C13": (_c13, _req_adx),
    "C14": (_c14, _req_none),
    "C15": (_c15, _req_bb),
    "C16": (_c16, _req_rsi),
    "X0":  (_x0,  lambda p: [("ema", _i(p, "fast", 5)),
                             ("ema", _i(p, "slow", 21))]),
    "X1":  (_x1,  lambda p: [("ema", _i(p, "fast", 5)),
                             ("ema", _i(p, "mid", 8)),
                             ("ema", _i(p, "slow", 21))]),
    "X2":  (_x2,  lambda p: [("ema", _i(p, "mid", 8))]),
    "L0":  (_l0,  _req_rsi),
    "L1":  (_l1,  _req_di),
    "L2":  (_l2,  _req_none),
}


# ───────────────────────────────────────────── how much history is needed
def min_bars(cid, params) -> int:
    """Roughly how many completed bars before this condition can be judged."""
    p = params
    if cid in ("C0", "C4", "C15"):
        return _i(p, "bb_period", 20) + 2
    if cid in ("C1", "C2", "C9", "L0"):
        return _i(p, "rsi_period", 14) + 3
    if cid == "C16":
        return (_i(p, "rsi_period", 14) + _i(p, "offset", 5)
                + _i(p, "width", 5) + 1)
    if cid == "C3":
        return _i(p, "n", 10) + 2
    if cid in ("C5", "C10"):
        return _i(p, "adx_period", 14) * 2 + _i(p, "n", 3) + 2
    if cid in ("C12", "C13"):
        return _i(p, "adx_period", 14) * 2 + _i(p, "n", 5) + 2
    if cid in ("C7", "C8", "L1"):
        return _i(p, "di_period", 14) * 2 + _i(p, "n", 3) + 2
    if cid == "C6":
        return _i(p, "atr_period", 10) + 3
    if cid == "C11":
        return _i(p, "n", 4) + 1
    if cid in ("X0", "X1", "X2"):
        return max(_i(p, "fast", 5), _i(p, "mid", 8),
                   _i(p, "slow", 21)) + 2
    return 2


# ──────────────────────────────────────────────────────── public access
def evaluate(cid, ctx, params):
    entry = CHECKS.get(cid)
    if entry is None:
        return None
    try:
        return entry[0](ctx, params)
    except Exception:
        return None


def requirements(strategy):
    """
    Walk one strategy and return timeframe -> set of indicator specs, plus
    timeframe -> how many bars the hungriest condition on it needs.
    """
    specs, needed = {}, {}
    tokens = list(strategy.entry) + list(strategy.exit)
    if strategy.late_enabled:
        tokens += list(strategy.late)
    for cid in {t for t in tokens if t in C.BY_ID}:
        params = strategy.params.get(cid, C.default_params(cid))
        if not C.get(cid).timeframed:
            # C14 and L2 read only the live price, so they need no series
            continue
        tf = str(params.get("timeframe", "5m"))
        specs.setdefault(tf, set()).update(CHECKS[cid][1](params))
        needed[tf] = max(needed.get(tf, 0), min_bars(cid, params))
    return specs, needed


def merge_requirements(strategies):
    """Combine the needs of every active strategy into one build plan."""
    specs, needed = {}, {}
    for strategy in strategies:
        s_specs, s_needed = requirements(strategy)
        for tf, items in s_specs.items():
            specs.setdefault(tf, set()).update(items)
        for tf, bars in s_needed.items():
            needed[tf] = max(needed.get(tf, 0), bars)
    return specs, needed


def evaluate_expression(tokens, ctx, strategy):
    """
    Work out a saved expression against one strike.
    Returns True, False, or None when any condition lacks data.
    """
    from . import expression as E
    values = {}
    for cid in E.conditions_used(tokens):
        params = strategy.params.get(cid, C.default_params(cid))
        result = evaluate(cid, ctx, params)
        if result is None:
            return None
        values[cid] = result
    if not values:
        return None
    try:
        return E.evaluate(tokens, values)
    except Exception:
        return None
