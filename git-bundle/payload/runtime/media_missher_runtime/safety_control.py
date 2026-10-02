"""Local operator maintenance; never opens a browser or starts collection."""
import argparse
import json

from .shared_safety import (SharedSafetyError, acknowledge_platform_risk,
                            collection_lease, platform_risk_status, runtime_home)
from .xhs_policy import SafetyBlocked, SharedXhsSafetyGate


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acknowledge-risk", action="store_true",
                        help="Acknowledge one platform after manually inspecting its normal browser page; cooldowns remain")
    parser.add_argument("--platform", choices=("bilibili", "xhs", "douyin", "weibo", "x"))
    args = parser.parse_args(argv)
    if args.acknowledge_risk and not args.platform:
        parser.error("--acknowledge-risk requires --platform")
    try:
        with collection_lease(runtime_home(), inherit=True, state_only=True):
            if args.acknowledge_risk:
                acknowledge_platform_risk(args.platform)
            result = platform_risk_status()
            result["xhs"] = SharedXhsSafetyGate().status()
            result["blocked"] = bool(result["platforms"]) or result["xhs"]["blocked"]
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (SharedSafetyError, SafetyBlocked, ValueError, OSError) as error:
        code = "collection-busy" if str(error) == "collection-busy" else "shared-state-invalid"
        print(json.dumps({"blocked": True, "reason": code}))
        return 78


if __name__ == "__main__":
    raise SystemExit(main())
