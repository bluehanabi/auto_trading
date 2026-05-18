#!/usr/bin/env python3
"""KIS Open API 연결 점검 — 키 설정과 시세 조회가 되는지 확인한다.

이 스크립트는 실제 네트워크·인증이 필요하므로 본인 PC에서 실행한다.
실행 전 환경변수 설정 (모의투자 예시):

  export KIS_ENV=paper
  export KIS_APP_KEY=발급받은_앱키
  export KIS_APP_SECRET=발급받은_앱시크릿

키 발급: KIS 개발자센터 https://apiportal.koreainvestment.com
  1) 한국투자증권 계좌 개설 → (선택) 모의투자 신청
  2) 개발자센터에서 API 신청 → APP KEY / APP SECRET 발급

사용:
  python3 run_kis.py                 # 토큰 + 삼성전자 일봉/분봉 샘플
  python3 run_kis.py --symbol 000660
  python3 run_kis.py --no-minute     # 일봉만 확인
"""
import argparse
import datetime as dt


def main():
    today = dt.date.today()
    p = argparse.ArgumentParser(
        description="KIS Open API 연결 점검",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--symbol", default="005930", help="종목코드 (기본: 삼성전자)")
    p.add_argument("--no-minute", action="store_true", help="분봉 조회 생략")
    args = p.parse_args()

    try:
        from kis_api import KISClient, KISConfigError
    except ImportError as exc:
        print(f"[오류] 의존성 누락: {exc}  →  pip install -r requirements.txt")
        return 1

    try:
        client = KISClient()
    except Exception as exc:  # KISConfigError 등
        print(f"[설정 오류]\n{exc}")
        return 1

    print(f"환경: {client.env}  ({client.base})")

    # 1) 토큰
    try:
        token = client.token()
        print(f"토큰 발급 OK  (…{token[-8:]})")
    except Exception as exc:
        print(f"[토큰 실패] {exc}")
        return 1

    # 2) 일봉
    start = str(today - dt.timedelta(days=20))
    try:
        daily = client.daily_ohlcv(args.symbol, start, str(today))
        print(f"\n[일봉] {args.symbol}  {len(daily)} 행")
        print(daily.tail(3).to_string())
    except Exception as exc:
        print(f"[일봉 실패] {exc}")
        return 1

    # 3) 분봉
    if not args.no_minute:
        try:
            minute = client.minute_ohlcv(args.symbol)
            print(f"\n[분봉] {args.symbol}  {len(minute)} 봉")
            print(minute.tail(3).to_string())
        except Exception as exc:
            print(f"[분봉 실패] {exc}")
            print("  (장 시작 전·휴장일이면 분봉이 비어 있을 수 있습니다)")

    print("\n연결 점검 완료. 이제 run_backtest.py 에 --source kis 를 쓸 수 있습니다.")
    print("  예: python3 run_backtest.py --symbol 005930 --source kis "
          "--start 2024-01-01 --end 2024-12-31")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
