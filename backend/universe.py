"""
Universe loader — the single source of truth for which tickers to scan.

Priority order:
  1. Dynamic cache (universe_cache.json) — built weekly by universe_builder.py
  2. Static fallback list below — used only on first deployment before any
     universe refresh has run

Both main.py and scanner.py import from this file:
  - main.py uses get_universe() for the /scan endpoint and /status
  - scanner.py uses UNIVERSE as the default when tickers=None

Compatible with Python 3.9+.
"""

import logging
from universe_engine import load_cached_universe

logger = logging.getLogger(__name__)

# ── Static fallback universe ──────────────────────────────────────────────────
# Used only when universe_cache.json does not exist or is corrupted.
# This list was the original hand-curated set of ~473 liquid US names.
# Once the first weekly universe refresh completes, this list is never used
# again unless the cache file is deleted.

STATIC_UNIVERSE = [
    "AAPL", "ABBV", "ABNB", "ABT", "ACHR", "ACN", "ADBE", "ADI", "ADM",
    "ADP", "ADSK", "AEM", "AES", "AFL", "AFRM", "AG", "AGCO", "AGI",
    "AGIO", "AIG", "ALAB", "ALB", "ALC", "ALGN", "ALIT", "ALL", "AMAT",
    "AMD", "AMGN", "AMP", "AMZN", "ANET", "ANSS", "APA", "APD", "APH",
    "APLS", "APLT", "APP", "APPS", "APTV", "AR", "ARCC", "ARE", "ARES",
    "ARKK", "ARM", "ARQT", "ASPN", "ASRT", "AVGO", "AVTR", "AVY", "AXP",
    "BA", "BABA", "BAC", "BAX", "BBAI", "BBWI", "BCS", "BDX", "BE",
    "BEKE", "BG", "BGRY", "BIDU", "BIIB", "BJ", "BK", "BKNG", "BKR",
    "BLDR", "BLK", "BMO", "BMY", "BN", "BNS", "BOX", "BP", "BRKB",
    "BSX", "BTU", "BUD", "BURL", "BWA", "BX", "BXP", "C", "CAH",
    "CARR", "CAT", "CB", "CCI", "CCJ", "CCL", "CDAY", "CDNS", "CE",
    "CEG", "CF", "CFG", "CFLT", "CG", "CHPT", "CHRW", "CI", "CL",
    "CLF", "CLX", "CM", "CMA", "CMCSA", "CME", "CMG", "CMI", "CMS",
    "CNC", "CNP", "COIN", "COP", "COST", "CPAY", "CPNG", "CPRT", "CRM",
    "CRSP", "CRWD", "CSCO", "CSGP", "CTAS", "CTLT", "CTSH", "CTVA",
    "CVE", "CVNA", "CVS", "CVX", "CZR", "D", "DAL", "DASH", "DDOG",
    "DE", "DELL", "DFS", "DG", "DHI", "DHR", "DIA", "DIS", "DKNG",
    "DLR", "DLTR", "DOCS", "DOW", "DRVN", "DT", "DTE", "DUK", "DVN",
    "DXCM", "EA", "EBAY", "ECL", "ED", "EEM", "EFA", "EL", "EMB",
    "EMR", "ENPH", "ENR", "EOG", "EPAM", "EPD", "EQIX", "EQR", "EQT",
    "ERIE", "ES", "ESS", "ET", "ETN", "ETSY", "EW", "EWJ", "EWZ",
    "EXAS", "EXC", "EXPD", "EXPE", "F", "FANG", "FAST", "FCEL", "FCX",
    "FDX", "FE", "FERG", "FFIV", "FIS", "FISV", "FITB", "FIVE", "FL",
    "FLR", "FLUT", "FMC", "FSLR", "FTNT", "FUBO", "FUTU", "FXI",
    "GBTC", "GD", "GDDY", "GDX", "GDXJ", "GE", "GEHC", "GERN", "GEV",
    "GFS", "GILD", "GIS", "GL", "GLW", "GM", "GNRC", "GOLD", "GOOGL",
    "GPC", "GPN", "GRAB", "GRMN", "GS", "GWW", "HAL", "HAS", "HBAN",
    "HCA", "HD", "HES", "HIG", "HIMS", "HLT", "HON", "HOOD", "HPE",
    "HPQ", "HST", "HSY", "HUM", "HWM", "HYG", "IBKR", "IBM", "IBN",
    "ICE", "ICLR", "IDXX", "IEF", "IEFA", "IEMG", "IFGL", "IGV",
    "INCY", "INTC", "INTU", "INVH", "IONQ", "IP", "IPG", "IQV", "IR",
    "ISRG", "IT", "ITES", "ITW", "IVV", "IWM", "IYR", "JAZZ", "JBL",
    "JBLU", "JCI", "JD", "JNJ", "JNPR", "JPM", "JWN", "KDP", "KEY",
    "KGC", "KHC", "KIM", "KLAC", "KMB", "KMI", "KO", "KR", "KRE",
    "KVUE", "KWEB", "LABU", "LEN", "LIN", "LLY", "LMT", "LNTH", "LOW",
    "LPLA", "LRCX", "LSCC", "LULU", "LUV", "LVS", "LW", "LYB", "LYV",
    "MA", "MAA", "MAR", "MARA", "MCD", "MCHP", "MCK", "MCO", "MDLZ",
    "MDT", "MDY", "MELI", "MET", "META", "MGM", "MKC", "MKTX", "MLM",
    "MMC", "MMM", "MNST", "MO", "MOH", "MPLX", "MPC", "MPW", "MRK",
    "MRNA", "MRVL", "MS", "MSCI", "MSFT", "MSI", "MSTR", "MT", "MTB",
    "MTCH", "MTG", "MU", "NCLH", "NDAQ", "NDSN", "NEM", "NET", "NFLX",
    "NI", "NIO", "NKE", "NLOK", "NOC", "NOW", "NRG", "NSC", "NTAP",
    "NTES", "NTNX", "NU", "NUE", "NVDA", "NVST", "NVO", "NXPI", "O",
    "ODFL", "OIH", "OKE", "OMC", "ON", "ORCL", "ORI", "OTIS", "OXY",
    "PANW", "PARA", "PATH", "PAYC", "PAYX", "PBR", "PCAR", "PCG",
    "PDD", "PEAK", "PEG", "PEP", "PFE", "PG", "PGR", "PH", "PHM",
    "PINS", "PLD", "PLTR", "PM", "PNC", "PNR", "POOL", "PPG", "PPL",
    "PSTG", "PSX", "PXD", "PYPL", "QCOM", "QQQ", "RBLX", "RCL",
    "REGN", "RF", "RGEN", "RIG", "RIOT", "RIVN", "RKT", "RL", "ROKU",
    "ROK", "ROL", "ROP", "ROST", "RPM", "RSP", "RTX", "RUN", "RVTY",
    "RY", "S", "SAIA", "SBUX", "SCHW", "SE", "SEDG", "SHOP", "SHW",
    "SHY", "SI", "SIRI", "SLB", "SLV", "SMCI", "SMH", "SN", "SNAP",
    "SNPS", "SNY", "SO", "SOFI", "SOXX", "SPGI", "SPOT", "SPY",
    "SQ", "SRE", "SSNC", "STAG", "STLA", "STM", "STNE", "STNG",
    "STX", "STZ", "SU", "SUI", "SWK", "SWKS", "SYF", "SYK", "SYY",
    "T", "TAL", "TBT", "TD", "TDG", "TDOC", "TEAM", "TECK", "TER",
    "TFC", "TGT", "TJX", "TLT", "TMO", "TMUS", "TPR", "TRGP", "TRIP",
    "TRMB", "TSLA", "TSM", "TSN", "TT", "TTD", "TTWO", "TUR", "TWLO",
    "TXN", "TXT", "U", "UAL", "UBER", "UNH", "UNP", "UPS", "URI",
    "USB", "V", "VALE", "VFC", "VICI", "VLO", "VMC", "VMW", "VNDA",
    "VNO", "VRSN", "VRSK", "VRTX", "VST", "VTR", "VZ", "W", "WAB",
    "WAT", "WBA", "WBD", "WDAY", "WDC", "WELL", "WFC", "WHR", "WM",
    "WMB", "WMT", "WPM", "WST", "WY", "WYNN", "X", "XBI", "XHB",
    "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV",
    "XLY", "XME", "XMTR", "XOM", "XOP", "XP", "XPEV", "XRT", "XSP",
    "XTLA", "YUM", "Z", "ZBH", "ZBRA", "ZIM", "ZION", "ZM", "ZS", "ZTO",
]


def get_universe():
    """
    Return the current scan universe.

    Tries the dynamic cache first (built weekly by universe_builder.py).
    Falls back to the static list if no cache exists or cache is empty.
    """
    cached = load_cached_universe()
    if cached:
        logger.info(f"Universe loaded from cache: {len(cached)} tickers")
        return cached

    logger.info(f"No universe cache found — using static fallback: {len(STATIC_UNIVERSE)} tickers")
    return STATIC_UNIVERSE


# Backward compatibility: scanner.py imports UNIVERSE directly as a fallback
UNIVERSE = STATIC_UNIVERSE
