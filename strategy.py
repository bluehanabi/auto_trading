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


def sma_cross(df, short=5, long=20):
    """단기 이동평균이 장기 이동평균을 상향 돌파(골든크로스)."""
    s = df["Close"].rolling(short).mean()
    l = df["Close"].rolling(long).mean()
    cross = (s > l) & (s.shift(1) <= l.shift(1))
    return cross.fillna(False)


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
    "sma": sma_cross,
    "rsi": rsi_oversold,
}
