"""일봉(OHLCV) 데이터 로딩.

우선순위:
  1) synthetic=True 면 합성 데이터(GBM)를 생성 — 네트워크가 막힌 환경의 데모/테스트용
  2) data/cache/<symbol>_<start>_<end>.csv 캐시가 있으면 재사용
  3) FinanceDataReader 로 다운로드 후 캐시에 저장 (네트워크 필요)

KIS 실거래 연동 시에도 백테스트 데이터는 FinanceDataReader(KRX) 로 받는 것이
간편하다. 종목코드는 6자리 문자열(예: 삼성전자 '005930').
"""
import os

import numpy as np
import pandas as pd

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cache")

_REQUIRED = ["Open", "High", "Low", "Close"]


def load_data(symbol, start, end, synthetic=False, seed=42):
    """OHLCV DataFrame 반환 (DatetimeIndex, 컬럼: Open/High/Low/Close[/Volume])."""
    if synthetic:
        return make_synthetic(symbol, start, end, seed=seed)

    os.makedirs(CACHE_DIR, exist_ok=True)
    cache = os.path.join(CACHE_DIR, f"{symbol}_{start}_{end}.csv")
    if os.path.exists(cache):
        df = pd.read_csv(cache, index_col=0, parse_dates=True)
        return _normalize(df)

    try:
        import FinanceDataReader as fdr
    except ImportError as exc:
        raise RuntimeError(
            "FinanceDataReader 가 설치되어 있지 않습니다. "
            "`pip install finance-datareader` 후 다시 시도하거나, synthetic=True 를 사용하세요."
        ) from exc

    df = fdr.DataReader(symbol, start, end)
    if df is None or df.empty:
        raise RuntimeError(
            f"'{symbol}' 데이터를 가져오지 못했습니다 (네트워크 차단 또는 잘못된 종목코드). "
            "오프라인 환경이라면 synthetic=True 로 검증해 보세요."
        )
    df = _normalize(df)
    df.to_csv(cache)
    return df


def make_synthetic(symbol, start, end, *, seed=42, mu=0.0004, sigma=0.018,
                   base_price=50_000.0, volume_scale=1.0):
    """기하 브라운 운동 기반 합성 일봉.

    실제 시세는 아니지만 변동성·갭·장중 고저를 흉내 내므로 엔진·스크리너
    검증과 '익절폭' 전략 거동 체험에 충분하다. mu/sigma/base_price/volume_scale
    을 종목마다 다르게 주면 유동성·변동성이 제각각인 가상 유니버스를 만들 수 있다.
    """
    offset = sum(map(ord, symbol)) if symbol else 0
    rng = np.random.default_rng(seed + offset)
    dates = pd.bdate_range(start, end)
    n = len(dates)
    if n == 0:
        raise ValueError("기간(start~end)에 거래일이 없습니다.")

    intraday = max(sigma * 0.45, 0.002)   # 장중 고가/저가 변동 폭

    rets = rng.normal(mu, sigma, n)
    close = base_price * np.exp(np.cumsum(rets))
    prev_close = np.concatenate([[base_price], close[:-1]])
    gap = rng.normal(0.0, sigma * 0.2, n)
    open_ = prev_close * (1.0 + gap)
    high = np.maximum(open_, close) * (1.0 + np.abs(rng.normal(0.0, intraday, n)))
    low = np.minimum(open_, close) * (1.0 - np.abs(rng.normal(0.0, intraday, n)))
    volume = (rng.integers(1_000_000, 5_000_000, n) * volume_scale).astype(np.int64)

    df = pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=dates,
    )
    return df.round(0)


def _normalize(df):
    df = df.rename(columns=str.capitalize)
    missing = [c for c in _REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"필수 컬럼 누락: {missing}")
    keep = _REQUIRED + (["Volume"] if "Volume" in df.columns else [])
    df = df[keep].copy()
    df.index = pd.to_datetime(df.index)
    return df.dropna().sort_index()
