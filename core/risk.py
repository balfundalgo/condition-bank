"""
Risk and exits.

Everything that can close a position other than an exit condition lives
here: targets, stop-losses, the per-position trailing lock, the two
profit-lock layers and the day limits.

The order they are checked in is the eleven-step precedence from Section 8
of the specification, and the principle behind it is worth stating once:
anything protecting the whole account comes before anything managing a
single trade, and a full exit always beats a partial one.

    1   combined day loss            whole account
    2   combined day profit          whole account
    3   combined profit lock         whole account
    4   strategy day loss            whole strategy
    5   strategy day profit          whole strategy
    6   strategy profit lock         whole strategy
    7   square-off time              whole strategy
    8   trailing lock                one position
    9   stop-loss levels             one position, may be partial
    10  target levels                one position, may be partial
    11  exit conditions              one position

Price-based rules (targets, stops, trailing) work on the premium, because
that is what the user typed a percentage of. Money-based rules (day limits
and profit locks) work on NET profit after charges, because that is what
actually lands in the account.
"""

from dataclasses import dataclass

# What a check returns when it wants something closed.
SCOPE_ACCOUNT = "account"
SCOPE_STRATEGY = "strategy"
SCOPE_POSITION = "position"


@dataclass
class Action:
    scope: str
    reason: str
    qty: int = 0          # 0 with a position scope means the whole position
    level: str = ""       # which rule fired, e.g. "T2" or "S1"

    def __bool__(self):
        return True


def _rows(value):
    return value if isinstance(value, list) else []


def profit_percent(position):
    """Move from the entry price, as a percentage."""
    if not position.entry_price:
        return 0.0
    price = position.ltp or position.entry_price
    return (price - position.entry_price) / position.entry_price * 100.0


# ───────────────────────────────────────────────── per position rules
def check_targets(strategy, position):
    """
    Targets fire in order and each one fires once. Qty % is a share of the
    ORIGINAL quantity, so three 30% targets close 90% of what was opened,
    not 90% of whatever is left.
    """
    for index, row in enumerate(_rows(strategy.targets), start=1):
        name = f"T{index}"
        if not row.get("on") or name in position.levels_hit:
            continue
        rate = float(row.get("rate") or 0)
        if rate <= 0 or profit_percent(position) < rate:
            continue
        qty = _share(position, row.get("qty"))
        return Action(SCOPE_POSITION, f"target {index} at {rate:g}%",
                      qty, name)
    return None


def check_stops(strategy, position):
    """Stop rates are written as a positive number meaning an adverse move."""
    for index, row in enumerate(_rows(strategy.stops), start=1):
        name = f"S{index}"
        if not row.get("on") or name in position.levels_hit:
            continue
        rate = float(row.get("rate") or 0)
        if rate <= 0 or profit_percent(position) > -abs(rate):
            continue
        qty = _share(position, row.get("qty"))
        return Action(SCOPE_POSITION, f"stop-loss {index} at -{rate:g}%",
                      qty, name)
    return None


def _share(position, percent):
    """A percentage of the original quantity, rounded to whole lots."""
    percent = float(percent or 0)
    if percent <= 0 or percent >= 100:
        return 0                       # 0 means close everything left
    qty = int(position.original_qty * percent / 100.0)
    lot = int(position.lot_size or 0)
    if lot > 0:
        qty = (qty // lot) * lot
    return max(0, min(qty, position.qty)) or position.qty


def update_trailing(strategy, position):
    """
    Raise the locked floor as profit grows. The floor only ever moves up.
    Returns an Action when price has fallen back to the floor.
    """
    if not strategy.trailing_on:
        return None
    moved = profit_percent(position)

    for row in _rows(strategy.trailing):
        if not row.get("on"):
            continue
        at = float(row.get("at") or 0)
        lock = float(row.get("lock") or 0)
        if moved >= at:
            if position.lock_floor is None or lock > position.lock_floor:
                position.lock_floor = lock

    if position.lock_floor is None:
        return None
    if moved <= position.lock_floor:
        return Action(SCOPE_POSITION,
                      f"trailing lock at {position.lock_floor:g}%", 0,
                      "TRAIL")
    return None


# ──────────────────────────────────────────── strategy and account rules
def check_money_lock(levels, enabled, profit, state, label):
    """
    Shared by the strategy lock and the combined lock. `state` is a dict
    carrying the floor between calls, so the floor survives across ticks.
    """
    if not enabled:
        return None
    floor = state.get("floor")
    for row in _rows(levels):
        if not row.get("on"):
            continue
        at = float(row.get("at") or 0)
        lock = float(row.get("lock") or 0)
        if profit >= at and (floor is None or lock > floor):
            floor = lock
    state["floor"] = floor
    if floor is None:
        return None
    if profit <= floor:
        return Action(SCOPE_ACCOUNT if label == "combined" else SCOPE_STRATEGY,
                      f"{label} profit lock at {floor:,.0f}", 0, "LOCK")
    return None


def check_day_limits(profit, profit_on, profit_at, loss_on, loss_at, label):
    """Loss is checked before profit, as the precedence requires."""
    if loss_on and loss_at and profit <= -abs(float(loss_at)):
        scope = SCOPE_ACCOUNT if label == "combined" else SCOPE_STRATEGY
        return Action(scope, f"{label} day loss limit "
                             f"{abs(float(loss_at)):,.0f}", 0, "DAYLOSS")
    if profit_on and profit_at and profit >= abs(float(profit_at)):
        scope = SCOPE_ACCOUNT if label == "combined" else SCOPE_STRATEGY
        return Action(scope, f"{label} day profit limit "
                             f"{abs(float(profit_at)):,.0f}", 0, "DAYPROFIT")
    return None


# ───────────────────────────────────────────────────────── the sequence
class RiskState:
    """Floors and halts that have to survive between ticks."""

    def __init__(self):
        self.combined_lock = {}
        self.strategy_lock = {}        # strategy number -> {"floor": x}
        self.halted = set()            # strategy numbers halted for the day
        self.account_halted = False
        self.reasons = []

    def halt(self, action, strategy_number=None):
        if action.scope == SCOPE_ACCOUNT:
            self.account_halted = True
        elif strategy_number is not None:
            self.halted.add(strategy_number)
        self.reasons.append(action.reason)

    def entries_allowed(self, strategy_number):
        return not self.account_halted and strategy_number not in self.halted

    def reset(self):
        self.__init__()


def check_account(book, settings, state: RiskState):
    """Steps 1 to 3. Returns an Action that closes everything, or None."""
    totals = book.totals()
    profit = totals["net"]
    combined = settings.get("combined", {}) if settings else {}

    action = check_day_limits(
        profit, combined.get("day_profit_on"), combined.get("day_profit"),
        combined.get("day_loss_on"), combined.get("day_loss"), "combined")
    if action:
        return action
    return check_money_lock(combined.get("locks"), combined.get("lock_on"),
                            profit, state.combined_lock, "combined")


def check_strategy(strategy, book, state: RiskState):
    """Steps 4 to 6. Returns an Action that closes this strategy, or None."""
    totals = book.totals(strategy.number)
    profit = totals["net"]

    action = check_day_limits(
        profit, strategy.day_profit_on, strategy.day_profit,
        strategy.day_loss_on, strategy.day_loss, "strategy")
    if action:
        return action
    return check_money_lock(
        strategy.profit_locks, strategy.profit_lock_on, profit,
        state.strategy_lock.setdefault(strategy.number, {}), "strategy")


def check_position(strategy, position):
    """
    Steps 8 to 10, in order. The exit conditions, step 11, are checked by
    the engine itself because they need the indicator series.
    """
    action = update_trailing(strategy, position)
    if action:
        return action
    action = check_stops(strategy, position)
    if action:
        return action
    return check_targets(strategy, position)
