"""Capture or replay the current calculation in a new output directory."""

import argparse
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

import requests


BUNDLE = Path(__file__).resolve().parent


def main():
    """Run the saved processors with recorded HTTP responses."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--normalize-missing-elo", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    metadata = json.loads((BUNDLE / "metadata.json").read_text())
    season = metadata["season"]
    frozen = datetime.fromisoformat(metadata["captured_local_time"])
    responses = BUNDLE / "inputs" / "http"
    responses.mkdir(exist_ok=True)
    failures = []
    original_send = requests.Session.send

    def send(session, request, **kwargs):
        """Retain successful responses or replay them without network access."""
        key = hashlib.sha256(request.url.encode()).hexdigest()
        body_path = responses / f"{key}.body"
        info_path = responses / f"{key}.json"
        if body_path.exists() and info_path.exists():
            info = json.loads(info_path.read_text())
            response = requests.Response()
            response.status_code = info["status"]
            response._content = body_path.read_bytes()
            response.url = info["url"]
            response.headers["Content-Type"] = info["content_type"]
            response.request = request
            return response
        if not args.capture:
            raise RuntimeError(f"Missing recorded response: {request.url}")
        try:
            response = original_send(session, request, **kwargs)
            response.raise_for_status()
            response.json()
        except Exception as error:
            failures.append(f"{request.url}: {error}")
            raise
        body_path.write_bytes(response.content)
        info_path.write_text(json.dumps({
            "url": request.url, "status": response.status_code,
            "content_type": response.headers.get("Content-Type", ""),
            "retrieved_utc": datetime.now(timezone.utc).isoformat(),
            "sha256": hashlib.sha256(response.content).hexdigest(),
        }, indent=2) + "\n")
        return response

    class FrozenDateTime(datetime):
        """Keep date-dependent behavior fixed for replay."""

        @classmethod
        def now(cls, tz=None):
            return frozen if tz is None else frozen.astimezone(tz)

    sys.path.insert(0, str(BUNDLE / "source"))
    import config.manager as configuration
    import rating_fetcher.api_client as ratings_api
    from rating_fetcher.processor import RatingProcessor
    import results_processor.processor as results
    from rilton_processor.processor import RiltonProcessor
    import standings_generator.excel_exporter as exporter
    from standings_generator.processor import StandingsProcessor

    (output / "config").mkdir()
    shutil.copy2(BUNDLE / "inputs" / "tournaments.json", output / "config" / "tournaments.json")
    data = output / "data"
    data.mkdir()
    for section in (1800, 2200):
        filename = f"rilton-u{section}-{season}.xls"
        shutil.copy2(BUNDLE / "inputs" / "rilton" / filename, data / filename)
    configuration.CONFIG_FILE = str(output / "config" / "tournaments.json")
    ratings_api.datetime = results.datetime = exporter.datetime = FrozenDateTime
    requests.Session.send = send
    if args.normalize_missing_elo:
        original_classify = RatingProcessor.add_klass_classification

        def classify(processor, players):
            """Treat null Elo as zero for this explicitly adjusted reference."""
            missing = [player["id"] for player in players if player.get("elo") is None]
            (output / "normalization.json").write_text(json.dumps({
                "rule": "Replace missing or null elo with an empty mapping before classification",
                "member_ids": missing,
            }, indent=2) + "\n")
            return original_classify(processor, [
                {**player, "elo": {}} if player.get("elo") is None else player
                for player in players
            ])

        RatingProcessor.add_klass_classification = classify
    os.chdir(output)
    with (output / "generation.log").open("w") as log, redirect_stdout(log), redirect_stderr(log):
        RatingProcessor(season, str(data)).process()
        processor = results.ResultsProcessor(season)
        processor.data_dir = str(data)
        processor.tournaments_dir = str(output / "tournaments")
        processor.run()
        RiltonProcessor(season, str(data)).process()
        standings = StandingsProcessor(season)
        standings.process_and_export(str(output / "output"))
        (output / "standings.json").write_text(json.dumps({
            klass: [asdict(player) for player in players.values()]
            for klass, players in standings.player_standings.items()
        }, ensure_ascii=False, indent=2) + "\n")
    if failures:
        raise RuntimeError("Capture had HTTP failures; outputs are not complete: " + "; ".join(failures))
    configured = json.loads((BUNDLE / "inputs" / "tournaments.json").read_text())["tournaments"]
    for tournament in configured:
        matches = list((output / "tournaments" / str(season)).glob(f"*-{tournament['id']}.json"))
        if len(matches) != 1:
            raise RuntimeError(f"Missing tournament output: {tournament['id']}")
    print(f"Generated reference outputs in {output}")


if __name__ == "__main__":
    main()
