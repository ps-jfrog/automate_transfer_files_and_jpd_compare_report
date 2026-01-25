from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo


@dataclass
class ScheduleWindow:
    start: datetime
    end: datetime | None


def parse_hhmm(value: str) -> time:
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid time format: {value}")
    return time(hour=int(parts[0]), minute=int(parts[1]))


def next_window(now: datetime, start_hhmm: str, end_hhmm: str | None, tz: str) -> ScheduleWindow:
    zone = ZoneInfo(tz)
    local_now = now.astimezone(zone)
    start_time = parse_hhmm(start_hhmm)
    start_dt = datetime.combine(local_now.date(), start_time, zone)
    if start_dt <= local_now:
        start_dt += timedelta(days=1)

    end_dt = None
    if end_hhmm:
        end_time = parse_hhmm(end_hhmm)
        end_dt = datetime.combine(start_dt.date(), end_time, zone)
        if end_dt <= start_dt:
            end_dt += timedelta(days=1)

    return ScheduleWindow(start=start_dt, end=end_dt)


def sleep_seconds_until(target: datetime) -> int:
    now = datetime.now(tz=target.tzinfo)
    delta = target - now
    return max(int(delta.total_seconds()), 0)


def get_missed_windows(
    last_run_time: datetime,
    now: datetime,
    start_hhmm: str,
    end_hhmm: str | None,
    tz: str,
) -> list[ScheduleWindow]:
    """
    Get list of missed schedule windows between last_run_time and now.
    
    Returns:
        List of ScheduleWindow objects representing missed scheduled times
    """
    zone = ZoneInfo(tz)
    local_last = last_run_time.astimezone(zone)
    local_now = now.astimezone(zone)
    start_time = parse_hhmm(start_hhmm)
    
    missed = []
    current_date = local_last.date()
    
    while current_date <= local_now.date():
        window_start = datetime.combine(current_date, start_time, zone)
        
        # Only include if it's after last_run_time and before now
        if window_start > local_last and window_start < local_now:
            window_end = None
            if end_hhmm:
                end_time = parse_hhmm(end_hhmm)
                window_end = datetime.combine(current_date, end_time, zone)
                if window_end <= window_start:
                    window_end += timedelta(days=1)
            
            missed.append(ScheduleWindow(start=window_start, end=window_end))
        
        current_date += timedelta(days=1)
    
    return missed
