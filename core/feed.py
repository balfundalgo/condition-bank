"""
Live market feed.

Dhan allows five WebSocket connections per user, 5,000 instruments on each
and 100 instruments per subscribe message. That is a ceiling of 25,000, and
the pool below is built to use all of it rather than imposing a smaller
limit of our own.

The pool owns the sockets. Strategies never touch them. Callers hand it a
desired set of instruments and it works out the difference — what to add,
what to drop — and keeps the sockets matching that set through reconnects.
"""

import json
import logging
import struct
import threading
import time
from collections import deque

log = logging.getLogger("feed")

MAX_CONNECTIONS = 5
MAX_PER_CONNECTION = 5000
MAX_PER_MESSAGE = 100
CAPACITY = MAX_CONNECTIONS * MAX_PER_CONNECTION

# Dhan request codes. 15 subscribes to the ticker stream. The unsubscribe
# code is applied best-effort: if the broker ignores it, the pool simply
# stops routing that security and the socket is rebuilt on the next
# reconnect, so a stale subscription costs bandwidth and nothing else.
CODE_SUBSCRIBE = 15
CODE_UNSUBSCRIBE = 16

SEGMENTS = {0: "IDX_I", 1: "NSE_EQ", 2: "NSE_FNO", 3: "NSE_CUR",
            4: "BSE_EQ", 5: "MCX_COMM", 7: "BSE_CUR", 8: "BSE_FNO"}


def parse_packet(msg):
    """Returns (security_id, ltp, ltt) for a ticker packet, else None."""
    if len(msg) < 16:
        return None
    if msg[0] != 2:                      # 2 is the ticker response code
        return None
    security_id = str(struct.unpack_from("<I", msg, 4)[0])
    ltp = float(struct.unpack_from("<f", msg, 8)[0])
    ltt = int(struct.unpack_from("<I", msg, 12)[0])
    return security_id, ltp, ltt


class _Connection:
    """One socket and the instruments assigned to it."""

    def __init__(self, pool, index):
        self.pool = pool
        self.index = index
        self.ws = None
        self.alive = False
        self.assigned = {}               # security_id -> {segment, id}
        self.subscribed = set()
        self._lock = threading.Lock()
        self._thread = None
        self._stop = threading.Event()

    @property
    def room(self):
        return MAX_PER_CONNECTION - len(self.assigned)

    def started_once(self):
        return self._thread is not None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name=f"feed-{self.index}")
        self._thread.start()

    def stop(self):
        self._stop.set()
        try:
            if self.ws:
                self.ws.close()
        except Exception:
            pass

    def _run(self):
        import websocket
        backoff = 1
        while not self._stop.is_set():
            try:
                self.ws = websocket.WebSocketApp(
                    self.pool.url_provider(),
                    on_open=self._on_open, on_message=self._on_message,
                    on_error=self._on_error, on_close=self._on_close)
                self.ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as e:
                log.error("feed %d crashed: %s", self.index, e)
            self.alive = False
            if self._stop.is_set():
                break
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)

    def _on_open(self, ws):
        self.alive = True
        self.subscribed.clear()
        log.info("feed %d open", self.index)
        self._flush()

    def _on_message(self, ws, msg):
        if isinstance(msg, str):
            return
        parsed = parse_packet(bytes(msg))
        if parsed:
            self.pool._dispatch(*parsed)

    def _on_error(self, ws, error):
        log.warning("feed %d error: %s", self.index, error)

    def _on_close(self, ws, code, reason):
        self.alive = False
        log.warning("feed %d closed (%s)", self.index, code)

    # -------------------------------------------------------- messaging
    def _send(self, code, instruments):
        if not (self.alive and self.ws and instruments):
            return False
        for i in range(0, len(instruments), MAX_PER_MESSAGE):
            chunk = instruments[i:i + MAX_PER_MESSAGE]
            try:
                self.ws.send(json.dumps({
                    "RequestCode": code,
                    "InstrumentCount": len(chunk),
                    "InstrumentList": [
                        {"ExchangeSegment": c["segment"],
                         "SecurityId": str(c["security_id"])} for c in chunk]}))
            except Exception as e:
                log.warning("feed %d send failed: %s", self.index, e)
                return False
        return True

    def _flush(self):
        """Bring the socket in line with whatever is assigned to it."""
        with self._lock:
            pending = [c for sid, c in self.assigned.items()
                       if sid not in self.subscribed]
            if pending and self._send(CODE_SUBSCRIBE, pending):
                self.subscribed.update(c["security_id"] for c in pending)

            stale = self.subscribed - set(self.assigned)
            if stale:
                drop = [{"security_id": sid,
                         "segment": self.pool.segment_of(sid)}
                        for sid in stale]
                self._send(CODE_UNSUBSCRIBE, drop)
                self.subscribed -= stale

    def add(self, instruments):
        with self._lock:
            for inst in instruments:
                self.assigned[inst["security_id"]] = inst
        self._flush()

    def remove(self, security_ids):
        with self._lock:
            for sid in security_ids:
                self.assigned.pop(sid, None)
        self._flush()


class FeedPool:
    """The whole feed. Hand it a desired set; it does the rest."""

    def __init__(self, url_provider, on_tick):
        self.url_provider = url_provider
        self.on_tick = on_tick
        self.connections = [_Connection(self, i) for i in range(MAX_CONNECTIONS)]
        self._home = {}                  # security_id -> connection index
        self._last_segment = {}
        self._lock = threading.Lock()
        self.packets = 0
        self.last_packet_at = 0.0
        self._window = deque(maxlen=40)
        self.started = False

    # ------------------------------------------------------------ state
    @property
    def subscribed_count(self):
        return len(self._home)

    @property
    def live_connections(self):
        return sum(1 for c in self.connections if c.alive)

    @property
    def ticks_per_second(self):
        if len(self._window) < 2:
            return 0.0
        span = self._window[-1][0] - self._window[0][0]
        if span <= 0:
            return 0.0
        return (self._window[-1][1] - self._window[0][1]) / span

    def health(self):
        return {"connections": self.live_connections,
                "instruments": self.subscribed_count,
                "capacity": CAPACITY,
                "packets": self.packets,
                "ticks_per_sec": round(self.ticks_per_second, 1),
                "seconds_since_tick": (round(time.time() - self.last_packet_at, 1)
                                       if self.last_packet_at else None)}

    # ------------------------------------------------------- lifecycle
    def start(self):
        self.started = True
        self.connections[0].start()
        threading.Thread(target=self._heartbeat, daemon=True).start()

    def stop(self):
        self.started = False
        for c in self.connections:
            c.stop()

    def _heartbeat(self):
        while self.started:
            self._window.append((time.time(), self.packets))
            time.sleep(1.0)

    # -------------------------------------------------------- dispatch
    def segment_of(self, security_id):
        return self._last_segment.get(security_id, "NSE_FNO")

    def _dispatch(self, security_id, ltp, ltt):
        self.packets += 1
        self.last_packet_at = time.time()
        try:
            self.on_tick(security_id, ltp, ltt)
        except Exception as e:
            log.error("tick handler failed for %s: %s", security_id, e)

    # ------------------------------------------------------ the set
    def set_instruments(self, wanted):
        """
        wanted is a list of {'security_id', 'segment'}. Works out the
        difference against what is already subscribed and applies it.
        Returns (added, removed) or raises if the ceiling is exceeded.
        """
        wanted_map = {str(i["security_id"]): i for i in wanted}
        if len(wanted_map) > CAPACITY:
            raise RuntimeError(
                f"{len(wanted_map)} instruments requested but the broker "
                f"allows {CAPACITY} ({MAX_CONNECTIONS} connections of "
                f"{MAX_PER_CONNECTION}). Narrow the strike filters.")

        with self._lock:
            current = set(self._home)
            target = set(wanted_map)
            to_add = target - current
            to_drop = current - target

            for sid in to_drop:
                index = self._home.pop(sid, None)
                if index is not None:
                    self.connections[index].remove([sid])

            for sid in to_add:
                inst = wanted_map[sid]
                inst = {"security_id": sid,
                        "segment": inst.get("segment", "NSE_FNO")}
                self._last_segment[sid] = inst["segment"]
                conn = self._pick_connection()
                if conn is None:
                    raise RuntimeError("every feed connection is full")
                conn.add([inst])
                self._home[sid] = conn.index

        return len(to_add), len(to_drop)

    def _pick_connection(self):
        """Fill one socket before opening the next, so idle ones stay shut."""
        for conn in self.connections:
            if conn.room > 0:
                if not conn.started_once():
                    conn.start()
                return conn
        return None
