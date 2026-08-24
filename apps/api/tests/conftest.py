import os

# Test hermeticity: force transactional auth email OFF before anything imports the app
# (which caches Settings at import). An OS env var overrides the developer's git-ignored
# .env, so the suite always uses the provider-neutral fake sender and NEVER calls real
# Resend — even when a developer has AUTH_EMAIL_ENABLED=true and a real key configured
# locally for the manual smoke. Tests that need enabled/real behavior build their own
# Settings explicitly.
os.environ["AUTH_EMAIL_ENABLED"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from sky_bridge_jet.main import app  # noqa: E402
from sky_bridge_jet.modules.iam import router as iam_router  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_auth_rate_limiters() -> None:
    """Isolate the per-process, module-level auth rate limiters between tests.

    The login limiter is keyed per-email, so unique-email tests never collide; but the
    IP-keyed register/verification-resend limiters (Phase 9.2.A) would otherwise share a
    single bucket across every test in the process (all requests present the same
    TestClient host). Clearing them before each test keeps the production per-IP policy
    intact while letting each test exercise it in isolation.
    """
    for limiter in (
        iam_router._login_limiter,
        iam_router._reset_limiter,
        iam_router._recover_limiter,
        iam_router._register_limiter,
        iam_router._resend_limiter,
    ):
        limiter.clear()


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client
