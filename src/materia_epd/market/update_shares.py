import os
from materia_epd.market.market import generate_market
from materia_epd.io import files as io_files

my_path = r"..\materia_epd\src\materia_epd\data\market_shares\LUX"
out_path = r"..\materia_epd\src\materia_epd\data\market_shares\new_LUX"

hs_codes = [f[:-5] for f in os.listdir(my_path) if f.endswith(".json")]

for hs_code in hs_codes:
    output_path = os.path.join(out_path, f"{hs_code}.json")
    print(f"HS Code: {hs_code}")
    market_shares = generate_market("LUX", hs_code)
    print(market_shares)
    if len(market_shares.keys()) == 0:
        print(f"No market shares generated for {hs_code}.")
    io_files.write_json_file(output_path, market_shares)
