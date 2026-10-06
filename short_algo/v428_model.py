"""Separated V4.2.8 trend/reversal/confirmed-entry models."""

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier


TREND_FEATURE_NAMES = [
    "candidate_context_points",
    "return_1h_pct","return_3h_pct","return_4h_pct","return_12h_pct","return_24h_pct",
    "relative_1h_pct","relative_3h_pct","relative_4h_pct","relative_24h_pct",
    "ema20_distance_atr","range_position_12h","range_position_24h","range_position_48h",
    "distance_12h_low_atr","distance_24h_low_atr","distance_12h_high_atr",
    "atr_pct_1h","volume_ratio_1h",
    "s1_ema_bear","s1_lower_high","s1_lower_low",
    "s4_ema_bear","s4_lower_high","s4_lower_low","s4_macro_bear",
    "breakdown_detected","breakdown_retest","breakdown_age_1h","breakdown_distance_atr",
    "sweep_detected","sweep_age_1h","bearish_rejection",
    "continuation_quality","continuation_ready","break_departure_atr","break_body_atr",
    "break_volume_ratio","retest_touched","retest_rejection","reclaim_seen",
    "acceptance_bars","rebound_from_break_low_atr",
    "anti_bottom_total","squeeze_risk",
    "market_r4_pct","market_r24_pct","market_risk_on","market_risk_off",
    "market_bull","market_bear",
    "coin_return_1h_pct","coin_return_3h_pct",
    "relative_recovery_1h_pct","relative_recovery_3h_pct",
    "xs_weak_rank_4h","xs_weak_rank_12h","xs_weak_rank_24h",
    "xs_relative_weak_rank_4h","xs_relative_weak_rank_24h",
    "xs_weak_consistency","xs_weak_average",
    "v428_structure_score","v428_exhaustion_score","v428_recovery_score",
    "v428_phase_early","v428_phase_mature",
    "v428_phase_exhausted","v428_phase_recovery",
]

REVERSAL_FEATURE_NAMES = TREND_FEATURE_NAMES + [
    "distance_12h_low_atr","distance_24h_low_atr",
    "support_distance_atr",
]

ENTRY_FEATURE_NAMES = [
    "zone_distance_atr","support_distance_atr","supply_distance_atr",
    "atr_pct_1h","volume_ratio_1h",
    "bearish_rejection","continuation_quality","continuation_ready",
    "break_departure_atr","break_body_atr","break_volume_ratio",
    "retest_touched","retest_rejection","reclaim_seen","acceptance_bars",
    "anti_bottom_total","squeeze_risk",
    "zone_supply_1h","zone_supply_4h","zone_broken_support","zone_sweep_retest",
    "v428_entry_zone_distance_atr","v428_confirm_support_room_r",
    "v428_strong_zone","v428_zone_touched_recent",
    "v428_bearish_rejection_now","v428_no_reclaim_after_touch",
    "v428_micro_turn_down","v428_close_below_zone_mid",
    "v428_entry_confirm_score","v428_confirmation_below_zone_atr",
]


def _matrix(rows,names):
    out=[]
    for row in rows:
        vals=[]
        for name in names:
            try:
                v=float(row.get(name))
                vals.append(v if np.isfinite(v) else np.nan)
            except (TypeError,ValueError):
                vals.append(np.nan)
        out.append(vals)
    return np.asarray(out,dtype=float)


def fit_model(rows,target_key,feature_names,cfg):
    usable=[r for r in rows if r.get(target_key) is not None]
    if not usable:
        return {
            "type":"constant","probability":0.5,"base_rate":0.5,
            "train_n":0,"target":target_key,"feature_names":feature_names,
        }
    y=np.asarray([1 if bool(r[target_key]) else 0 for r in usable],dtype=int)
    base=float(np.mean(y))
    if len(usable)<50 or np.unique(y).size<2:
        return {
            "type":"constant","probability":base,"base_rate":base,
            "train_n":len(usable),"target":target_key,"feature_names":feature_names,
        }
    model=HistGradientBoostingClassifier(
        learning_rate=cfg["learning_rate"],
        max_iter=cfg["max_iter"],
        max_leaf_nodes=cfg["max_leaf_nodes"],
        min_samples_leaf=cfg["min_samples_leaf"],
        l2_regularization=cfg["l2"],
        random_state=42,
    )
    model.fit(_matrix(usable,feature_names),y)
    return {
        "type":"hgb","model":model,"base_rate":base,
        "train_n":len(usable),"target":target_key,
        "feature_names":feature_names,
    }


def predict_model(model,rows):
    if not rows:
        return []
    if model.get("type")=="constant":
        return [float(model.get("probability",0.5))]*len(rows)
    return model["model"].predict_proba(
        _matrix(rows,model["feature_names"])
    )[:,1].tolist()
