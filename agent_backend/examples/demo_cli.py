"""Example CLI: argparse subcommands with sleep + intermittent prints (no other side effects)."""

from __future__ import annotations

import argparse
import sys
import time


def cmd_slow() -> None:
    for i in range(5):
        print(f"slow tick {i}", flush=True)
        time.sleep(0.4)


def cmd_sleep(seconds: float) -> None:
    n = 4
    step = seconds / n
    for i in range(n):
        print(f"sleep step {i}", flush=True)
        time.sleep(step)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="demo_cli")
    sub = parser.add_subparsers(dest="command", required=True)

    p_slow = sub.add_parser("slow", help="short sleeps with prints")
    p_sleep = sub.add_parser("sleep", help="longer sleep split into steps")
    p_sleep.add_argument(
        "--seconds",
        type=float,
        default=2.0,
        help="total sleep duration",
    )

    args = parser.parse_args(argv)

    if args.command == "slow":
        cmd_slow()
    elif args.command == "sleep":
        cmd_sleep(args.seconds)
    else:
        parser.error(f"unknown command {args.command!r}")


if __name__ == "__main__":
    main(sys.argv[1:])
