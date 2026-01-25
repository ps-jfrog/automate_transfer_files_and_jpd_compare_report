from datetime import datetime, timezone

from jfrog_transfer_automation.util.time import next_window, parse_hhmm


def test_parse_hhmm() -> None:
    value = parse_hhmm("01:30")
    assert value.hour == 1
    assert value.minute == 30


def test_next_window_future_start() -> None:
    now = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    window = next_window(now, "01:00", None, "UTC")
    assert window.start.hour == 1
