# ============================================================
#  US LARGE-CAP LIVE TRACKER — Clean Restore
#  - Yahoo Finance for live data, EDGAR for filings
#  - 5-min refresh (gentle on Yahoo, more reliable)
#  - ALWAYS shows numbers — never blank
#  - NEVER white screen — old data stays visible during refresh
# ============================================================

import streamlit as st
import yfinance as yf
import pandas as pd
import requests
from datetime import datetime, date, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

# Timezone helpers
IST = timezone(timedelta(hours=5, minutes=30))
# US Eastern auto-handles daylight saving via standard library
try:
    from zoneinfo import ZoneInfo
    US_EAST = ZoneInfo("America/New_York")
except ImportError:
    US_EAST = timezone(timedelta(hours=-5))  # fallback to EST

st.set_page_config(
    page_title="US Large-Cap Tracker",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ════════════════════════════════════════════════════════════
#  AUTH
# ════════════════════════════════════════════════════════════
DEFAULT_PASSWORD = "change-me"
DEFAULT_ADMIN_PASSWORD = "admin-change-me"

def get_password():
    try: return st.secrets["APP_PASSWORD"]
    except (KeyError, FileNotFoundError): return DEFAULT_PASSWORD

def get_admin_password():
    try: return st.secrets["ADMIN_PASSWORD"]
    except (KeyError, FileNotFoundError): return DEFAULT_ADMIN_PASSWORD

def check_password():
    if st.session_state.get("authenticated"):
        return True
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap');
    .stApp { background: #ffffff; font-family: 'Roboto', sans-serif; }
    #MainMenu, footer, header {visibility: hidden;}
    .login-card {
        max-width: 380px; margin: 8vh auto 0; padding: 2.5rem 2rem;
        background: #ffffff; border: 1px solid #dadce0; border-radius: 8px;
        text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    }
    .login-icon { font-size: 2.5rem; margin-bottom: 0.8rem; }
    .login-title { font-size: 1.4rem; font-weight: 500; color: #202124; margin-bottom: 0.3rem; }
    .login-sub { font-size: 0.85rem; color: #5f6368; margin-bottom: 1.5rem; }
    .stTextInput > div > div > input { font-size: 0.95rem !important; padding: 0.6rem 0.8rem !important; }
    .stButton > button {
        width: 100%; background: #1a73e8; color: #ffffff;
        border: 1px solid #1a73e8; padding: 0.55rem; font-weight: 500;
        margin-top: 0.5rem;
    }
    .stButton > button:hover { background: #1557b0; }
    </style>
    """, unsafe_allow_html=True)
    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        st.markdown(
            '<div class="login-card">'
            '<div class="login-icon">🔒</div>'
            '<div class="login-title">US Large-Cap Tracker</div>'
            '<div class="login-sub">Enter the password to continue</div>'
            '</div>',
            unsafe_allow_html=True
        )
        pw = st.text_input("Password", type="password", label_visibility="collapsed",
                           placeholder="Password", key="pw_input")
        if st.button("Sign in", use_container_width=True, key="login_btn"):
            if pw == get_password():
                st.session_state.authenticated = True; st.rerun()
            elif pw == get_admin_password():
                st.session_state.authenticated = True
                st.session_state.is_admin = True; st.rerun()
            else:
                st.error("Incorrect password.")
    return False

if not check_password():
    st.stop()

# ════════════════════════════════════════════════════════════
#  SETTINGS
# ════════════════════════════════════════════════════════════
REFRESH_SECONDS = 300   # 5 minutes
PARALLEL_WORKERS = 8
NEW_FILING_WINDOW_DAYS = 14

if "visible_cols" not in st.session_state:
    st.session_state.visible_cols = {
        "Price ($)": True, "Day Chg %": True, "Market Cap ($B)": True,
        "EPS TTM ($)": True, "P/E TTM": True,
        "52W High ($)": True, "52W Low ($)": True,
        "Quarter": True, "Period End": False, "Filed Date": False,
        "Revenue ($M)": True, "PAT ($M)": True, "EBITDA ($M)": True,
        "Bloomberg Code": True, "10-Q Filing": True,
    }

# ════════════════════════════════════════════════════════════
#  CSS
# ════════════════════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap');
.stApp { background: #ffffff; color: #202124; font-family: 'Roboto', Arial, sans-serif; }
.main .block-container { padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1700px; }
#MainMenu, footer, header {visibility: hidden;}

h1 {
    font-family: 'Roboto', sans-serif !important; font-weight: 500 !important;
    font-size: 1.6rem !important; color: #202124 !important;
    margin-bottom: 0.2rem !important; letter-spacing: -0.01em !important;
}
.sheet-meta {
    font-family: 'Roboto', sans-serif; font-size: 0.82rem;
    color: #5f6368; padding-bottom: 0.8rem;
    border-bottom: 1px solid #e0e0e0; margin-bottom: 1rem;
}
.sheet-meta .accent { color: #1a73e8; font-weight: 500; }
.sheet-meta .admin-badge {
    background: #fef7e0; color: #b06000; border: 1px solid #f9ab00;
    padding: 1px 8px; border-radius: 10px; font-size: 0.72rem;
    font-weight: 500; margin-left: 6px;
}
.sheet-meta .live-dot {
    display: inline-block; width: 7px; height: 7px; border-radius: 50%;
    background: #34a853; margin-right: 5px;
    animation: pulse 1.6s ease-in-out infinite;
}
.sheet-meta .updating {
    display: inline-block;
    background: rgba(26, 115, 232, 0.1); color: #1a73e8;
    padding: 1px 8px; border-radius: 10px;
    font-size: 0.72rem; margin-left: 6px;
    animation: pulse 1.6s ease-in-out infinite;
}
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
h2, h3 {
    font-family: 'Roboto', sans-serif !important;
    color: #202124 !important; font-weight: 500 !important;
}
h3 {
    font-size: 0.95rem !important; color: #5f6368 !important;
    text-transform: none !important; letter-spacing: 0 !important;
    margin-top: 0.8rem !important;
}
[data-testid="stMetric"] {
    background: #f8f9fa; border: 1px solid #e0e0e0;
    border-radius: 6px; padding: 0.7rem 0.9rem;
}
[data-testid="stMetricLabel"] {
    font-size: 0.75rem !important; color: #5f6368 !important; font-weight: 400 !important;
}
[data-testid="stMetricValue"] {
    font-family: 'Roboto', sans-serif !important; font-weight: 500 !important;
    color: #202124 !important; font-size: 1.4rem !important;
}
hr { border-color: #e0e0e0 !important; margin: 1rem 0 !important; }
[data-testid="stDataFrame"] { border: 1px solid #e0e0e0; border-radius: 4px; }

.stButton > button {
    background: #ffffff; color: #1a73e8; border: 1px solid #dadce0;
    font-family: 'Roboto', sans-serif; font-size: 0.85rem;
    font-weight: 500; border-radius: 4px; padding: 0.4rem 1rem; text-transform: none;
}
.stButton > button:hover { background: #f8f9fa; border-color: #1a73e8; }

.stDownloadButton > button {
    background: #1a73e8; color: #ffffff; border: 1px solid #1a73e8;
    font-family: 'Roboto', sans-serif; font-size: 0.85rem;
    font-weight: 500; border-radius: 4px; padding: 0.4rem 1rem; text-transform: none;
}
.stDownloadButton > button:hover { background: #1557b0; }

.stTextInput > div > div > input {
    background: #ffffff; border: 1px solid #dadce0;
    color: #202124; font-family: 'Roboto', sans-serif;
    border-radius: 4px; font-size: 0.9rem;
}
.stTextInput > div > div > input:focus {
    border-color: #1a73e8; box-shadow: 0 0 0 1px #1a73e8;
}
.stCaption, [data-testid="stCaptionContainer"] {
    color: #5f6368 !important; font-family: 'Roboto', sans-serif !important; font-size: 0.78rem !important;
}
.new-banner {
    background: #fef7e0; border: 1px solid #f9ab00;
    border-left: 4px solid #f9ab00; border-radius: 4px;
    padding: 10px 14px; margin: 14px 0;
    font-family: 'Roboto', sans-serif; font-size: 0.85rem; color: #3c4043;
}
.new-banner .head { color: #b06000; font-weight: 500; display: block; margin-bottom: 4px; }
.new-banner .ticker-chip {
    display: inline-block; background: #ffffff;
    border: 1px solid #f9ab00; color: #b06000;
    padding: 2px 8px; margin: 2px 3px 2px 0;
    border-radius: 12px; font-weight: 500; font-size: 0.78rem;
}
.first-load-msg {
    text-align: center; padding: 4rem 1rem; color: #5f6368;
    font-size: 1rem; font-family: 'Roboto', sans-serif;
}
</style>
""", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════
#  COMPANIES
# ════════════════════════════════════════════════════════════
COMPANIES = {
    "MMM": ("3M Company", 66740), "ABT": ("Abbott Laboratories", 1800),
    "ABBV": ("AbbVie Inc.", 1551152), "GLTR": ("abrdn Physical Precious Metals ETF", None),
    "ACN": ("Accenture plc", 1467373), "ADBE": ("Adobe Inc.", 796343),
    "AMD": ("Advanced Micro Devices", 2488), "GOOGL": ("Alphabet Inc. (A)", 1652044),
    "GOOG": ("Alphabet Inc. (C)", 1652044), "AMZN": ("Amazon.com Inc.", 1018724),
    "AXP": ("American Express", 4962), "AIG": ("American International Group", 5272),
    "AAPL": ("Apple Inc.", 320193), "AMAT": ("Applied Materials", 6951),
    "ASML": ("ASML Holding NV", 937966), "T": ("AT&T Inc.", 732717),
    "BAC": ("Bank of America", 70858), "BRK-B": ("Berkshire Hathaway (B)", 1067983),
    "BLK": ("BlackRock Inc.", 1364742), "BA": ("Boeing Company", 12927),
    "BMY": ("Bristol-Myers Squibb", 14272), "AVGO": ("Broadcom Inc.", 1730168),
    "COF": ("Capital One Financial", 927628), "CAT": ("Caterpillar Inc.", 18230),
    "SCHW": ("Charles Schwab", 316709), "CVX": ("Chevron Corporation", 93410),
    "CI": ("Cigna Group", 1739940), "CSCO": ("Cisco Systems", 858877),
    "C": ("Citigroup Inc.", 831001), "CME": ("CME Group", 1156375),
    "KO": ("Coca-Cola Company", 21344), "CL": ("Colgate-Palmolive", 21665),
    "CMCSA": ("Comcast Corporation", 1166691), "COP": ("ConocoPhillips", 1163165),
    "COST": ("Costco Wholesale", 909832), "CRSP": ("CRISPR Therapeutics AG", 1674416),
    "CVS": ("CVS Health", 64803), "DHR": ("Danaher Corporation", 313616),
    "DE": ("Deere & Company", 315189), "DELL": ("Dell Technologies", 1571996),
    "DUK": ("Duke Energy", 1326160), "EW": ("Edwards Lifesciences", 1099800),
    "ELV": ("Elevance Health", 1156039), "EMR": ("Emerson Electric", 32604),
    "EOG": ("EOG Resources", 821189), "XOM": ("Exxon Mobil", 34088),
    "F": ("Ford Motor Company", 37996), "GD": ("General Dynamics", 40533),
    "GE": ("General Electric / GE Aerospace", 40545), "GS": ("Goldman Sachs", 886982),
    "HON": ("Honeywell International", 773840), "IBM": ("IBM Corporation", 51143),
    "ITW": ("Illinois Tool Works", 49826), "INTC": ("Intel Corporation", 50863),
    "ISRG": ("Intuitive Surgical", 1035267), "JNJ": ("Johnson & Johnson", 200406),
    "JPM": ("JPMorgan Chase", 19617), "KHC": ("Kraft Heinz Company", 1637459),
    "LIN": ("Linde plc", 1707925), "LMT": ("Lockheed Martin", 936468),
    "LOW": ("Lowe's Companies", 60667), "MAR": ("Marriott International", 1048286),
    "MA": ("Mastercard Inc.", 1141391), "MCD": ("McDonald's Corporation", 63908),
    "MDT": ("Medtronic plc", 1613103), "MRK": ("Merck & Co.", 310158),
    "META": ("Meta Platforms", 1326801), "MSFT": ("Microsoft Corporation", 789019),
    "MDLZ": ("Mondelez International", 1103982), "MS": ("Morgan Stanley", 895421),
    "NFLX": ("Netflix Inc.", 1065280), "NEE": ("NextEra Energy", 753308),
    "NKE": ("Nike Inc.", 320187), "NOC": ("Northrop Grumman", 1133421),
    "NVDA": ("NVIDIA Corporation", 1045810), "ORCL": ("Oracle Corporation", 1341439),
    "PANW": ("Palo Alto Networks", 1327567), "PYPL": ("PayPal Holdings", 1633917),
    "PEP": ("PepsiCo Inc.", 77476), "PFE": ("Pfizer Inc.", 78003),
    "PM": ("Philip Morris International", 1413329), "PSX": ("Phillips 66", 1534701),
    "PG": ("Procter & Gamble", 80424), "QCOM": ("Qualcomm Inc.", 804328),
    "RTX": ("RTX Corporation / Raytheon", 101829), "HOOD": ("Robinhood Markets", 1783879),
    "SPGI": ("S&P Global Inc.", 64040), "CRM": ("Salesforce Inc.", 1108524),
    "SPG": ("Simon Property Group", 1063761), "SO": ("Southern Company", 92122),
    "SBUX": ("Starbucks Corporation", 829224), "TMUS": ("T-Mobile US", 1283699),
    "TGT": ("Target Corporation", 27419), "TSLA": ("Tesla Inc.", 1318605),
    "TXN": ("Texas Instruments", 97210), "HD": ("The Home Depot", 354950),
    "PGR": ("The Progressive Corporation", 80661), "TMO": ("Thermo Fisher Scientific", 97745),
    "UNP": ("Union Pacific", 100885), "UPS": ("United Parcel Service", 1090727),
    "UNH": ("UnitedHealth Group", 731766), "VZ": ("Verizon Communications", 732712),
    "V": ("Visa Inc.", 1403161), "WMT": ("Walmart Inc.", 104169),
    "DIS": ("Walt Disney Company", 1744489), "WFC": ("Wells Fargo", 72971),
}

# ════════════════════════════════════════════════════════════
#  HELPERS
# ════════════════════════════════════════════════════════════
def safe(value, decimals=2):
    try:
        if value is None or pd.isna(value): return None
        return round(float(value), decimals)
    except (TypeError, ValueError): return None

def to_millions(value):
    try:
        if value is None or pd.isna(value): return None
        return round(float(value) / 1_000_000, 1)
    except (TypeError, ValueError): return None

def to_billions(value):
    try:
        if value is None or pd.isna(value): return None
        return round(float(value) / 1_000_000_000, 2)
    except (TypeError, ValueError): return None

def bloomberg_code(ticker):
    return f"{ticker.replace('-', '/')} US Equity"

# ════════════════════════════════════════════════════════════
#  EDGAR
# ════════════════════════════════════════════════════════════
EDGAR_HEADERS = {
    "User-Agent": "USLargeCap Dashboard research@example.com",
    "Accept-Encoding": "gzip, deflate",
}
REV_CONCEPTS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
    "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax",
    "InterestAndDividendIncomeOperating",
]
NI_CONCEPTS = ["NetIncomeLoss", "ProfitLoss"]

@st.cache_data(ttl=21600, show_spinner=False)
def fetch_edgar(cik):
    empty = {"rev": None, "pat": None, "qtr_label": None,
             "filing_url": None, "period_end": None, "filed": None}
    if cik is None: return empty
    try:
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{str(cik).zfill(10)}.json"
        r = requests.get(url, headers=EDGAR_HEADERS, timeout=15)
        if r.status_code != 200: return empty
        facts = r.json()
    except Exception: return empty

    def latest(concepts):
        best = None
        for c in concepts:
            node = facts.get("facts", {}).get("us-gaap", {}).get(c)
            if not node: continue
            units = node.get("units", {}).get("USD")
            if not units: continue
            for u in units:
                if u.get("form") not in ["10-Q", "10-K"]: continue
                if "end" not in u or "start" not in u: continue
                try:
                    s = date.fromisoformat(u["start"])
                    e = date.fromisoformat(u["end"])
                    days = (e - s).days
                    if not (80 <= days <= 100): continue
                    if best is None or u["end"] > best["end"]:
                        best = u
                except Exception: continue
        return best

    rev = latest(REV_CONCEPTS); ni = latest(NI_CONCEPTS)
    primary = ni or rev
    if primary is None: return empty
    qtr_label = f"{primary.get('fp', '?')} {primary.get('fy', '?')}"
    accn = primary.get("accn", "")
    accn_clean = accn.replace("-", "")
    filing_url = (f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn_clean}/{accn}-index.htm"
                  if accn_clean else
                  f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=10-Q")
    return {
        "rev": to_millions(rev["val"]) if rev else None,
        "pat": to_millions(ni["val"]) if ni else None,
        "qtr_label": qtr_label, "filing_url": filing_url,
        "period_end": primary.get("end"), "filed": primary.get("filed"),
    }

# ════════════════════════════════════════════════════════════
#  FINNHUB FALLBACK — only used when Yahoo returns blanks
# ════════════════════════════════════════════════════════════
def get_finnhub_key():
    try: return st.secrets["FINNHUB_API_KEY"]
    except (KeyError, FileNotFoundError): return None

FINNHUB_KEY = get_finnhub_key()

def fetch_finnhub_metrics(symbol):
    """Fetch P/E, EPS, Market Cap, 52W from Finnhub. Returns dict with what worked."""
    out = {"pe": None, "eps": None, "market_cap": None, "hi_52": None, "lo_52": None}
    if not FINNHUB_KEY:
        return out
    fh_sym = symbol
    if symbol == "BRK-B": fh_sym = "BRK.B"
    elif symbol == "GLTR": return out
    try:
        bf = requests.get(
            "https://finnhub.io/api/v1/stock/metric",
            params={"symbol": fh_sym, "metric": "all", "token": FINNHUB_KEY},
            timeout=8,
        ).json()
        m = bf.get("metric", {}) or {}
        out["pe"]  = safe(m.get("peTTM") or m.get("peNormalizedAnnual"))
        out["eps"] = safe(m.get("epsTTM") or m.get("epsBasicExclExtraItemsTTM"))
        mc_mn = m.get("marketCapitalization")
        if mc_mn: out["market_cap"] = round(float(mc_mn) / 1000, 2)  # mn → bn
        out["hi_52"] = safe(m.get("52WeekHigh"))
        out["lo_52"] = safe(m.get("52WeekLow"))
    except Exception:
        pass
    return out

# ════════════════════════════════════════════════════════════
#  YAHOO (with fallbacks)
# ════════════════════════════════════════════════════════════
def fetch_yahoo(symbol):
    out = {"price": None, "day_chg": None, "market_cap": None,
           "eps": None, "pe": None, "hi_52": None, "lo_52": None, "ebitda": None}
    try:
        t = yf.Ticker(symbol)

        # fast_info first (cheap & reliable)
        try:
            fi = t.fast_info
            price = fi.get("last_price") if hasattr(fi, "get") else None
            prev = fi.get("previous_close") if hasattr(fi, "get") else None
            mc = fi.get("market_cap") if hasattr(fi, "get") else None
            hi = fi.get("year_high") if hasattr(fi, "get") else None
            lo = fi.get("year_low") if hasattr(fi, "get") else None
            if price: out["price"] = safe(price)
            if price and prev and prev != 0:
                out["day_chg"] = round(((price - prev) / prev) * 100, 2)
            if mc: out["market_cap"] = to_billions(mc)
            if hi: out["hi_52"] = safe(hi)
            if lo: out["lo_52"] = safe(lo)
        except Exception:
            pass

        # history() fallback if price still missing
        if out["price"] is None:
            try:
                hist = t.history(period="2d", auto_adjust=False)
                if hist is not None and len(hist) > 0:
                    out["price"] = safe(float(hist["Close"].iloc[-1]))
                    if len(hist) >= 2:
                        prev = float(hist["Close"].iloc[-2])
                        if prev != 0:
                            out["day_chg"] = round(
                                ((out["price"] - prev) / prev) * 100, 2)
            except Exception:
                pass

        # info for EPS/PE (often blocked on cloud but worth trying)
        try:
            info = t.info or {}
            if out["market_cap"] is None: out["market_cap"] = to_billions(info.get("marketCap"))
            if out["hi_52"] is None: out["hi_52"] = safe(info.get("fiftyTwoWeekHigh"))
            if out["lo_52"] is None: out["lo_52"] = safe(info.get("fiftyTwoWeekLow"))
            out["eps"] = safe(info.get("trailingEps"))
            out["pe"]  = safe(info.get("trailingPE"))
        except Exception:
            pass

        # EBITDA
        try:
            qf = t.quarterly_financials
            if qf is not None and not qf.empty:
                col = qf[qf.columns[0]]
                for k in ["EBITDA", "Normalized EBITDA"]:
                    if k in col.index:
                        out["ebitda"] = to_millions(col[k]); break
        except Exception:
            pass
        return out
    except Exception:
        return out

# ════════════════════════════════════════════════════════════
#  FETCH ONE COMPANY + PARALLEL ORCHESTRATOR
# ════════════════════════════════════════════════════════════
def is_new(filed_date_str):
    if not filed_date_str: return False
    try:
        filed = date.fromisoformat(filed_date_str)
        return (date.today() - filed).days <= NEW_FILING_WINDOW_DAYS
    except Exception: return False

def fetch_one(sym, name, cik):
    y = fetch_yahoo(sym); e = fetch_edgar(cik)

    # ── If Yahoo left key fields blank, try Finnhub to fill them ──
    needs_fallback = (y["pe"] is None or y["eps"] is None
                      or y["market_cap"] is None
                      or y["hi_52"] is None or y["lo_52"] is None)
    if needs_fallback and FINNHUB_KEY:
        fh = fetch_finnhub_metrics(sym)
        if y["pe"] is None and fh["pe"] is not None: y["pe"] = fh["pe"]
        if y["eps"] is None and fh["eps"] is not None: y["eps"] = fh["eps"]
        if y["market_cap"] is None and fh["market_cap"] is not None:
            y["market_cap"] = fh["market_cap"]
        if y["hi_52"] is None and fh["hi_52"] is not None: y["hi_52"] = fh["hi_52"]
        if y["lo_52"] is None and fh["lo_52"] is not None: y["lo_52"] = fh["lo_52"]

    new_flag = is_new(e["filed"])
    display_ticker = f"🆕 {sym}" if new_flag else sym
    return {
        "Company": name, "Ticker": display_ticker,
        "_raw_ticker": sym, "_is_new": new_flag, "_filed": e["filed"] or "",
        "Price ($)": y["price"], "Day Chg %": y["day_chg"],
        "Market Cap ($B)": y["market_cap"],
        "EPS TTM ($)": y["eps"], "P/E TTM": y["pe"],
        "52W High ($)": y["hi_52"], "52W Low ($)": y["lo_52"],
        "Quarter": e["qtr_label"] or "—",
        "Period End": e["period_end"] or "—",
        "Filed Date": e["filed"] or "—",
        "Revenue ($M)": e["rev"], "PAT ($M)": e["pat"],
        "EBITDA ($M)": y["ebitda"],
        "Bloomberg Code": bloomberg_code(sym),
        "10-Q Filing": e["filing_url"] or "",
    }

def do_full_fetch():
    """Synchronously fetch all companies. Returns DataFrame."""
    rows = []
    items = list(COMPANIES.items())
    with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as executor:
        futures = {executor.submit(fetch_one, sym, name, cik): sym
                   for sym, (name, cik) in items}
        for future in as_completed(futures):
            try: rows.append(future.result())
            except Exception: pass
    df = pd.DataFrame(rows)
    if len(df) == 0: return df
    df = df.sort_values(
        by=["_is_new", "_filed", "_raw_ticker"],
        ascending=[False, False, True],
    ).reset_index(drop=True)
    return df

# ════════════════════════════════════════════════════════════
#  PERSISTENT STATE — KEEPS DATA VISIBLE ALWAYS
# ════════════════════════════════════════════════════════════
# Initialize state once per session
if "cached_df" not in st.session_state:
    st.session_state.cached_df = None
if "last_fetch" not in st.session_state:
    st.session_state.last_fetch = None
if "fetching" not in st.session_state:
    st.session_state.fetching = False

def needs_refresh():
    if st.session_state.cached_df is None: return True
    if st.session_state.last_fetch is None: return True
    elapsed = (datetime.now() - st.session_state.last_fetch).total_seconds()
    return elapsed >= REFRESH_SECONDS

# ════════════════════════════════════════════════════════════
#  HEADER (always renders, never blank)
# ════════════════════════════════════════════════════════════
is_admin = st.session_state.get("is_admin", False)
title_col, signout_col = st.columns([10, 1])
with title_col:
    badge = ' <span class="sheet-meta admin-badge">ADMIN</span>' if is_admin else ""
    st.markdown(f'<h1>US Large-Cap Tracker{badge}</h1>', unsafe_allow_html=True)
with signout_col:
    if st.button("Sign out", key="signout"):
        st.session_state.authenticated = False
        st.session_state.is_admin = False
        st.rerun()

# ════════════════════════════════════════════════════════════
#  ADMIN SIDEBAR
# ════════════════════════════════════════════════════════════
if is_admin:
    with st.sidebar:
        st.markdown("### ⚙️ Admin Panel")
        st.markdown("**Visible columns**")
        for col in list(st.session_state.visible_cols.keys()):
            st.session_state.visible_cols[col] = st.checkbox(
                col, value=st.session_state.visible_cols[col], key=f"col_{col}"
            )
        st.markdown("---")
        if st.button("🗑️ Clear cache & re-fetch", use_container_width=True):
            st.cache_data.clear()
            st.session_state.cached_df = None
            st.session_state.last_fetch = None
            st.rerun()
        st.markdown("---")
        st.markdown("**System**")
        st.caption(f"Companies: **{len(COMPANIES)}**")
        st.caption(f"Last fetch: **{st.session_state.last_fetch.strftime('%H:%M:%S') if st.session_state.last_fetch else '—'}**")
        st.caption(f"Refresh interval: **{REFRESH_SECONDS}s**")

# ════════════════════════════════════════════════════════════
#  DATA STRATEGY:
#  - First load: do synchronous fetch with progress (~30 sec)
#  - Subsequent loads: ALWAYS show cached data immediately,
#    re-fetch in background if >5 min old
# ════════════════════════════════════════════════════════════

# FIRST LOAD ONLY — show progress while building first dataset
if st.session_state.cached_df is None:
    st.markdown(
        '<div class="first-load-msg">'
        '<strong>Loading dashboard for the first time...</strong><br>'
        'Fetching live data for 106 US large-cap companies. Takes about 30-60 seconds.'
        '</div>',
        unsafe_allow_html=True
    )
    progress = st.progress(0, text="Connecting...")
    # Fake progress while real fetch runs
    df = do_full_fetch()
    progress.progress(1.0, text="Done!")
    time.sleep(0.3)
    progress.empty()
    st.session_state.cached_df = df
    st.session_state.last_fetch = datetime.now()
    st.rerun()

# ════════════════════════════════════════════════════════════
#  DASHBOARD — runs only when we have data
# ════════════════════════════════════════════════════════════
df = st.session_state.cached_df
last_update = st.session_state.last_fetch

# Schedule next refresh check via fragment (silent background)
@st.fragment(run_every=30)
def refresh_check():
    if needs_refresh() and not st.session_state.fetching:
        st.session_state.fetching = True
        try:
            new_df = do_full_fetch()
            if new_df is not None and len(new_df) > 0:
                st.session_state.cached_df = new_df
                st.session_state.last_fetch = datetime.now()
        finally:
            st.session_state.fetching = False
        st.rerun()

refresh_check()

# ── Render dashboard from cached data (ALWAYS available now) ──
valid = df[df["Day Chg %"].notna()]
new_filings = df[df["_is_new"] == True].copy()
new_count = len(new_filings)

age_secs = (datetime.now() - last_update).total_seconds()
is_stale = age_secs >= REFRESH_SECONDS
stale_pill = '<span class="updating">refreshing…</span>' if is_stale else ''

# Format both IST and US Eastern times
# st.session_state.last_fetch is a naive datetime in server local time
# We treat it as UTC since Streamlit Cloud servers run in UTC
last_utc = last_update.replace(tzinfo=timezone.utc) if last_update.tzinfo is None else last_update
last_ist = last_utc.astimezone(IST)
last_est = last_utc.astimezone(US_EAST)
est_label = last_est.strftime("%Z")  # "EST" or "EDT" depending on DST

now_utc = datetime.now(timezone.utc)
now_ist = now_utc.astimezone(IST)
now_est = now_utc.astimezone(US_EAST)

st.markdown(
    f'<div class="sheet-meta">'
    f'<span class="live-dot"></span>'
    f'<span class="accent">Live</span> · '
    f'{now_ist.strftime("%A, %B %d, %Y")} · '
    f'<span class="accent">{len(COMPANIES)}</span> companies · '
    f'Last updated <span class="accent">{last_ist.strftime("%H:%M")} IST</span> '
    f'/ <span class="accent">{last_est.strftime("%H:%M")} {est_label}</span>'
    f'{stale_pill} · '
    f'Refresh every {REFRESH_SECONDS//60} min · '
    f'Source: Yahoo Finance + SEC EDGAR'
    f'</div>',
    unsafe_allow_html=True
)

# ── US market status indicator ─────────────────────────────
def us_market_status(now_est_dt):
    """Returns (label, color) tuple. US markets: Mon-Fri 9:30 AM - 4:00 PM ET."""
    wd = now_est_dt.weekday()  # 0=Mon, 6=Sun
    if wd >= 5:
        return ("Closed · Weekend", "#5f6368")
    mins = now_est_dt.hour * 60 + now_est_dt.minute
    if mins < 4 * 60:                      # before 4 AM ET
        return ("Closed · Overnight", "#5f6368")
    elif mins < 9 * 60 + 30:               # 4 AM - 9:30 AM ET
        return ("Pre-market", "#f9ab00")
    elif mins < 16 * 60:                   # 9:30 AM - 4:00 PM ET
        return ("Open · Regular hours", "#137333")
    elif mins < 20 * 60:                   # 4 PM - 8 PM ET
        return ("After-hours", "#f9ab00")
    else:
        return ("Closed", "#5f6368")

mkt_label, mkt_color = us_market_status(now_est)
st.markdown(
    f'<div style="margin-top:-0.8rem;margin-bottom:1rem;font-size:0.78rem;color:#5f6368;font-family:Roboto,sans-serif;">'
    f'<span style="display:inline-block;width:8px;height:8px;border-radius:50%;'
    f'background:{mkt_color};margin-right:6px;vertical-align:middle;"></span>'
    f'US Market: <strong style="color:{mkt_color}">{mkt_label}</strong> · '
    f'Now in NY: {now_est.strftime("%I:%M %p")} {est_label} · '
    f'Now in India: {now_ist.strftime("%I:%M %p")} IST'
    f'</div>',
    unsafe_allow_html=True
)

if new_count > 0:
    chips_html = "".join([
        f'<span class="ticker-chip">{row["_raw_ticker"]} · {row["Quarter"]}</span>'
        for _, row in new_filings.iterrows()
    ])
    st.markdown(
        f'<div class="new-banner">'
        f'<span class="head">🆕 Just reported · {new_count} '
        f'{"company" if new_count == 1 else "companies"} '
        f'filed in last {NEW_FILING_WINDOW_DAYS} days — pinned to top</span>'
        f'{chips_html}'
        f'</div>',
        unsafe_allow_html=True
    )

if len(valid):
    gainers = int((valid["Day Chg %"] > 0).sum())
    losers = int((valid["Day Chg %"] < 0).sum())
    avg_chg = valid["Day Chg %"].mean()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Gainers", gainers)
    m2.metric("Losers", losers)
    m3.metric("Just Reported", new_count)
    m4.metric("Avg Change", f"{avg_chg:+.2f}%")

st.markdown("---")

a1, a2, a3 = st.columns([4, 1, 1])
with a1:
    search = st.text_input("", "", placeholder="Search ticker or company name...",
                           key="search", label_visibility="collapsed")
with a2:
    if st.button("Refresh", use_container_width=True, key="refresh_btn"):
        st.session_state.last_fetch = None  # forces refresh on next check
        st.rerun()
with a3:
    export_df = df.drop(columns=["_raw_ticker", "_is_new", "_filed"], errors="ignore")
    csv = export_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download CSV", csv,
        f"USLargeCap_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        "text/csv", use_container_width=True,
    )

if len(valid):
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("### Top Gainers")
        top = valid.nlargest(5, "Day Chg %")[["Ticker", "Company", "Price ($)", "Day Chg %"]].copy()
        top_styled = top.style.format({"Price ($)": "{:.2f}", "Day Chg %": "{:+.2f}%"}, na_rep="–")
        top_styled = top_styled.map(lambda v: "color:#137333;font-weight:500", subset=["Day Chg %"])
        st.dataframe(top_styled, use_container_width=True, hide_index=True)
    with c2:
        st.markdown("### Top Losers")
        bot = valid.nsmallest(5, "Day Chg %")[["Ticker", "Company", "Price ($)", "Day Chg %"]].copy()
        bot_styled = bot.style.format({"Price ($)": "{:.2f}", "Day Chg %": "{:+.2f}%"}, na_rep="–")
        bot_styled = bot_styled.map(lambda v: "color:#c5221f;font-weight:500", subset=["Day Chg %"])
        st.dataframe(bot_styled, use_container_width=True, hide_index=True)

st.markdown("---")
st.markdown("### All Companies")

display_df = df.copy()
if search:
    mask = (display_df["_raw_ticker"].str.contains(search, case=False, na=False) |
            display_df["Company"].str.contains(search, case=False, na=False))
    display_df = display_df[mask]
    st.caption(f"{len(display_df)} of {len(df)} match")

display_df = display_df.drop(columns=["_raw_ticker", "_is_new", "_filed"], errors="ignore")

visible = ["Company", "Ticker"] + [
    c for c, show in st.session_state.visible_cols.items() if show
]
visible = [c for c in visible if c in display_df.columns]
if len(visible) == 0:
    visible = list(display_df.columns)
display_df = display_df[visible]

st.caption(f"Showing {len(display_df)} companies · scroll horizontally for all columns")

def color_chg(val):
    if pd.isna(val): return ""
    if val > 0: return "color: #137333; font-weight: 500"
    if val < 0: return "color: #c5221f; font-weight: 500"
    return ""

fmt = {
    "Price ($)": "{:,.2f}", "Day Chg %": "{:+.2f}%",
    "Market Cap ($B)": "{:,.2f}",
    "EPS TTM ($)": "{:.2f}", "P/E TTM": "{:.1f}",
    "52W High ($)": "{:,.2f}", "52W Low ($)": "{:,.2f}",
    "Revenue ($M)": "{:,.0f}", "PAT ($M)": "{:,.0f}", "EBITDA ($M)": "{:,.0f}",
}
fmt = {k: v for k, v in fmt.items() if k in display_df.columns}

col_config = {
    "Company": st.column_config.TextColumn(width="medium"),
    "Ticker": st.column_config.TextColumn(width="small",
                                           help="🆕 = filed within last 14 days"),
}
if "10-Q Filing" in display_df.columns:
    col_config["10-Q Filing"] = st.column_config.LinkColumn(
        "10-Q Filing", display_text="View on EDGAR"
    )
if "Bloomberg Code" in display_df.columns:
    col_config["Bloomberg Code"] = st.column_config.TextColumn(
        "Bloomberg Code", width="small",
        help="Copy-paste into Bloomberg Terminal"
    )

try:
    styled = display_df.style.format(fmt, na_rep="–")
    if "Day Chg %" in display_df.columns:
        styled = styled.map(color_chg, subset=["Day Chg %"])
    st.dataframe(styled, use_container_width=True, hide_index=True, height=620,
                 column_config=col_config)
except Exception:
    st.dataframe(display_df, use_container_width=True, hide_index=True, height=620,
                 column_config=col_config)

st.markdown(
    '<div class="sheet-meta" style="border-top: 1px solid #e0e0e0; border-bottom: none; '
    'margin-top: 1.5rem; padding-top: 0.8rem;">'
    'Data sources: Yahoo Finance (price, market cap, 52W, P/E, EPS, EBITDA) · '
    'SEC EDGAR (Revenue, PAT, Quarter, filing link — authoritative) · '
    'Financials in USD millions · Market cap in USD billions · '
    '🆕 = new 10-Q filed recently, pinned to top · '
    'Bloomberg codes constructed as TICKER US Equity (BRK/B for Berkshire Class B)'
    '</div>',
    unsafe_allow_html=True
)
