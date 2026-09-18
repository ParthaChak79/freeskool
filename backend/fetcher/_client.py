import requests

import config


class SerpApiError(Exception):
    pass


def serpapi_get(params: dict) -> dict:
    full_params = {**params, "api_key": config.SERPAPI_API_KEY}
    resp = requests.get(config.SERPAPI_BASE_URL, params=full_params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("error"):
        raise SerpApiError(data["error"])
    return data
