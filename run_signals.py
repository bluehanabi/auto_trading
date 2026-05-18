#!/usr/bin/env python3
"""진입 신호 비교 — watchlist 전체에서 어떤 신호가 우위(edge)를 갖는지 평가.

여러 진입 신호를 같은 종목·기간·비용 조건에서 백테스트하고, 모든 매매를
합산해 신호별 승률·손익비·기대값을 한 표로 비교한다.

중요: 합성 데이터의 기본 regime 은 'random'(랜덤워크)이라 어떤 신호도 우위가
없는 게 정상이다. --regime momentum|meanrev 로 '패턴이 있는 시장'을 가정하면
그 패턴을 잡는 신호가 드러난다. 즉 edge 는 시장에 실제 패턴이 있을 때만
존재하며, 진짜 검증은 실데이터로 해야 한다.

사용 예시
  python3 run_signals.py --synthetic --top 20
  python3 run_signals.py --synthetic --top 20 --regime momentum
  python3 run_signals.py --synthetic --top 20 --regime meanrev
  python3 run_signals.py --watchlist watchlist.csv --tp 0.02 --sl 0.02
"""
import argparse
import datetime as dt
import sys

import pandas as pd

import config
from backtest import run_backtest
from data import load_data, load_intraday, make_synthetic, make_synthetic_intraday
from metrics import compute_metrics
from run_watchlist import aggregate
from screener import get_universe
from strategy import ENTRY_SIGNALS

DEFAULT_SIGNALS = ["everyday", "upbar", "momentum", "breakout", "volbreak", "pullback"]


def _build_symbols(args):
    """[{code, name, profile|None}, ...] 반환."""
    if args.synthetic:
        uni = get_universe(synthetic=True, n_synthetic=max(args.top, 40))
        uni = uni.iloc[:args.top]
        return [
            {"code": r.Code, "name": r.Name,
             "profile": {"mu": r.mu, "sigma": r.sigma,
                         "base_price": r.base_price, "volume_scale": r.volume_scale}}
            for r in uni.itertuples(index=False)
        ]
    if not args.watchlist:
        raise RuntimeError("실데이터 모드에는 --watchlist CSV 가 필요합니다.")
    wl = pd.read_csv(args.watchlist, dtype={"code": str})
    cols = {c.lower(): c for c in wl.columns}
    code_col = cols.get("code") or cols.get("symbol")
    if code_col is None:
        raise RuntimeError(f"watchlist 에 code 컬럼이 없습니다: {list(wl.columns)}")
    name_col = cols.get("name", code_col)
    return [
        {"code": str(r[code_col]).zfill(6), "name": str(r[name_col]), "profile": None}
        for _, r in wl.iloc[:args.top].iterrows()
    ]


def _load_one(sym, args):
    code, profile = sym["code"], sym["profile"]
    if args.synthetic:
        if args.daily:
            return make_synthetic(code, args.start, args.end, **profile)
        return make_synthetic_intraday(code, args.start, args.end,
                                       regime=args.regime, **profile)
    if args.daily:
        return load_data(code, args.start, args.end)
    return load_intraday(code, args.start, args.end)


def compare(frames, signal_names, args):
    """신호별 집계 결과 리스트 반환 (기대값 내림차순 정렬)."""
    rows = []
    for name in signal_names:
        signal_fn = ENTRY_SIGNALS[name]
        per_symbol = []
        for code, df in frames.items():
            res = run_backtest(
                df, signal_fn(df), take_profit=args.tp, stop_loss=args.sl,
                max_hold_bars=args.max_hold, flat_eod=not args.daily,
                initial_cash=args.cash, commission=args.commission,
                tax=args.tax, slippage=args.slippage,
            )
            per_symbol.append({"code": code, "result": res,
                               "metrics": compute_metrics(res)})
        agg = aggregate(per_symbol)
        agg["signal"] = name
        rows.append(agg)
    # 매매당 수익률(%)로 정렬 — 포지션 크기·복리 효과에 무관한 신호 품질 지표
    rows.sort(key=lambda a: a["expectancy_pct"], reverse=True)
    return rows


def print_report(rows, args):
    print()
    print("=" * 78)
    mode = "일봉" if args.daily else "분봉(장마감 청산)"
    src = f"합성/regime={args.regime}" if args.synthetic else "실데이터"
    print(f" 진입 신호 비교 — {rows[0]['symbols']}개 종목 / {mode} / {src}")
    print(f" 익절 +{args.tp * 100:.1f}% | 손절 -{args.sl * 100:.1f}% | "
          f"기간 {args.start}~{args.end}")
    print("=" * 78)
    print(f" {'신호':<10} {'매매수':>8} {'승률':>7} {'손익비':>7} "
          f"{'기대값/매매':>13} {'종목평균':>9} {'수익종목':>8}")
    print("-" * 78)
    for a in rows:
        print(f" {a['signal']:<10} {a['num_trades']:>8,} "
              f"{a['win_rate'] * 100:>6.1f}% {a['payoff']:>7.2f} "
              f"{a['expectancy']:>9,.0f}원 {a['expectancy_pct'] * 100:>+6.3f}% "
              f"{a['avg_return'] * 100:>+8.2f}% "
              f"{a['profitable_symbols']:>3}/{a['symbols']:<3}")
    print("=" * 78)
    _verdict(rows, args)
    print("=" * 78)


def _verdict(rows, args):
    best = rows[0]
    if best["expectancy_pct"] > 0:
        print(f" ▶ '{best['signal']}' 신호가 기대값 플러스로 가장 우위 "
              f"(매매당 {best['expectancy']:+,.0f}원).")
        if args.synthetic and args.regime == "random":
            print("   하지만 regime=random(랜덤워크)이라 이는 표본 노이즈일 가능성이 크다.")
            print("   기간을 늘리거나 종목 수를 늘려 재현되는지 확인하라.")
        elif args.synthetic:
            print(f"   단, 이는 주입한 '{args.regime}' 패턴 덕분이다. 실제 시장에 같은")
            print("   패턴이 있어야 유효 — 실데이터로 반드시 재검증해야 한다.")
        else:
            print("   실데이터 결과다. 기간분할(워크포워드)로 과최적화 여부를 확인하라.")
    else:
        print(" ▶ 기대값 플러스인 신호가 하나도 없다.")
        if args.synthetic and args.regime == "random":
            print("   regime=random 에서는 당연한 결과 — 랜덤워크엔 잡을 패턴이 없다.")
            print("   --regime momentum / meanrev 로 패턴을 주입하면 비교 도구가")
            print("   해당 패턴을 잡는 신호를 가려내는지 확인할 수 있다.")
        else:
            print("   거래비용을 넘는 우위가 없다. 신호를 더 다듬거나 익절/손절폭,")
            print("   매매 빈도를 재검토해야 한다.")


def main():
    today = dt.date.today()
    p = argparse.ArgumentParser(
        description="진입 신호 우위 비교 도구",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--watchlist", default=None, help="스크리너 결과 CSV 경로")
    p.add_argument("--synthetic", action="store_true",
                   help="합성 유니버스 사용 (네트워크 불필요)")
    p.add_argument("--daily", action="store_true", help="일봉 모드 (기본: 분봉)")
    p.add_argument("--regime", default="random",
                   choices=["random", "momentum", "meanrev"],
                   help="합성 데이터에 주입할 시장 패턴")
    p.add_argument("--top", type=int, default=20, help="종목 수")
    p.add_argument("--start", default=None)
    p.add_argument("--end", default=None)
    p.add_argument("--signals", default=None,
                   help="비교할 신호 쉼표 구분 (기본: 주요 6종)")
    p.add_argument("--tp", type=float, default=0.02, help="익절 비율")
    p.add_argument("--sl", type=float, default=0.02, help="손절 비율")
    p.add_argument("--max-hold", type=int, default=config.MAX_HOLD_BARS)
    p.add_argument("--cash", type=float, default=config.INITIAL_CASH)
    p.add_argument("--commission", type=float, default=config.COMMISSION_RATE)
    p.add_argument("--tax", type=float, default=config.TAX_RATE)
    p.add_argument("--slippage", type=float, default=config.SLIPPAGE_RATE)
    args = p.parse_args()

    if args.daily:
        args.end = args.end or str(today)
        args.start = args.start or str(today - dt.timedelta(days=365))
    else:
        args.end = args.end or str(today)
        args.start = args.start or str(today - dt.timedelta(days=30))

    signal_names = ([s.strip() for s in args.signals.split(",")]
                    if args.signals else DEFAULT_SIGNALS)
    bad = [s for s in signal_names if s not in ENTRY_SIGNALS]
    if bad:
        print(f"[오류] 알 수 없는 신호: {bad} (가능: {list(ENTRY_SIGNALS)})")
        return 1

    try:
        symbols = _build_symbols(args)
    except (RuntimeError, FileNotFoundError) as exc:
        print(f"[오류] {exc}")
        return 1

    # 종목별 데이터는 한 번만 로드해 모든 신호에 재사용한다.
    frames = {}
    for done, sym in enumerate(symbols, start=1):
        sys.stderr.write(f"\r  데이터 로드 {done}/{len(symbols)} ({sym['code']})   ")
        sys.stderr.flush()
        try:
            frames[sym["code"]] = _load_one(sym, args)
        except RuntimeError as exc:
            sys.stderr.write(f"\n  [스킵] {sym['code']}: {exc}\n")
    sys.stderr.write("\n")
    if not frames:
        print("[오류] 백테스트 가능한 데이터가 없습니다. 오프라인이면 --synthetic 사용.")
        return 1

    rows = compare(frames, signal_names, args)
    print_report(rows, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
