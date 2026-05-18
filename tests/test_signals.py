"""진입 신호 / regime 주입 / 신호 비교 검증 — 단독 실행 가능.

  python3 tests/test_signals.py
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from data import make_synthetic_intraday
from strategy import ENTRY_SIGNALS

NEW_SIGNALS = ("momentum", "breakout", "volbreak", "pullback")


def _args(**kw):
    d = dict(tp=0.02, sl=0.02, max_hold=None, daily=False, cash=10_000_000,
             commission=0.00015, tax=0.0015, slippage=0.0)
    d.update(kw)
    return argparse.Namespace(**d)


def _frames(regime, n=8):
    frames = {}
    for i in range(n):
        code = f"90{i:04d}"
        frames[code] = make_synthetic_intraday(
            code, "2024-01-01", "2024-02-29", sigma=0.025, regime=regime)
    return frames


def test_new_signals_registered():
    for name in NEW_SIGNALS:
        assert name in ENTRY_SIGNALS, name
    df = make_synthetic_intraday("005930", "2024-01-01", "2024-01-10")
    for name in NEW_SIGNALS + ("upbar",):
        s = ENTRY_SIGNALS[name](df)
        assert len(s) == len(df)
        assert s.dtype == bool, (name, s.dtype)
        assert not s.isna().any()
    print("  ok test_new_signals_registered")


def test_regime_autocorrelation():
    """momentum 은 양의, meanrev 는 음의 분봉 자기상관을 가져야 한다."""
    def lag1(regime):
        df = make_synthetic_intraday("005930", "2024-01-01", "2024-03-31",
                                     regime=regime)
        r = np.log(df["Close"]).diff().dropna().to_numpy()
        return float(np.corrcoef(r[:-1], r[1:])[0, 1])

    ac_mom, ac_rev, ac_rnd = lag1("momentum"), lag1("meanrev"), lag1("random")
    assert ac_mom > 0.3, ac_mom
    assert ac_rev < -0.3, ac_rev
    assert abs(ac_rnd) < 0.1, ac_rnd
    print(f"  ok test_regime_autocorrelation "
          f"(mom {ac_mom:+.2f} / rev {ac_rev:+.2f} / rnd {ac_rnd:+.2f})")


def test_compare_discriminates_momentum():
    """momentum regime 에서 추세추종 신호가 무신호(everyday)보다 우위여야 한다."""
    from run_signals import compare

    rows = compare(_frames("momentum"),
                   ["everyday", "breakout", "volbreak"], _args())
    by = {r["signal"]: r for r in rows}
    assert by["breakout"]["expectancy_pct"] > by["everyday"]["expectancy_pct"]
    assert by["volbreak"]["expectancy_pct"] > by["everyday"]["expectancy_pct"]
    pe = [r["expectancy_pct"] for r in rows]
    assert pe == sorted(pe, reverse=True), "기대값(%) 내림차순 정렬이어야 함"
    print(f"  ok test_compare_discriminates_momentum "
          f"(volbreak {by['volbreak']['expectancy_pct']*100:+.3f}% vs "
          f"everyday {by['everyday']['expectancy_pct']*100:+.3f}%)")


def test_random_regime_no_edge():
    """random regime 에서는 어떤 신호도 무신호를 크게 앞서지 못해야 한다."""
    from run_signals import compare

    rows = compare(_frames("random"),
                   ["everyday", "breakout", "volbreak", "momentum"], _args())
    for r in rows:
        # 랜덤워크 → 신호의 우위는 거래비용 수준 안의 잡음에 그쳐야 한다
        assert r["expectancy_pct"] < 0, (r["signal"], r["expectancy_pct"])
    print("  ok test_random_regime_no_edge (랜덤워크엔 우위 없음)")


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(f"신호/regime 테스트 {len(tests)}건 실행")
    for t in tests:
        t()
    print(f"\n전체 통과 ({len(tests)}건)")


if __name__ == "__main__":
    main()
