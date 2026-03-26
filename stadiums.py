# Park Factors: 1.0 is neutral. Above 1.0 favors hitters. 
# These are simplified examples for our model.
PARK_FACTORS = {
    "Colorado Rockies": 1.25,      # Coors Field (Huge scoring)
    "San Diego Padres": 0.94,      # Petco Park (Pitcher friendly)
    "Cincinnati Reds": 1.12,       # Great American Ball Park
    "Texas Rangers": 1.08,         # Globe Life Field
    "Los Angeles Dodgers": 1.02,   # Dodger Stadium
    "Default": 1.00                # Every other team for now
}

def get_park_factor(home_team_name):
    """Looks up the stadium factor based on the home team."""
    return PARK_FACTORS.get(home_team_name, PARK_FACTORS["Default"])