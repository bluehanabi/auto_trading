"""KIS API 클라이언트 검증 — 네트워크 없이 가능한 부분만 (파싱·설정).

  python3 tests/test_kis.py

토큰 발급·시세 조회 등 네트워크가 필요한 부분은 본인 PC에서 run_kis.py 로
점검한다(여기서는 검증 불가).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from kis_api import KISClient, KISConfigError, _parse_daily, _parse_minute


def test_parse_daily():
    rows = [
        {"stck_bsop_date": "20240105", "stck_oprc": "71000", "stck_hgpr": "72000",
         "stck_lwpr": "70500", "stck_clpr": "71500", "acml_vol": "12000000"},
        {"stck_bsop_date": "20240104", "stck_oprc": "70000", "stck_hgpr": "70800",
         "stck_lwpr": "69500", "stck_clpr": "70600", "acml_vol": "9000000"},
    ]
    df = _parse_daily(rows)
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert len(df) == 2
    assert df.index.is_monotonic_increasing
    assert df.loc[pd.Timestamp("2024-01-05"), "Close"] == 71500.0
    print("  ok test_parse_daily")


def test_parse_daily_skips_bad_rows():
    rows = [
        {"stck_bsop_date": "20240105", "stck_oprc": "71000", "stck_hgpr": "72000",
         "stck_lwpr": "70500", "stck_clpr": "71500", "acml_vol": "1"},
        {"stck_bsop_date": "", "stck_clpr": ""},          # 빈 행 → 무시
    ]
    df = _parse_daily(rows)
    assert len(df) == 1
    print("  ok test_parse_daily_skips_bad_rows")


def test_parse_minute():
    rows = [
        {"stck_bsop_date": "20240105", "stck_cntg_hour": "093000",
         "stck_oprc": "71000", "stck_hgpr": "71100", "stck_lwpr": "70900",
         "stck_prpr": "71050", "cntg_vol": "5000"},
    ]
    out = _parse_minute(rows)
    ts = pd.Timestamp("2024-01-05 09:30:00")
    assert ts in out
    assert out[ts]["Close"] == 71050.0
    assert out[ts]["Volume"] == 5000.0
    print("  ok test_parse_minute")


def test_parse_minute_day_fallback():
    """행에 날짜가 없으면 day 인자로 보완한다."""
    rows = [{"stck_cntg_hour": "100000", "stck_oprc": "100", "stck_hgpr": "101",
             "stck_lwpr": "99", "stck_prpr": "100", "cntg_vol": "10"}]
    out = _parse_minute(rows, day="20240105")
    assert pd.Timestamp("2024-01-05 10:00:00") in out
    print("  ok test_parse_minute_day_fallback")


def test_config_error_without_keys():
    """앱키/시크릿이 없으면 KISConfigError 가 나야 한다."""
    saved = {k: os.environ.pop(k, None)
             for k in ("KIS_APP_KEY", "KIS_APP_SECRET", "KIS_ENV")}
    try:
        try:
            KISClient()
            raise AssertionError("키 없이 생성되면 안 됨")
        except KISConfigError:
            pass
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
    print("  ok test_config_error_without_keys")


def test_bad_env_rejected():
    try:
        KISClient(app_key="x", app_secret="y", env="invalid")
        raise AssertionError("잘못된 env 가 통과됨")
    except KISConfigError:
        pass
    print("  ok test_bad_env_rejected")


def test_domain_by_env():
    paper = KISClient(app_key="x", app_secret="y", env="paper")
    real = KISClient(app_key="x", app_secret="y", env="real")
    assert "openapivts" in paper.base, paper.base
    assert real.base.endswith(":9443"), real.base
    assert paper._interval > real._interval   # 모의 레이트리밋이 더 빡빡
    print("  ok test_domain_by_env")


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(f"KIS API 테스트 {len(tests)}건 실행")
    for t in tests:
        t()
    print(f"\n전체 통과 ({len(tests)}건)")


if __name__ == "__main__":
    main()
