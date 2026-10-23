"""Feature release scripts written before the membership cutover are retired.

They publish hand-picked file sets, check production through the old public
address or anonymous APIs, and several write production without any flag.
Since 2026-10-23 every release goes through `tools/deploy_realism_release.py`
(`--check-remote` for a read-only check, `--execute` to publish). The scripts'
main() stays importable so their offline tests keep documenting the logic;
re-enabling one needs a reviewed change to its entry point.
"""
import sys

OFFICIAL_RELEASE = "tools/deploy_realism_release.py --execute"


def refuse(script):
    """Stop a retired entry point before it reads credentials or connects."""
    name = str(script).replace("\\", "/").rsplit("/", 1)[-1]
    raise SystemExit(
        f"{name} is retired since the membership cutover (2026-10-23); "
        f"release through {OFFICIAL_RELEASE} (read-only check: --check-remote)."
    )
