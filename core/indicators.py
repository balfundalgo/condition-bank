"""
Indicator engine.

Every indicator is incremental. State is a small tuple of floats and each
new bar advances it with a single step, so the cost per bar does not grow
with history. That matters here because thousands of option strikes can be
live at once, each on more than one timeframe.

Each indicator exposes the same two calls:

    update(bar)   advances the state and returns the new value
    preview(bar)  returns what the value WOULD be, without advancing

preview() is what makes live-bar conditions possible. C2, C4, C5, C6, C11,
L0 and L1 all read the still-forming bar, and they must not corrupt the
state that the completed bars have built up.

Wilder smoothing is used for RSI, ATR and ADX/DI, which is what charting
packages use. Bollinger Bands are calculated on the LOW series throughout,
as the specification requires.
"""

import math
from collections import deque


class _Base:
    """update() commits, preview() does not. Subclasses implement _step()."""

    def _step(self, state, bar):
        raise NotImplementedError

    def update(self, bar):
        self._state, value = self._step(self._state, bar)
        return value

    def preview(self, bar):
        _, value = self._step(self._state, bar)
        return value

    @property
    def ready(self):
        return self._count >= self._min_bars


# ───────────────────────────────────────────────────────────── EMA
class Ema(_Base):
    def __init__(self, period):
        self.period = int(period)
        self.alpha = 2.0 / (self.period + 1.0)
        self._min_bars = self.period
        self._count = 0
        # state: (ema, seed_sum, seed_n)
        self._state = (None, 0.0, 0)

    def _step(self, state, bar):
        ema, seed_sum, seed_n = state
        close = bar["c"]
        if ema is None:
            seed_sum += close
            seed_n += 1
            if seed_n >= self.period:
                ema = seed_sum / seed_n
                return (ema, seed_sum, seed_n), ema
            return (None, seed_sum, seed_n), None
        ema = close * self.alpha + ema * (1.0 - self.alpha)
        return (ema, seed_sum, seed_n), ema

    def update(self, bar):
        self._count += 1
        return super().update(bar)


# ───────────────────────────────────────────────────────────── RSI
class Rsi(_Base):
    """Wilder's RSI."""

    def __init__(self, period):
        self.period = int(period)
        self._min_bars = self.period + 1
        self._count = 0
        # state: (prev_close, avg_gain, avg_loss, seeded_n, gain_sum, loss_sum)
        self._state = (None, None, None, 0, 0.0, 0.0)

    def _step(self, state, bar):
        prev_close, avg_gain, avg_loss, n, gain_sum, loss_sum = state
        close = bar["c"]
        if prev_close is None:
            return (close, None, None, 0, 0.0, 0.0), None

        change = close - prev_close
        gain = change if change > 0 else 0.0
        loss = -change if change < 0 else 0.0

        if avg_gain is None:
            gain_sum += gain
            loss_sum += loss
            n += 1
            if n < self.period:
                return (close, None, None, n, gain_sum, loss_sum), None
            avg_gain = gain_sum / self.period
            avg_loss = loss_sum / self.period
        else:
            avg_gain = (avg_gain * (self.period - 1) + gain) / self.period
            avg_loss = (avg_loss * (self.period - 1) + loss) / self.period

        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
        return (close, avg_gain, avg_loss, n, gain_sum, loss_sum), rsi

    def update(self, bar):
        self._count += 1
        return super().update(bar)


# ───────────────────────────────────────────────────────────── ATR
class Atr(_Base):
    """Wilder's ATR. Returns (atr, true_range)."""

    def __init__(self, period):
        self.period = int(period)
        self._min_bars = self.period + 1
        self._count = 0
        # state: (prev_close, atr, seed_sum, seed_n)
        self._state = (None, None, 0.0, 0)

    @staticmethod
    def true_range(bar, prev_close):
        if prev_close is None:
            return bar["h"] - bar["l"]
        return max(bar["h"] - bar["l"],
                   abs(bar["h"] - prev_close),
                   abs(bar["l"] - prev_close))

    def _step(self, state, bar):
        prev_close, atr, seed_sum, seed_n = state
        if prev_close is None:
            # The first bar has no previous close, so its true range is just
            # the high-low range and is not comparable. Wilder starts the
            # average from the second bar.
            return (bar["c"], None, 0.0, 0), None
        tr = self.true_range(bar, prev_close)
        if atr is None:
            seed_sum += tr
            seed_n += 1
            if seed_n >= self.period:
                atr = seed_sum / self.period
                return (bar["c"], atr, seed_sum, seed_n), atr
            return (bar["c"], None, seed_sum, seed_n), None
        atr = (atr * (self.period - 1) + tr) / self.period
        return (bar["c"], atr, seed_sum, seed_n), atr

    def update(self, bar):
        self._count += 1
        return super().update(bar)


# ───────────────────────────────────────────────────────── ADX / DI
class Dmi(_Base):
    """
    Wilder's Directional Movement. Returns a dict with plus_di, minus_di
    and adx, any of which may be None until enough bars have passed.
    """

    def __init__(self, period):
        self.period = int(period)
        self._min_bars = self.period * 2 + 1
        self._count = 0
        # state: (prev_high, prev_low, prev_close,
        #         sm_tr, sm_pdm, sm_mdm, seed_n,
        #         tr_sum, pdm_sum, mdm_sum,
        #         adx, dx_sum, dx_n)
        self._state = (None, None, None,
                       None, None, None, 0,
                       0.0, 0.0, 0.0,
                       None, 0.0, 0)

    def _step(self, state, bar):
        (ph, pl, pc, sm_tr, sm_pdm, sm_mdm, seed_n,
         tr_sum, pdm_sum, mdm_sum, adx, dx_sum, dx_n) = state

        h, l, c = bar["h"], bar["l"], bar["c"]
        if ph is None:
            return ((h, l, c, None, None, None, 0, 0.0, 0.0, 0.0,
                     None, 0.0, 0),
                    {"plus_di": None, "minus_di": None, "adx": None})

        up_move = h - ph
        down_move = pl - l
        pdm = up_move if (up_move > down_move and up_move > 0) else 0.0
        mdm = down_move if (down_move > up_move and down_move > 0) else 0.0
        tr = max(h - l, abs(h - pc), abs(l - pc))

        if sm_tr is None:
            tr_sum += tr
            pdm_sum += pdm
            mdm_sum += mdm
            seed_n += 1
            if seed_n < self.period:
                return ((h, l, c, None, None, None, seed_n,
                         tr_sum, pdm_sum, mdm_sum, adx, dx_sum, dx_n),
                        {"plus_di": None, "minus_di": None, "adx": None})
            sm_tr, sm_pdm, sm_mdm = tr_sum, pdm_sum, mdm_sum
        else:
            sm_tr = sm_tr - (sm_tr / self.period) + tr
            sm_pdm = sm_pdm - (sm_pdm / self.period) + pdm
            sm_mdm = sm_mdm - (sm_mdm / self.period) + mdm

        if sm_tr == 0:
            plus_di = minus_di = 0.0
        else:
            plus_di = 100.0 * sm_pdm / sm_tr
            minus_di = 100.0 * sm_mdm / sm_tr

        di_sum = plus_di + minus_di
        dx = 0.0 if di_sum == 0 else 100.0 * abs(plus_di - minus_di) / di_sum

        if adx is None:
            dx_sum += dx
            dx_n += 1
            if dx_n >= self.period:
                adx = dx_sum / self.period
        else:
            adx = (adx * (self.period - 1) + dx) / self.period

        return ((h, l, c, sm_tr, sm_pdm, sm_mdm, seed_n,
                 tr_sum, pdm_sum, mdm_sum, adx, dx_sum, dx_n),
                {"plus_di": plus_di, "minus_di": minus_di, "adx": adx})

    def update(self, bar):
        self._count += 1
        return super().update(bar)


# ──────────────────────────────────────────────────────── Supertrend
class Supertrend(_Base):
    """
    Returns (direction, line). direction is +1 when price is above the
    Supertrend line (up state) and -1 when below (down state).
    """

    def __init__(self, period=10, multiplier=3.0):
        self.period = int(period)
        self.multiplier = float(multiplier)
        self._min_bars = self.period + 1
        self._count = 0
        self._atr = Atr(period)
        # state: (atr_state, final_upper, final_lower, direction, prev_close)
        self._state = (self._atr._state, None, None, 1, None)

    def _step(self, state, bar):
        atr_state, f_upper, f_lower, direction, prev_close = state
        atr_state, atr = self._atr._step(atr_state, bar)
        if atr is None:
            return (atr_state, None, None, direction, bar["c"]), (direction, None)

        hl2 = (bar["h"] + bar["l"]) / 2.0
        basic_upper = hl2 + self.multiplier * atr
        basic_lower = hl2 - self.multiplier * atr

        if f_upper is None:
            f_upper, f_lower = basic_upper, basic_lower
        else:
            f_upper = (basic_upper
                       if (basic_upper < f_upper or prev_close > f_upper)
                       else f_upper)
            f_lower = (basic_lower
                       if (basic_lower > f_lower or prev_close < f_lower)
                       else f_lower)

        close = bar["c"]
        if direction == 1:
            direction = -1 if close < f_lower else 1
        else:
            direction = 1 if close > f_upper else -1

        line = f_lower if direction == 1 else f_upper
        return (atr_state, f_upper, f_lower, direction, close), (direction, line)

    def update(self, bar):
        self._count += 1
        self._state, value = self._step(self._state, bar)
        self._atr._state = self._state[0]
        return value


# ─────────────────────────────────────────────── Bollinger on the LOW
class BollingerLow:
    """
    Bollinger Bands computed on the LOW series, as the specification
    requires. Running sum and sum of squares keep this O(1) per bar.
    """

    def __init__(self, period=20, stdev=2.0):
        self.period = int(period)
        self.k = float(stdev)
        self._min_bars = self.period
        self._lows = deque(maxlen=self.period)
        self._sum = 0.0
        self._sumsq = 0.0

    @property
    def ready(self):
        return len(self._lows) >= self.period

    def _bands(self, total, total_sq, n):
        if n < self.period:
            return None
        mean = total / n
        var = max(total_sq / n - mean * mean, 0.0)
        sd = math.sqrt(var)
        return {"mid": mean, "upper": mean + self.k * sd,
                "lower": mean - self.k * sd, "stdev": sd}

    def update(self, bar):
        low = bar["l"]
        if len(self._lows) == self.period:
            oldest = self._lows[0]
            self._sum -= oldest
            self._sumsq -= oldest * oldest
        self._lows.append(low)
        self._sum += low
        self._sumsq += low * low
        return self._bands(self._sum, self._sumsq, len(self._lows))

    def preview(self, bar):
        low = bar["l"]
        total, total_sq, n = self._sum, self._sumsq, len(self._lows)
        if n == self.period:
            oldest = self._lows[0]
            total -= oldest
            total_sq -= oldest * oldest
            n -= 1
        total += low
        total_sq += low * low
        n += 1
        return self._bands(total, total_sq, n)
