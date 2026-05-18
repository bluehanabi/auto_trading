"""종목 스크리너 검증 — pytest 없이도 단독 실행 가능.

  python3 tests/test_screener.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from screener import get_universe, screen

START, END = "2024-01-01", "2024-03-31"


def test_synthetic_universe_shape():
    uni = get_universe(synthetic=True, n_synthetic=40)
    assert len(uni) == 40
    for col in ("Code", "Name", "Market", "sigma", "base_price", "volume_scale"):
        assert col in uni.columns, col
    assert set(uni["Market"]) <= {"KOSPI", "KOSDAQ"}
    assert uni["Code"].is_unique
    print("  ok test_synthetic_universe_shape")


def test_screen_returns_ranked_subset():
    df = screen(START, END, synthetic=True, n_synthetic=60, top_n=10,
                min_value=0, min_volatility=0)
    assert 0 < len(df) <= 10
    scores = df["score"].tolist()
    assert scores == sorted(scores, reverse=True), "점수 내림차순 정렬이어야 함"
    for col in ("code", "name", "avg_value", "volatility", "score"):
        assert col in df.columns, col
    print(f"  ok test_screen_returns_ranked_subset ({len(df)}개)")


def test_filters_exclude_out_of_range():
    """변동성 하한을 매우 높게 주면 통과 종목이 크게 줄어야 한다."""
    loose = screen(START, END, synthetic=True, n_synthetic=60, top_n=100,
                   min_value=0, min_volatility=0)
    strict = screen(START, END, synthetic=True, n_synthetic=60, top_n=100,
                    min_value=0, min_volatility=0.035)
    assert len(strict) < len(loose)
    if not strict.empty:
        assert strict["volatility"].min() >= 0.035
    print(f"  ok test_filters_exclude_out_of_range "
          f"(완화 {len(loose)} → 엄격 {len(strict)})")


def test_price_filter():
    """주가 범위 밖 종목은 결과에 없어야 한다."""
    df = screen(START, END, synthetic=True, n_synthetic=60, top_n=100,
                min_value=0, min_volatility=0, min_price=10_000, max_price=100_000)
    if not df.empty:
        assert df["last_price"].between(10_000, 100_000).all()
    print("  ok test_price_filter")


def test_sort_by_volatility():
    df = screen(START, END, synthetic=True, n_synthetic=60, top_n=15,
                min_value=0, min_volatility=0, sort_by="volatility")
    vols = df["volatility"].tolist()
    assert vols == sorted(vols, reverse=True)
    print("  ok test_sort_by_volatility")


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(f"스크리너 테스트 {len(tests)}건 실행")
    for t in tests:
        t()
    print(f"\n전체 통과 ({len(tests)}건)")


if __name__ == "__main__":
    main()
