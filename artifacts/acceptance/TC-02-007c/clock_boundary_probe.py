"""Exercise the real session test with a response-time crossing or bad cookie TTL.

This diagnostic is outside pytest's collection path. It changes only in-memory
clock/cookie behavior, restores it with the test's monkeypatch fixture, and uses
the existing SQLite real-HTTP fixture. No provider or PostgreSQL claim is made.
"""

import argparse
import os
import sys
from pathlib import Path

import pytest


class Probe:
    def __init__(self, mode):
        self.mode = mode

    @pytest.hookimpl(tryfirst=True)
    def pytest_runtest_call(self, item):
        if (
            item.originalname
            != "test_creation_preserves_the_existing_and_target_absolute_deadlines"
        ):
            return
        from tests.release import test_session_persistence as case

        patch = item.funcargs["monkeypatch"]
        if self.mode == "crossing":
            real_reissue = case.reissue

            def reissue_then_cross_second(*args, **kwargs):
                issued_at = int(case.time.time())
                patch.setattr(case.session.time, "time", lambda: issued_at + 0.1)
                response = real_reissue(*args, **kwargs)
                cookie = case.issued_cookie(response)
                signed = case.session.verify_token(cookie.value)
                print(
                    f"bound={item.callspec.params['bound']} "
                    f"issued_at={issued_at} exp={signed['exp']} "
                    f"max_age={cookie['max-age']}"
                )
                # Model response transport/observation across one whole second.
                # Do not replace signing, the response, the database, or auth.
                patch.setattr(case.session.time, "time", lambda: issued_at + 1.1)
                print(f"observed_remaining={signed['exp'] - int(case.time.time())}")
                return response

            patch.setattr(case, "reissue", reissue_then_cross_second)
        else:
            real_cookie_kwargs = case.workspaces._session_cookie_kwargs

            def extend_cookie_one_second(max_age, *, persistent):
                kwargs = real_cookie_kwargs(max_age, persistent=persistent)
                if persistent:
                    kwargs["max_age"] += 1
                return kwargs

            # Deliberately wrong output: the exact assertion must reject +1s.
            patch.setattr(case.workspaces, "_session_cookie_kwargs", extend_cookie_one_second)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("crossing", "extend-cookie"))
    args = parser.parse_args()
    api = Path(__file__).resolve().parents[3] / "apps" / "api"
    os.chdir(api)
    sys.path.insert(0, str(api))
    # No PostgreSQL server exists locally. Fail fast in the shared fixture's
    # optional residue probe; each selected case uses its real SQLite database.
    os.environ["TC_TEST_DATABASE_URL"] = (
        "postgresql://127.0.0.1:1/trustcopilot_test?connect_timeout=1"
    )
    return pytest.main(
        [
            "tests/release/test_session_persistence.py",
            "-k",
            "sqlite and test_creation_preserves_the_existing_and_target_absolute_deadlines",
            "-q",
            "-s",
            "--tb=short",
        ],
        plugins=[Probe(args.mode)],
    )


if __name__ == "__main__":
    raise SystemExit(main())
