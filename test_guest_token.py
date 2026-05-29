import urllib.request
import json

try:
    url = "https://open.spotify.com/get_access_token?reason=transport&productType=web-player"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Referer": "https://open.spotify.com/"
        }
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        html = response.read().decode("utf-8")
        data = json.loads(html)
        print("Success!")
        print("Access Token Keys:", data.keys())
        print("Token Length:", len(data.get("accessToken", "")))
        print("Token Preview:", data.get("accessToken")[:30] + "...")
except Exception as e:
    print("Error fetching guest token:", e)
