"""Real Open-Meteo signal adapter. Failures never turn into 'no rain'."""
from datetime import datetime, timezone
import threading
import time
import httpx
from .storage import now
from .validation import StudioError, number

CACHE = {}
LOCK = threading.Lock()


def weather(latitude, longitude):
    lat, lon = number(latitude, "latitude"), number(longitude, "longitude")
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise StudioError("Invalid latitude or longitude.")
    key = (round(lat, 3), round(lon, 3))
    with LOCK:
        cached = CACHE.get(key)
    if cached and time.time()-cached[0] < 300:
        return {**cached[1], "status": "cached", "cache_age_seconds": round(time.time()-cached[0])}
    try:
        response = httpx.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": lat, "longitude": lon, "current": "rain,showers,weather_code",
            "timezone": "UTC", "timeformat": "unixtime"}, timeout=7)
        response.raise_for_status()
        data = response.json()["current"]
        rain, showers = number(data["rain"], "rain"), number(data["showers"], "showers")
        observed = datetime.fromtimestamp(data["time"], timezone.utc)
        if rain < 0 or showers < 0 or abs(time.time()-observed.timestamp()) > 3600:
            raise ValueError("Provider returned invalid or old current data")
        result = {"provider": "Open-Meteo", "source_type": "weather_model",
                  "status": "live", "fetched_at": now(), "signal_time": observed.isoformat(),
                  "latitude": lat, "longitude": lon, "rain_mm": rain, "showers_mm": showers,
                  "interval_seconds": data.get("interval", 900), "weather_code": data["weather_code"],
                  "is_raining": rain+showers > 0, "mapping": "rain + showers > 0 mm",
                  "attribution": "Weather data by Open-Meteo (CC BY 4.0)", "cache_age_seconds": 0}
        with LOCK:
            CACHE[key] = (time.time(), result)
            if len(CACHE) > 200:
                CACHE.pop(next(iter(CACHE)))
        return result
    except (httpx.HTTPError, ValueError, KeyError, TypeError, OverflowError, ImportError) as e:
        if cached and time.time()-cached[0] < 1800:
            return {**cached[1], "status": "stale", "cache_age_seconds": round(time.time()-cached[0]),
                    "warning": "Provider unavailable; a saved response is being used."}
        raise StudioError("Live weather is unavailable. Retry or explicitly use manual scenario inputs.", "WEATHER_UNAVAILABLE", 503) from e
