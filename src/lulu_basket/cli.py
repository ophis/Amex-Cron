import argparse
import math
import sys
import time
from collections.abc import Callable

from lulu_basket.errors import SolveError, ToolError
from lulu_basket.scrape.fetch import Fetcher, HttpGet, curl_http_get
from lulu_basket.scrape.scrape import scrape
from lulu_basket.snapshot import load_snapshot, write_snapshot
from lulu_basket.solve.items import build_items
from lulu_basket.solve.knapsack import top_combinations
from lulu_basket.solve.report import render

DEFAULT_TARGET_CENTS = 7500
DEFAULT_SNAPSHOT = "snapshot.json"
DEFAULT_DELAY_SECONDS = 1.0


def main(
    argv: list[str] | None = None,
    *,
    http_get: HttpGet | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command in ("scrape", "run"):
            _scrape(args, http_get, sleep)
        if args.command in ("solve", "run"):
            sys.stdout.write(_solve(args))
    except ToolError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def _scrape(args: argparse.Namespace, http_get: HttpGet | None, sleep: Callable[[float], None]):
    fetcher = Fetcher(curl_http_get() if http_get is None else http_get, sleep, args.delay)
    snapshot = scrape(args.target, fetcher, lambda line: print(line, file=sys.stderr))
    write_snapshot(args.snapshot, snapshot)


def _solve(args: argparse.Namespace) -> str:
    snapshot = load_snapshot(args.snapshot)
    if args.target > snapshot.target_cents:
        raise SolveError(
            f"target {args.target} exceeds snapshot target {snapshot.target_cents}; "
            f"re-run scrape --target {args.target}"
        )
    items = build_items(snapshot.skus, args.target)
    return render(snapshot, args.target, top_combinations(items, args.target))


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid int value: {text!r}") from None
    if value <= 0:
        raise argparse.ArgumentTypeError(f"must be a positive integer: {text!r}")
    return value


def _delay_seconds(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid float value: {text!r}") from None
    if not math.isfinite(value) or value < 0:
        raise argparse.ArgumentTypeError(f"must be a finite number >= 0: {text!r}")
    return value


def _parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--target",
        type=_positive_int,
        default=DEFAULT_TARGET_CENTS,
        metavar="CENTS",
        help="subtotal limit in cents (default: %(default)s)",
    )
    common.add_argument(
        "--snapshot",
        default=DEFAULT_SNAPSHOT,
        metavar="PATH",
        help="snapshot file (default: %(default)s)",
    )
    crawl = argparse.ArgumentParser(add_help=False)
    crawl.add_argument(
        "--delay",
        type=_delay_seconds,
        default=DEFAULT_DELAY_SECONDS,
        metavar="SECONDS",
        help="pause before every request but the first (default: %(default)s)",
    )

    parser = argparse.ArgumentParser(
        prog="lulu-basket",
        description="Fill a lululemon.com basket as close to a target subtotal as possible.",
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="{scrape,solve,run}")
    commands.add_parser(
        "scrape", parents=[common, crawl], help="crawl lululemon.com into the snapshot file"
    )
    commands.add_parser(
        "solve", parents=[common], help="print the top 3 combinations from the snapshot"
    )
    commands.add_parser("run", parents=[common, crawl], help="scrape, then solve")
    return parser
