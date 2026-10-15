"""Retired compatibility shims for lazy dependency installs.

The real provisioning path is PM (``pm`` package: extras + prepared backends);
this module only keeps the old import shape alive so plugins constructed before
the P0 light-core cut fail loudly instead of at import time. The historical
updater handoff that used to live here is gone with the updater itself
(FORK.org): there is no update to hand off to.
"""

from typing import NoReturn


def ensure(feature: str, *, prompt: bool = True) -> NoReturn:
    # Never claims readiness; callers see a dependency-unavailable failure.
    raise ImportError(f"lazy install of {feature!r} is retired; provision it with `hermes pm`.")


def install_specs(specs: list[str] | tuple[str, ...], *, timeout: int = 300,
                  constraints: list | None = None, dry_run: bool = False) -> NoReturn:
    # Plugins still call this retired API during normal agent construction.
    raise ImportError(
        "tools.lazy_deps.install_specs is retired; runtime dependency "
        "installation is unavailable. Use `hermes pm`."
    )
