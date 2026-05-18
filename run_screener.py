#!/usr/bin/env python3
"""종목 스크리너 실행기 — 단타 감시 후보군 선정.

사용 예시
  # 합성 유니버스로 즉시 검증 (오프라인)
  python3 run_screener.py --synthetic

  # 실데이터 (네트워크 필요). 전종목 스캔은 수 분 걸린다 → --limit 로 테스트 권장
  python3 run_screener.py --market both --top 100
  python3 run_screener.py --market KOSPI --limit 200 --save watchlist.csv

  # 변동성 우선 정렬
  python3 run_screener.py --synthetic --sort volatility
"""
import argparse
import datetime as dt
import sys

import config
from screener import screen


def _won_eok(x):
    """원 → '억' 단위 문자열."""
    return f"{x / 1e8:,.0f}억"


def _progress(done, total):
    bar = int(done / total * 30) if total else 0
    sys.stderr.write(f"\r  스캔 {done}/{total} [{'#' * bar}{'.' * (30 - bar)}]")
    sys.stderr.flush()
    if done == total:
        sys.stderr.write("\n")


def print_table(df, args):
    print()
    print("=" * 74)
    print(f" 종목 스크리너 결과 — 상위 {len(df)}개  (정렬: {args.sort})")
    print(f" 기준: 거래대금≥{_won_eok(args.min_value)} | "
          f"변동폭≥{args.min_vol * 100:.1f}% | "
          f"주가 {args.min_price:,}~{args.max_price:,}원")
    print("=" * 74)
    if df.empty:
        print(" 조건을 만족하는 종목이 없습니다. 기준을 완화해 보세요.")
        print("=" * 74)
        return
    print(f" {'순위':>3} {'코드':>7} {'종목명':<14} {'시장':>6} "
          f"{'현재가':>9} {'거래대금':>9} {'변동폭':>7} {'점수':>6}")
    print("-" * 74)
    for i, r in enumerate(df.itertuples(index=False), start=1):
        print(f" {i:>3} {r.code:>7} {r.name:<14} {r.market:>6} "
              f"{r.last_price:>9,.0f} {_won_eok(r.avg_value):>9} "
              f"{r.volatility * 100:>6.2f}% {r.score:>6.2f}")
    print("=" * 74)
    print(f" ▶ 이 {len(df)}개를 분봉 감시 대상으로 삼으면 KIS API 호출 한계 안에서")
    print(f"   현실적으로 운용 가능. 다음 단계: 이 후보군에 +2%/-2% 백테스트.")
    print("=" * 74)


def main():
    today = dt.date.today()
    p = argparse.ArgumentParser(
        description="단타 감시 후보군을 추리는 종목 스크리너",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--market", default="both",
                   choices=["KOSPI", "KOSDAQ", "both"])
    p.add_argument("--start", default=None, help="특징 계산 시작일 (기본: 30일 전)")
    p.add_argument("--end", default=str(today))
    p.add_argument("--top", type=int, default=config.SCREEN_TOP_N)
    p.add_argument("--min-value", type=float, default=config.SCREEN_MIN_VALUE,
                   help="최소 평균 일거래대금 (원)")
    p.add_argument("--min-price", type=int, default=config.SCREEN_MIN_PRICE)
    p.add_argument("--max-price", type=int, default=config.SCREEN_MAX_PRICE)
    p.add_argument("--min-vol", type=float, default=config.SCREEN_MIN_VOLATILITY,
                   help="최소 평균 일중 변동폭 (예: 0.015 = 1.5%%)")
    p.add_argument("--sort", default="score",
                   choices=["score", "value", "volatility"])
    p.add_argument("--synthetic", action="store_true",
                   help="합성 유니버스 사용 (네트워크 불필요)")
    p.add_argument("--n-synthetic", type=int, default=60,
                   help="합성 유니버스 종목 수")
    p.add_argument("--limit", type=int, default=None,
                   help="스캔할 종목 수 상한 (실데이터 테스트용)")
    p.add_argument("--save", default=None, help="결과를 저장할 CSV 경로")
    args = p.parse_args()

    if args.start is None:
        args.start = str(today - dt.timedelta(days=config.SCREEN_LOOKBACK_DAYS))
    markets = ("KOSPI", "KOSDAQ") if args.market == "both" else (args.market,)

    try:
        df = screen(
            args.start, args.end, markets=markets, top_n=args.top,
            min_value=args.min_value, min_price=args.min_price,
            max_price=args.max_price, min_volatility=args.min_vol,
            synthetic=args.synthetic, n_synthetic=args.n_synthetic,
            sort_by=args.sort, limit=args.limit,
            progress=None if args.synthetic else _progress,
        )
    except RuntimeError as exc:
        print(f"[스크리너 오류] {exc}")
        return 1

    print_table(df, args)

    if args.save and not df.empty:
        df.to_csv(args.save, index=False, encoding="utf-8-sig")
        print(f" 저장 완료: {args.save}  ({len(df)}개 종목)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
