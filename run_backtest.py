#!/usr/bin/env python3
"""한국 주식 '익절 + 손절' 전략 백테스트 실행기 (일봉·분봉).

사용 예시
  # 일봉, 합성 데이터
  python3 run_backtest.py --synthetic --entry everyday

  # 분봉 + 2%/-2% (장 마감 강제청산) — 합성 데이터
  python3 run_backtest.py --synthetic --minute --entry upbar --tp 0.02 --sl 0.02

  # 실데이터 일봉 (네트워크 필요)
  python3 run_backtest.py --symbol 005930 --start 2020-01-01 --end 2024-12-31

  # 손절폭 비교
  python3 run_backtest.py --synthetic --minute --sweep
"""
import argparse
import datetime as dt

import config
from backtest import run_backtest
from data import load_data, load_intraday
from metrics import compute_metrics
from strategy import ENTRY_SIGNALS


def buy_and_hold_return(df, initial_cash, commission, tax):
    """첫 봉 시가에 전액 매수해 마지막 봉 종가에 청산한 경우의 수익률."""
    first_open = float(df["Open"].iloc[0])
    shares = int(initial_cash // (first_open * (1 + commission)))
    if shares <= 0:
        return 0.0
    spent = shares * first_open * (1 + commission)
    last_close = float(df["Close"].iloc[-1])
    proceeds = shares * last_close * (1 - commission - tax)
    final = (initial_cash - spent) + proceeds
    return final / initial_cash - 1.0


def _load(args):
    if args.minute:
        return load_intraday(args.symbol, args.start, args.end,
                             synthetic=args.synthetic, source=args.source)
    return load_data(args.symbol, args.start, args.end,
                     synthetic=args.synthetic, source=args.source)


def _won(x):
    return f"{x:>16,.0f}원"


def _pct(x):
    return f"{x * 100:+.2f}%"


def print_report(df, m, args, bh_return):
    sl_txt = "없음(위험!)" if not args.sl_value else f"-{args.sl_value * 100:.2f}%"
    unit = "봉" if args.minute else "거래일"
    print()
    print("=" * 64)
    print(f" 백테스트 결과 — {args.label}")
    print(f" 기간: {df.index[0]} ~ {df.index[-1]}  ({len(df):,} {unit})")
    mode = "분봉, 장마감 강제청산" if args.minute else "일봉"
    print(f" 모드: {mode}")
    print(f" 전략: 진입={args.entry} | 익절 +{args.tp * 100:.2f}% | 손절 {sl_txt}")
    print("=" * 64)
    print(f" 초기 자금      {_won(m['initial_cash'])}")
    print(f" 최종 자산      {_won(m['final_equity'])}")
    print(f" 총 수익률           {_pct(m['total_return'])}")
    print(f" (참고) 매수후보유   {_pct(bh_return)}")
    print("-" * 64)
    if m["num_trades"] == 0:
        print(" 매매가 한 건도 발생하지 않았습니다 (진입 신호 없음).")
        print("=" * 64)
        return
    print(f" 총 매매 횟수         {m['num_trades']:>8,} 회")
    print(f" 승률                 {m['win_rate'] * 100:>8.1f} %")
    print(f" 평균 수익(이긴 매매) {_pct(m['avg_win'])}")
    print(f" 평균 손실(진 매매)   {_pct(m['avg_loss'])}")
    print(f" 손익비(payoff)       {m['payoff']:>9.2f}   (1 미만이면 구조적으로 불리)")
    print(f" Profit Factor        {m['profit_factor']:>9.2f}   (1 미만이면 손실)")
    print(f" 매매 1회 기대값    {_won(m['expectancy'])}  ({_pct(m['expectancy_pct'])})")
    print(f" 최대 낙폭(MDD)       {_pct(m['max_drawdown'])}")
    print(f" 총 거래비용    {_won(m['total_cost'])}  (수익률을 갉아먹는 주범)")
    print(f" 평균 보유            {m['avg_hold_bars']:>8.1f} 봉")
    rtxt = " / ".join(f"{k} {v}" for k, v in sorted(m["reasons"].items()))
    print(f" 청산 사유            {rtxt}")
    print("=" * 64)
    _verdict(m, bh_return, args)
    print("=" * 64)


def _verdict(m, bh_return, args):
    win = m["win_rate"] * 100
    if m["total_return"] <= 0:
        print(f" ▶ 승률 {win:.0f}% 인데도 '손실'. 작은 익절을 큰 손실과 잦은")
        print(f"   거래비용({m['total_cost']:,.0f}원)이 상쇄 — 익절폭 전략의 전형적 함정.")
    elif m["total_return"] < bh_return:
        print(f" ▶ 수익은 났지만 단순 매수후보유({_pct(bh_return)})보다 부진.")
    else:
        print(f" ▶ 매수후보유({_pct(bh_return)})를 앞섬. 단, 합성/단일종목 결과이므로")
        print(f"   여러 종목·기간으로 재검증 필요 (과최적화 주의).")
    if args.minute:
        print(" * 분봉 단타는 매매가 잦아 거래비용 비중이 일봉보다 훨씬 큽니다.")


def run_sweep(df, args):
    """손절폭을 바꿔 가며 비교 — 승률↑ 이 수익↑ 이 아님을 보여 준다."""
    sl_list = [0.01, 0.02, 0.03, 0.05, None]
    sig = ENTRY_SIGNALS[args.entry](df)
    bh = buy_and_hold_return(df, args.cash, args.commission, args.tax)
    print()
    print("=" * 64)
    print(f" 손절폭 비교 — {args.label}  (익절 고정 +{args.tp * 100:.2f}%)")
    print(f" 진입={args.entry} | 매수후보유 수익률 {_pct(bh)}")
    print("=" * 64)
    print(f" {'손절':>8} | {'승률':>7} | {'손익비':>7} | {'매매수':>9} | {'총수익률':>10}")
    print("-" * 64)
    for sl in sl_list:
        res = run_backtest(
            df, sig, take_profit=args.tp, stop_loss=sl,
            max_hold_bars=args.max_hold, flat_eod=args.minute,
            initial_cash=args.cash, commission=args.commission,
            tax=args.tax, slippage=args.slippage,
        )
        m = compute_metrics(res)
        sl_txt = "없음" if not sl else f"-{sl * 100:.1f}%"
        print(f" {sl_txt:>8} | {m['win_rate'] * 100:>6.1f}% | "
              f"{m['payoff']:>7.2f} | {m['num_trades']:>9,} | "
              f"{m['total_return'] * 100:>+9.2f}%")
    print("=" * 64)
    print(" ▶ 손절을 늘리면 승률은 오르지만 한 번의 손실이 커진다.")
    print("   승률이 아니라 손익비·총수익률을 봐야 한다.")
    print("=" * 64)


def main():
    today = dt.date.today()
    p = argparse.ArgumentParser(
        description="한국 주식 '익절+손절' 전략 백테스트 (일봉·분봉)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--symbol", default="005930", help="종목코드 6자리 (기본: 삼성전자)")
    p.add_argument("--start", default=None)
    p.add_argument("--end", default=None)
    p.add_argument("--minute", action="store_true",
                   help="분봉 백테스트 (장마감 강제청산)")
    p.add_argument("--synthetic", action="store_true",
                   help="합성 데이터 사용 (네트워크 불필요)")
    p.add_argument("--source", default="fdr", choices=["fdr", "kis"],
                   help="실데이터 출처 (fdr=일봉, kis=일봉/분봉)")
    p.add_argument("--entry", default=None, choices=list(ENTRY_SIGNALS),
                   help="진입 신호 (기본: 분봉=upbar, 일봉=everyday)")
    p.add_argument("--tp", type=float, default=None, help="익절 비율")
    p.add_argument("--sl", type=float, default=None, help="손절 비율")
    p.add_argument("--no-stop", action="store_true", help="손절 비활성화")
    p.add_argument("--max-hold", type=int, default=config.MAX_HOLD_BARS,
                   help="최대 보유 봉 수")
    p.add_argument("--cash", type=float, default=config.INITIAL_CASH)
    p.add_argument("--commission", type=float, default=config.COMMISSION_RATE)
    p.add_argument("--tax", type=float, default=config.TAX_RATE)
    p.add_argument("--slippage", type=float, default=config.SLIPPAGE_RATE)
    p.add_argument("--sweep", action="store_true",
                   help="손절폭을 바꿔 가며 비교표 출력")
    args = p.parse_args()

    # 모드별 기본값 해석
    if args.minute:
        args.end = args.end or str(today)
        args.start = args.start or str(today - dt.timedelta(days=20))
        args.entry = args.entry or "upbar"
    else:
        args.end = args.end or "2024-12-31"
        args.start = args.start or "2020-01-01"
        args.entry = args.entry or "everyday"
    args.tp = args.tp if args.tp is not None else (0.02 if args.minute else config.TAKE_PROFIT)
    args.sl = args.sl if args.sl is not None else (0.02 if args.minute else config.STOP_LOSS)
    args.label = f"합성:{args.symbol}" if args.synthetic else args.symbol

    try:
        df = _load(args)
    except RuntimeError as exc:
        print(f"[데이터 오류] {exc}")
        return 1

    if args.sweep:
        run_sweep(df, args)
        return 0

    args.sl_value = None if args.no_stop else args.sl
    sig = ENTRY_SIGNALS[args.entry](df)
    res = run_backtest(
        df, sig, take_profit=args.tp, stop_loss=args.sl_value,
        max_hold_bars=args.max_hold, flat_eod=args.minute,
        initial_cash=args.cash, commission=args.commission,
        tax=args.tax, slippage=args.slippage,
    )
    m = compute_metrics(res)
    bh = buy_and_hold_return(df, args.cash, args.commission, args.tax)
    print_report(df, m, args, bh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
