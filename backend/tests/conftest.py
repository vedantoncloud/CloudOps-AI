"""Keep the assembled app's process-wide limiter from coupling unrelated tests."""

import os


# Rate-limit behavior has dedicated unit tests with an explicit small limiter.
# The shared TestClient app should not rate-limit the suite based on test order.
os.environ.setdefault("CLOUDOPS_RATE_LIMIT_REQUESTS", "10000")
