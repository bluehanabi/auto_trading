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


def load_data(symbol, start, end, synthetic=False, seed=42, source="fdr"):
    """일봉 OHLCV DataFrame 반환 (DatetimeIndex, 컬럼: Open/High/Low/Close[/Volume]).

    source: 'fdr'(FinanceDataReader, 기본) | 'kis'(한국투자증권 Open API).
    한 번 받은 데이터는 캐시 CSV 로 저장돼 다음 실행·다른 도구에서 재사용된다.
    """
    if synthetic:
        return make_synthetic(symbol, start, end, seed=seed)

    os.makedirs(CACHE_DIR, exist_ok=True)
    cache = os.path.join(CACHE_DIR, f"{symbol}_{start}_{end}.csv")
    if os.path.exists(cache):
        df = pd.read_csv(cache, index_col=0, parse_dates=True)
        return _normalize(df)

    df = _fetch_kis_daily(symbol, start, end) if source == "kis" \
        else _fetch_fdr_daily(symbol, start, end)
    df.to_csv(cache)
    return df


def _fetch_fdr_daily(symbol, start, end):
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
    return _normalize(df)


def _fetch_kis_daily(symbol, start, end):
    from kis_api import KISClient
    return _normalize(KISClient().daily_ohlcv(symbol, start, end))


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


def load_intraday(symbol, start, end, synthetic=False, seed=42,
                  source="fdr", **kwargs):
    """분봉(1분봉) OHLCV DataFrame 반환.

    source='kis' 면 KIS Open API 로 'end' 날짜의 분봉을 받는다(KIS 분봉 TR 은
    당일 위주라 한 번에 하루치만 제공). source 가 그 외이면 캐시 CSV 가 있을
    때만 쓰고, 없으면 안내한다. 오프라인 검증은 synthetic=True 를 사용한다.
    """
    if synthetic:
        return make_synthetic_intraday(symbol, start, end, seed=seed, **kwargs)

    os.makedirs(CACHE_DIR, exist_ok=True)

    if source == "kis":
        day = pd.Timestamp(end).strftime("%Y%m%d")
        cache = os.path.join(CACHE_DIR, f"{symbol}_intraday_{day}.csv")
        if os.path.exists(cache):
            return _normalize(pd.read_csv(cache, index_col=0, parse_dates=True))
        from kis_api import KISClient
        df = _normalize(KISClient().minute_ohlcv(symbol, day=day))
        df.to_csv(cache)
        return df

    cache = os.path.join(CACHE_DIR, f"{symbol}_intraday.csv")
    if os.path.exists(cache):
        return _normalize(pd.read_csv(cache, index_col=0, parse_dates=True))
    raise RuntimeError(
        f"'{symbol}' 분봉 데이터가 없습니다. 실데이터 분봉은 source='kis' 가 필요합니다 "
        f"(FinanceDataReader 는 분봉 미제공). 오프라인 검증은 synthetic=True 를 사용하세요."
    )


# 합성 데이터 regime 별 분봉 수익률 자기상관 계수(AR(1) phi).
#   random   : 0    — 랜덤워크. 잡을 패턴이 없다(어떤 신호도 우위 없음).
#   momentum : +    — 추세 지속. 돌파·모멘텀 신호가 우위를 가진다.
#   meanrev  : -    — 평균 회귀. 눌림목(pullback) 신호가 우위를 가진다.
_REGIME_PHI = {"random": 0.0, "momentum": 0.55, "meanrev": -0.55}


def _ar1(eps, phi):
    """AR(1) 과정 생성: r_t = phi * r_{t-1} + eps_t."""
    if phi == 0.0:
        return eps
    out = np.empty_like(eps)
    prev = 0.0
    for t in range(len(eps)):
        prev = phi * prev + eps[t]
        out[t] = prev
    return out


def make_synthetic_intraday(symbol, start, end, *, seed=42, mu=0.0004,
                            sigma=0.018, base_price=50_000.0, volume_scale=1.0,
                            bars_per_day=380, regime="random"):
    """1분봉 합성 데이터.

    sigma 는 '일' 변동성이며 분봉 변동성은 sigma/sqrt(bars_per_day) 로 환산한다.
    하루 거래시간을 09:00 부터 bars_per_day 분으로 두고(점심 휴장은 생략),
    거래일 사이에는 오버나이트 갭을 넣는다.

    regime 으로 분봉 수익률의 자기상관(추세/평균회귀)을 주입할 수 있다.
    기본 'random' 은 랜덤워크라 진입 신호의 우위가 존재하지 않는다.
    """
    if regime not in _REGIME_PHI:
        raise ValueError(f"알 수 없는 regime: {regime} (가능: {list(_REGIME_PHI)})")
    phi = _REGIME_PHI[regime]

    offset = sum(map(ord, symbol)) if symbol else 0
    rng = np.random.default_rng(seed + offset)
    days = pd.bdate_range(start, end)
    if len(days) == 0:
        raise ValueError("기간(start~end)에 거래일이 없습니다.")

    bar_sigma = sigma / np.sqrt(bars_per_day)
    bar_mu = mu / bars_per_day
    overnight_sigma = sigma * 0.4
    eps_sigma = bar_sigma * np.sqrt(max(1.0 - phi * phi, 1e-6))  # 정상분산 보정

    stamps, o_all, h_all, l_all, c_all, v_all = [], [], [], [], [], []
    price = base_price
    for day in days:
        price = price * np.exp(rng.normal(0.0, overnight_sigma))   # 시초가 갭
        session = pd.date_range(day + pd.Timedelta(hours=9),
                                periods=bars_per_day, freq="1min")
        rets = _ar1(rng.normal(0.0, eps_sigma, bars_per_day), phi) + bar_mu
        closes = price * np.exp(np.cumsum(rets))
        opens = np.concatenate([[price], closes[:-1]])
        wig = np.abs(rng.normal(0.0, bar_sigma * 0.6, bars_per_day))
        highs = np.maximum(opens, closes) * (1.0 + wig)
        lows = np.minimum(opens, closes) * (1.0 - wig)
        vols = (rng.integers(2_000, 20_000, bars_per_day) * volume_scale).astype(np.int64)
        stamps.append(session.to_numpy())
        o_all.append(opens)
        h_all.append(highs)
        l_all.append(lows)
        c_all.append(closes)
        v_all.append(vols)
        price = closes[-1]

    df = pd.DataFrame(
        {
            "Open": np.concatenate(o_all),
            "High": np.concatenate(h_all),
            "Low": np.concatenate(l_all),
            "Close": np.concatenate(c_all),
            "Volume": np.concatenate(v_all),
        },
        index=pd.DatetimeIndex(np.concatenate(stamps)),
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
