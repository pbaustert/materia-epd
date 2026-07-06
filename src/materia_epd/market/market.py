import time
import pandas as pd
import comtradeapicall

from materia_epd.core import constants as C
from materia_epd.resources import (
    get_location_data,
    get_comtrade_api_key,
    get_national_production,
)

QUANTITY_COL = "netWgt"  # Column name for quantity in the trade data


def fetch_trade_data(
    loc_code: str,
    hs_code: str,
    flow_code: str,
    aggregate: bool = False,
) -> pd.DataFrame | None:
    """Fetch trade data with support for multiple quantity units (kg, m³, etc.)."""
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
            flowCode=flow_code,
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
            df = df[~df["partnerDesc"].str.fullmatch("World", case=False, na=False)]

            if aggregate:
                return df.groupby("refYear")[QUANTITY_COL].sum().reset_index()
            return df

        print(f"No {flow_code} data for HS {hs_code}")
    except Exception as e:
        print(f"Error fetching {flow_code} data for HS {hs_code}: {e}")
    finally:
        time.sleep(1)
    return None


def fetch_import_data_for_hs_code(loc_code: str, hs_code: str) -> pd.DataFrame | None:
    """Get raw import data from comtrade."""
    return fetch_trade_data(loc_code, hs_code, "M", aggregate=False)


def fetch_export_data_for_hs_code(loc_code: str, hs_code: str) -> pd.DataFrame | None:
    """Get aggregated export data from comtrade."""
    return fetch_trade_data(loc_code, hs_code, "X", aggregate=True)


def fetch_reexport_data_for_hs_code(loc_code: str, hs_code: str) -> pd.DataFrame | None:
    """Get aggregated re-export data from comtrade."""
    return fetch_trade_data(loc_code, hs_code, "RX", aggregate=True)


def fetch_reimport_data_for_hs_code(loc_code: str, hs_code: str) -> pd.DataFrame | None:
    """Get aggregated re-import data from comtrade."""
    return fetch_trade_data(loc_code, hs_code, "RM", aggregate=True)


def add_national_production(loc_code, hs_code, trade_df):
    """Adds national production retained for the domestic market."""

    new_rows = []

    location = get_location_data(loc_code)
    national_production = get_national_production(loc_code, hs_code)

    comtradeID = location["comtradeID"]
    country_name = location["Name"]

    annual_production = national_production["production"]

    if annual_production == 0:
        return trade_df

    else:
        export_df = fetch_export_data_for_hs_code(loc_code, hs_code)
        reimport_df = fetch_reimport_data_for_hs_code(loc_code, hs_code)
        reexport_df = fetch_reexport_data_for_hs_code(loc_code, hs_code)

        exports_by_year = {}
        reimports_by_year = {}
        reexports_by_year = {}

        if export_df is not None:
            exports_by_year = dict(zip(export_df["refYear"], export_df[QUANTITY_COL]))

        if reimport_df is not None:
            reimports_by_year = dict(
                zip(reimport_df["refYear"], reimport_df[QUANTITY_COL])
            )

        if reexport_df is not None:
            reexports_by_year = dict(
                zip(reexport_df["refYear"], reexport_df[QUANTITY_COL])
            )

        ref_row = trade_df.iloc[0]

        for year in map(int, C.TRADE_YEARS):
            exports = exports_by_year.get(year, 0)
            reimports = reimports_by_year.get(year, 0)
            reexports = reexports_by_year.get(year, 0)

            # Production retained in the domestic market
            domestic_production = max(
                annual_production - exports + reimports + reexports, 0
            )

            new_row = ref_row.copy()
            new_row["refYear"] = year
            new_row["refPeriodId"] = f"{year}0101"
            new_row["period"] = year
            new_row["partnerCode"] = comtradeID
            new_row["partnerISO"] = loc_code
            new_row["partnerDesc"] = country_name

            new_row[QUANTITY_COL] = domestic_production
            new_row["altQty"] = domestic_production
            new_row["netWgt"] = domestic_production
            new_row["cifvalue"] = domestic_production
            new_row["fobvalue"] = domestic_production
            new_row["primaryValue"] = domestic_production

            new_rows.append(new_row)

        return pd.concat([trade_df, pd.DataFrame(new_rows)], ignore_index=True)


def estimate_market_shares(df):
    """Estimate market shares from raw data."""
    df.columns = [c.lower().strip() for c in df.columns]
    if not {"partneriso", QUANTITY_COL}.issubset(df.columns):
        print("❌ Missing required columns:", df.columns.tolist())
        return {}

    s = df.groupby("partneriso", as_index=False)[QUANTITY_COL].sum()
    row_qty = s.loc[s["partneriso"].isin(C.TRADE_ROW_REGIONS), QUANTITY_COL].sum()

    m = pd.concat(
        [
            s[~s["partneriso"].isin(C.TRADE_ROW_REGIONS)],
            pd.DataFrame([{"partneriso": "RoW", QUANTITY_COL: row_qty}]),
        ],
        ignore_index=True,
    )

    tot = m[QUANTITY_COL].sum()
    if tot == 0:
        return {}

    m["share"] = m[QUANTITY_COL] / tot
    small = (m["partneriso"] != "RoW") & (m["share"] < 0.01)
    if small.any():
        m.loc[m["partneriso"] == "RoW", QUANTITY_COL] += m.loc[
            small, QUANTITY_COL
        ].sum()
        m = m[~small]
        m["share"] = m[QUANTITY_COL] / m[QUANTITY_COL].sum()

    m["share"] /= m["share"].sum()
    sorted_m = m.sort_values("share", ascending=False)

    return dict(zip(sorted_m["partneriso"], sorted_m["share"]))


def generate_market(loc_code, hs_code) -> None:
    """Generate the market for the provided country and HS code."""
    df = fetch_import_data_for_hs_code(loc_code, hs_code)
    df = add_national_production(loc_code, hs_code, df)
    if df is not None:
        return estimate_market_shares(df)
    else:
        print(f"No market shares can be generated for {hs_code} imports to {loc_code}.")
        return None
