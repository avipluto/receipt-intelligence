"""Question -> tool call -> query result -> cited answer.

Three steps, each doing what it is best at:
  1. route()   LLM reads the question and picks a tool + a *period label*
               ("this_month", month=9, ...). It never computes dates or totals.
  2. resolve_period() + queries.TOOLS   Python turns the label into exact dates and
               runs tested SQL.
  3. answer()  LLM phrases the result. Every number in its reply is checked against
               the query result; if it invents one, we fall back to a plain template.
"""

from __future__ import annotations

import calendar
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

import requests
from pydantic import BaseModel, Field

from . import queries
from .extract import MODEL, NUM_CTX, OLLAMA_URL
from .queries import QueryResult

PeriodType = Literal["all", "this_month", "last_month", "this_year", "last_year", "month", "year", "last_n_days", "range"]
ToolName = Literal["total_spent", "spend_by_merchant", "spend_by_month", "find_items", "list_receipts"]


class Route(BaseModel):
    tool: ToolName
    period: PeriodType
    month: int | None = Field(None, description="1-12, only when period is 'month'")
    year: int | None = Field(None, description="only when the question names a year")
    n_days: int | None = Field(None, description="only for last_n_days")
    start: str | None = Field(None, description="YYYY-MM-DD, only for period 'range'")
    end: str | None = Field(None, description="YYYY-MM-DD, only for period 'range'")
    merchant: str | None = Field(None, description="store name if the question names one")
    item: str | None = Field(None, description="product searched for, for find_items")


ROUTER_PROMPT = """You turn a question about personal spending into a tool call. Output JSON only.

Tools:
- total_spent: how much was spent (optionally at one merchant)
- spend_by_merchant: which stores got the most money / breakdown by store
- spend_by_month: spending over time, month by month, trends
- find_items: what was bought, when a product was bought, how much a product cost
- list_receipts: show/list receipts or transactions

Periods: all, this_month, last_month, this_year, last_year,
month (set month 1-12, and year only if the question says one), year (set year),
last_n_days (set n_days), range (set start and end as YYYY-MM-DD).
Use "all" when the question gives no time period.

Examples:
"How much did I spend this month?" -> {"tool":"total_spent","period":"this_month"}
"What was my total in September?" -> {"tool":"total_spent","period":"month","month":9}
"Which store got the most money from me?" -> {"tool":"spend_by_merchant","period":"all"}
"When did I last buy butter?" -> {"tool":"find_items","period":"all","item":"butter"}
"How much did I spend at Big Bazaar last month?" -> {"tool":"total_spent","period":"last_month","merchant":"Big Bazaar"}
"Show my spending trend this year" -> {"tool":"spend_by_month","period":"this_year"}"""


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def resolve_period(route: Route, today: date) -> tuple[str | None, str | None, str]:
    """Period label -> (start, end, human description). Pure function, unit-tested."""
    p = route.period
    if p == "this_month":
        s, _ = _month_bounds(today.year, today.month)
        return s.isoformat(), today.isoformat(), today.strftime("%B %Y")
    if p == "last_month":
        first_this = today.replace(day=1)
        s, e = _month_bounds((first_this - timedelta(days=1)).year, (first_this - timedelta(days=1)).month)
        return s.isoformat(), e.isoformat(), s.strftime("%B %Y")
    if p == "this_year":
        return date(today.year, 1, 1).isoformat(), today.isoformat(), str(today.year)
    if p == "last_year":
        return date(today.year - 1, 1, 1).isoformat(), date(today.year - 1, 12, 31).isoformat(), str(today.year - 1)
    if p == "year" and route.year:
        return date(route.year, 1, 1).isoformat(), date(route.year, 12, 31).isoformat(), str(route.year)
    if p == "month" and route.month and 1 <= route.month <= 12:
        # "September" without a year = the most recent September that has started.
        year = route.year or (today.year if route.month <= today.month else today.year - 1)
        s, e = _month_bounds(year, route.month)
        return s.isoformat(), e.isoformat(), s.strftime("%B %Y")
    if p == "last_n_days" and route.n_days:
        return (today - timedelta(days=route.n_days - 1)).isoformat(), today.isoformat(), f"the last {route.n_days} days"
    if p == "range" and route.start and route.end:
        return route.start, route.end, f"{route.start} to {route.end}"
    return None, None, "all time"


def _chat(messages: list[dict], fmt: dict | None = None, timeout: int = 120) -> str:
    body = {"model": MODEL, "messages": messages, "stream": False,
            "options": {"temperature": 0, "num_ctx": NUM_CTX}, "keep_alive": "10m"}
    if fmt:
        body["format"] = fmt
    r = requests.post(f"{OLLAMA_URL}/api/chat", json=body, timeout=timeout)
    r.raise_for_status()
    return r.json()["message"]["content"]


def route(question: str, today: date) -> Route:
    schema = Route.model_json_schema()
    schema["required"] = list(schema["properties"])  # see extract.llm_schema for why
    raw = _chat(
        [{"role": "system", "content": ROUTER_PROMPT},
         {"role": "user", "content": f"Today is {today.isoformat()}.\nQuestion: {question}"}],
        fmt=schema,
    )
    return Route.model_validate_json(raw)


_TIME_WORDS = re.compile(
    r"\b(today|yesterday|week|weeks|month|months|year|years|day|days|since|ago|past|recent|recently|"
    r"this|last|jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|april|june|"
    r"july|august|september|october|november|december|\d{4}|\d{1,2}[/-]\d{1,2})\b",
    re.I,
)
_PERIOD_FIELDS = {"month": {"month", "year"}, "year": {"year"}, "last_n_days": {"n_days"}, "range": {"start", "end"}}


def _mentioned(value: str | None, question: str) -> bool:
    """Is this LLM-chosen value actually in the question? (fuzzy, so "Big Bazaar's" matches)."""
    from rapidfuzz import fuzz

    return bool(value) and fuzz.partial_ratio(value.lower(), question.lower()) >= 85


def sanitize_route(question: str, r: Route) -> Route:
    """Keep only what the question actually supports.

    Measured live: with every key required (see route()), the 3B router fills every
    field: merchant='all', item='butter' copied from the prompt's examples, n_days=3e15,
    and period='this_month' for "How much did I spend in total?". Each of those
    silently filters the SQL down to nothing. Python checks each value against the
    question and drops the ones it can't trace back.
    """
    period = r.period
    if period != "all" and not _TIME_WORDS.search(question):
        period = "all"
    keep = _PERIOD_FIELDS.get(period, set())
    year = r.year if "year" in keep and r.year and str(r.year) in question else None
    n_days = r.n_days if "n_days" in keep and r.n_days and str(r.n_days) in question else None
    return Route(
        tool=r.tool,
        period=period,
        month=r.month if "month" in keep else None,
        year=year,
        n_days=n_days,
        start=r.start if "start" in keep else None,
        end=r.end if "end" in keep else None,
        merchant=r.merchant if r.tool != "find_items" and _mentioned(r.merchant, question) else None,
        item=r.item if r.tool == "find_items" and _mentioned(r.item, question) else None,
    )


def run_tool(conn: sqlite3.Connection, r: Route, today: date) -> tuple[QueryResult, str]:
    start, end, period_text = resolve_period(r, today)
    if r.tool == "find_items":
        result = queries.find_items(conn, r.item or "", start, end)
    elif r.tool == "spend_by_merchant":
        result = queries.spend_by_merchant(conn, start, end)
    else:
        result = queries.TOOLS[r.tool](conn, start, end, r.merchant)
    return result, period_text


# ---------------------------------------------------------------- answer

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def numbers_in(text: str) -> set[Decimal]:
    # Decimal compares by value: Decimal("892.30") == Decimal("892.3") == the "892.3" the LLM may write.
    return {Decimal(n.replace(",", "")) for n in _NUMBER.findall(text)}


def grounded(answer: str, allowed: set[Decimal]) -> bool:
    """True if every number in the answer appears in the data we gave the model.

    A 3B model may "helpfully" add, round or invent figures. Any number we can't
    trace back to the query result means the answer can't be trusted.
    """
    return numbers_in(answer) <= allowed


def template_answer(r: Route, result: QueryResult, period_text: str) -> str:
    rows = result.rows
    if r.tool == "total_spent":
        where = f" at {r.merchant}" if r.merchant else ""
        if not rows[0]["receipts"]:
            return f"No receipts found{where} for {period_text}."
        return f"You spent {rows[0]['total']}{where} in {period_text}, across {rows[0]['receipts']} receipt(s)."
    if not rows:
        return f"No matching receipts found for {period_text}."
    if r.tool == "spend_by_merchant":
        top = rows[0]
        return f"In {period_text}, {top['merchant']} received the most: {top['total']} over {top['receipts']} receipt(s)."
    if r.tool == "spend_by_month":
        return "Monthly spending: " + "; ".join(f"{x['month']}: {x['total']}" for x in rows) + "."
    if r.tool == "find_items":
        last = rows[-1]
        when = f" on {last['date']}" if last["date"] else ""
        where = f" at {last['merchant']}" if last["merchant"] else ""
        return f"Found {len(rows)} matching item(s); latest: {last['item']} ({last['line_total']}){when}{where}."
    return f"{len(rows)} receipt(s) in {period_text}."


# One number or a plain list: the tested template says it exactly. LLM phrasing adds
# nothing and (measured live) sometimes returned a bare "552600". The LLM is kept for
# tools whose rows benefit from summarising.
TEMPLATE_TOOLS = {"total_spent", "list_receipts"}


def answer(question: str, r: Route, result: QueryResult, period_text: str, today: date) -> tuple[str, bool]:
    """Returns (answer_text, used_llm)."""
    if r.tool in TEMPLATE_TOOLS:
        return template_answer(r, result, period_text), False
    payload = result.to_dict()
    data = json.dumps({"period": period_text, **payload}, ensure_ascii=False)
    try:
        text = _chat([
            {"role": "system", "content": (
                "Answer the user's spending question in 1-3 full sentences using ONLY the DATA. "
                "Copy amounts exactly as they appear in DATA. Do not add, round or calculate. "
                "Do not add currency symbols. If DATA has no rows or a zero total, say nothing matched. "
                "Do not mention receipt ids, review flags or field names."
            )},
            # No "today" here: the period is already resolved into DATA, and measured live
            # the model copied today's date into an answer about an undated receipt.
            {"role": "user", "content": f"QUESTION: {question}\nDATA: {data}"},
        ])
    except requests.RequestException:
        return template_answer(r, result, period_text), False

    allowed = numbers_in(data) | numbers_in(question)
    if not grounded(text, allowed):
        return template_answer(r, result, period_text), False
    return text.strip(), True


REVIEW_NOTE = "Some of these receipts are flagged for review, so check them before relying on this."


def with_review_note(text: str, result: QueryResult) -> str:
    # Appended by Python, not asked of the LLM: measured live, a 3B model told to "end
    # with" the note sometimes replied with ONLY the note and dropped the answer.
    return f"{text} {REVIEW_NOTE}" if result.needs_review else text


@dataclass
class Answer:
    question: str
    text: str
    route: Route
    result: QueryResult
    period_text: str
    used_llm: bool


def ask(conn: sqlite3.Connection, question: str, today: date | None = None) -> Answer:
    today = today or date.today()
    r = sanitize_route(question, route(question, today))
    result, period_text = run_tool(conn, r, today)
    text, used_llm = answer(question, r, result, period_text, today)
    text = with_review_note(text, result)
    return Answer(question, text, r, result, period_text, used_llm)
