"""백테스트 엔진 검증 — pytest 없이도 단독 실행 가능.

  python3 tests/test_backtest.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from backtest import run_backtest
from data import load_data
from metrics import compute_metrics
from strategy import everyday, ENTRY_SIGNALS


def _bars(rows):
    """rows: (open, high, low, close) 리스트 → OHLCV DataFrame."""
    idx = pd.bdate_range("2024-01-01", periods=len(rows))
    df = pd.DataFrame(rows, columns=["Open", "High", "Low", "Close"], index=idx)
    df["Volume"] = 1_000_000
    return df


def test_take_profit_hit():
    """+1% 목표를 친 봉에서 익절 체결되어야 한다."""
    df = _bars([
        (100, 100, 100, 100),   # 0: 신호용
        (100, 100, 100, 100),   # 1: 시가 100 진입
        (100, 102, 100, 101),   # 2: 고가 102 → target 101 도달
        (101, 101, 101, 101),
    ])
    sig = pd.Series([True, False, False, False], index=df.index)
    res = run_backtest(df, sig, take_profit=0.01, stop_loss=0.01,
                       commission=0, tax=0, slippage=0)
    assert len(res.trades) == 1, res.trades
    t = res.trades[0]
    assert t.reason == "target"
    assert abs(t.exit_price - 101.0) < 1e-9
    print("  ok test_take_profit_hit")


def test_stop_loss_hit():
    """-1% 손절선을 친 봉에서 손절 체결되어야 한다."""
    df = _bars([
        (100, 100, 100, 100),
        (100, 100, 100, 100),   # 진입 100
        (100, 100, 98, 99),     # 저가 98 → stop 99 도달
        (99, 99, 99, 99),
    ])
    sig = pd.Series([True, False, False, False], index=df.index)
    res = run_backtest(df, sig, take_profit=0.01, stop_loss=0.01,
                       commission=0, tax=0, slippage=0)
    assert len(res.trades) == 1
    t = res.trades[0]
    assert t.reason == "stop"
    assert abs(t.exit_price - 99.0) < 1e-9
    assert t.net_pnl < 0
    print("  ok test_stop_loss_hit")


def test_ambiguous_is_pessimistic():
    """한 봉에서 목표·손절선을 둘 다 통과하면 기본은 손절 우선."""
    df = _bars([
        (100, 100, 100, 100),
        (100, 100, 100, 100),   # 진입 100
        (100, 103, 97, 100),    # 고가 103·저가 97 → 둘 다 도달
    ])
    sig = pd.Series([True, False, False], index=df.index)
    res = run_backtest(df, sig, take_profit=0.01, stop_loss=0.01,
                       commission=0, tax=0, slippage=0)
    assert res.trades[0].reason == "stop"

    res2 = run_backtest(df, sig, take_profit=0.01, stop_loss=0.01,
                        commission=0, tax=0, slippage=0, ambiguous="optimistic")
    assert res2.trades[0].reason == "target"
    print("  ok test_ambiguous_is_pessimistic")


def test_costs_reduce_return():
    """동일 시나리오에서 거래비용이 있으면 순손익이 더 작아야 한다."""
    df = _bars([
        (100, 100, 100, 100),
        (100, 100, 100, 100),
        (100, 102, 100, 101),
        (101, 101, 101, 101),
    ])
    sig = pd.Series([True, False, False, False], index=df.index)
    free = run_backtest(df, sig, commission=0, tax=0, slippage=0)
    costly = run_backtest(df, sig, commission=0.00015, tax=0.0015, slippage=0.001)
    assert costly.trades[0].net_pnl < free.trades[0].net_pnl
    print("  ok test_costs_reduce_return")


def test_no_lookahead_entry():
    """신호 봉 당일이 아니라 '다음 봉 시가'에 체결되어야 한다."""
    df = _bars([
        (100, 100, 100, 100),
        (200, 200, 200, 200),   # 신호 다음 봉: 시가 200 에 체결
        (200, 202, 200, 201),
    ])
    sig = pd.Series([True, False, False], index=df.index)
    res = run_backtest(df, sig, commission=0, tax=0, slippage=0)
    assert abs(res.trades[0].entry_price - 200.0) < 1e-9
    print("  ok test_no_lookahead_entry")


def test_no_stop_holds_loser():
    """손절이 없으면 손실 포지션을 마지막 봉까지 들고 가 'eod' 청산."""
    df = _bars([
        (100, 100, 100, 100),
        (100, 100, 100, 100),   # 진입 100
        (100, 100, 80, 85),     # 폭락 — 손절 없으면 버팀
        (85, 85, 70, 75),
    ])
    sig = pd.Series([True, False, False, False], index=df.index)
    res = run_backtest(df, sig, take_profit=0.01, stop_loss=None,
                       commission=0, tax=0, slippage=0)
    assert res.trades[0].reason == "eod"
    assert res.trades[0].net_pnl < 0
    print("  ok test_no_stop_holds_loser")


def test_synthetic_pipeline():
    """합성 데이터 전체 파이프라인이 동작하고 지표가 산출되어야 한다."""
    df = load_data("005930", "2022-01-01", "2023-12-31", synthetic=True)
    assert len(df) > 200
    assert (df["High"] >= df["Low"]).all()
    sig = ENTRY_SIGNALS["everyday"](df)
    res = run_backtest(df, sig)
    m = compute_metrics(res)
    assert m["num_trades"] > 0
    assert 0.0 <= m["win_rate"] <= 1.0
    assert m["max_drawdown"] <= 0.0
    print(f"  ok test_synthetic_pipeline (매매 {m['num_trades']}회, "
          f"승률 {m['win_rate']*100:.1f}%, 수익률 {m['total_return']*100:+.2f}%)")


def test_equity_consistency():
    """최종 평가금액과 매매 순손익 합계가 일치해야 한다."""
    df = load_data("000660", "2022-01-01", "2023-06-30", synthetic=True)
    res = run_backtest(df, everyday(df))
    total_net = sum(t.net_pnl for t in res.trades)
    expected = res.initial_cash + total_net
    assert abs(res.equity.iloc[-1] - expected) < 1.0, (
        res.equity.iloc[-1], expected)
    print("  ok test_equity_consistency")


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(f"백테스트 엔진 테스트 {len(tests)}건 실행")
    for t in tests:
        t()
    print(f"\n전체 통과 ({len(tests)}건)")


if __name__ == "__main__":
    main()
