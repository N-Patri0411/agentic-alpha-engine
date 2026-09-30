import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from alpha_workbench.alpha.pipeline import _prices_available_at_snapshot, run_offline_pipeline
from alpha_workbench.cli import main
from alpha_workbench.graph_registry import GraphSnapshot


def test_backtest_cli_emits_a_machine_readable_report(capsys: object) -> None:
    assert (
        main(
            [
                "backtest",
                "--prices",
                "data/demo_prices.csv",
                "--factors",
                "data/demo_factors.csv",
                "--as-of",
                "2024-01-05T21:00:00+00:00",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out  # type: ignore[attr-defined]

    report = json.loads(output)
    assert report["periods"] == 3
    assert report["trial_count"] == 1


def test_alpha_run_writes_offline_receipt(tmp_path: Path, capsys: object) -> None:
    receipt_path = tmp_path / "receipt.json"
    assert main(
        [
            "alpha-run",
            "--prices",
            "data/demo_prices.csv",
            "--features",
            "data/demo_factors.csv",
            "--expression",
            "Mean(score,2)",
            "--as-of",
            "2024-01-05T21:00:00+00:00",
            "--receipt",
            str(receipt_path),
        ]
    ) == 0
    summary = json.loads(capsys.readouterr().out)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert summary["receipt_sha256"] == receipt["receipt_sha256"]
    assert receipt["formula"] == "Mean(score,2)"
    assert "backtest" in receipt and "gatekeeper" in receipt


def test_pipeline_uses_locked_oos_holdout_before_paper_targets() -> None:
    start = datetime(2024, 1, 1)
    dates = [start + timedelta(days=index) for index in range(43)]
    prices = pd.DataFrame(
        [
            {
                "date": date,
                "ticker": ticker,
                "close": (100 + index) if ticker == "Z" else (100 - index),
                "available_at": date + timedelta(hours=21),
            }
            for index, date in enumerate(dates)
            for ticker in ("A", "Z")
        ]
    )
    features = pd.DataFrame(
        [
            {
                "date": date,
                "ticker": ticker,
                "score": 1.0 if ticker == "Z" else -1.0,
                "available_at": date + timedelta(hours=20),
            }
            for date in dates[:-1]
            for ticker in ("A", "Z")
        ]
    )
    receipt = run_offline_pipeline(
        prices,
        features,
        feature_names=["score"],
        expression="Rank(score)",
        as_of_time=datetime(2024, 3, 1, tzinfo=UTC),
    )
    assert receipt["backtest"]["split"]["holdout_periods"] == 20
    assert receipt["backtest"]["oos"]["candidate"]["periods"] >= 20
    assert receipt["gatekeeper"]["decision"] == "accepted", receipt["gatekeeper"]
    assert receipt["paper_portfolio"]["status"] == "paper_only"


def test_graph_snapshot_filter_keeps_same_day_bar_published_after_snapshot() -> None:
    snapshot = GraphSnapshot.from_json(
        Path("data/graph_snapshots/semiconductor-sec-reviewed-v1.json")
    )
    created = max(
        [snapshot.created_at]
        + [
            timestamp
            for edge in snapshot.edges
            for timestamp in (edge.evidence.filing_date, edge.review.reviewed_at)
        ]
    )
    prices = pd.DataFrame(
        {
            "date": [created.date()],
            "ticker": ["TSM"],
            "close": [100.0],
            "available_at": [created + timedelta(hours=2)],
        }
    )
    filtered = _prices_available_at_snapshot(prices, snapshot)
    assert len(filtered) == 1
