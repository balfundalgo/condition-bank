"""
The Condition Bank register.

Every condition is a small self-describing object: an id, a group, a plain
English description, the formula from the specification, and the list of
settings the user can change.  Nothing about a condition is hardcoded into
the strategy engine or the UI -- both read this register.  To add a new
condition, append one Condition() below and it appears everywhere.
"""

from dataclasses import dataclass, field
from typing import List, Tuple

TIMEFRAMES = ("1m", "3m", "5m", "15m", "30m", "1h")


@dataclass
class Param:
    key: str
    label: str
    default: float
    kind: str = "int"          # int | float | choice
    lo: float = 0
    hi: float = 1000
    choices: Tuple = ()
    hint: str = ""


@dataclass
class Condition:
    cid: str
    group: str                 # entry | exit | late
    name: str
    plain: str                 # what it means, in simple words
    formula: str               # exactly as written in the spec document
    phrase: str                # used to build the plain English sentence
    params: List[Param] = field(default_factory=list)
    timeframed: bool = True

    @property
    def color_group(self):
        return self.group


def _tf():
    return Param("timeframe", "Timeframe", "5m", "choice", choices=TIMEFRAMES,
                 hint="Chart this condition runs on")


def _bb():
    return [Param("bb_period", "BB period", 20, "int", 2, 200),
            Param("bb_stdev", "BB std deviation", 2.0, "float", 0.1, 6.0),
            _tf()]


REGISTER: List[Condition] = [
    # ---------------------------------------------------------------- ENTRY
    Condition(
        "C0", "entry", "First break above the band",
        "The last completed bar opened below the upper band and closed above "
        "it. The bar before that stayed fully below the band. This is the "
        "first push through the band.",
        "open[-1]  <  UB[-1]\nclose[-1] >  UB[-1]\nopen[-2]  <  UB[-2]\nclose[-2] <  UB[-2]",
        "the option broke above the upper band for the first time",
        _bb()),

    Condition(
        "C1", "entry", "RSI enters overbought on the last completed bar",
        "RSI must cross into the overbought zone. Simply being above the "
        "level is not enough.",
        "RSI[-2] <  Level\nRSI[-1] >= Level",
        "RSI just crossed into overbought on the last bar",
        [Param("rsi_period", "RSI period", 14, "int", 2, 100),
         Param("level", "Overbought level", 70, "float", 1, 100), _tf()]),

    Condition(
        "C2", "entry", "RSI enters overbought on the live bar",
        "The same cross, but happening on the bar that is still forming.",
        "RSI[-1] <  Level\nRSI[0]  >= Level",
        "RSI is crossing into overbought right now",
        [Param("rsi_period", "RSI period", 14, "int", 2, 100),
         Param("level", "Overbought level", 70, "float", 1, 100), _tf()]),

    Condition(
        "C3", "entry", "Volume higher than the previous N bars",
        "Checked on the last completed bar, so the volume figure is final.",
        "volume[-1] > highest volume from bar[-2] back to bar[-1-N]",
        "volume is higher than the recent bars",
        [Param("n", "N bars", 10, "int", 1, 200), _tf()]),

    Condition(
        "C4", "entry", "Price above the upper band right now",
        "The live price is trading above the upper Bollinger Band.",
        "LTP > UB[0]",
        "price is still above the upper band",
        _bb()),

    Condition(
        "C5", "entry", "ADX rising for the last N bars (live bar included)",
        "Trend strength is building, measured up to and including the live bar.",
        "ADX[0] > ADX[-1] > ADX[-2] > ... > ADX[-N]",
        "ADX is rising",
        [Param("adx_period", "ADX period", 14, "int", 2, 100),
         Param("n", "N bars", 3, "int", 1, 50), _tf()]),

    Condition(
        "C6", "entry", "Supertrend turns up on the live bar",
        "Supertrend was in the down state on the last completed bar and has "
        "flipped to the up state on the live bar.",
        "Supertrend direction[-1] = down\nSupertrend direction[0]  = up",
        "Supertrend just turned up",
        [Param("atr_period", "ATR period", 10, "int", 2, 100),
         Param("multiplier", "Multiplier", 3.0, "float", 0.5, 10.0), _tf()]),

    Condition(
        "C7", "entry", "+DI above the level on the last completed bar",
        "The positive direction line is strong.",
        "+DI[-1] > Level",
        "+DI is strong",
        [Param("di_period", "DI period", 14, "int", 2, 100),
         Param("level", "Level", 23, "float", 0, 100), _tf()]),

    Condition(
        "C8", "entry", "Minus DI below the level on the last completed bar",
        "This is the -DI line, not the +DI line. It confirms the downward "
        "pressure is weak.",
        "-DI[-1] < Level",
        "-DI is weak",
        [Param("di_period", "DI period", 14, "int", 2, 100),
         Param("level", "Level", 23, "float", 0, 100), _tf()]),

    Condition(
        "C9", "entry", "RSI inside a band on the last completed bar",
        "RSI is strong but not extreme.",
        "Lower <= RSI[-1] <= Upper",
        "RSI is inside the strong zone",
        [Param("rsi_period", "RSI period", 14, "int", 2, 100),
         Param("lower", "Lower", 70, "float", 1, 100),
         Param("upper", "Upper", 80, "float", 1, 100), _tf()]),

    Condition(
        "C10", "entry", "ADX rising for the last N bars, checked one bar back",
        "Same idea as C5, but the live bar is ignored so the value is confirmed.",
        "ADX[-1] > ADX[-2] > ... > ADX[-1-N]",
        "ADX was already rising on the last bar",
        [Param("adx_period", "ADX period", 14, "int", 2, 100),
         Param("n", "N bars", 3, "int", 1, 50), _tf()]),

    Condition(
        "C11", "entry", "Break of the previous N bar high",
        "Checked live. Price is now above the highest high of the last N "
        "completed bars.",
        "LTP > highest high from bar[-1] back to bar[-N]",
        "price broke the recent high",
        [Param("n", "N bars", 4, "int", 1, 100), _tf()]),

    Condition(
        "C12", "entry", "+DI crosses above ADX within the last N bars",
        "The cross must have happened somewhere inside the window, not "
        "necessarily on this bar.",
        "for any bar k inside the last N bars:\n    +DI[k-1] <= ADX[k-1]  and  +DI[k] > ADX[k]",
        "+DI recently cut above ADX",
        [Param("adx_period", "ADX / DI period", 14, "int", 2, 100),
         Param("n", "N bars", 5, "int", 1, 50), _tf()]),

    Condition(
        "C13", "entry", "Minus DI crosses below ADX within the last N bars",
        "Downward pressure has recently given way.",
        "for any bar k inside the last N bars:\n    -DI[k-1] >= ADX[k-1]  and  -DI[k] < ADX[k]",
        "-DI recently cut below ADX",
        [Param("adx_period", "ADX / DI period", 14, "int", 2, 100),
         Param("n", "N bars", 5, "int", 1, 50), _tf()]),

    Condition(
        "C14", "entry", "Option price inside a band",
        "A price filter on the option premium itself. Checked at the moment "
        "of the signal.",
        "Lower <= LTP <= Upper",
        "the premium is inside the allowed price band",
        [Param("lower", "Lower price", 90, "float", 0, 100000),
         Param("upper", "Upper price", 300, "float", 0, 100000)],
        timeframed=False),

    Condition(
        "C15", "entry", "Re-break above the band",
        "Same crossing bar as C0, but the bar before it was fully ABOVE the "
        "band. Price was already extended, came back, and pushed through again.",
        "open[-1]  <  UB[-1]\nclose[-1] >  UB[-1]\nopen[-2]  >  UB[-2]\nclose[-2] >  UB[-2]",
        "the option re-broke above the upper band",
        _bb()),

    Condition(
        "C16", "entry", "RSI stayed below a level in an older window",
        "Looks at an older stretch of bars, not the recent ones. It confirms "
        "the move is fresh.",
        "window starts at bar[-Offset]\nwindow is Width bars long\n\nRSI must be below Level on every bar in that window",
        "RSI was quiet before this move",
        [Param("rsi_period", "RSI period", 14, "int", 2, 100),
         Param("level", "Level", 40, "float", 1, 100),
         Param("offset", "Offset (bars back)", 5, "int", 1, 200),
         Param("width", "Width (bars)", 5, "int", 1, 200), _tf()]),

    # ----------------------------------------------------------------- EXIT
    Condition(
        "X0", "exit", "EMA5 below EMA21 on the live bar",
        "The fast average has dropped under the slow average right now.",
        "EMA5[0] < EMA21[0]",
        "EMA5 has fallen below EMA21",
        [Param("fast", "Fast EMA", 5, "int", 2, 100),
         Param("slow", "Slow EMA", 21, "int", 2, 400), _tf()]),

    Condition(
        "X1", "exit", "EMA5 and EMA8 below EMA21 on the last completed bar",
        "Both short averages are under the slow average, confirmed on a "
        "closed bar.",
        "EMA5[-1] < EMA21[-1]\nEMA8[-1] < EMA21[-1]",
        "both short EMAs closed below EMA21",
        [Param("fast", "Fast EMA", 5, "int", 2, 100),
         Param("mid", "Mid EMA", 8, "int", 2, 200),
         Param("slow", "Slow EMA", 21, "int", 2, 400), _tf()]),

    Condition(
        "X2", "exit", "Last completed bar low below EMA8",
        "The bar traded through the mid average.",
        "low[-1] < EMA8[-1]",
        "the last bar dipped below EMA8",
        [Param("mid", "Mid EMA", 8, "int", 2, 200), _tf()]),

    # ----------------------------------------------------------- LATE ENTRY
    Condition(
        "L0", "late", "RSI above a level on the live bar",
        "Momentum is still present when the confirmation is checked.",
        "RSI[0] > Level",
        "RSI is still above the level",
        [Param("rsi_period", "RSI period", 14, "int", 2, 100),
         Param("level", "Level", 70, "float", 1, 100), _tf()]),

    Condition(
        "L1", "late", "+DI rising for the last N bars (live bar included)",
        "The upward pressure has not faded since the signal.",
        "+DI[0] > +DI[-1] > ... > +DI[-N]",
        "+DI is still rising",
        [Param("di_period", "DI period", 14, "int", 2, 100),
         Param("n", "N bars", 3, "int", 1, 50), _tf()]),

    Condition(
        "L2", "late", "Price has moved a set percentage after the signal",
        "Proof that the move is real before any money is put in.",
        "LTP >= signal price x (1 + Percent / 100)",
        "price has already moved in our favour",
        [Param("percent", "Percent move", 2.0, "float", 0.1, 100.0)],
        timeframed=False),
]

BY_ID = {c.cid: c for c in REGISTER}


def get(cid: str) -> Condition:
    return BY_ID[cid]


def by_group(group: str) -> List[Condition]:
    return [c for c in REGISTER if c.group == group]


def ids(group: str = None) -> List[str]:
    return [c.cid for c in REGISTER if group is None or c.group == group]


def default_params(cid: str) -> dict:
    return {p.key: p.default for p in BY_ID[cid].params}


def all_defaults() -> dict:
    return {c.cid: default_params(c.cid) for c in REGISTER}
