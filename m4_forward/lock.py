"""Immutable H3 preregistration. Must be committed BEFORE 2026-10-13 00:00 UTC."""
import json
from datetime import datetime,timezone
from pathlib import Path
from .protocol import (
 PROTOCOL_HASH,FREEZE_START_UTC,HYPOTHESIS_ID,rules
)

def _utc(t):
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)

def lock_protocol(path=Path("state/m4_forward/H3_protocol_lock.json"),now=None):
    path=Path(path);now=_utc(now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    freeze=datetime.fromisoformat(FREEZE_START_UTC)
    if path.exists():
        data=json.loads(path.read_text(encoding="utf-8"))
        if (data["protocol_sha256"]!=PROTOCOL_HASH or
            data["hypothesis_id"]!=HYPOTHESIS_ID or
            data["freeze_start_utc"]!=FREEZE_START_UTC or
            datetime.fromisoformat(data["locked_at_utc"])>=freeze):
            raise RuntimeError("Frozen H3 preregistration conflict: do not retune.")
        return data
    if now>=freeze:
        raise RuntimeError("Cannot preregister H3 retrospectively AFTER freeze start.")
    obj={"hypothesis_id":HYPOTHESIS_ID,"protocol_sha256":PROTOCOL_HASH,
         "freeze_start_utc":FREEZE_START_UTC,"locked_at_utc":now.isoformat(),
         "rules":rules(),"no_prior_outcome_analysis":True,
         "status":"REGISTERED_BEFORE_START"}
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")
    return obj

def main():
    out=lock_protocol()
    print(json.dumps({k:out[k] for k in ("hypothesis_id","protocol_sha256",
                                         "freeze_start_utc","locked_at_utc","status")},indent=2))
    return 0

if __name__=="__main__":raise SystemExit(main())
