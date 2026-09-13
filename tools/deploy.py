"""Retired deployment entry point kept only for an explicit fail-closed error."""
import sys


RETIRED_DEPLOY_MESSAGE = (
    "This deployment entry point is retired. Use the reviewed release command: "
    "python tools/deploy_realism_release.py --execute --allow-unauthenticated-public"
)


def main():
    print(RETIRED_DEPLOY_MESSAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
