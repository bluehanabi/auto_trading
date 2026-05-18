"""백테스트 엔진 — 단일 종목, 동시 1포지션, 보유 현금 전액 매수.

체결 규칙
  - 진입: 직전 봉의 종가 기준 신호 → 이번 봉 '시가'에 매수 (룩어헤드 방지)
  - 청산: 보유 중 매 봉마다 아래 순서로 검사
      1) 시가가 이미 손절선 이하  → 시가에 손절 (갭하락)
      2) 시가가 이미 목표가 이상  → 시가에 익절 (갭상승)
      3) 그 외엔 고가가 목표 도달 → 익절 / 저가가 손절선 도달 → 손절
      4) 한 봉에서 목표·손절선을 동시에 통과하면 일봉만으로는 선후를 알 수 없음.
         기본은 보수적으로 '손절 우선'(ambiguous='pessimistic').
      5) max_hold_days 초과 시 종가에 시간청산
  - 마지막 봉까지 남은 포지션은 종가에 강제청산('eod')

비용
  - 매수: 체결금액 × commission
  - 매도: 체결금액 × (commission + tax)
  - slippage 는 체결가에 반영 (매수는 불리하게 +, 매도는 불리하게 -)
"""
import math
from dataclasses import dataclass

import pandas as pd


@dataclass
class Trade:
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    entry_price: float
    exit_price: float
    shares: int
    reason: str          # 'target' | 'stop' | 'time' | 'eod'
    gross_pnl: float     # 가격 차익만 (비용 제외)
    cost: float          # 매수·매도 비용 합계
    net_pnl: float       # 비용까지 차감한 순손익

    @property
    def net_return(self):
        return self.net_pnl / (self.entry_price * self.shares)

    @property
    def hold_days(self):
        return (self.exit_date - self.entry_date).days


@dataclass
class Result:
    trades: list
    equity: pd.Series
    initial_cash: float


def run_backtest(
    df,
    entry_signal,
    *,
    take_profit=0.01,
    stop_loss=0.01,
    max_hold_days=None,
    initial_cash=10_000_000,
    commission=0.00015,
    tax=0.0015,
    slippage=0.0,
    ambiguous="pessimistic",
):
    """백테스트 실행 후 Result(trades, equity, initial_cash) 반환."""
    idx = df.index
    o = df["Open"].to_numpy(dtype=float)
    h = df["High"].to_numpy(dtype=float)
    l = df["Low"].to_numpy(dtype=float)
    c = df["Close"].to_numpy(dtype=float)
    sig = entry_signal.reindex(idx).fillna(False).to_numpy(dtype=bool)
    n = len(df)

    cash = float(initial_cash)
    pos = None
    trades = []
    equity = []

    for i in range(n):
        exited = False

        # --- 1. 보유 포지션 청산 검사 ---
        if pos is not None:
            ep = pos["entry_price"]
            target = ep * (1 + take_profit)
            stop = ep * (1 - stop_loss) if stop_loss else None
            held = i - pos["entry_idx"]
            xprice, reason = None, None

            if stop is not None and o[i] <= stop:
                xprice, reason = o[i], "stop"
            elif o[i] >= target:
                xprice, reason = o[i], "target"
            else:
                hit_target = h[i] >= target
                hit_stop = stop is not None and l[i] <= stop
                if hit_target and hit_stop:
                    if ambiguous == "optimistic":
                        xprice, reason = target, "target"
                    else:
                        xprice, reason = stop, "stop"
                elif hit_target:
                    xprice, reason = target, "target"
                elif hit_stop:
                    xprice, reason = stop, "stop"
                elif max_hold_days is not None and held >= max_hold_days:
                    xprice, reason = c[i], "time"

            if xprice is not None:
                cash, trade = _close(cash, pos, idx[i], xprice, reason,
                                     commission, tax, slippage)
                trades.append(trade)
                pos = None
                exited = True

        # --- 2. 진입: 직전 봉 신호 → 이번 봉 시가 체결 ---
        if pos is None and not exited and i > 0 and sig[i - 1]:
            fill = o[i] * (1 + slippage)
            shares = math.floor(cash / (fill * (1 + commission)))
            if shares > 0:
                buy_cost = fill * shares * commission
                cash -= fill * shares + buy_cost
                pos = {
                    "entry_price": fill,
                    "shares": shares,
                    "entry_idx": i,
                    "entry_date": idx[i],
                    "entry_cost": buy_cost,
                }

        # --- 3. 평가금액 기록 ---
        equity.append(cash + (pos["shares"] * c[i] if pos else 0.0))

    # 마지막 봉에 남은 포지션 강제청산
    if pos is not None:
        cash, trade = _close(cash, pos, idx[-1], c[-1], "eod",
                             commission, tax, slippage)
        trades.append(trade)
        equity[-1] = cash

    return Result(trades, pd.Series(equity, index=idx, dtype=float), float(initial_cash))


def _close(cash, pos, exit_date, raw_exit, reason, commission, tax, slippage):
    shares = pos["shares"]
    exit_price = raw_exit * (1 - slippage)
    proceeds = exit_price * shares
    sell_cost = proceeds * (commission + tax)
    cash += proceeds - sell_cost

    gross = (exit_price - pos["entry_price"]) * shares
    total_cost = pos["entry_cost"] + sell_cost
    net = gross - total_cost
    trade = Trade(
        entry_date=pos["entry_date"],
        exit_date=exit_date,
        entry_price=pos["entry_price"],
        exit_price=exit_price,
        shares=shares,
        reason=reason,
        gross_pnl=gross,
        cost=total_cost,
        net_pnl=net,
    )
    return cash, trade
