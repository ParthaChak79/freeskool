import requests

import config


class SerpApiError(Exception):
    """Base class for SerpApi-related failures."""


class SerpApiQuotaExceededError(SerpApiError):
    """SerpApi returned 429 - rate limit or monthly quota exhausted. Always a
    hard failure; callers must not silently treat this as 'no data for this
    video' the way a genuine soft error (e.g. no transcript available) is."""


def serpapi_get(params: dict) -> dict:
    full_params = {**params, "api_key": config.SERPAPI_API_KEY}
    try:
        resp = requests.get(config.SERPAPI_BASE_URL, params=full_params, timeout=30)
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 429:
            raise SerpApiQuotaExceededError(
                "SerpApi rate limit or monthly quota exceeded. Check usage at serpapi.com/account."
            ) from e
        raise SerpApiError(f"SerpApi request failed ({e.response.status_code if e.response is not None else '?'}): {e}") from e
    except requests.exceptions.RequestException as e:
        raise SerpApiError(f"Could not reach SerpApi: {e}") from e

    data = resp.json()
    if data.get("error"):
        raise SerpApiError(data["error"])
    return data
