# test_trade_module.py
import pandas as pd
import pytest
from unittest.mock import patch

import materia_epd.market.market as tm


def test_fetch_trade_data_success(monkeypatch):
    df = pd.DataFrame({"x": [1]})
    with (
        patch("materia_epd.market.market.get_comtrade_api_key", return_value="KEY"),
        patch(
            "materia_epd.market.market.get_location_data",
            return_value={"comtradeID": 442},
        ),
        patch("materia_epd.market.market.C.TRADE_YEARS", ["2020", "2021"]),
        patch("materia_epd.market.market.C.TRADE_FLOW", "M"),
        patch(
            "materia_epd.market.market.comtradeapicall.getFinalData", return_value=df
        ) as mget,
        patch("materia_epd.market.market.time.sleep") as msleep,
    ):
        out = tm.fetch_trade_data_for_hs_code("LU", "0101")
        assert isinstance(out, pd.DataFrame) and not out.empty
        mget.assert_called_once()
        msleep.assert_called_once_with(1)


def test_fetch_trade_data_no_data(monkeypatch, capsys):
    with (
        patch("materia_epd.market.market.get_comtrade_api_key", return_value="KEY"),
        patch(
            "materia_epd.market.market.get_location_data",
            return_value={"comtradeID": 442},
        ),
        patch("materia_epd.market.market.C.TRADE_YEARS", ["2020"]),
        patch("materia_epd.market.market.C.TRADE_FLOW", "M"),
        patch(
            "materia_epd.market.market.comtradeapicall.getFinalData",
            return_value=pd.DataFrame(),
        ),
        patch("materia_epd.market.market.time.sleep"),
    ):
        out = tm.fetch_trade_data_for_hs_code("LU", "0101")
        assert out is None
        assert "No data for HS 0101" in capsys.readouterr().out


def test_fetch_trade_data_exception(capsys):
    with (
        patch("materia_epd.market.market.get_comtrade_api_key", return_value="KEY"),
        patch(
            "materia_epd.market.market.get_location_data",
            return_value={"comtradeID": 442},
        ),
        patch("materia_epd.market.market.C.TRADE_YEARS", ["2020"]),
        patch("materia_epd.market.market.C.TRADE_FLOW", "M"),
        patch(
            "materia_epd.market.market.comtradeapicall.getFinalData",
            side_effect=RuntimeError("boom"),
        ),
        patch("materia_epd.market.market.time.sleep"),
    ):
        out = tm.fetch_trade_data_for_hs_code("LU", "0101")
        assert out is None
        msg = capsys.readouterr().out
        assert "Error fetching data for HS 0101: boom" in msg


def test_estimate_market_shares_happy_path(monkeypatch):
    monkeypatch.setattr(tm, "TRADE_ROW_REGIONS", {"W01", "W02"})
    df = pd.DataFrame(
        {
            "partneriso": ["DE", "FR", "W01", "DE", "Small"],
            "qty": [60, 30, 10, 40, 1],
        }
    )
    shares = tm.estimate_market_shares(df.copy())
    assert set(shares.keys()) == {"DE", "FR", "RoW"}
    assert pytest.approx(sum(shares.values()), 1e-12) == 1.0
    assert shares["DE"] > shares["FR"] > shares["RoW"]


def test_estimate_market_shares_missing_columns(capsys):
    df = pd.DataFrame({"partner": ["DE"], "qty": [1]})
    assert tm.estimate_market_shares(df) == {}
    assert "Missing required columns" in capsys.readouterr().out


def test_estimate_market_shares_zero_total(monkeypatch):
    monkeypatch.setattr(tm, "TRADE_ROW_REGIONS", {"W01"})
    df = pd.DataFrame({"partneriso": ["W01"], "qty": [0]})
    assert tm.estimate_market_shares(df) == {}


def test_estimate_market_shares_filters_W00(monkeypatch):
    monkeypatch.setattr(tm, "TRADE_ROW_REGIONS", set())
    df = pd.DataFrame({"partneriso": ["W00", "DE"], "qty": [999, 1]})
    shares = tm.estimate_market_shares(df)
    import pytest

    assert pytest.approx(sum(shares.values()), 1e-12) == 1.0
    assert pytest.approx(shares.get("DE", 0.0)) == 1.0
    assert pytest.approx(shares.get("RoW", 0.0)) == 0.0


def test_generate_market_returns_estimates(monkeypatch):
    fake_df = pd.DataFrame({"partneriso": ["DE"], "qty": [100]})
    monkeypatch.setattr(tm, "fetch_trade_data_for_hs_code", lambda *_: fake_df)
    monkeypatch.setattr(tm, "estimate_market_shares", lambda df: {"DE": 1.0})
    assert tm.generate_market("LU", "0101") == {"DE": 1.0}


def test_generate_market_no_df(capsys, monkeypatch):
    monkeypatch.setattr(tm, "fetch_trade_data_for_hs_code", lambda *_: None)
    assert tm.generate_market("LU", "0101") is None
    assert (
        "No market shares can be generated for 0101 imports to LU."
        in capsys.readouterr().out
    )
