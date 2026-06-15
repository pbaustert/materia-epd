from pathlib import Path
from materia_epd.market.market import fetch_trade_data_for_hs_code, generate_market

hs_code = "7314"

trade_data = fetch_trade_data_for_hs_code("LUX", hs_code)

print(trade_data)

# Save to Downloads folder (creates CSV)
if trade_data is not None:
    downloads_path = str(Path.home() / "Downloads" / "trade_data_LUX.csv")
    trade_data.to_csv(downloads_path, index=False)
    print(f"✅ Saved trade data to: {downloads_path}")

market_shares = generate_market("LUX", hs_code)

print(market_shares)
