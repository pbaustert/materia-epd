from unittest.mock import patch, MagicMock
import sys
import types

import materia_epd.resources as res


def test_load_json_from_package_success_and_cache():
    res.load_json_from_package.cache_clear()

    mock_path = MagicMock()
    with (
        patch("materia_epd.resources.files") as mock_files,
        patch("materia_epd.resources.as_file") as mock_as_file,
        patch("materia_epd.resources.io_files.read_json_file") as mock_read,
    ):
        mock_files.return_value.joinpath.return_value = mock_path
        mock_as_file.return_value.__enter__.return_value = mock_path
        mock_read.return_value = {"ok": 1}

        assert res.load_json_from_package("foo.json") == {"ok": 1}
        assert res.load_json_from_package("foo.json") == {"ok": 1}
        assert mock_read.call_count == 1


def test_load_json_from_package_error_when_none():
    res.load_json_from_package.cache_clear()

    mock_path = MagicMock()
    with (
        patch("materia_epd.resources.files") as mock_files,
        patch("materia_epd.resources.as_file") as mock_as_file,
        patch("materia_epd.resources.io_files.read_json_file", return_value=None),
    ):
        mock_files.return_value.joinpath.return_value = mock_path
        mock_as_file.return_value.__enter__.return_value = mock_path

        import pytest

        with pytest.raises(ValueError, match=r"Invalid or missing JSON file: foo.json"):
            res.load_json_from_package("foo.json")


@patch(
    "materia_epd.resources.io_files.gen_json_objects",
    return_value=[("a.json", {"a": 1}), ("b.json", {"b": 2})],
)
@patch("materia_epd.resources.as_file")
@patch("materia_epd.resources.files")
def test_iter_json_from_package_folder(mock_files, mock_as_file, mock_gen):
    fake_folder = MagicMock()
    mock_files.return_value.joinpath.return_value = fake_folder
    mock_as_file.return_value.__enter__.return_value = fake_folder

    items = list(res.iter_json_from_package_folder("folder"))
    assert items == [("a.json", {"a": 1}), ("b.json", {"b": 2})]

    mock_files.return_value.joinpath.assert_called_once_with("data", "folder")
    mock_gen.assert_called_once_with(fake_folder)


@patch("materia_epd.resources.load_json_from_package")
def test_get_regions_mapping(mock_load):
    mock_load.return_value = {"EU": "Europe"}
    result = res.get_regions_mapping()
    assert result == {"EU": "Europe"}
    mock_load.assert_called_once_with("regions_mapping.json")


@patch("materia_epd.resources.load_json_from_package")
def test_get_indicator_synonyms(mock_load):
    mock_load.return_value = {"GHG": "Greenhouse gases"}
    result = res.get_indicator_synonyms()
    assert result == {"GHG": "Greenhouse gases"}
    mock_load.assert_called_once_with("indicator_synonyms.json")


def test_get_market_shares_pkg_resource(tmp_path):
    res.get_market_shares.cache_clear()

    pkg_res = MagicMock()
    pkg_res.is_file.return_value = True
    with (
        patch("materia_epd.resources.files") as mfiles,
        patch("materia_epd.resources.as_file") as mas_file,
        patch(
            "materia_epd.resources.io_files.read_json_file", return_value={"pkg": True}
        ) as mread,
        patch("materia_epd.resources.io_files.write_json_file") as mwrite,
    ):
        mfiles.return_value.joinpath.return_value = pkg_res
        mas_file.return_value.__enter__.return_value = tmp_path / "pkg.json"

        assert res.get_market_shares("LU", "0101") == {"pkg": True}
        mwrite.assert_not_called()
        mread.assert_called_once()


def test_get_market_shares_user_file(tmp_path):
    res.get_market_shares.cache_clear()

    pkg_res = MagicMock()
    pkg_res.is_file.return_value = False
    user_root = tmp_path
    user_file = user_root / "market_shares" / "LU" / "0101.json"
    user_file.parent.mkdir(parents=True, exist_ok=True)
    user_file.write_text("{}", encoding="utf-8")

    with (
        patch("materia_epd.resources.USER_DATA_DIR", user_root),
        patch("materia_epd.resources.files") as mfiles,
        patch("materia_epd.resources.as_file"),
        patch(
            "materia_epd.resources.io_files.read_json_file",
            return_value={"user": True},
        ) as mread,
        patch("materia_epd.resources.io_files.write_json_file") as mwrite,
    ):
        mfiles.return_value.joinpath.return_value = pkg_res

        assert res.get_market_shares("LU", "0101") == {"user": True}
        mwrite.assert_not_called()
        mread.assert_called_once()


def test_get_market_shares_generate_and_store(tmp_path, capsys):
    res.get_market_shares.cache_clear()

    pkg_res = MagicMock()
    pkg_res.is_file.return_value = False
    user_root = tmp_path

    market_mod = types.ModuleType("materia_epd.market.market")
    market_mod.generate_market = MagicMock(return_value={"gen": True})
    sys.modules.setdefault("materia_epd", types.ModuleType("materia_epd"))
    sys.modules.setdefault("materia_epd.market", types.ModuleType("materia_epd.market"))
    sys.modules["materia_epd.market.market"] = market_mod

    with (
        patch("materia_epd.resources.USER_DATA_DIR", user_root),
        patch("materia_epd.resources.files") as mfiles,
        patch("materia_epd.resources.as_file"),
        patch("materia_epd.resources.io_files.write_json_file") as mwrite,
    ):
        mfiles.return_value.joinpath.return_value = pkg_res

        out = res.get_market_shares("FR", "0303")
        assert out == {"gen": True}
        market_mod.generate_market.assert_called_once_with("FR", "0303")

        expected = user_root / "market_shares" / "FR" / "0303.json"
        assert mwrite.call_args[0][0] == expected
        assert mwrite.call_args[0][1] == {"gen": True}

        msg = capsys.readouterr().out
        assert f"Market share for imports of 0303 to FR stored in {expected}." in msg


def test_get_comtrade_api_key_from_file(tmp_path):
    api_path = tmp_path / "comtrade_api_key.json"
    with (
        patch("materia_epd.resources.USER_DATA_DIR", tmp_path),
        patch(
            "materia_epd.resources.io_files.read_json_file",
            return_value={"apikey": "XYZ"},
        ) as mread,
    ):
        api_path.write_text("{}", encoding="utf-8")
        assert res.get_comtrade_api_key() == "XYZ"
        mread.assert_called_once_with(api_path)


def test_get_comtrade_api_key_prompt_and_store(tmp_path, capsys):
    api_path = tmp_path / "comtrade_api_key.json"
    with (
        patch("materia_epd.resources.USER_DATA_DIR", tmp_path),
        patch("builtins.input", return_value="abc123"),
        patch("materia_epd.resources.io_files.read_json_file", return_value={}),
        patch("materia_epd.resources.io_files.write_json_file") as mwrite,
    ):
        key = res.get_comtrade_api_key()
        assert key == "abc123"
        mwrite.assert_called_once_with(api_path, {"apikey": "abc123"})
        assert f"API key stored in {api_path}." in capsys.readouterr().out


def test_get_comtrade_api_key_empty_raises(tmp_path):
    with (
        patch("materia_epd.resources.USER_DATA_DIR", tmp_path),
        patch("builtins.input", return_value="  "),
        patch("materia_epd.resources.io_files.read_json_file", return_value={}),
    ):
        import pytest

        with pytest.raises(ValueError, match="API key cannot be empty."):
            res.get_comtrade_api_key()


@patch("materia_epd.resources.load_json_from_package")
def test_get_location_data(mock_load):
    mock_load.return_value = {"name": "Luxembourg"}
    result = res.get_location_data("LU")
    assert result == {"name": "Luxembourg"}
    mock_load.assert_called_once_with("locations", "LU.json")
