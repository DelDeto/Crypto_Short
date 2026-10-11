"""M3 V4.5.1 replication gate against the original V4.4.1 frozen result."""
import json,os,sys
from .config import OUTPUT_DIR
from .m3_v451_frozen_cohort import SOURCE_MANIFEST_ID,FROZEN_SYMBOL_COUNT,FROZEN_SYMBOL_SHA256,assert_frozen_cohort

EXPECTED={
    "entries":98,
    "block_entries":[16,32,22,28],
    "expectancy_r":0.10261,
    "total_r":10.05575,
}
TOL=1e-5

def _close(a,b):return a is not None and abs(float(a)-float(b))<=TOL

def main(analysis_path="output/m3_v45_analysis.json",manifest_path="frozen/m3_v451_manifest.json"):
    with open(analysis_path,encoding="utf-8") as f:a=json.load(f)
    with open(manifest_path,encoding="utf-8") as f:m=json.load(f)
    symbol_hash=assert_frozen_cohort(m.get("symbols") or [])
    perf=a.get("frozen_strategy_performance") or {}
    blocks=perf.get("block_expectancy") or []
    block_entries=[int(x.get("entries") or 0) for x in sorted(blocks,key=lambda x:int(x.get("block") or 0))]
    checks={
        "source_manifest_match":m.get("source_manifest_id")==SOURCE_MANIFEST_ID,
        "symbol_count_match":int(m.get("symbol_count") or 0)==FROZEN_SYMBOL_COUNT and int(a.get("selected_symbols") or 0)==FROZEN_SYMBOL_COUNT,
        "symbol_hash_match":symbol_hash==FROZEN_SYMBOL_SHA256 and m.get("frozen_symbol_sha256")==FROZEN_SYMBOL_SHA256,
        "entries_match":int(perf.get("entries") or 0)==EXPECTED["entries"],
        "block_entries_match":block_entries==EXPECTED["block_entries"],
        "expectancy_match":_close(perf.get("expectancy_r"),EXPECTED["expectancy_r"]),
        "total_r_match":_close(perf.get("total_r"),EXPECTED["total_r"]),
    }
    out={
        "engine":"M3 V4.5.1 Frozen Cohort Integrity",
        "pass":all(checks.values()),
        "checks":checks,
        "expected":EXPECTED,
        "observed":{"entries":perf.get("entries"),"block_entries":block_entries,"expectancy_r":perf.get("expectancy_r"),"total_r":perf.get("total_r")},
        "source_manifest_id":SOURCE_MANIFEST_ID,
        "frozen_symbol_sha256":FROZEN_SYMBOL_SHA256,
        "next_step":"V4.6 separately frozen OOS regime validation only after this gate passes",
    }
    os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,"m3_v451_integrity.json"),"w",encoding="utf-8") as f:json.dump(out,f,ensure_ascii=False,indent=2)
    with open(os.path.join(OUTPUT_DIR,"m3_v451_summary.md"),"w",encoding="utf-8") as f:
        f.write("# M3 V4.5.1 - Frozen Cohort Integrity\n\n")
        f.write("PASS\n\n" if out["pass"] else "FAIL\n\n")
        f.write(json.dumps(out,ensure_ascii=False,indent=2))
        f.write("\n")
    print(json.dumps(out,ensure_ascii=False,indent=2))
    return 0 if out["pass"] else 2

if __name__=="__main__":
    ap=sys.argv[1] if len(sys.argv)>1 else "output/m3_v45_analysis.json"
    mp=sys.argv[2] if len(sys.argv)>2 else "frozen/m3_v451_manifest.json"
    raise SystemExit(main(ap,mp))
