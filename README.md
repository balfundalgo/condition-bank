# Condition Bank

Multi-strategy trading platform built on a reusable condition library.
Conditions are written once and stored in a shared bank; a strategy is a
chosen combination of them joined with AND, OR and brackets.

Built from the specification **The Condition Bank v1.0**.

---

## What is in this build

| Screen | State |
|---|---|
| Password gate / licensing | Deferred — added once the software is finished |
| Condition Bank browser (C0–C16, X0–X2, L0–L2) | Working |
| Strategy Builder — visual expression builder, live validation, plain English preview | Working |
| Per-condition, per-strategy settings | Working |
| Dashboard layout, day limits, profit locking, quick exits | Layout live, figures in Phase 4 |
| Dhan connection — TOTP token flow, funds, scrip master | Working |
| Indicator engine — BB on lows, RSI, ATR, ADX/DI, Supertrend, EMA | Working, verified against reference |
| Candle engine — multi-timeframe, per strike | Working |
| Condition evaluator — all 23 conditions | Working |
| Live strike universe — expiry rule, ITM/OTM band from the spot tick | Working |
| Feed pool — 5 sockets x 5,000 instruments | Working |
| Backfill — 10 days per strike, resampled to each timeframe | Working |
| Signals, including late entry | Working |
| Market order placement, paper and live | Working |
| Paper / Live switch per strategy, with confirmation | Working |
| Error basket with retry | Working |
| Position book, MTM, state across restarts | Working |
| Broker reconciliation (the broker is always the truth) | Working |
| Charges per trade — brokerage, STT, exchange, SEBI, stamp duty, GST | Working, rates editable |
| Exit on exit conditions, square-off time, manual Exit all | Working |
| Targets and stop-losses, four levels each, partial exits | Working |
| Trailing lock profit, ten levels, per position | Working |
| Profit lock per strategy and across all strategies | Working |
| Day profit / day loss, per strategy and combined | Working |
| Eleven-step exit precedence | Working |
| Execution screen — strike filters, sizing, timing, caps | Working |
| Targets screen — all of the above, per strategy | Working |
| Copy trade, Security | Later phases |

The data engine and the order path are both live. A strategy in **Paper**
mode fills instantly at the signal price and touches no broker API; a
strategy in **Live** mode sends real market orders. The switch is per
strategy, so paper and live can run side by side.

Every strategy starts in **Paper**. Switching one to Live is done on the
dashboard row and asks you to type `LIVE` to confirm; starting the engine
with any live strategy asks again. A strategy cannot change mode while it
holds an open position.

Every P&L figure is shown gross, as charges, and as net. Charges cover
brokerage, STT, exchange transaction charges, the SEBI turnover fee, stamp
duty and GST, and the rates are editable on the dashboard — they change
with budgets and exchange circulars, so check them against a real contract
note before trusting the net figure.

A position can be closed by a target, a stop-loss, the trailing lock, a
profit lock, a day limit, an exit condition, the square-off time, or the
Exit all button — resolved in the eleven-step order from Section 8 of the
specification. Account-level rules outrank strategy-level ones, which
outrank anything managing a single trade.

Day limits and profit locks work on NET profit after charges. Targets,
stops and the trailing lock work on the premium, because that is what the
user typed a percentage of.

---

## Run it

```bash
pip install -r requirements.txt
python app.py
```

Strategies are stored in `condition_bank.json` next to the app (or next to
the EXE when frozen).

## Build the EXE

Every push to `main` builds a Windows EXE through GitHub Actions.
**Actions tab → latest run → Artifacts → ConditionBank-Windows**

Locally: `python bundler.py`

---

## Layout

```
condition-bank/
├── app.py                      entry point
├── bundler.py                  local PyInstaller build
├── core/
│   ├── theme.py                palette and fonts
│   ├── conditions.py           the condition register — add new ones here
│   ├── expression.py           parser, validator, plain English translator
│   ├── indicators.py           incremental BB / RSI / ATR / ADX / Supertrend / EMA
│   ├── series.py               candles and per-timeframe indicator history
│   ├── evaluator.py            every condition, as arithmetic
│   ├── dhan.py                 Dhan v2 REST, auth, scrip master, orders
│   ├── feed.py                 WebSocket pool, 5 x 5,000 instruments
│   ├── universe.py             expiry rule and the live strike band
│   ├── charges.py              brokerage, STT, exchange, SEBI, stamp, GST
│   ├── risk.py                 targets, stops, trailing, locks, day limits
│   ├── orders.py               priority queue, retries, error basket
│   ├── positions.py            position book, MTM, state, reconciliation
│   ├── engine.py               orchestrator
│   └── store.py                strategies, load and save
├── ui/
│   ├── widgets.py              cards, pills, chip flow layout
│   ├── shell.py                sidebar and page switching
│   └── pages/
│       ├── dashboard.py
│       ├── condition_bank.py
│       ├── strategy_builder.py
│       ├── brokers.py
│       ├── engine_page.py
│       ├── execution.py
│       ├── targets.py
│       └── placeholder.py
└── .github/workflows/build.yml
```

## Adding a condition

Append one `Condition(...)` to `REGISTER` in `core/conditions.py`. It appears
in the bank browser, the palette and the validator automatically. No other
file needs changing.

## Security

Password protection and the licensing controls from Section 11 are switched
off for now, by decision, and will be added once the software is finished.
Only `core/store.py` and `app.py` need to change when they go back in — the
pages call `STORE.save()` and never touch the file themselves.

---

Balfund Trading Pvt. Ltd. · www.balfund.com
