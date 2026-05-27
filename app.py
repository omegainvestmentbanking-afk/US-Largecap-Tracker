# ============================================================
#  US LARGE-CAP LIVE TRACKER — Password Protected
#  Clean Google Sheets-style dashboard with 30-day session cookie
#
#  Live data:  Yahoo Finance
#  Filed data: SEC EDGAR
#
#  RUN LOCALLY:  py -m streamlit run app.py
# ============================================================

import streamlit as st
import yfinance as yf
import pandas as pd
import requests
from datetime import datetime, date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import secrets

# ════════════════════════════════════════════════════════════
#  PAGE CONFIG
# ════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="US Large-Cap Tracker",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ════════════════════════════════════════════════════════════
#  AUTHENTICATION
#  Password is stored in Streamlit's secrets (set in dashboard UI)
#  Falls back to a default for local testing
# ════════════════════════════════════════════════════════════
DEFAULT_PASSWORD = "change-me-in-secrets"   # only used for local testing

def get_password():
    """Read password from st.secrets; fall back to default locally."""
    try:
        return st.secrets["APP_PASSWORD"]
    except (KeyError, FileNotFoundError):
        return DEFAULT_PASSWORD

def check_password():
    """Returns True if user already authenticated, otherwise shows login form."""
    # Already authenticated this session? — let them through
    if st.session_state.get("authenticated"):
        return True

    # ── Login screen ──
    # Use minimal styling for the gate
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
    .login-title {
        font-size: 1.4rem; font-weight: 500; color: #202124;
        margin-bottom: 0.3rem; letter-spacing: -0.01em;
    }
    .login-sub {
        font-size: 0.85rem; color: #5f6368; margin-bottom: 1.5rem;
    }
    .stTextInput > div > div > input {
        font-size: 0.95rem !important; padding: 0.6rem 0.8rem !important;
    }
    .stButton > button {
        width: 100%; background: #1a73e8; color: #ffffff;
        border: 1px solid #1a73e8; padding: 0.55rem; font-weight: 500;
        margin-top: 0.5rem;
    }
    .stButton > button:hover { background: #1557b0; }
    </style>
    """, unsafe_allow_html=True)

    # Centered card
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
        login_clicked = st.button("Sign in", use_container_width=True, key="login_btn")

        if login_clicked:
            if pw == get_password():
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Incorrect password.")

    return False

# Gate the entire app behind login
if not check_password():
    st.stop()

# ════════════════════════════════════════════════════════════
#  MAIN APP — only runs if authenticated
# ════════════════════════════════════════════════════════════

# ── Google Sheets-style CSS ──
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&family=Roboto+Mono:wght@400;500&display=swap');

.stApp {
    background: #ffffff;
    color: #202124;
    font-family: 'Roboto', Arial, sans-serif;
}

.main .block-container {
    padding-top: 1.2rem;
    padding-bottom: 2rem;
    max-width: 1600px;
}

#MainMenu, footer, header {visibility: hidden;}

h1 {
    font-family: 'Roboto', sans-serif !important;
    font-weight: 500 !important;
    font-size: 1.6rem !important;
    color: #202124 !important;
    margin-bottom: 0.2rem !important;
    letter-spacing: -0.01em !important;
}

.sheet-meta {
    font-family: 'Roboto', sans-serif;
    font-size: 0.82rem;
    color: #5f6368;
    padding-bottom: 0.8rem;
    border-bottom: 1px solid #e0e0e0;
    margin-bottom: 1rem;
}
.sheet-meta .accent { color: #1a73e8; font-weight: 500; }
.sheet-meta .live-dot {
    display: inline-block; width: 7px; height: 7px; border-radius: 50%;
    background: #34a853; margin-right: 5px;
    animation: pulse 1.6s ease-in-out infinite;
}
@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
}

h2, h3 {
    font-family: 'Roboto', sans-serif !important;
    color: #202124 !important;
    font-weight: 500 !important;
}
h3 {
    font-size: 0.95rem !important;
    color: #5f6368 !important;
    text-transform: none !important;
    letter-spacing: 0 !important;
    margin-top: 0.8rem !important;
}

[data-testid="stMetric"] {
    background: #f8f9fa;
    border: 1px solid #e0e0e0;
    border-radius: 6px;
    padding: 0.7rem 0.9rem;
}
[data-testid="stMetricLabel"] {
    font-size: 0.75rem !important;
    color: #5f6368 !important;
    font-weight: 400 !important;
}
[data-testid="stMetricValue"] {
    font-family: 'Roboto', sans-serif !important;
    font-weight: 500 !important;
    color: #202124 !important;
    font-size: 1.4rem !important;
}

hr { border-color: #e0e0e0 !important; margin: 1rem 0 !important; }

[data-testid="stDataFrame"] {
    border: 1px solid #e0e0e0;
    border-radius: 4px;
}

.stButton > button {
    background: #ffffff;
    color: #1a73e8;
    border: 1px solid #dadce0;
    font-family: 'Roboto', sans-serif;
    font-size: 0.85rem;
    font-weight: 500;
    border-radius: 4px;
    padding: 0.4rem 1rem;
    text-transform: none;
}
.stButton > button:hover {
    background: #f8f9fa;
    border-color: #1a73e8;
}

.stDownloadButton > button {
    background: #1a73e8;
    color: #ffffff;
    border: 1px solid #1a73e8;
    font-family: 'Roboto', sans-serif;
    font-size: 0.85rem;
    font-weight: 500;
    border-radius: 4px;
    padding: 0.4rem 1rem;
    text-transform: none;
}
.stDownloadButton > button:hover { background: #1557b0; }

.stTextInput > div > div > input {
    background: #ffffff;
    border: 1px solid #dadce0;
    color: #202124;
    font-family: 'Roboto', sans-serif;
    border-radius: 4px;
    font-size: 0.9rem;
}
.stTextInput > div > div > input:focus {
    border-color: #1a73e8;
    box-shadow: 0 0 0 1px #1a73e8;
}

.stCaption, [data-testid="stCaptionContainer"] {
    color: #5f6368 !important;
    font-family: 'Roboto', sans-serif !important;
    font-size: 0.78rem !important;
}

.stProgress > div > div > div > div { background: #1a73e8; }

.new-banner {
    background: #fef7e0;
    border: 1px solid #f9ab00;
    border-left: 4px solid #f9ab00;
    border-radius: 4px;
    padding: 10px 14px;
    margin: 14px 0;
    font-family: 'Roboto', sans-serif;
    font-size: 0.85rem;
    color: #3c4043;
}
.new-banner .head {
    color: #b06000;
    font-weight: 500;
    display: block;
    margin-bottom: 4px;
}
.new-banner .ticker-chip {
    display: inline-block;
    background: #ffffff;
    border: 1px solid #f9ab00;
    color: #b06000;
    padding: 2px 8px;
    margin: 2px 3px 2px 0;
    border-radius: 12px;
    font-weight: 500;
    font-size: 0.78rem;
}
</style>
""", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════
#  COMPANIES (106 unique tickers)
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

REFRESH_SECONDS = 60
PARALLEL_WORKERS = 12
NEW_FILING_WINDOW_DAYS = 14

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
    except Exception:
        return empty

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

    rev = latest(REV_CONCEPTS)
    ni = latest(NI_CONCEPTS)
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
        "qtr_label": qtr_label,
        "filing_url": filing_url,
        "period_end": primary.get("end"),
        "filed": primary.get("filed"),
    }

# ════════════════════════════════════════════════════════════
#  YAHOO
# ════════════════════════════════════════════════════════════
def fetch_yahoo(symbol):
    try:
        t = yf.Ticker(symbol)
        info = t.info or {}
        price = info.get("regularMarketPrice") or info.get("currentPrice")
        prev = info.get("regularMarketPreviousClose") or info.get("previousClose")
        day_chg = None
        if price and prev and prev != 0:
            day_chg = round(((price - prev) / prev) * 100, 2)

        ebitda = None
        try:
            qf = t.quarterly_financials
            if qf is not None and not qf.empty:
                col = qf[qf.columns[0]]
                for k in ["EBITDA", "Normalized EBITDA"]:
                    if k in col.index:
                        ebitda = to_millions(col[k]); break
        except Exception: pass

        return {
            "price": safe(price), "day_chg": day_chg,
            "eps": safe(info.get("trailingEps")), "pe": safe(info.get("trailingPE")),
            "hi_52": safe(info.get("fiftyTwoWeekHigh")), "lo_52": safe(info.get("fiftyTwoWeekLow")),
            "ebitda": ebitda,
        }
    except Exception:
        return {"price": None, "day_chg": None, "eps": None, "pe": None,
                "hi_52": None, "lo_52": None, "ebitda": None}

# ════════════════════════════════════════════════════════════
#  PARALLEL FETCH
# ════════════════════════════════════════════════════════════
def is_new(filed_date_str):
    if not filed_date_str: return False
    try:
        filed = date.fromisoformat(filed_date_str)
        return (date.today() - filed).days <= NEW_FILING_WINDOW_DAYS
    except Exception: return False

def fetch_one(sym, name, cik):
    y = fetch_yahoo(sym)
    e = fetch_edgar(cik)
    new_flag = is_new(e["filed"])
    display_ticker = f"🆕 {sym}" if new_flag else sym
    return {
        "Company": name,
        "Ticker": display_ticker,
        "_raw_ticker": sym,
        "_is_new": new_flag,
        "_filed": e["filed"] or "",
        "Price ($)": y["price"],
        "Day Chg %": y["day_chg"],
        "EPS TTM ($)": y["eps"],
        "P/E TTM": y["pe"],
        "52W High ($)": y["hi_52"],
        "52W Low ($)": y["lo_52"],
        "Quarter": e["qtr_label"] or "—",
        "Period End": e["period_end"] or "—",
        "Filed Date": e["filed"] or "—",
        "Revenue ($M)": e["rev"],
        "PAT ($M)": e["pat"],
        "EBITDA ($M)": y["ebitda"],
        "10-Q Filing": e["filing_url"] or "",
    }

@st.cache_data(ttl=REFRESH_SECONDS, show_spinner=False)
def fetch_all_data():
    rows = []
    items = list(COMPANIES.items())
    progress = st.progress(0.0, text=f"Loading {len(items)} companies...")

    with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as executor:
        futures = {executor.submit(fetch_one, sym, name, cik): sym
                   for sym, (name, cik) in items}
        done = 0
        for future in as_completed(futures):
            try: rows.append(future.result())
            except Exception: pass
            done += 1
            progress.progress(done / len(items),
                              text=f"Loading... {done}/{len(items)}")

    progress.empty()
    df = pd.DataFrame(rows)
    df = df.sort_values(
        by=["_is_new", "_filed", "_raw_ticker"],
        ascending=[False, False, True],
    ).reset_index(drop=True)
    return df, datetime.now()

# ════════════════════════════════════════════════════════════
#  UI
# ════════════════════════════════════════════════════════════
# Title + small "Sign out" link in top right
title_col, signout_col = st.columns([10, 1])
with title_col:
    st.title("US Large-Cap Tracker")
with signout_col:
    if st.button("Sign out", key="signout"):
        st.session_state.authenticated = False
        st.rerun()

@st.fragment(run_every=REFRESH_SECONDS)
def dashboard():
    df, last_update = fetch_all_data()
    valid = df[df["Day Chg %"].notna()]
    new_filings = df[df["_is_new"] == True].copy()
    new_count = len(new_filings)

    st.markdown(
        f'<div class="sheet-meta">'
        f'<span class="live-dot"></span>'
        f'<span class="accent">Live</span> · '
        f'{datetime.now().strftime("%A, %B %d, %Y")} · '
        f'<span class="accent">{len(COMPANIES)}</span> companies · '
        f'Last updated <span class="accent">{last_update.strftime("%H:%M:%S")}</span> · '
        f'Auto-refresh every {REFRESH_SECONDS}s · '
        f'Source: Yahoo Finance + SEC EDGAR'
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
            st.cache_data.clear()
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
            top_styled = top.style.format({"Price ($)": "{:.2f}", "Day Chg %": "{:+.2f}%"})
            top_styled = top_styled.map(lambda v: "color:#137333;font-weight:500", subset=["Day Chg %"])
            st.dataframe(top_styled, use_container_width=True, hide_index=True)
        with c2:
            st.markdown("### Top Losers")
            bot = valid.nsmallest(5, "Day Chg %")[["Ticker", "Company", "Price ($)", "Day Chg %"]].copy()
            bot_styled = bot.style.format({"Price ($)": "{:.2f}", "Day Chg %": "{:+.2f}%"})
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

    def color_chg(val):
        if pd.isna(val): return ""
        if val > 0: return "color: #137333; font-weight: 500"
        if val < 0: return "color: #c5221f; font-weight: 500"
        return ""

    styled = (display_df.style
              .map(color_chg, subset=["Day Chg %"])
              .format({
                  "Price ($)": "{:,.2f}", "Day Chg %": "{:+.2f}%",
                  "EPS TTM ($)": "{:.2f}", "P/E TTM": "{:.1f}",
                  "52W High ($)": "{:,.2f}", "52W Low ($)": "{:,.2f}",
                  "Revenue ($M)": "{:,.0f}",
                  "PAT ($M)": "{:,.0f}",
                  "EBITDA ($M)": "{:,.0f}",
              }, na_rep="–"))

    st.dataframe(
        styled, use_container_width=True, hide_index=True, height=620,
        column_config={
            "10-Q Filing": st.column_config.LinkColumn(
                "10-Q Filing", display_text="View on EDGAR"
            ),
            "Company": st.column_config.TextColumn(width="medium"),
            "Ticker": st.column_config.TextColumn(width="small",
                                                   help="🆕 = filed within last 14 days"),
        },
    )

dashboard()

st.markdown(
    '<div class="sheet-meta" style="border-top: 1px solid #e0e0e0; border-bottom: none; '
    'margin-top: 1.5rem; padding-top: 0.8rem;">'
    'Data sources: Yahoo Finance (price, 52W, P/E, EPS, EBITDA — 15-min delayed) · '
    'SEC EDGAR (Revenue, PAT, Quarter, filing link — authoritative) · '
    'Financials in USD millions · '
    '🆕 = new 10-Q filed within last 14 days, pinned to top'
    '</div>',
    unsafe_allow_html=True
)
