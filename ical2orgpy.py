#!/usr/bin/env python
from __future__ import print_function

import sys
import traceback
from builtins import object
from datetime import date, datetime, timedelta

import click
import recurring_ical_events
from icalendar import Calendar
from pytz import all_timezones, timezone, utc
from tzlocal import get_localzone


def orgDatetime(dt, tz):
    """Timezone aware datetime to YYYY-MM-DD DayofWeek HH:MM str in localtime."""
    return dt.astimezone(tz).strftime("<%Y-%m-%d %a %H:%M>")


def orgDate(dt, tz):
    """Timezone aware date to YYYY-MM-DD DayofWeek in localtime."""
    if hasattr(dt, "astimezone"):
        dt = dt.astimezone(tz)
    return dt.strftime("<%Y-%m-%d %a>")


class IcalParsingError(Exception):
    pass


class Convertor(object):
    RECUR_TAG = "\t:RECURRING:"

    # Do not change anything below

    def __init__(self, days=90, tz=None, continue_on_error=False):
        """days: Window length in days (left & right from current time). Has
        to be positive.
        """
        self.tz = timezone(tz) if tz else get_localzone()
        self.days = days
        self.continue_on_error = continue_on_error

    def __call__(self, fh, fh_w):
        try:
            cal = Calendar.from_ical(fh.read())
        except ValueError as e:
            msg = "ERROR parsing ical file: %s" % str(e)
            raise IcalParsingError(msg)

        fh_w.write("".join(self.create_org_calendar(cal)))

    def create_org_calendar(self, calendar):
        now = datetime.now(utc)
        start = now - timedelta(days=self.days)
        end = now + timedelta(days=self.days)
        for comp in recurring_ical_events.of(
            calendar, keep_recurrence_attributes=True
        ).between(start, end):
            try:
                yield self.create_entry(comp)
            except Exception:
                print("Exception when processing:\n", file=sys.stderr)
                print(comp.to_ical().decode("utf-8") + "\n", file=sys.stderr)
                if self.continue_on_error:
                    print(traceback.format_exc(), file=sys.stderr)
                else:
                    raise

    def create_entry(self, comp):
        fh_w = []
        summary = ""
        if "SUMMARY" in comp:
            summary = comp["SUMMARY"].to_ical().decode("utf-8")
            summary = summary.replace("\\,", ",")
        location = ""
        if "LOCATION" in comp:
            location = comp["LOCATION"].to_ical().decode("utf-8")
            location = location.replace("\\,", ",")
        if not any((summary, location)):
            summary = "(No title)"
        else:
            summary += " - " + location if location else ""
        tag = "RRULE" in comp and self.RECUR_TAG or ""
        fh_w.append("* {}{}\n".format(summary, tag))

        ev_start = None
        if "DTSTART" in comp:
            ev_start = comp["DTSTART"].dt

        ev_end = None
        duration = None
        if "DTEND" in comp:
            ev_end = comp["DTEND"].dt
            if ev_start is not None:
                duration = ev_end - ev_start
        elif "DURATION" in comp:
            duration = comp["DURATION"].dt
            if ev_start is not None:
                ev_end = ev_start + duration

        if isinstance(ev_start, datetime):
            fh_w.append(
                "  {}--{}\n".format(
                    orgDatetime(ev_start, self.tz), orgDatetime(ev_end, self.tz)
                )
            )
        elif isinstance(ev_start, date):
            if ev_start == ev_end - timedelta(days=1):  # single day event
                fh_w.append("  {}\n".format(orgDate(ev_start, self.tz)))
            else:  # multiple day event
                fh_w.append(
                    "  {}--{}\n".format(
                        orgDate(ev_start, self.tz),
                        orgDate(ev_end - timedelta(days=1), self.tz),
                    )
                )
        if "DESCRIPTION" in comp:
            description = "\n".join(
                comp["DESCRIPTION"].to_ical().decode("utf-8").split("\\n")
            )
            description = description.replace("\\,", ",")
            fh_w.append("{}\n".format(description))

        fh_w.append("\n")

        return "".join(fh_w)


def check_timezone(ctx, param, value):
    if (value is None) or (value in all_timezones):
        return value
    else:
        click.echo("Invalid timezone value {value}.".format(value=value))
        click.echo("Use --print-timezones to show acceptable values.")
        ctx.exit(1)


def print_timezones(ctx, param, value):
    if not value or ctx.resilient_parsing:
        return
    for tz in all_timezones:
        click.echo(tz)
    ctx.exit()


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--print-timezones",
    "-p",
    is_flag=True,
    callback=print_timezones,
    is_eager=True,
    expose_value=False,
    help="Print acceptable timezone names and exit.",
)
@click.option(
    "--days",
    "-d",
    default=90,
    type=click.IntRange(0, clamp=True),
    help=(
        "Window length in days (left & right from current time). " "Has to be positive."
    ),
)
@click.option(
    "--timezone",
    "-t",
    default=None,
    callback=check_timezone,
    help="Timezone to use. (local timezone by default)",
)
@click.option(
    "--continue-on-error",
    default=False,
    is_flag=True,
    help="Pass this to attempt to continue even if some events are not handled",
)
@click.argument("ics_file", type=click.File("r", encoding="utf-8"))
@click.argument("org_file", type=click.File("w", encoding="utf-8"))
def main(ics_file, org_file, days, timezone, continue_on_error):
    """Convert ICAL format into org-mode.

    Files can be set as explicit file name, or `-` for stdin or stdout::

        $ ical2orgpy in.ical out.org

        $ ical2orgpy in.ical - > out.org

        $ cat in.ical | ical2orgpy - out.org

        $ cat in.ical | ical2orgpy - - > out.org
    """
    convertor = Convertor(days, timezone, continue_on_error=continue_on_error)
    try:
        convertor(ics_file, org_file)
    except IcalParsingError as e:
        click.echo(str(e), err=True)
        raise click.Abort()
