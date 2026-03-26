from stadium_data import get_stadium_info

# Pretend we just got this from the Odds API
api_home_team = "Colorado Rockies"

# Look up the info
info = get_stadium_info(api_home_team)

print(f"Odds API Name: {api_home_team}")
print(f"Target City: {info['city']}")
print(f"Stats Abbreviation: {info['abbr']}")