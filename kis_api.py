"""한국투자증권(KIS) Open API 클라이언트 — 시세 데이터 조회.

주의: 이 모듈은 실제 네트워크·인증이 필요해 오프라인 환경에서는 동작
검증이 불가능하다. 본인 PC에서 환경변수에 키를 넣고 실행해야 한다.
순수 파싱 함수(_parse_daily/_parse_minute)만 네트워크 없이 테스트한다.

필요 환경변수 (KIS 개발자센터에서 발급, 절대 코드/저장소에 직접 쓰지 말 것)
  KIS_APP_KEY      앱키
  KIS_APP_SECRET   앱시크릿
  KIS_ENV          'paper'(모의, 기본) | 'real'(실전)
  KIS_ACCOUNT_NO   계좌번호 (시세 조회만 하면 불필요)

시세 조회 TR 은 모의·실전 도메인 모두에서 동일하다. 모의 도메인에서
시세 조회가 막히면 KIS_ENV=real 로 두고 조회만 해도 된다(주문은 별개).
"""
import json
import os
import time

import pandas as pd
import requests

_DOMAINS = {
    "paper": "https://openapivts.koreainvestment.com:29443",
    "real": "https://openapi.koreainvestment.com:9443",
}
# 레이트리밋: 실전 초당 약 20건, 모의 약 2건 — 보수적으로 간격을 둔다.
_RATE_INTERVAL = {"real": 0.06, "paper": 0.5}

_TOKEN_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            ".kis_token.json")


class KISConfigError(RuntimeError):
    """키 미설정 등 설정 오류."""


def _parse_daily(rows):
    """KIS 일봉 응답(output2 list)을 OHLCV DataFrame 으로."""
    recs = {}
    for r in rows:
        date = r.get("stck_bsop_date")
        if not date or not r.get("stck_clpr"):
            continue
        recs[pd.Timestamp(date)] = {
            "Open": float(r["stck_oprc"]),
            "High": float(r["stck_hgpr"]),
            "Low": float(r["stck_lwpr"]),
            "Close": float(r["stck_clpr"]),
            "Volume": float(r.get("acml_vol", 0) or 0),
        }
    df = pd.DataFrame.from_dict(recs, orient="index",
                               columns=["Open", "High", "Low", "Close", "Volume"])
    df.index.name = "Date"
    return df.sort_index()


def _parse_minute(rows, day=None):
    """KIS 분봉 응답(output2 list)을 {Timestamp: OHLCV} dict 로."""
    out = {}
    for r in rows:
        date = r.get("stck_bsop_date") or day
        hhmmss = r.get("stck_cntg_hour")
        if not date or not hhmmss or not r.get("stck_prpr"):
            continue
        hhmmss = str(hhmmss).zfill(6)
        ts = pd.Timestamp(f"{date} {hhmmss[:2]}:{hhmmss[2:4]}:{hhmmss[4:6]}")
        out[ts] = {
            "Open": float(r["stck_oprc"]),
            "High": float(r["stck_hgpr"]),
            "Low": float(r["stck_lwpr"]),
            "Close": float(r["stck_prpr"]),
            "Volume": float(r.get("cntg_vol", 0) or 0),
        }
    return out


class KISClient:
    """KIS Open API 시세 조회 클라이언트."""

    def __init__(self, app_key=None, app_secret=None, env=None, account=None):
        self.env = (env or os.getenv("KIS_ENV", "paper")).lower()
        if self.env not in _DOMAINS:
            raise KISConfigError(
                f"KIS_ENV 는 'paper' 또는 'real' 이어야 합니다 (현재: {self.env}).")
        self.app_key = app_key or os.getenv("KIS_APP_KEY")
        self.app_secret = app_secret or os.getenv("KIS_APP_SECRET")
        self.account = account or os.getenv("KIS_ACCOUNT_NO", "")
        if not self.app_key or not self.app_secret:
            raise KISConfigError(
                "환경변수 KIS_APP_KEY / KIS_APP_SECRET 가 설정되지 않았습니다.\n"
                "  KIS 개발자센터(https://apiportal.koreainvestment.com)에서 발급 후\n"
                "  export KIS_APP_KEY=...  export KIS_APP_SECRET=...  로 설정하세요.")
        self.base = _DOMAINS[self.env]
        self._interval = _RATE_INTERVAL[self.env]
        self._last_call = 0.0
        self._token = None

    # ------------------------------------------------------------------ 인증
    def _load_cached_token(self):
        if not os.path.exists(_TOKEN_CACHE):
            return None
        try:
            with open(_TOKEN_CACHE, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return None
        if data.get("env") != self.env or data.get("app_key") != self.app_key:
            return None
        if time.time() > data.get("expires_at", 0) - 600:   # 만료 10분 전 폐기
            return None
        return data.get("token")

    def _save_token(self, token, expires_in):
        data = {"env": self.env, "app_key": self.app_key, "token": token,
                "expires_at": time.time() + float(expires_in)}
        try:
            with open(_TOKEN_CACHE, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.chmod(_TOKEN_CACHE, 0o600)
        except OSError:
            pass

    def token(self):
        """접근토큰 반환. KIS 는 토큰 재발급을 제한하므로 캐시를 반드시 사용한다."""
        if self._token:
            return self._token
        cached = self._load_cached_token()
        if cached:
            self._token = cached
            return cached
        try:
            resp = requests.post(
                f"{self.base}/oauth2/tokenP",
                json={"grant_type": "client_credentials",
                      "appkey": self.app_key, "appsecret": self.app_secret},
                timeout=10,
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"KIS 토큰 요청 실패 (네트워크 확인): {exc}") from exc
        if resp.status_code != 200:
            raise KISConfigError(
                f"KIS 토큰 발급 실패 (HTTP {resp.status_code}). "
                f"앱키/시크릿과 KIS_ENV 를 확인하세요: {resp.text[:200]}")
        token = resp.json().get("access_token")
        if not token:
            raise KISConfigError(f"KIS 토큰 응답에 access_token 이 없습니다: {resp.text[:200]}")
        self._token = token
        self._save_token(token, resp.json().get("expires_in", 86400))
        return token

    # -------------------------------------------------------------- 공통 호출
    def _throttle(self):
        wait = self._interval - (time.time() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.time()

    def _get(self, path, tr_id, params):
        self._throttle()
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self.token()}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
            "custtype": "P",
        }
        try:
            resp = requests.get(f"{self.base}{path}", headers=headers,
                                params=params, timeout=10)
        except requests.RequestException as exc:
            raise RuntimeError(f"KIS API 요청 실패 (네트워크 확인): {exc}") from exc
        if resp.status_code != 200:
            raise RuntimeError(f"KIS API HTTP {resp.status_code} [{path}]: "
                               f"{resp.text[:200]}")
        body = resp.json()
        if str(body.get("rt_cd", "")) != "0":
            raise RuntimeError(f"KIS API 오류 [{tr_id}]: {body.get('msg1')} "
                               f"(rt_cd={body.get('rt_cd')})")
        return body

    # ------------------------------------------------------------------ 일봉
    def daily_ohlcv(self, symbol, start, end):
        """일봉 OHLCV DataFrame. start/end 는 'YYYY-MM-DD'.

        KIS 일봉 TR 은 한 호출에 약 100건 → 구간을 나눠 거슬러 올라가며 모은다.
        """
        s, e = pd.Timestamp(start), pd.Timestamp(end)
        frames, cursor = [], e
        while cursor >= s:
            seg_start = max(s, cursor - pd.Timedelta(days=140))
            body = self._get(
                "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
                "FHKST03010100",
                {
                    "FID_COND_MRKT_DIV_CODE": "J",
                    "FID_INPUT_ISCD": symbol,
                    "FID_INPUT_DATE_1": seg_start.strftime("%Y%m%d"),
                    "FID_INPUT_DATE_2": cursor.strftime("%Y%m%d"),
                    "FID_PERIOD_DIV_CODE": "D",
                    "FID_ORG_ADJ_PRC": "0",
                },
            )
            rows = body.get("output2") or []
            parsed = _parse_daily(rows)
            if parsed.empty:
                break
            frames.append(parsed)
            cursor = seg_start - pd.Timedelta(days=1)
        if not frames:
            raise RuntimeError(f"'{symbol}' 일봉 데이터를 받지 못했습니다.")
        df = pd.concat(frames)
        df = df[~df.index.duplicated()].sort_index()
        return df.loc[s:e]

    # ------------------------------------------------------------------ 분봉
    def minute_ohlcv(self, symbol, day=None):
        """1분봉 OHLCV DataFrame.

        KIS 분봉 TR 은 한 호출에 30건, 기본적으로 '당일' 데이터를 준다.
        기준시각을 거슬러 올리며 하루치를 모은다. day 는 'YYYYMMDD'(생략 시 당일).
        """
        bars, cursor = {}, "153000"
        for _ in range(25):                       # 30건 × 25 = 750분 → 하루 충분
            body = self._get(
                "/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice",
                "FHKST03010200",
                {
                    "FID_ETC_CLS_CODE": "",
                    "FID_COND_MRKT_DIV_CODE": "J",
                    "FID_INPUT_ISCD": symbol,
                    "FID_INPUT_HOUR_1": cursor,
                    "FID_PW_DATA_INCU_YN": "N",
                },
            )
            parsed = _parse_minute(body.get("output2") or [], day)
            fresh = {ts: v for ts, v in parsed.items() if ts not in bars}
            if not fresh:
                break
            bars.update(fresh)
            earliest = min(parsed)
            if earliest.strftime("%H%M%S") <= "090100":
                break
            cursor = (earliest - pd.Timedelta(minutes=1)).strftime("%H%M%S")
        if not bars:
            raise RuntimeError(f"'{symbol}' 분봉 데이터를 받지 못했습니다.")
        df = pd.DataFrame.from_dict(bars, orient="index",
                                    columns=["Open", "High", "Low", "Close", "Volume"])
        return df.sort_index()
