"""분봉 백테스트 / 장마감 청산 / watchlist 집계 검증 — 단독 실행 가능.

  python3 tests/test_intraday.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from backtest import run_backtest
from data import make_synthetic_intraday
from metrics import compute_metrics
from run_watchlist import aggregate
from strategy import ENTRY_SIGNALS


def _flat_bars(stamps, price=100.0):
    """가격이 일정한(목표·손절 미도달) 분봉 DataFrame."""
    idx = pd.to_datetime(stamps)
    df = pd.DataFrame(
        {"Open": price, "High": price, "Low": price, "Close": price,
         "Volume": 1000},
        index=idx,
    )
    return df


def test_intraday_data_shape():
    df = make_synthetic_intraday("005930", "2024-01-01", "2024-01-05",
                                 bars_per_day=380)
    assert len(df) == 380 * 5, len(df)
    assert (df["High"] >= df["Low"]).all()
    assert df.index.normalize().nunique() == 5
    print(f"  ok test_intraday_data_shape ({len(df):,} 봉)")


def test_flat_eod_closes_position():
    """장 마감 봉에서 미청산 포지션이 'day_end' 로 강제청산되어야 한다."""
    df = _flat_bars([
        "2024-01-02 09:00", "2024-01-02 09:01", "2024-01-02 09:02",
        "2024-01-03 09:00", "2024-01-03 09:01",
    ])
    sig = pd.Series([True, False, False, False, False], index=df.index)
    res = run_backtest(df, sig, take_profit=0.02, stop_loss=0.02,
                       flat_eod=True, commission=0, tax=0, slippage=0)
    assert len(res.trades) == 1, res.trades
    assert res.trades[0].reason == "day_end"
    print("  ok test_flat_eod_closes_position")


def test_no_entry_on_last_bar_of_day():
    """곧 강제청산될 그날 마지막 봉에는 진입하지 않아야 한다."""
    df = _flat_bars([
        "2024-01-02 09:00", "2024-01-02 09:01", "2024-01-02 09:02",
        "2024-01-03 09:00",
    ])
    sig = pd.Series([False, True, False, False], index=df.index)  # 신호→마지막봉 진입
    res = run_backtest(df, sig, take_profit=0.02, stop_loss=0.02,
                       flat_eod=True, commission=0, tax=0, slippage=0)
    assert len(res.trades) == 0, res.trades
    print("  ok test_no_entry_on_last_bar_of_day")


def test_flat_eod_no_overnight_holds():
    """flat_eod 이면 모든 매매가 당일 진입·청산이어야 한다(오버나이트 없음)."""
    df = make_synthetic_intraday("000660", "2024-01-01", "2024-01-31",
                                 sigma=0.03, bars_per_day=380)
    sig = ENTRY_SIGNALS["upbar"](df)
    res = run_backtest(df, sig, take_profit=0.02, stop_loss=0.02, flat_eod=True)
    assert res.trades, "매매가 발생해야 한다"
    for t in res.trades:
        assert t.entry_date.date() == t.exit_date.date(), (
            f"오버나이트 보유 발생: {t.entry_date} → {t.exit_date}")
    print(f"  ok test_flat_eod_no_overnight_holds ({len(res.trades)}건 전부 당일청산)")


def test_watchlist_aggregate():
    """다종목 결과 집계가 매매를 합산해 통계를 산출해야 한다."""
    per_symbol = []
    for code in ("900001", "900002", "900003"):
        df = make_synthetic_intraday(code, "2024-01-01", "2024-01-15",
                                     sigma=0.025, bars_per_day=380)
        sig = ENTRY_SIGNALS["upbar"](df)
        res = run_backtest(df, sig, take_profit=0.02, stop_loss=0.02,
                           flat_eod=True)
        per_symbol.append({"code": code, "name": code,
                           "result": res, "metrics": compute_metrics(res)})
    agg = aggregate(per_symbol)
    assert agg["symbols"] == 3
    assert agg["num_trades"] == sum(len(r["result"].trades) for r in per_symbol)
    assert 0.0 <= agg["win_rate"] <= 1.0
    assert 0 <= agg["profitable_symbols"] <= 3
    print(f"  ok test_watchlist_aggregate "
          f"(매매 {agg['num_trades']}건, 통합승률 {agg['win_rate']*100:.1f}%)")


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(f"분봉/watchlist 테스트 {len(tests)}건 실행")
    for t in tests:
        t()
    print(f"\n전체 통과 ({len(tests)}건)")


if __name__ == "__main__":
    main()
