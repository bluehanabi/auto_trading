#!/usr/bin/env python3
"""watchlist 다종목 일괄 백테스트.

스크리너가 추린 후보군 각각에 '익절 + 손절'(기본 +2%/-2%, 분봉) 전략을
적용한 뒤, 모든 매매를 한데 모아 전략의 통계적 우위를 평가한다.

주의: 종목별로 '독립된 자금'으로 백테스트한다. 자금을 공유하고 동시
보유 종목 수를 제한하는 진짜 포트폴리오 백테스트가 아니라, 전략 자체의
손익비·기대값을 보기 위한 것이다.

사용 예시
  # 합성 유니버스로 즉시 검증 (오프라인)
  python3 run_watchlist.py --synthetic --top 20

  # 스크리너 결과 CSV 로 백테스트 (실데이터 분봉 → KIS 연동 필요)
  python3 run_watchlist.py --watchlist watchlist.csv --tp 0.02 --sl 0.02

  # 일봉 모드
  python3 run_watchlist.py --synthetic --top 20 --daily
"""
import argparse
import datetime as dt
import sys

import pandas as pd

import config
from backtest import run_backtest
from data import load_data, load_intraday, make_synthetic, make_synthetic_intraday
from metrics import compute_metrics
from screener import get_universe
from strategy import ENTRY_SIGNALS


def _build_symbols(args):
    """백테스트할 종목 목록 반환: [{code, name, profile|None}, ...]."""
    if args.synthetic:
        uni = get_universe(synthetic=True, n_synthetic=max(args.top, args.n_synthetic))
        uni = uni.iloc[:args.top]
        return [
            {
                "code": r.Code,
                "name": r.Name,
                "profile": {"mu": r.mu, "sigma": r.sigma,
                            "base_price": r.base_price,
                            "volume_scale": r.volume_scale},
            }
            for r in uni.itertuples(index=False)
        ]

    if not args.watchlist:
        raise RuntimeError("실데이터 모드에는 --watchlist CSV 가 필요합니다 "
                           "(run_screener.py --save 로 생성).")
    wl = pd.read_csv(args.watchlist, dtype={"code": str})
    cols = {c.lower(): c for c in wl.columns}
    code_col = cols.get("code") or cols.get("symbol")
    if code_col is None:
        raise RuntimeError(f"watchlist 에 code 컬럼이 없습니다: {list(wl.columns)}")
    name_col = cols.get("name", code_col)
    rows = wl.iloc[:args.top]
    return [
        {"code": str(r[code_col]).zfill(6), "name": str(r[name_col]), "profile": None}
        for _, r in rows.iterrows()
    ]


def _load_one(sym, args):
    code, profile = sym["code"], sym["profile"]
    if args.synthetic:
        if args.daily:
            return make_synthetic(code, args.start, args.end, **profile)
        return make_synthetic_intraday(code, args.start, args.end, **profile)
    if args.daily:
        return load_data(code, args.start, args.end)
    return load_intraday(code, args.start, args.end)


def _backtest_one(sym, args):
    df = _load_one(sym, args)
    sig = ENTRY_SIGNALS[args.entry](df)
    res = run_backtest(
        df, sig, take_profit=args.tp, stop_loss=args.sl,
        max_hold_bars=args.max_hold, flat_eod=not args.daily,
        initial_cash=args.cash, commission=args.commission,
        tax=args.tax, slippage=args.slippage,
    )
    m = compute_metrics(res)
    return res, m


def aggregate(per_symbol):
    """종목별 결과를 모아 전략 전체의 통계 산출."""
    all_trades = [t for row in per_symbol for t in row["result"].trades]
    rets = [row["metrics"]["total_return"] for row in per_symbol]
    agg = {
        "symbols": len(per_symbol),
        "num_trades": len(all_trades),
        "profitable_symbols": sum(1 for r in rets if r > 0),
        "avg_return": sum(rets) / len(rets) if rets else 0.0,
        "median_return": float(pd.Series(rets).median()) if rets else 0.0,
    }
    if not all_trades:
        agg.update(win_rate=0.0, payoff=0.0, expectancy=0.0,
                   expectancy_pct=0.0, total_cost=0.0)
        return agg

    nets = [t.net_pnl for t in all_trades]
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x <= 0]
    win_rets = [t.net_return for t in all_trades if t.net_pnl > 0]
    loss_rets = [t.net_return for t in all_trades if t.net_pnl <= 0]
    avg_win = sum(win_rets) / len(win_rets) if win_rets else 0.0
    avg_loss = sum(loss_rets) / len(loss_rets) if loss_rets else 0.0
    agg.update(
        win_rate=len(wins) / len(all_trades),
        payoff=(avg_win / abs(avg_loss)) if avg_loss != 0 else float("inf"),
        expectancy=sum(nets) / len(nets),
        expectancy_pct=sum(t.net_return for t in all_trades) / len(all_trades),
        total_cost=sum(t.cost for t in all_trades),
    )
    return agg


def print_report(per_symbol, agg, args):
    print()
    print("=" * 72)
    mode = "일봉" if args.daily else "분봉(장마감 청산)"
    print(f" watchlist 일괄 백테스트 — {agg['symbols']}개 종목 / {mode}")
    print(f" 전략: 진입={args.entry} | 익절 +{args.tp * 100:.1f}% | "
          f"손절 -{args.sl * 100:.1f}% | 기간 {args.start}~{args.end}")
    print("=" * 72)
    print(f" {'코드':>7} {'종목명':<14} {'매매수':>7} {'승률':>7} {'수익률':>10}")
    print("-" * 72)
    for row in sorted(per_symbol, key=lambda r: r["metrics"]["total_return"],
                      reverse=True):
        m = row["metrics"]
        print(f" {row['code']:>7} {row['name']:<14} {m['num_trades']:>7,} "
              f"{m['win_rate'] * 100:>6.1f}% {m['total_return'] * 100:>+9.2f}%")
    print("=" * 72)
    print(" [전략 전체 — 모든 종목의 매매를 합산]")
    print(f"  총 매매 횟수      {agg['num_trades']:>10,} 회")
    print(f"  통합 승률         {agg['win_rate'] * 100:>9.1f} %")
    print(f"  손익비(payoff)    {agg['payoff']:>10.2f}   (1 미만이면 구조적 불리)")
    print(f"  매매 1회 기대값   {agg['expectancy']:>9,.0f}원  "
          f"({agg['expectancy_pct'] * 100:+.3f}%)")
    print(f"  총 거래비용       {agg['total_cost']:>9,.0f}원")
    print(f"  수익 종목 비율    {agg['profitable_symbols']}/{agg['symbols']}")
    print(f"  종목 평균 수익률  {agg['avg_return'] * 100:>+9.2f}%  "
          f"(중앙값 {agg['median_return'] * 100:+.2f}%)")
    print("=" * 72)
    if agg["expectancy"] <= 0:
        print(" ▶ 매매당 기대값이 '마이너스'. 종목을 늘려도 손실 구조는 그대로다.")
        print("   진입 신호의 우위가 거래비용을 못 넘는다는 뜻 — 신호 개선이 먼저.")
    elif agg["avg_return"] <= 0:
        print(" ▶ 매매 기대값은 양수여도 종목 평균 수익률은 손실. 편차가 크다.")
    else:
        print(" ▶ 통계상 우위가 보인다. 단 합성/단순신호 결과이므로 실데이터·")
        print("   기간분할(워크포워드)로 재검증 필요. 과최적화를 경계할 것.")
    print("=" * 72)


def main():
    today = dt.date.today()
    p = argparse.ArgumentParser(
        description="watchlist 다종목 일괄 백테스트",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--watchlist", default=None, help="스크리너 결과 CSV 경로")
    p.add_argument("--synthetic", action="store_true",
                   help="합성 유니버스 사용 (네트워크 불필요)")
    p.add_argument("--daily", action="store_true", help="일봉 모드 (기본: 분봉)")
    p.add_argument("--top", type=int, default=20, help="백테스트할 종목 수")
    p.add_argument("--n-synthetic", type=int, default=40)
    p.add_argument("--start", default=None)
    p.add_argument("--end", default=None)
    p.add_argument("--entry", default=None, choices=list(ENTRY_SIGNALS))
    p.add_argument("--tp", type=float, default=0.02, help="익절 비율 (기본 +2%%)")
    p.add_argument("--sl", type=float, default=0.02, help="손절 비율 (기본 -2%%)")
    p.add_argument("--max-hold", type=int, default=config.MAX_HOLD_BARS)
    p.add_argument("--cash", type=float, default=config.INITIAL_CASH)
    p.add_argument("--commission", type=float, default=config.COMMISSION_RATE)
    p.add_argument("--tax", type=float, default=config.TAX_RATE)
    p.add_argument("--slippage", type=float, default=config.SLIPPAGE_RATE)
    p.add_argument("--save", default=None, help="종목별 결과 CSV 저장 경로")
    args = p.parse_args()

    if args.daily:
        args.end = args.end or str(today)
        args.start = args.start or str(today - dt.timedelta(days=365))
        args.entry = args.entry or "everyday"
    else:
        args.end = args.end or str(today)
        args.start = args.start or str(today - dt.timedelta(days=20))
        args.entry = args.entry or "upbar"

    try:
        symbols = _build_symbols(args)
    except (RuntimeError, FileNotFoundError) as exc:
        print(f"[오류] {exc}")
        return 1
    if not symbols:
        print("[오류] 백테스트할 종목이 없습니다.")
        return 1

    per_symbol, skipped = [], 0
    for done, sym in enumerate(symbols, start=1):
        sys.stderr.write(f"\r  백테스트 {done}/{len(symbols)} ({sym['code']})   ")
        sys.stderr.flush()
        try:
            res, m = _backtest_one(sym, args)
        except RuntimeError as exc:
            skipped += 1
            if skipped == 1:
                sys.stderr.write(f"\n  [스킵] {sym['code']}: {exc}\n")
            continue
        per_symbol.append({"code": sym["code"], "name": sym["name"],
                           "result": res, "metrics": m})
    sys.stderr.write("\n")

    if not per_symbol:
        print("[오류] 백테스트 가능한 종목이 없습니다 (분봉 데이터 부재 등). "
              "오프라인이면 --synthetic 을 사용하세요.")
        return 1
    if skipped:
        print(f"  ({skipped}개 종목은 데이터가 없어 제외)")

    agg = aggregate(per_symbol)
    print_report(per_symbol, agg, args)

    if args.save:
        out = pd.DataFrame([
            {"code": r["code"], "name": r["name"],
             "num_trades": r["metrics"]["num_trades"],
             "win_rate": r["metrics"]["win_rate"],
             "total_return": r["metrics"]["total_return"]}
            for r in per_symbol
        ])
        out.to_csv(args.save, index=False, encoding="utf-8-sig")
        print(f" 저장 완료: {args.save}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
