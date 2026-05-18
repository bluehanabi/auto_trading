"""종목 스크리너 — 단타 감시 후보군 선정.

코스피+코스닥 전종목(~2,700개)을 실시간 감시하는 것은 KIS 개인 API로는
비현실적이다(WebSocket 동시 구독 수십 개 제한, REST 초당 호출 제한).
그래서 먼저 '유동성·변동성이 충분한 종목'만 추려 감시 대상을 줄인다.

선정 기준
  - 평균 일거래대금(avg_value) : 클수록 체결이 잘 되고 슬리피지가 작다
  - 평균 일중 변동폭(volatility): 너무 낮으면 +2%/-2% 기회 자체가 안 나온다
  - 주가 범위                  : 동전주(호가단위 부담)·초고가주 제외
점수(score) = 거래대금 백분위와 변동성 백분위의 평균. 둘 다 높아야 좋다.

오프라인(네트워크 차단) 환경에서는 synthetic=True 로 가상 유니버스를 만들어
스크리너 로직 자체를 검증할 수 있다.
"""
import pandas as pd

from data import load_data, make_synthetic

MARKETS = ("KOSPI", "KOSDAQ")
_CODE_COLS = ("Code", "Symbol", "code", "symbol")
_NAME_COLS = ("Name", "name")


def get_universe(markets=MARKETS, synthetic=False, n_synthetic=60):
    """감시 대상 후보가 될 전체 종목 목록(DataFrame: Code/Name/Market[, 합성 프로파일])."""
    if synthetic:
        return _synthetic_universe(n_synthetic)

    try:
        import FinanceDataReader as fdr
    except ImportError as exc:
        raise RuntimeError(
            "FinanceDataReader 미설치. `pip install finance-datareader` 하거나 "
            "synthetic=True 를 사용하세요."
        ) from exc

    frames = []
    for mkt in markets:
        listing = fdr.StockListing(mkt)
        if listing is None or listing.empty:
            raise RuntimeError(f"'{mkt}' 종목 목록을 받지 못했습니다 (네트워크 차단?).")
        frames.append(_normalize_listing(listing, mkt))
    uni = pd.concat(frames, ignore_index=True).drop_duplicates("Code")
    return uni.reset_index(drop=True)


def screen(start, end, *, markets=MARKETS, top_n=100, min_value=5e9,
           min_price=1_000, max_price=500_000, min_volatility=0.015,
           synthetic=False, n_synthetic=60, sort_by="score", limit=None,
           progress=None):
    """유니버스를 훑어 후보군을 추린 뒤 점수순 상위 top_n 을 DataFrame 으로 반환.

    progress: callable(done, total) — 진행 상황 콜백(선택).
    """
    uni = get_universe(markets, synthetic=synthetic, n_synthetic=n_synthetic)
    if limit:
        uni = uni.iloc[:limit]
    total = len(uni)

    records = []
    for done, row in enumerate(uni.itertuples(index=False), start=1):
        feat = _features_for(row, start, end, synthetic)
        if feat is not None:
            records.append(feat)
        if progress:
            progress(done, total)

    df = pd.DataFrame(records)
    if df.empty:
        return df

    mask = (
        (df["avg_value"] >= min_value)
        & df["last_price"].between(min_price, max_price)
        & (df["volatility"] >= min_volatility)
    )
    df = df[mask].copy()
    if df.empty:
        return df

    df["value_pct"] = df["avg_value"].rank(pct=True)
    df["vol_pct"] = df["volatility"].rank(pct=True)
    df["score"] = (df["value_pct"] + df["vol_pct"]) / 2.0

    sort_col = {"score": "score", "value": "avg_value",
                "volatility": "volatility"}.get(sort_by, "score")
    df = df.sort_values(sort_col, ascending=False).head(top_n)
    return df.reset_index(drop=True)


def _features_for(row, start, end, synthetic):
    """종목 1개의 특징 계산. 데이터가 없거나 부족하면 None 반환(거래정지 등 자연 제외)."""
    code = getattr(row, "Code")
    name = getattr(row, "Name", code)
    market = getattr(row, "Market", "")
    try:
        if synthetic:
            df = make_synthetic(
                code, start, end,
                mu=getattr(row, "mu", 0.0003),
                sigma=getattr(row, "sigma", 0.02),
                base_price=getattr(row, "base_price", 50_000.0),
                volume_scale=getattr(row, "volume_scale", 1.0),
            )
        else:
            df = load_data(code, start, end)
    except Exception:
        return None
    if len(df) < 5:
        return None

    value = df["Close"] * df["Volume"]
    day_range = (df["High"] - df["Low"]) / df["Close"]
    return {
        "code": code,
        "name": name,
        "market": market,
        "last_price": float(df["Close"].iloc[-1]),
        "avg_value": float(value.mean()),
        "volatility": float(day_range.mean()),
        "trading_days": int(len(df)),
    }


def _normalize_listing(listing, market):
    cols = {c.lower(): c for c in listing.columns}
    code_col = next((cols[c.lower()] for c in _CODE_COLS if c.lower() in cols), None)
    name_col = next((cols[c.lower()] for c in _NAME_COLS if c.lower() in cols), None)
    if code_col is None or name_col is None:
        raise RuntimeError(
            f"종목 목록에서 코드/이름 컬럼을 찾지 못했습니다: {list(listing.columns)}"
        )
    out = pd.DataFrame({
        "Code": listing[code_col].astype(str).str.zfill(6),
        "Name": listing[name_col].astype(str),
        "Market": market,
    })
    return out[~out["Code"].str.contains("nan", case=False, na=False)]


def _synthetic_universe(n, seed=7):
    """유동성·변동성이 제각각인 가상 종목 유니버스 (오프라인 검증용)."""
    import numpy as np

    rng = np.random.default_rng(seed)
    price_choices = [1_500, 5_000, 12_000, 35_000, 80_000, 200_000]
    rows = []
    for i in range(n):
        market = "KOSPI" if i % 2 == 0 else "KOSDAQ"
        rows.append({
            "Code": f"{900000 + i:06d}",
            "Name": f"가상{market[:2]}{i:03d}",
            "Market": market,
            "mu": float(rng.normal(0.0002, 0.0006)),
            "sigma": float(rng.uniform(0.008, 0.05)),
            "base_price": float(rng.choice(price_choices)),
            "volume_scale": float(rng.uniform(0.1, 12.0)),
        })
    return pd.DataFrame(rows)
