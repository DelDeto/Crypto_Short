"""Non-linear walk-forward model for V4.2.6."""

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier


FEATURE_NAMES = [
    "candidate_context_points",
    "return_1h_pct","return_3h_pct","return_4h_pct","return_12h_pct","return_24h_pct",
    "relative_1h_pct","relative_3h_pct","relative_4h_pct","relative_24h_pct",
    "ema20_distance_atr","range_position_12h","range_position_24h","range_position_48h",
    "distance_12h_low_atr","distance_24h_low_atr","distance_12h_high_atr",
    "support_distance_atr","supply_distance_atr","zone_distance_atr",
    "atr_pct_1h","volume_ratio_1h",
    "s1_ema_bear","s1_lower_high","s1_lower_low",
    "s4_ema_bear","s4_lower_high","s4_lower_low","s4_macro_bear",
    "breakdown_detected","breakdown_retest","breakdown_age_1h","breakdown_distance_atr",
    "sweep_detected","sweep_age_1h","bearish_rejection",
    "continuation_quality","continuation_ready","break_departure_atr","break_body_atr",
    "break_volume_ratio","retest_touched","retest_rejection","reclaim_seen",
    "acceptance_bars","rebound_from_break_low_atr","anti_bottom_total","squeeze_risk",
    "market_r4_pct","market_r24_pct","market_risk_on","market_risk_off",
    "market_bull","market_bear",
    "zone_supply_1h","zone_supply_4h","zone_broken_support","zone_sweep_retest",
    "v426_entry_zone_distance_atr","v426_support_room_r",
    "v426_rr2_room_ok","v426_strong_zone",
]


def _matrix(rows):
    data = []
    for row in rows:
        values = []
        for name in FEATURE_NAMES:
            try:
                v = float(row.get(name))
                values.append(v if np.isfinite(v) else np.nan)
            except (TypeError, ValueError):
                values.append(np.nan)
        data.append(values)
    return np.asarray(data, dtype=float)


def fit_model(rows, target_key, cfg):
    usable = [r for r in rows if r.get(target_key) is not None]
    if not usable:
        return {"type":"constant","probability":0.5,"train_n":0,"target":target_key}

    y = np.asarray([1 if bool(r[target_key]) else 0 for r in usable], dtype=int)
    base = float(np.mean(y))
    if len(usable) < 50 or np.unique(y).size < 2:
        return {
            "type":"constant","probability":base,
            "train_n":len(usable),"target":target_key,
            "base_rate":base,
        }

    model = HistGradientBoostingClassifier(
        learning_rate=cfg["learning_rate"],
        max_iter=cfg["max_iter"],
        max_leaf_nodes=cfg["max_leaf_nodes"],
        min_samples_leaf=cfg["min_samples_leaf"],
        l2_regularization=cfg["l2"],
        random_state=42,
    )
    model.fit(_matrix(usable), y)
    return {
        "type":"hgb",
        "model":model,
        "train_n":len(usable),
        "target":target_key,
        "base_rate":base,
    }


def predict_model(model, rows):
    if not rows:
        return []
    if model.get("type") == "constant":
        return [float(model.get("probability",0.5))] * len(rows)
    return model["model"].predict_proba(_matrix(rows))[:,1].tolist()
