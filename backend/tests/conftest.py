"""Keep the assembled app's process-wide limiter from coupling unrelated tests."""

import os


# Rate-limit behavior has dedicated unit tests with an explicit small limiter.
# The shared TestClient app should not rate-limit the suite based on test order.
os.environ.setdefault("CLOUDOPS_RATE_LIMIT_REQUESTS", "10000")


class _ConsoleSourceResponse:
    """Expose the HTML page and its external script as one inspectable test source."""

    def __init__(self, response, source):
        self._response = response
        self.text = source

    def __getattr__(self, name):
        return getattr(self._response, name)


def console_response(client, **kwargs):
    """Fetch the console document and its same-origin JavaScript for source assertions."""
    response = client.get("/console", **kwargs)
    source = response.text
    if response.status_code == 200:
        script = client.get("/static/console.js")
        if script.status_code == 200:
            source += "\\n" + script.text
    return _ConsoleSourceResponse(response, source)


def read_console_source():
    """Read the console document and its external JavaScript for source assertions."""
    from pathlib import Path

    static_dir = Path(__file__).parents[1] / "static"
    return (static_dir / "console.html").read_text(encoding="utf-8") + "\\n" + (
        static_dir / "console.js"
    ).read_text(encoding="utf-8")
