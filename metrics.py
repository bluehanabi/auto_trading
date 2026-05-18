"""백테스트 성과 지표 계산.

'1% 익절' 전략을 평가할 때 핵심은 승률이 아니라
  - 손익비(payoff)  : 평균이익 / 평균손실
  - 기대값(expectancy): 매매 1회당 평균 순손익
  - 거래비용 총합
이 세 가지다. 승률이 높아도 손익비·기대값이 나쁘면 결국 잃는다.
"""
import numpy as np


def compute_metrics(result):
    trades = result.trades
    eq = result.equity
    init = result.initial_cash
    final = float(eq.iloc[-1])

    m = {
        "initial_cash": init,
        "final_equity": final,
        "total_return": final / init - 1.0,
        "num_trades": len(trades),
        "max_drawdown": _max_drawdown(eq),
    }
    if not trades:
        m.update(
            win_rate=0.0, gross_pnl=0.0, net_pnl=0.0, total_cost=0.0,
            avg_win=0.0, avg_loss=0.0, payoff=0.0, profit_factor=0.0,
            expectancy=0.0, expectancy_pct=0.0, avg_hold_bars=0.0, reasons={},
        )
        return m

    nets = np.array([t.net_pnl for t in trades], dtype=float)
    rets = np.array([t.net_return for t in trades], dtype=float)
    is_win = nets > 0
    wins, losses = nets[is_win], nets[~is_win]

    gross_win = float(wins.sum())
    gross_loss = float(abs(losses.sum()))
    avg_win = float(rets[is_win].mean()) if wins.size else 0.0
    avg_loss = float(rets[~is_win].mean()) if losses.size else 0.0

    reasons = {}
    for t in trades:
        reasons[t.reason] = reasons.get(t.reason, 0) + 1

    m.update(
        win_rate=float(is_win.mean()),
        gross_pnl=float(sum(t.gross_pnl for t in trades)),
        net_pnl=float(nets.sum()),
        total_cost=float(sum(t.cost for t in trades)),
        avg_win=avg_win,
        avg_loss=avg_loss,
        payoff=(avg_win / abs(avg_loss)) if avg_loss != 0 else float("inf"),
        profit_factor=(gross_win / gross_loss) if gross_loss > 0 else float("inf"),
        expectancy=float(nets.mean()),
        expectancy_pct=float(rets.mean()),
        avg_hold_bars=float(np.mean([t.bars_held for t in trades])),
        reasons=reasons,
    )
    return m


def _max_drawdown(eq):
    arr = eq.to_numpy(dtype=float)
    if arr.size == 0:
        return 0.0
    peak = np.maximum.accumulate(arr)
    return float((arr / peak - 1.0).min())
