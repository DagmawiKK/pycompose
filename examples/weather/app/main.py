"""A city's weather now and for the days ahead, from Open-Meteo's free API."""

import httpx

import pycompose.blocks as pc

PLACES = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST = "https://api.open-meteo.com/v1/forecast"
DAILY = (
    "temperature_2m_min",
    "temperature_2m_max",
    "precipitation_probability_max",
    "weather_code",
)
SKIES = {
    0: "clear",
    1: "mostly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    61: "rain",
    63: "rain",
    65: "heavy rain",
    80: "showers",
    95: "thunderstorm",
}


def forecast(city: str, units: str, days: float, rainy_only: bool) -> tuple[str, str]:
    """Find the city, then fetch its current weather and daily forecast."""
    if not city.strip():
        raise ValueError("Type a city first")
    places = httpx.get(PLACES, params={"name": city, "count": 1}, timeout=15).json()
    if not places.get("results"):
        raise ValueError(f"No city called {city!r}")
    place = places["results"][0]
    unit = units.lower()
    weather = httpx.get(
        FORECAST,
        timeout=15,
        params={
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "current": "temperature_2m,wind_speed_10m,weather_code",
            "daily": ",".join(DAILY),
            "temperature_unit": unit,
            "timezone": "auto",
            "forecast_days": int(days),
        },
    ).json()
    degree = "°F" if unit == "fahrenheit" else "°C"
    now = weather["current"]
    summary = (
        f"{place['name']}, {place.get('country', '')}\n"
        f"{now['temperature_2m']}{degree}, {SKIES.get(now['weather_code'], 'mixed')}, "
        f"wind {now['wind_speed_10m']} km/h"
    )
    daily = weather["daily"]
    rows = [
        f"{day}: {low} to {high}{degree}, {SKIES.get(code, 'mixed')}, {rain}% rain"
        for day, low, high, rain, code in zip(
            daily["time"],
            daily["temperature_2m_min"],
            daily["temperature_2m_max"],
            daily["precipitation_probability_max"],
            daily["weather_code"],
            strict=True,
        )
        if not rainy_only or rain >= 50
    ]
    return summary, "\n".join(rows) or "No rainy days ahead."


with pc.Blocks() as app:
    city = pc.Textbox(label="City", placeholder="Addis Ababa")
    units = pc.Radio(["Celsius", "Fahrenheit"], "Celsius", label="Units")
    days = pc.Slider(1, 7, 3, step=1, label="Days")
    rainy_only = pc.Checkbox(label="Only days likely to rain")
    go = pc.Button("Get forecast")
    with pc.Tabs():
        with pc.Tab("Now"):
            now = pc.Markdown("Pick a city to see its weather.")
        with pc.Tab("Days ahead"):
            ahead = pc.Markdown()
    go.click(forecast, inputs=[city, units, days, rainy_only], outputs=[now, ahead])
