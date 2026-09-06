"""Load and render the config-driven conference timeline."""

from __future__ import annotations

from dataclasses import dataclass
import datetime
import html
from pathlib import Path
import re
from urllib.parse import urlparse

import yaml


CONFERENCE_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
CONFERENCE_FIELDS = {"id", "name", "enabled", "homepage", "meetings"}
MEETING_FIELDS = {
    "edition", "status", "start_date", "end_date", "location", "source_url", "verified_on", "website", "proceedings_url"
}
MEETING_STATUSES = {"confirmed", "dates_pending"}


@dataclass(frozen=True, slots=True)
class ConferenceMeeting:
    edition: str
    status: str
    start_date: datetime.date | None
    end_date: datetime.date | None
    location: str
    source_url: str
    verified_on: datetime.date
    website: str | None = None
    proceedings_url: str | None = None


@dataclass(frozen=True, slots=True)
class Conference:
    id: str
    name: str
    homepage: str
    meetings: tuple[ConferenceMeeting, ...]


def _mapping(value: object, context: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be a mapping")
    return value


def _text(value: object, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} must be a non-empty string")
    return value.strip()


def _date(value: object, context: str) -> datetime.date:
    if isinstance(value, datetime.datetime):
        value = value.date()
    if isinstance(value, datetime.date):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{context} must be an ISO date")
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{context} must be an ISO date") from error


def _https_url(value: object, context: str) -> str:
    url = _text(value, context)
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError(f"{context} must be an HTTPS URL")
    return url


def _reject_unknown_fields(payload: dict, allowed: set[str], context: str) -> None:
    unknown = sorted(str(field) for field in set(payload) - allowed)
    if unknown:
        raise ValueError(f"{context} has unknown fields: {', '.join(unknown)}")


def _load_meeting(payload: object, context: str, as_of: datetime.date) -> ConferenceMeeting:
    data = _mapping(payload, context)
    _reject_unknown_fields(data, MEETING_FIELDS, context)
    edition = _text(data.get("edition"), f"{context}.edition")
    status = _text(data.get("status"), f"{context}.status")
    if status not in MEETING_STATUSES:
        raise ValueError(f"{context}.status must be one of: {', '.join(sorted(MEETING_STATUSES))}")

    has_start = data.get("start_date") is not None
    has_end = data.get("end_date") is not None
    if has_start != has_end:
        raise ValueError(f"{context} start_date and end_date must be provided together")
    start_date = _date(data["start_date"], f"{context}.start_date") if has_start else None
    end_date = _date(data["end_date"], f"{context}.end_date") if has_end else None
    if status == "confirmed" and start_date is None:
        raise ValueError(f"{context} confirmed meetings require start_date and end_date")
    if status == "dates_pending" and start_date is not None:
        raise ValueError(f"{context} dates_pending meetings must omit start_date and end_date")
    if start_date is not None and start_date > end_date:
        raise ValueError(f"{context}.start_date must not follow end_date")

    verified_on = _date(data.get("verified_on"), f"{context}.verified_on")
    if verified_on > as_of:
        raise ValueError(f"{context}.verified_on must not be in the future")
    return ConferenceMeeting(
        edition=edition,
        status=status,
        start_date=start_date,
        end_date=end_date,
        location=_text(data.get("location"), f"{context}.location"),
        source_url=_https_url(data.get("source_url"), f"{context}.source_url"),
        verified_on=verified_on,
        website=_https_url(data["website"], f"{context}.website") if data.get("website") is not None else None,
        proceedings_url=_https_url(data["proceedings_url"], f"{context}.proceedings_url") if data.get("proceedings_url") is not None else None,
    )


def load_conferences(
    path: str | Path, *, as_of: datetime.date | None = None
) -> tuple[Conference, ...]:
    """Load enabled conferences without discarding historical or future editions."""
    config_path = Path(path)
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    root = _mapping(payload, f"conference config {config_path}")
    if set(root) - {"version", "conferences"}:
        _reject_unknown_fields(root, {"version", "conferences"}, "conference config")
    if root.get("version") != 1:
        raise ValueError(f"Unsupported conference config version: {root.get('version')!r}")
    raw_conferences = root.get("conferences")
    if not isinstance(raw_conferences, list):
        raise ValueError("conference config conferences must be a list")

    today = as_of or datetime.date.today()
    conferences: list[Conference] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(raw_conferences):
        context = f"conferences[{index}]"
        data = _mapping(item, context)
        _reject_unknown_fields(data, CONFERENCE_FIELDS, context)
        conference_id = _text(data.get("id"), f"{context}.id")
        if not CONFERENCE_ID_PATTERN.fullmatch(conference_id):
            raise ValueError(f"{context}.id must be a lowercase URL-safe identifier")
        if conference_id in seen_ids:
            raise ValueError(f"Duplicate conference id: {conference_id}")
        seen_ids.add(conference_id)
        enabled = data.get("enabled")
        if not isinstance(enabled, bool):
            raise ValueError(f"{context}.enabled must be true or false")
        meetings_data = data.get("meetings")
        if not isinstance(meetings_data, list):
            raise ValueError(f"{context}.meetings must be a list")
        meetings = tuple(
            _load_meeting(meeting, f"{context}.meetings[{meeting_index}]", today)
            for meeting_index, meeting in enumerate(meetings_data)
        )
        editions = [meeting.edition for meeting in meetings]
        if len(editions) != len(set(editions)):
            raise ValueError(f"{context}.meetings contains duplicate editions")
        if enabled:
            conferences.append(Conference(
                id=conference_id,
                name=_text(data.get("name"), f"{context}.name"),
                homepage=_https_url(data.get("homepage"), f"{context}.homepage"),
                meetings=meetings,
            ))
    return tuple(conferences)


def _meeting_date_label(meeting: ConferenceMeeting) -> str:
    if meeting.start_date is None or meeting.end_date is None:
        return "日期未公布"
    start = meeting.start_date
    end = meeting.end_date
    if start == end:
        return start.strftime("%Y.%m.%d")
    if start.year == end.year and start.month == end.month:
        return f"{start.strftime('%Y.%m.%d')}–{end.strftime('%m.%d')}"
    if start.year == end.year:
        return f"{start.strftime('%Y.%m.%d')}–{end.strftime('%m.%d')}"
    return f"{start.strftime('%Y.%m.%d')}–{end.strftime('%Y.%m.%d')}"


def _meeting_year(meeting: ConferenceMeeting) -> int:
    if meeting.start_date is not None:
        return meeting.start_date.year
    year = re.search(r"\b(20\d{2})\b", meeting.edition)
    if year is None:
        raise ValueError(f"Pending meeting edition must include its year: {meeting.edition}")
    return int(year.group(1))


def render_conference_section(
    conferences: tuple[Conference, ...], *, as_of: datetime.date | None = None
) -> str:
    """Render the current calendar year and two preceding years in chronological order."""
    today = as_of or datetime.date.today()
    first_year = today.year - 2
    meetings = sorted(
        (
            (conference, meeting)
            for conference in conferences
            for meeting in conference.meetings
            if first_year <= _meeting_year(meeting) <= today.year
        ),
        key=lambda item: (
            _meeting_year(item[1]),
            item[1].start_date or datetime.date(_meeting_year(item[1]), 12, 31),
            item[0].name,
        ),
    )
    cards = []
    for conference, meeting in meetings:
        year = _meeting_year(meeting)
        pending = meeting.status == "dates_pending"
        state = "status-announced" if pending else "status-released"
        status_label = "日期未公布" if pending else ("已举办" if meeting.end_date < today else "已确认")
        date_label = html.escape(_meeting_date_label(meeting))
        date_markup = date_label if pending else f'<time datetime="{meeting.start_date.isoformat()}">{date_label}</time>'
        website = html.escape(meeting.website or meeting.source_url, quote=True)
        proceedings = (
            f'<a href="{html.escape(meeting.proceedings_url, quote=True)}">录用论文</a>'
            if meeting.proceedings_url else '<span>论文库待公布</span>'
        )
        cards.append(f"""      <li class="timeline-release conference-release {state}" data-conference-year="{year}">
        <span class="timeline-dot" aria-hidden="true"></span>
        <p class="conference-year">{year}</p>
        {date_markup}
        <h3><a href="{website}">{html.escape(meeting.edition)}</a></h3>
        <p class="conference-location">{html.escape(meeting.location)}</p>
        <p class="conference-status">{status_label}</p>
        <div class="conference-links"><a href="{website}">官网</a>{proceedings}</div>
        <footer><a href="{html.escape(meeting.source_url, quote=True)}">官方来源</a><span>核验于 {meeting.verified_on.strftime('%Y.%m.%d')}</span></footer>
      </li>""")
    if cards:
        timeline = (
            '<div class="milestone-timeline-viewport conference-timeline" tabindex="0" '
            'aria-label="会议时间线，可使用左右方向键浏览" data-drag-scroll '
            f'data-conference-current-year="{today.year}">\n'
            '    <ol class="milestone-timeline">\n'
            + "\n".join(cards)
            + "\n    </ol>\n  </div>"
        )
    else:
        timeline = '<p class="conference-empty">近三年暂无会议信息。</p>'
    return f"""<section class="topic-section conference-section" id="conferences" data-topic-section="conferences" data-topic-aliases="">
  <header class="topic-header">
    <p>Conference</p>
    <h2>Timeline</h2>
    <span>{first_year}–{today.year} · {len(conferences)} 个会议</span>
  </header>
  {timeline}
</section>"""
