import json

from alpha_workbench.cli import main


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
