"""
Candles and indicator series for one strike on one timeframe.

A strike can be watched on several timeframes at once, because every
condition carries its own. Each timeframe gets its own Series.

Two things are kept side by side and stay aligned:

    bars    the last N completed bars
    snaps   the indicator values AS THEY WERE at each of those bars

The snapshots matter. Conditions like C0 and C15 compare a bar's open and
close against the Bollinger band AT THAT BAR, not against today's band. The
only honest way to do that is to record the value when the bar closed.

The live bar is never written into either list. Its indicator values are
produced on demand with preview(), so the completed-bar state stays clean.
"""

from collections import deque

from . import indicators as I

HISTORY = 400          # completed bars kept per series
TIMEFRAME_SECONDS = {"1m": 60, "3m": 180, "5m": 300,
                     "15m": 900, "30m": 1800, "1h": 3600}


def tf_seconds(timeframe) -> int:
    return TIMEFRAME_SECONDS.get(str(timeframe), 300)


def make_indicator(spec):
    """spec is a tuple like ('rsi', 14) or ('bb', 20, 2.0)."""
    kind = spec[0]
    if kind == "rsi":
        return I.Rsi(spec[1])
    if kind == "ema":
        return I.Ema(spec[1])
    if kind == "atr":
        return I.Atr(spec[1])
    if kind == "dmi":
        return I.Dmi(spec[1])
    if kind == "st":
        return I.Supertrend(spec[1], spec[2])
    if kind == "bb":
        return I.BollingerLow(spec[1], spec[2])
    raise ValueError(f"unknown indicator spec: {spec}")


class Series:
    """One timeframe of one strike."""

    def __init__(self, timeframe, specs):
        self.timeframe = str(timeframe)
        self.interval = tf_seconds(timeframe)
        self.specs = sorted(set(specs))
        self.ind = {s: make_indicator(s) for s in self.specs}
        self.bars = deque(maxlen=HISTORY)
        self.snaps = deque(maxlen=HISTORY)
        self.live = None            # the bar still forming
        self.bars_seen = 0

    # ---------------------------------------------------------- building
    def on_close(self, bar):
        """Commit a completed bar and record the indicator values at it."""
        snap = {}
        for spec, ind in self.ind.items():
            snap[spec] = ind.update(bar)
        self.bars.append(dict(bar))
        self.snaps.append(snap)
        self.bars_seen += 1

    def seed(self, bars):
        """Replay historical bars at warm-up. Same path as live closes."""
        for bar in bars:
            self.on_close(bar)

    # ------------------------------------------------------------ access
    def bar(self, offset):
        """offset 0 is the live bar, -1 the last completed bar, and so on."""
        if offset == 0:
            return self.live
        idx = len(self.bars) + offset
        if idx < 0 or idx >= len(self.bars):
            return None
        return self.bars[idx]

    def value(self, spec, offset):
        """Indicator value at that bar. offset 0 previews the live bar."""
        if spec not in self.ind:
            return None
        if offset == 0:
            if self.live is None:
                return None
            return self.ind[spec].preview(self.live)
        idx = len(self.snaps) + offset
        if idx < 0 or idx >= len(self.snaps):
            return None
        return self.snaps[idx].get(spec)

    def ready(self, needed_bars):
        return self.bars_seen >= needed_bars


class StrikeData:
    """All the timeframes being tracked for one strike, plus its candles."""

    def __init__(self, security_id, label, requirements):
        """requirements maps timeframe -> set of indicator specs."""
        self.security_id = str(security_id)
        self.label = label
        self.ltp = None
        self.series = {tf: Series(tf, specs)
                       for tf, specs in requirements.items()}
        self.warm = False
        self.partial = False        # warmed on less history than asked for
        self._buckets = {}

    # ---------------------------------------------------------- the feed
    def on_tick(self, ltp, epoch, volume_delta=0):
        """
        One price update. Rolls each timeframe's bar when its clock ends.
        Returns the list of timeframes that just closed a bar.
        """
        self.ltp = ltp
        closed = []
        for tf, series in self.series.items():
            bucket = epoch - (epoch % series.interval)
            live = series.live
            if live is None or bucket > live["t"]:
                if live is not None:
                    series.on_close(live)
                    closed.append(tf)
                series.live = {"t": bucket, "o": ltp, "h": ltp, "l": ltp,
                               "c": ltp, "v": volume_delta}
            else:
                live["h"] = max(live["h"], ltp)
                live["l"] = min(live["l"], ltp)
                live["c"] = ltp
                live["v"] += volume_delta
        return closed

    def seed(self, timeframe, bars):
        series = self.series.get(timeframe)
        if series is not None:
            series.seed(bars)

    def bars_seen(self, timeframe):
        series = self.series.get(timeframe)
        return series.bars_seen if series else 0
