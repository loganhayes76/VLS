import os
import requests
import datetime
from dotenv import load_dotenv
import streamlit as st

load_dotenv()


def get_api_key():
    val = os.getenv('WEATHER_API_KEY')
    if val:
        return val
    try:
        return st.secrets["WEATHER_API_KEY"]
    except Exception:
        return None


def calculate_wind_direction(wind_deg, stadium_orientation=0):
    """
    Translates degrees into 'in', 'out', or 'neutral'.
    wind_deg must be the direction the wind is blowing TOWARD (TO convention).
    relative_angle 0 = wind blowing directly toward CF = 'out'.
    """
    relative_angle = (wind_deg - stadium_orientation) % 360
    if 315 <= relative_angle or relative_angle <= 45:
        return "out"
    elif 135 <= relative_angle <= 225:
        return "in"
    else:
        return "neutral"


@st.cache_data(ttl=1800)
def get_weather(city, target_date=None, cf_orientation=180):
    """
    Connects to OpenWeatherMap. Uses live weather for today,
    and the 5-day forecast API for future dates.
    Cached 30 minutes per (city, target_date, cf_orientation).

    cf_orientation: compass degrees from home plate toward center field.
    OpenWeatherMap returns wind.deg as the FROM direction (meteorological
    standard), so we convert to TO direction (+180) before classifying.
    """
    api_key = get_api_key()
    if not api_key:
        return None

    today_str = datetime.date.today().strftime("%Y-%m-%d")

    def _classify(raw_from_deg):
        wind_to = (raw_from_deg + 180) % 360
        return calculate_wind_direction(wind_to, cf_orientation)

    if not target_date or target_date == today_str:
        url = (
            f"http://api.openweathermap.org/data/2.5/weather"
            f"?q={city}&appid={api_key}&units=imperial"
        )
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                return {
                    "temp": data["main"]["temp"],
                    "wind_speed": data["wind"]["speed"],
                    "wind_dir": _classify(data["wind"].get("deg", 0)),
                }
        except Exception:
            return None
    else:
        url = (
            f"http://api.openweathermap.org/data/2.5/forecast"
            f"?q={city}&appid={api_key}&units=imperial"
        )
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                day_forecasts = [
                    f for f in data["list"]
                    if f["dt_txt"].startswith(target_date)
                ]
                if day_forecasts:
                    target_forecast = day_forecasts[len(day_forecasts) // 2]
                    return {
                        "temp": target_forecast["main"]["temp"],
                        "wind_speed": target_forecast["wind"]["speed"],
                        "wind_dir": _classify(
                            target_forecast["wind"].get("deg", 0)
                        ),
                    }
        except Exception:
            return None

    return None
