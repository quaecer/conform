# SPDX-License-Identifier: Apache-2.0
"""Command-line entry point for running a suite."""

import argparse
import math
import shlex
from pathlib import Path

from .suite import load_suite, report, run_case, summary


def main() -> int:
    """Run each supplied case once and write EARL plus a JSON summary."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["run"])
    parser.add_argument("--suite", required=True, type=Path)
    parser.add_argument("--impl", required=True)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()
    try:
        command = shlex.split(args.impl)
        if not command or not math.isfinite(args.timeout) or args.timeout <= 0:
            raise ValueError("a command and a positive finite timeout are required")
        cases = load_suite(args.suite)
        # Exclusive creation prevents replacing an earlier run.
        with args.report.open("x", encoding="utf-8") as stream:
            results = tuple(run_case(case, command, args.timeout) for case in cases)
            stream.write(report(results))
        print(summary(results))
    except (OSError, ValueError, RecursionError) as error:
        parser.exit(2, f"conform: {error}\n")
    return int(any(result.outcome != "passed" for result in results))


if __name__ == "__main__":
    raise SystemExit(main())
