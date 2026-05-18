"""진입 신호 정의.

각 함수는 OHLCV DataFrame 을 받아 bool Series 를 반환한다.
신호는 해당 봉의 '종가 기준'으로 판단되며, 실제 매수 체결은 백테스트 엔진이
다음 봉의 '시가'에서 처리한다(룩어헤드 방지).

'1% 익절'은 출구 규칙일 뿐이고, 진짜 성패는 진입 신호가 가른다.
여기서 여러 진입 규칙을 바꿔 끼우며 비교할 수 있다.
"""
import numpy as np
import pandas as pd


def everyday(df):
    """포지션이 비어 있을 때마다 진입.

    진입 신호의 영향을 제거하고, 익절/손절 규칙과 거래비용의 '순수 효과'만
    보고 싶을 때 쓴다. '1% 익절' 함정을 가장 적나라하게 보여 준다.
    """
    return pd.Series(True, index=df.index)


def up_candle(df):
    """직전 봉이 양봉(종가>시가)일 때 진입 — '분봉이 상승할 때 진입'의 단순 구현.

    노이즈가 큰 약한 신호다. 이 신호로 +2%/-2% 가 실제로 수익이 나는지는
    반드시 백테스트로 확인해야 한다(대체로 거래비용에 잠식된다).
    """
    return (df["Close"] > df["Open"]).fillna(False)


def sma_cross(df, short=5, long=20):
    """단기 이동평균이 장기 이동평균을 상향 돌파(골든크로스)."""
    s = df["Close"].rolling(short).mean()
    l = df["Close"].rolling(long).mean()
    cross = (s > l) & (s.shift(1) <= l.shift(1))
    return cross.fillna(False)


def momentum(df, lookback=10):
    """최근 lookback 봉 동안 가격이 올랐을 때 진입 (추세추종).

    추세가 이어지는 시장(모멘텀 regime)에서는 우위가 있고, 랜덤워크에서는 없다.
    """
    return (df["Close"] > df["Close"].shift(lookback)).fillna(False)


def breakout(df, window=20):
    """직전 window 봉의 고가를 종가가 돌파할 때 진입 (전형적 돌파매매)."""
    prior_high = df["High"].shift(1).rolling(window).max()
    return (df["Close"] > prior_high).fillna(False)


def volume_breakout(df, window=20, vol_mult=1.5):
    """거래량이 평소(window 평균)의 vol_mult 배 이상인 상태의 가격 돌파.

    '거래량 동반 돌파' — 돌파의 신뢰도를 거래량으로 거른다.
    """
    prior_high = df["High"].shift(1).rolling(window).max()
    avg_vol = df["Volume"].shift(1).rolling(window).mean()
    price_break = df["Close"] > prior_high
    vol_surge = df["Volume"] > vol_mult * avg_vol
    return (price_break & vol_surge).fillna(False)


def pullback(df, ma=20, dip=0.01):
    """가격이 이동평균보다 dip 이상 아래로 눌렸을 때 진입 (눌림목/평균회귀)."""
    mid = df["Close"].rolling(ma).mean()
    return (df["Close"] < mid * (1 - dip)).fillna(False)


def rsi_oversold(df, period=14, threshold=30):
    """RSI 가 과매도 구간(threshold) 아래에서 위로 다시 올라올 때."""
    delta = df["Close"].diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    signal = (rsi > threshold) & (rsi.shift(1) <= threshold)
    return signal.fillna(False)


ENTRY_SIGNALS = {
    "everyday": everyday,
    "upbar": up_candle,
    "momentum": momentum,
    "breakout": breakout,
    "volbreak": volume_breakout,
    "pullback": pullback,
    "sma": sma_cross,
    "rsi": rsi_oversold,
}
