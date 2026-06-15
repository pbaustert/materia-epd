import time
import pandas as pd
import comtradeapicall

from materia_epd.core import constants as C
from materia_epd.resources import get_location_data, get_comtrade_api_key
from materia_epd.core.constants import TRADE_ROW_REGIONS


def fetch_trade_data_for_hs_code(loc_code: str, hs_code: str) -> pd.DataFrame | None:
    """Get raw trade flow data from comtrade."""
    comtradeapikey = get_comtrade_api_key()
    location = get_location_data(loc_code)
    comtradeID = location["comtradeID"]
    try:
        params = dict(
            typeCode="C",
            freqCode="A",
            clCode="HS",
            period=",".join(C.TRADE_YEARS),
            reporterCode=comtradeID,
            cmdCode=hs_code,
            flowCode=C.TRADE_FLOW,
            format_output="JSON",
            includeDesc=True,
            maxRecords=2500,
            breakdownMode="classic",
            partnerCode=None,
            partner2Code=None,
            customsCode=None,
            motCode=None,
        )
        df = comtradeapicall.getFinalData(comtradeapikey, **params)
        if isinstance(df, pd.DataFrame) and not df.empty:
            return df
        print(f"No data for HS {hs_code}")
    except Exception as e:
        print(f"Error fetching data for HS {hs_code}: {e}")
    finally:
        time.sleep(1)
    return None


def estimate_market_shares(df):
    """Estimate market shares from raw data."""
    df.columns = [c.lower().strip() for c in df.columns]
    if not {"partneriso", "qty"}.issubset(df.columns):
        print("❌ Missing required columns:", df.columns.tolist())
        return {}

    s = df[df["partneriso"] != "W00"].groupby("partneriso", as_index=False)["qty"].sum()
    row_qty = s.loc[s["partneriso"].isin(TRADE_ROW_REGIONS), "qty"].sum()

    m = pd.concat(
        [
            s[~s["partneriso"].isin(TRADE_ROW_REGIONS)],
            pd.DataFrame([{"partneriso": "RoW", "qty": row_qty}]),
        ],
        ignore_index=True,
    )

    tot = m["qty"].sum()
    if tot == 0:
        return {}

    m["share"] = m["qty"] / tot
    small = (m["partneriso"] != "RoW") & (m["share"] < 0.01)
    if small.any():
        m.loc[m["partneriso"] == "RoW", "qty"] += m.loc[small, "qty"].sum()
        m = m[~small]
        m["share"] = m["qty"] / m["qty"].sum()

    m["share"] /= m["share"].sum()
    sorted_m = m.sort_values("share", ascending=False)

    return dict(zip(sorted_m["partneriso"], sorted_m["share"]))


def generate_market(loc_code, hs_code) -> None:
    """Generate the market for the provided country and HS code."""
    df = fetch_trade_data_for_hs_code(loc_code, hs_code)
    if df is not None:
        return estimate_market_shares(df)
    else:
        print(f"No market shares can be generated for {hs_code} imports to {loc_code}.")
        return None
