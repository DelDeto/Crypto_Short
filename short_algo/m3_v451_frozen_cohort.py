"""M3 V4.5.1 - immutable V4.4.1 cohort used for replication integrity."""
import hashlib,json

SOURCE_MANIFEST_ID = 'm3v441-47b0d4a3c992ea45'
SOURCE_PERIOD_START = '2026-04-08T00:00:00+00:00'
SOURCE_PERIOD_END = '2026-08-06T00:00:00+00:00'
SOURCE_FUTURE_END = '2026-08-08T00:00:00+00:00'
SOURCE_BLOCKS = [{'block': 1, 'start': '2026-04-08T00:00:00+00:00', 'end': '2026-05-08T00:00:00+00:00', 'days': 30}, {'block': 2, 'start': '2026-05-08T00:00:00+00:00', 'end': '2026-06-07T00:00:00+00:00', 'days': 30}, {'block': 3, 'start': '2026-06-07T00:00:00+00:00', 'end': '2026-07-07T00:00:00+00:00', 'days': 30}, {'block': 4, 'start': '2026-07-07T00:00:00+00:00', 'end': '2026-08-06T00:00:00+00:00', 'days': 30}]
FROZEN_SYMBOLS = ['BTC_USDT', 'ZEC_USDT', 'ETH_USDT', 'SOL_USDT', 'XRP_USDT', 'NEAR_USDT', 'TIA_USDT', 'STRK_USDT', 'QNT_USDT', 'WLD_USDT', 'SUI_USDT', 'LINK_USDT', 'TAO_USDT', 'CHIP_USDT', 'DOGE_USDT', 'ARB_USDT', 'ADA_USDT', 'PEPE_USDT', 'INJ_USDT', 'HYPE_USDT', 'AVAX_USDT', 'ENA_USDT', 'RLC_USDT', 'CFX_USDT', 'ONDO_USDT', 'AAVE_USDT', 'APT_USDT', 'PUMPFUN_USDT', 'ATOM_USDT', 'MAGIC_USDT', 'FET_USDT', 'BAT_USDT', 'HBAR_USDT', 'DOT_USDT', 'OP_USDT', 'BTW_USDT', 'UNI_USDT', 'LTC_USDT', 'BR_USDT', 'ZRO_USDT', 'LUMIA_USDT', 'DASH_USDT', 'AERO_USDT', 'XLM_USDT', 'FILECOIN_USDT', 'SEI_USDT', 'ASTER_USDT', 'SAND_USDT', 'US_USDT', 'JUP_USDT', 'ICP_USDT', 'VIRTUAL_USDT', 'FARTCOIN_USDT', 'ETHFI_USDT', 'ZKSYNC_USDT', 'LDO_USDT', 'LIT_USDT', 'ALGO_USDT', 'S_USDT', 'XPL_USDT', 'BNB_USDT', 'ANTHROPIC_USDT', 'KAIA_USDT', 'PENGU_USDT', 'SHIB_USDT', 'RAY_USDT', 'JCT_USDT', 'JASMY_USDT', 'EIGEN_USDT', 'STX_USDT', 'KAS_USDT', 'CRV_USDT', 'BCH_USDT', 'RENDER_USDT', 'JTO_USDT', 'USELESS_USDT', 'VVV_USDT', 'PONS_USDT', 'XMR_USDT', 'NEO_USDT', 'PYTH_USDT', 'NIGHT_USDT', 'SI_USDT', 'GALA_USDT', 'NIL_USDT', '1000BONK_USDT', 'FLOKI_USDT', 'TRX_USDT', 'POL_USDT', 'GRASS_USDT', 'BATON_USDT', 'XDP_USDT', 'WIF_USDT', 'ORDI_USDT', 'CAP_USDT', 'GRAM_USDT', 'TRUMPOFFICIAL_USDT', 'APE_USDT', 'MINA_USDT', 'AKE_USDT', 'TESLA_USDT', 'AXS_USDT', 'ETC_USDT', 'W_USDT', 'AR_USDT', 'A_USDT', 'IMX_USDT', 'MONAD_USDT', 'MET_USDT', 'LUNC_USDT', 'SYN_USDT', 'LAB_USDT', 'WLFI_USDT', 'ERA_USDT', 'ENS_USDT', 'BEAT_USDT', 'CAKE_USDT', 'FLOW_USDT', 'VET_USDT', 'PI_USDT']
FROZEN_SYMBOL_COUNT = 120
FROZEN_SYMBOL_SHA256 = 'd13a7d408d4cbd777a3fb84001f2edf1d44bd611e466e96d116e8be6a63a9316'

def symbols_sha256(symbols):
    return hashlib.sha256(json.dumps(list(symbols),separators=(",",":")).encode()).hexdigest()

def assert_frozen_cohort(symbols):
    xs=list(symbols)
    if len(xs) != FROZEN_SYMBOL_COUNT:
        raise RuntimeError(f"Frozen cohort count mismatch: {len(xs)} != {FROZEN_SYMBOL_COUNT}")
    got=symbols_sha256(xs)
    if got != FROZEN_SYMBOL_SHA256:
        raise RuntimeError(f"Frozen cohort hash mismatch: {got} != {FROZEN_SYMBOL_SHA256}")
    return got
