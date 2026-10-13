"""Offline transport regression: MEXC 510 must retry without changing H3 rules."""
import pandas as pd
from . import provider

class Reply:
    def __init__(self,body,code=200):
        self.body=body;self.status_code=code
    def raise_for_status(self):
        if self.status_code>=400:raise RuntimeError(f"Unexpected HTTP {self.status_code}")
    def json(self):return self.body

def main():
    start=pd.Timestamp("2026-10-13T03:00:00Z")
    t0=int(start.timestamp())
    success={
        "success":True,"code":0,
        "data":{"time":[t0,t0+3600],"open":[100.0,101.0],
            "high":[102.0,103.0],"low":[99.0,100.0],
            "close":[101.0,102.0],"vol":[9.0,10.0],
            "amount":[15000.0,17000.0]},
    }
    class Fake:
        def __init__(self):self.calls=0
        def get(self,url,params,timeout):
            self.calls+=1
            assert params["interval"]=="Min60"
            assert url.endswith("/BTC_USDT")
            if self.calls==1:
                return Reply({"success":False,"code":510,"message":"Requests are too frequent, please try again later"})
            return Reply(success)
    fake=Fake()
    previous=(provider._session,provider._wait_turn,provider._cooldown)
    try:
        provider._session=lambda:fake
        provider._wait_turn=lambda:None
        provider._cooldown=lambda seconds:None
        frame,attempts=provider.fetch_hourly_paced("BTC_USDT",start,start+pd.Timedelta(hours=1))
    finally:
        provider._session,provider._wait_turn,provider._cooldown=previous
    assert fake.calls==2 and attempts==2
    assert len(frame)==2 and frame["amount"].iloc[-1]==17000
    print("M4 provider transport SELFTEST PASS: retry transient MEXC 510, preserve candle data, count true requests")
    return 0

if __name__=="__main__":raise SystemExit(main())
