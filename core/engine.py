"""
The engine.

Pulls the pieces together: broker connection, scrip master, strike
universe, feed, backfill, candles, indicators, condition evaluation, order
placement, positions and reconciliation.

The loop is simple to state. A tick arrives. If it is the index, the
strike band is recomputed. If it is a strike we hold, the exit expression
is checked. If it is a strike we do not hold, the entry expression is
checked. Orders go out through the order manager, never directly, so exits
always outrank entries and nothing is fired in a loop.

Targets, stop-losses, trailing locks and the two profit-lock layers are
Phase 4. What closes a position today is an exit condition, the square-off
time, or the user pressing a button.
"""

import logging
import os
import threading
import time
from collections import deque
from datetime import datetime

from . import dhan, evaluator as EV, expression as E
from .feed import FeedPool
from .orders import OrderManager, OrderRequest, PRIORITY_ENTRY, PRIORITY_EXIT
from .positions import BOOK, Position
from . import risk as RISK
from .series import StrikeData, tf_seconds
from .store import LOG_DIR
from .universe import Universe, UniverseFilter

log = logging.getLogger("engine")

EVAL_INTERVAL = 0.25            # seconds between evaluations of one strike
BACKFILL_WORKERS = 2
RECONCILE_SECONDS = 300


def _parse_time(text, fallback):
    try:
        hh, mm = str(text).split(":")
        return int(hh) * 60 + int(mm)
    except (ValueError, AttributeError):
        return fallback


def _minutes_now():
    now = dhan.now_ist()
    return now.hour * 60 + now.minute


class Signal:
    __slots__ = ("strategy", "security_id", "label", "price", "at",
                 "state", "entry_price", "reason")

    def __init__(self, strategy, security_id, label, price):
        self.strategy = strategy
        self.security_id = security_id
        self.label = label
        self.price = price
        self.at = datetime.now()
        self.state = "signalled"   # signalled | waiting | taken | dropped
                                   # | rejected
        self.entry_price = None
        self.reason = ""

    def describe(self):
        return {"time": self.at.strftime("%H:%M:%S"),
                "strategy": self.strategy.name,
                "strike": self.label,
                "price": self.price,
                "state": self.state,
                "entry": self.entry_price,
                "reason": self.reason}


class Engine:
    def __init__(self, client: dhan.DhanClient, on_event=None):
        self.client = client
        self.on_event = on_event or (lambda kind, data: None)

        self.rows = []
        self.lots = {}
        self.universes = {}           # strategy number -> Universe
        self.strategies = []
        self.strikes = {}             # security_id -> StrikeData
        self.owners = {}              # security_id -> set of strategy numbers
        self.specs = {}
        self.needed = {}

        self.feed = FeedPool(self.client.feed_url, self._on_tick)
        self.orders = OrderManager(self.client, on_event=self._order_event)
        self.book = BOOK

        self.signals = deque(maxlen=500)
        self.open_signals = {}        # (strategy, security_id) -> Signal
        self.held = set()             # (strategy number, security_id)
        self.pending = set()          # an order is in flight for this key

        self._backfill_q = deque()
        self._backfill_seen = set()
        self._last_eval = {}
        self._running = False
        self._squared_off = set()
        self._lock = threading.Lock()
        self.status = "stopped"
        self.last_error = ""
        self.notices = deque(maxlen=50)
        self.eval_count = 0
        self.risk = RISK.RiskState()

    # ───────────────────────────────────────────────────────── lifecycle
    def start(self, strategies):
        if self._running:
            return False
        self.strategies = [s for s in strategies if s.summary()]
        if not self.strategies:
            self.last_error = "No complete strategy to run."
            return False
        if not self.client.connected:
            self.last_error = "Broker is not connected."
            return False

        self._running = True
        self.last_error = ""
        self.status = "starting"
        threading.Thread(target=self._boot, daemon=True, name="engine").start()
        return True

    def stop(self):
        self._running = False
        self.feed.stop()
        self.orders.stop()
        self.status = "stopped"
        self._emit("stopped", {})

    def _emit(self, kind, data):
        try:
            self.on_event(kind, data)
        except Exception as e:
            log.error("event handler failed: %s", e)

    def _notice(self, text):
        self.notices.appendleft(
            {"at": datetime.now().strftime("%H:%M:%S"), "text": text})
        log.info(text)

    def _order_event(self, kind, data):
        if kind == "order_failed":
            self._notice(f"Order failed: {data.get('strike')} "
                         f"{data.get('side')} — {data.get('error')}")
        self._emit(kind, data)

    def _boot(self):
        try:
            self.status = "loading scrip master"
            self._emit("status", {"text": self.status})
            cache = os.path.join(LOG_DIR, "scrip_master.csv")
            raw = dhan.download_scrip_master(cache_path=cache)
            self.rows, self.lots = dhan.parse_scrip_master(raw)
            log.info("scrip master: %d rows", len(self.rows))

            self.book.load()
            for pos in self.book.open.values():
                self.held.add((pos.strategy_number, pos.security_id))
            if self.book.open:
                self._notice(f"Restored {len(self.book.open)} open positions "
                             f"from the last session.")

            self.specs, self.needed = EV.merge_requirements(self.strategies)
            self._emit("status", {"text": "building the strike universe"})
            for strategy in self.strategies:
                self.universes[strategy.number] = Universe(
                    strategy.instrument, self.rows, self._filter_for(strategy))

            self.orders.start()
            self.status = "connecting feed"
            self._emit("status", {"text": self.status})
            self.feed.start()
            self._subscribe()

            for _ in range(BACKFILL_WORKERS):
                threading.Thread(target=self._backfill_loop, daemon=True,
                                 name="backfill").start()
            threading.Thread(target=self._housekeeping, daemon=True,
                             name="housekeeping").start()
            threading.Thread(target=self._risk_loop, daemon=True,
                             name="risk").start()

            self.status = "running"
            self._emit("started", {"strategies": len(self.strategies)})
        except Exception as e:
            self._running = False
            self.last_error = str(e)
            self.status = "failed"
            log.exception("engine failed to start")
            self._emit("error", {"text": str(e)})

    def _filter_for(self, strategy):
        cfg = getattr(strategy, "strike_filter", None) or {}
        premium = strategy.params.get("C14", {})
        return UniverseFilter(
            option_type=cfg.get("option_type", "All"),
            moneyness=cfg.get("moneyness", "All"),
            allow_pct=cfg.get("allow_pct", 0.80),
            ignore_pct=cfg.get("ignore_pct", 0.35),
            step=cfg.get("step", 1),
            premium_low=cfg.get("premium_low", premium.get("lower")),
            premium_high=cfg.get("premium_high", premium.get("upper")))

    # ───────────────────────────────────────────────────── housekeeping
    def _housekeeping(self):
        """Square-off clock and periodic reconciliation against the broker."""
        last_reconcile = 0.0
        while self._running:
            try:
                self._check_square_off()
                if (self.client.connected
                        and time.time() - last_reconcile > RECONCILE_SECONDS
                        and any(p.mode == "Live"
                                for p in self.book.open.values())):
                    last_reconcile = time.time()
                    self._reconcile()
            except Exception as e:
                log.error("housekeeping: %s", e)
            time.sleep(5)

    def _risk_loop(self):
        """
        Steps 1 to 6 of the precedence: the account and strategy rules.
        They run on their own one-second clock rather than on ticks, so a
        day limit does not wait for the next quote on some strike.
        """
        while self._running:
            try:
                self._check_portfolio_risk()
                self._sweep_halted()
            except Exception as e:
                log.error("risk loop: %s", e)
            time.sleep(1.0)

    def _sweep_halted(self):
        """
        Once a limit has fired, anything still open is closed on every
        pass. Orders in flight at the moment of the halt land afterwards,
        so one sweep is not enough.
        """
        for strategy in self.strategies:
            if self.risk.entries_allowed(strategy.number):
                continue
            for pos in self.book.for_strategy(strategy.number):
                self._exit(strategy, pos, "day limit reached")

    def _check_portfolio_risk(self):
        settings = {}
        try:
            from .store import STORE
            settings = STORE.bank.settings if STORE.bank else {}
        except Exception:
            pass

        if not self.risk.account_halted:
            action = RISK.check_account(self.book, settings, self.risk)
            if action:
                self.risk.halt(action)
                closed = self.exit_all(reason=action.reason)
                self._notice(f"{action.reason} — closing everything "
                             f"({closed} position"
                             f"{'s' if closed != 1 else ''}). No new entries "
                             f"today.")
                self._emit("halted", {"scope": "account",
                                      "reason": action.reason})
                return

        for strategy in self.strategies:
            if not self.risk.entries_allowed(strategy.number):
                continue
            action = RISK.check_strategy(strategy, self.book, self.risk)
            if action:
                self.risk.halt(action, strategy.number)
                closed = self.exit_all(strategy.number, action.reason)
                self._notice(f"{strategy.name}: {action.reason} — closing "
                             f"{closed} position"
                             f"{'s' if closed != 1 else ''}. No new entries "
                             f"for this strategy today.")
                self._emit("halted", {"scope": "strategy",
                                      "strategy": strategy.name,
                                      "reason": action.reason})

    def _reconcile(self):
        mismatches = self.book.reconcile(self.client.positions())
        for text in mismatches:
            self._notice(f"Reconciliation — {text}")
        with self._lock:
            still_open = {(p.strategy_number, p.security_id)
                          for p in self.book.open.values()}
            self.held = still_open | {k for k in self.held
                                      if k in self.pending}
        if mismatches:
            self._emit("reconciled", {"mismatches": mismatches})

    def _check_square_off(self):
        now = _minutes_now()
        for strategy in self.strategies:
            if strategy.style == "Positional":
                continue
            if now < _parse_time(strategy.square_off_time, 15 * 60 + 10):
                continue
            for pos in self.book.for_strategy(strategy.number):
                key = (strategy.number, pos.security_id)
                if key in self._squared_off:
                    continue
                self._squared_off.add(key)
                self._exit(strategy, pos, "square-off time")

    # ──────────────────────────────────────────────────────── the feed
    def _subscribe(self):
        wanted, seen = [], set()
        for uni in self.universes.values():
            for inst in uni.instruments():
                if inst["security_id"] not in seen:
                    seen.add(inst["security_id"])
                    wanted.append(inst)
        # A strike we hold stays on the feed even after it leaves the band,
        # otherwise the exit conditions would go blind on an open position.
        for pos in self.book.open.values():
            if pos.security_id not in seen:
                seen.add(pos.security_id)
                wanted.append({"security_id": pos.security_id,
                               "segment": pos.segment})
        try:
            added, removed = self.feed.set_instruments(wanted)
            if added or removed:
                log.info("feed: +%d -%d (now %d)", added, removed,
                         self.feed.subscribed_count)
        except RuntimeError as e:
            self.last_error = str(e)
            self._notice(str(e))
            self._emit("error", {"text": str(e)})

    def _on_tick(self, security_id, ltp, ltt):
        epoch = dhan.normalise_epoch(ltt)

        spot_changed = False
        for strategy in self.strategies:
            uni = self.universes.get(strategy.number)
            if uni and security_id == uni.spot_security_id:
                added, removed = uni.on_spot(ltp)
                if added or removed:
                    spot_changed = True
                    self._universe_changed(strategy, added, removed)
        if spot_changed:
            self._subscribe()

        self.book.mark(security_id, ltp)

        strike = self.strikes.get(security_id)
        if strike is None:
            return
        for uni in self.universes.values():
            if security_id in uni.current:
                uni.on_premium(security_id, ltp)

        closed = strike.on_tick(ltp, epoch)
        now = time.monotonic()
        if closed or now - self._last_eval.get(security_id, 0) >= EVAL_INTERVAL:
            self._last_eval[security_id] = now
            self._evaluate(security_id, strike)

    def _universe_changed(self, strategy, added, removed):
        with self._lock:
            for row in added:
                sid = row["security_id"]
                self.owners.setdefault(sid, set()).add(strategy.number)
                if sid not in self.strikes:
                    self.strikes[sid] = StrikeData(sid, self._label(row),
                                                   self.specs)
                    if sid not in self._backfill_seen:
                        self._backfill_seen.add(sid)
                        self._backfill_q.append((sid, row))
            for row in removed:
                sid = row["security_id"]
                if (strategy.number, sid) in self.held:
                    continue
                owners = self.owners.get(sid, set())
                owners.discard(strategy.number)
                if not owners:
                    self.owners.pop(sid, None)
                    self.strikes.pop(sid, None)
                    self._last_eval.pop(sid, None)

    @staticmethod
    def _label(row):
        return (f"{row.get('underlying') or row.get('symbol')} "
                f"{int(row['strike'])} {row['option_type']}")

    # ───────────────────────────────────────────────────────── backfill
    def _backfill_loop(self):
        while self._running:
            try:
                sid, row = self._backfill_q.popleft()
            except IndexError:
                time.sleep(0.4)
                continue
            strike = self.strikes.get(sid)
            if strike is None:
                continue
            try:
                self._backfill_one(strike, row)
            except Exception as e:
                log.warning("backfill failed for %s: %s", sid, e)

    def _backfill_one(self, strike, row):
        segment = "BSE_FNO" if row.get("exchange") == "BSE" else "NSE_FNO"
        instrument = "OPTSTK" if row["instrument"] == "OPTSTK" else "OPTIDX"
        minutes = self.client.historical(row["security_id"], segment,
                                         instrument=instrument,
                                         interval="1", days=10)
        if not minutes:
            strike.warm = True
            strike.partial = True
            return
        partial = False
        for tf, series in strike.series.items():
            bars = resample(minutes, tf_seconds(tf))
            if len(bars) < self.needed.get(tf, 30):
                partial = True
            series.seed(bars[-400:])
        strike.partial = partial
        strike.warm = True
        self._emit("warm", {"security_id": strike.security_id,
                            "partial": partial})

    # ─────────────────────────────────────────────────────── evaluation
    def _evaluate(self, security_id, strike):
        if not strike.warm:
            return
        self.eval_count += 1
        for strategy in self.strategies:
            uni = self.universes.get(strategy.number)
            if not uni:
                continue
            key = (strategy.number, security_id)

            if key in self.pending:
                continue

            position = self.book.open.get(key)
            if position is not None:
                action = RISK.check_position(strategy, position)
                if action:
                    self._exit(strategy, position, action.reason,
                               qty=action.qty or None, level=action.level)
                else:
                    self._check_exit(strategy, position, strike)
                continue

            if security_id not in uni.current:
                continue
            if key in self.held:
                continue

            pending_signal = self.open_signals.get(key)
            if pending_signal is not None:
                self._advance_late(pending_signal, strategy, strike)
                continue

            if not self.risk.entries_allowed(strategy.number):
                continue
            if not self._entry_window_open(strategy):
                continue
            if self._at_capacity(strategy):
                continue

            ctx = EV.Ctx(strike)
            if EV.evaluate_expression(strategy.entry, ctx, strategy) is not True:
                continue

            signal = Signal(strategy, security_id, strike.label, strike.ltp)
            self.signals.appendleft(signal)
            if strategy.late_enabled:
                signal.state = "waiting"
                self.open_signals[key] = signal
            else:
                self._enter(signal, strategy, strike)
            self._emit("signal", signal.describe())

    def _entry_window_open(self, strategy):
        now = _minutes_now()
        return (_parse_time(strategy.entry_from, 9 * 60 + 20) <= now
                <= _parse_time(strategy.entry_to, 15 * 60))

    def _at_capacity(self, strategy):
        live = len(self.book.for_strategy(strategy.number))
        same_side = int(getattr(strategy, "max_same_side", 0) or 0)
        max_open = int(getattr(strategy, "max_open_positions", 0) or 0)
        return bool((same_side and live >= same_side)
                    or (max_open and live >= max_open))

    def _advance_late(self, signal, strategy, strike):
        ctx = EV.Ctx(strike, signal_price=signal.price)
        confirmed = EV.evaluate_expression(strategy.late, ctx, strategy)
        elapsed = (datetime.now() - signal.at).total_seconds()
        bars_passed = int(elapsed // tf_seconds(self._tf_of(strategy)))
        if bars_passed < int(strategy.late_x or 0):
            return
        key = (strategy.number, signal.security_id)
        if confirmed is True:
            self.open_signals.pop(key, None)
            self._enter(signal, strategy, strike)
            self._emit("signal", signal.describe())
        elif bars_passed > int(strategy.late_y or 0):
            signal.state = "dropped"
            signal.reason = "confirmation window passed"
            self.open_signals.pop(key, None)
            self._emit("signal", signal.describe())

    @staticmethod
    def _tf_of(strategy):
        for cid in E.conditions_used(strategy.entry):
            params = strategy.params.get(cid, {})
            if "timeframe" in params:
                return str(params["timeframe"])
        return "5m"

    # ─────────────────────────────────────────────────────────── orders
    def _quantity(self, strategy):
        uni = self.universes.get(strategy.number)
        lot = (uni.lot_size if uni else 0) or self.lots.get(
            strategy.instrument, 0)
        return max(1, int(strategy.lots or 1)) * lot, lot

    def _segment_for(self, strategy):
        uni = self.universes.get(strategy.number)
        return uni.segment if uni else "NSE_FNO"

    def _enter(self, signal, strategy, strike):
        qty, lot = self._quantity(strategy)
        if qty <= 0:
            signal.state = "rejected"
            signal.reason = "lot size unknown"
            self._notice(f"{signal.label}: lot size unknown, entry skipped.")
            return

        key = (strategy.number, signal.security_id)
        self.pending.add(key)
        self.held.add(key)
        price = strike.ltp or signal.price
        product = "INTRADAY" if strategy.style == "Intraday" else "CNC"

        def done(ok, fill_price, fill_qty, order_id):
            self.pending.discard(key)
            if not ok:
                self.held.discard(key)
                signal.state = "rejected"
                signal.reason = "order failed, see the error basket"
                self._emit("signal", signal.describe())
                return
            signal.state = "taken"
            signal.entry_price = fill_price
            signal.reason = strategy.mode.lower()
            self.book.add(Position(
                strategy_number=strategy.number,
                strategy_name=strategy.name,
                security_id=signal.security_id,
                label=signal.label,
                segment=self._segment_for(strategy),
                product=product, mode=strategy.mode,
                qty=fill_qty or qty, original_qty=fill_qty or qty,
                entry_price=fill_price,
                entry_at=datetime.now().strftime("%H:%M:%S"),
                lot_size=lot, ltp=fill_price))
            self._emit("signal", signal.describe())
            # The order was already at the broker when a limit fired, so
            # the position is real and has to be closed rather than
            # forgotten about.
            if not self.risk.entries_allowed(strategy.number):
                position = self.book.open.get(key)
                if position is not None:
                    self._exit(strategy, position,
                               "filled after the day limit fired")

        accepted, message = self.orders.submit(OrderRequest(
            strategy_number=strategy.number, strategy_name=strategy.name,
            security_id=signal.security_id, label=signal.label,
            segment=self._segment_for(strategy), side="BUY", qty=qty,
            product=product, mode=strategy.mode, priority=PRIORITY_ENTRY,
            reason="entry", reference_price=price, on_done=done))
        if not accepted:
            self.pending.discard(key)
            self.held.discard(key)
            signal.state = "rejected"
            signal.reason = message
            self._notice(message)

    def _check_exit(self, strategy, position, strike):
        ctx = EV.Ctx(strike)
        if EV.evaluate_expression(strategy.exit, ctx, strategy) is True:
            self._exit(strategy, position, "exit condition")

    def _exit(self, strategy, position, reason, qty=None, level=""):
        key = (strategy.number, position.security_id)
        if key in self.pending:
            return
        qty = int(qty or position.qty)
        if qty <= 0:
            return
        self.pending.add(key)
        # Mark the level now so a repeated tick cannot fire it twice while
        # the order is in flight. If the order fails, it is unmarked below
        # so the level can try again.
        if level and level not in position.levels_hit:
            position.levels_hit.append(level)
        price = position.ltp or position.entry_price

        def done(ok, fill_price, fill_qty, order_id):
            self.pending.discard(key)
            if not ok:
                if level and level in position.levels_hit:
                    position.levels_hit.remove(level)
                # The position is still open. It stays in the book and in
                # the error basket so it cannot be quietly forgotten.
                self._notice(f"{position.label}: exit failed and the "
                             f"position is still open.")
                return
            self.book.reduce(key, fill_qty or qty, fill_price, reason)
            if key not in self.book.open:
                self.held.discard(key)
            self._emit("exit", {"strike": position.label,
                                "price": fill_price, "reason": reason})

        accepted, message = self.orders.submit(OrderRequest(
            strategy_number=strategy.number, strategy_name=strategy.name,
            security_id=position.security_id, label=position.label,
            segment=position.segment, side="SELL", qty=qty,
            product=position.product, mode=position.mode,
            priority=PRIORITY_EXIT, reason=reason,
            reference_price=price, on_done=done))
        if not accepted:
            self.pending.discard(key)
            self._notice(message)

    # ──────────────────────────────────────────────── manual controls
    def exit_all(self, strategy_number=None, reason="manual exit"):
        count = 0
        for strategy in self.strategies:
            if strategy_number and strategy.number != strategy_number:
                continue
            for pos in self.book.for_strategy(strategy.number):
                self._exit(strategy, pos, reason)
                count += 1
        return count

    def release(self, strategy_number, security_id):
        """Let a strike be traded again once its position is gone."""
        self.held.discard((strategy_number, security_id))
        self._squared_off.discard((strategy_number, security_id))

    # ───────────────────────────────────────────────────────── reporting
    def snapshot(self):
        return {
            "status": self.status,
            "error": self.last_error,
            "strategies": len(self.strategies),
            "strikes": len(self.strikes),
            "warm": sum(1 for s in self.strikes.values() if s.warm),
            "partial": sum(1 for s in self.strikes.values() if s.partial),
            "pending_backfill": len(self._backfill_q),
            "series": sum(len(s.series) for s in self.strikes.values()),
            "evaluations": self.eval_count,
            "signals": len(self.signals),
            "held": len(self.held),
            "feed": self.feed.health(),
            "orders": self.orders.stats(),
            "positions": self.book.totals(),
            "mismatches": list(self.book.mismatches),
            "halted": sorted(self.risk.halted),
            "account_halted": self.risk.account_halted,
            "halt_reasons": list(self.risk.reasons),
            "universes": [u.describe() for u in self.universes.values()],
        }

    def strategy_rows(self):
        """One row per strategy, for the dashboard."""
        rows = []
        for strategy in self.strategies:
            rows.append({"number": strategy.number, "name": strategy.name,
                         "mode": strategy.mode,
                         **self.book.totals(strategy.number)})
        return rows

    def recent_signals(self, n=25):
        return [s.describe() for s in list(self.signals)[:n]]

    def open_positions(self):
        return self.book.describe_open()

    def errors(self, n=30):
        return self.orders.errors(n)


# ──────────────────────────────────────────────────────────── resampling
def resample(minutes, interval):
    """Roll one-minute candles up into the timeframe a condition asked for."""
    if interval <= 60:
        return list(minutes)
    out, bucket = [], None
    for bar in minutes:
        slot = bar["t"] - (bar["t"] % interval)
        if bucket is None or slot != bucket["t"]:
            if bucket is not None:
                out.append(bucket)
            bucket = {"t": slot, "o": bar["o"], "h": bar["h"],
                      "l": bar["l"], "c": bar["c"], "v": bar.get("v", 0)}
        else:
            bucket["h"] = max(bucket["h"], bar["h"])
            bucket["l"] = min(bucket["l"], bar["l"])
            bucket["c"] = bar["c"]
            bucket["v"] += bar.get("v", 0)
    if bucket is not None:
        out.append(bucket)
    return out
