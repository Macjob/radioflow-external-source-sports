import argparse
import json
import os

from dotenv import load_dotenv

from app.config import load_config
from app.football_client import FootballDataClient
from app.match_service import get_relevant_matches
from app.radioflow_blocks import to_radioflow_suggestions
from app.radioflow_publisher import PublishResult, RadioflowPublisher

REQUIRED_ENV = [
    "FOOTBALL_DATA_API_KEY",
    "RADIOFLOW_BASE_URL",
    "RADIOFLOW_SOURCE_KEY",
    "RADIOFLOW_SOURCE_TOKEN",
]


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    load_dotenv()

    missing = [name for name in REQUIRED_ENV if not os.getenv(name)]
    if missing:
        print("Missing required environment variables:")
        for name in missing:
            print(f"- {name}")
        print("Add them to .env before publishing RadioFlow suggestions.")
        return 1

    config = load_config()
    api_key = os.environ["FOOTBALL_DATA_API_KEY"]
    source_key = os.environ["RADIOFLOW_SOURCE_KEY"]
    client = FootballDataClient(api_key=api_key)

    events = get_relevant_matches(config, client, country=args.country)
    suggestions = to_radioflow_suggestions(events, config, source_key=source_key)

    _print_header(args.country, args.dry_run, len(events), len(suggestions))

    if args.dry_run:
        for suggestion in suggestions:
            print(json.dumps(suggestion.model_dump(by_alias=True, exclude_none=True), ensure_ascii=False, indent=2))
        _print_summary(len(events), len(suggestions), created=0, deduplicated=0, failed=0)
        return 0

    publisher = RadioflowPublisher(
        base_url=os.environ["RADIOFLOW_BASE_URL"],
        source_token=os.environ["RADIOFLOW_SOURCE_TOKEN"],
    )

    results = [publisher.publish_suggestion(suggestion) for suggestion in suggestions]
    for suggestion, result in zip(suggestions, results, strict=True):
        _print_result(suggestion.title, result)

    created = sum(1 for result in results if result.ok and result.status == "created")
    deduplicated = sum(1 for result in results if result.ok and result.status == "deduplicated")
    failed = sum(1 for result in results if not result.ok)
    _print_summary(len(events), len(suggestions), created=created, deduplicated=deduplicated, failed=failed)
    return 1 if failed else 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish sports suggestions to RadioFlow.")
    parser.add_argument("--dry-run", action="store_true", help="Print RadioFlow payloads without publishing.")
    parser.add_argument("--country", help="Filter relevant matches by configured country.")
    return parser.parse_args(argv)


def _print_header(country: str | None, dry_run: bool, found: int, prepared: int) -> None:
    print("RadioFlow Sports Publisher")
    print()
    print(f"Country: {country or 'all'}")
    print(f"Dry run: {str(dry_run).lower()}")
    print(f"Found relevant matches: {found}")
    print(f"Prepared suggestions: {prepared}")
    print()


def _print_result(title: str, result: PublishResult) -> None:
    if result.ok:
        suffix = f" - suggestionId={result.suggestion_id}" if result.suggestion_id else ""
        print(f"[{result.status}] {title}{suffix}")
        return

    http_status = f"{result.http_status} " if result.http_status is not None else ""
    code = f"{result.code}: " if result.code else ""
    message = result.message or "Unknown publish failure."
    print(f"[failed] {title} - {http_status}{code}{message}")


def _print_summary(found: int, prepared: int, created: int, deduplicated: int, failed: int) -> None:
    print()
    print("Summary:")
    print(f"- found: {found}")
    print(f"- prepared: {prepared}")
    print(f"- created: {created}")
    print(f"- deduplicated: {deduplicated}")
    print(f"- failed: {failed}")


if __name__ == "__main__":
    raise SystemExit(main())
