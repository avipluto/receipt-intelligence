"""Streamlit front end. Talks to the FastAPI backend over HTTP only.

  streamlit run src/receipt_ai/ui.py        (API_URL defaults to http://localhost:8765)

Keeping the UI a pure API client means the same backend can serve a mobile app or
scripts later, and the UI never touches the database or the models directly.
"""

from __future__ import annotations

import os
from decimal import Decimal

import plotly.graph_objects as go
import requests
import streamlit as st

API = os.environ.get("API_URL", "http://localhost:8765")
# Same key the API checks, if one is set (see api.require_token).
HEADERS = {"X-API-Key": t} if (t := os.environ.get("RECEIPTS_API_TOKEN")) else {}
BLUE = "#2a78d6"  # one series -> one hue, no legend (the title names it)

st.set_page_config(page_title="Receipt Intelligence", page_icon="🧾", layout="wide")


def api(method: str, path: str, **kw):
    try:
        r = requests.request(method, f"{API}{path}", timeout=kw.pop("timeout", 30), headers=HEADERS, **kw)
    except requests.RequestException as e:
        st.error(f"Can't reach the API at {API} ({type(e).__name__}). Is it running?")
        st.stop()
    if r.status_code >= 400:
        detail = r.json().get("detail", r.text) if r.headers.get("content-type", "").startswith("application/json") else r.text
        st.error(f"{r.status_code}: {detail}")
        return None
    return r.json() if r.content else None


def money(v) -> str:
    if v in (None, ""):
        return "—"
    d = Decimal(str(v))
    return f"{d:,.0f}" if d == d.to_integral() else f"{d:,.2f}"


def bar_chart(x, y, horizontal: bool = False, height: int = 320) -> go.Figure:
    fig = go.Figure(go.Bar(
        x=y if horizontal else x, y=x if horizontal else y,
        orientation="h" if horizontal else "v",
        marker=dict(color=BLUE, cornerradius=4),
        hovertemplate=("%{y}: %{x:,.2f}" if horizontal else "%{x}: %{y:,.2f}") + "<extra></extra>",
    ))
    fig.update_layout(
        height=height, margin=dict(l=8, r=8, t=8, b=8), bargap=0.35, showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    grid = dict(showgrid=True, gridcolor="rgba(128,128,128,0.18)", gridwidth=1, zeroline=False)
    fig.update_xaxes(**(grid if horizontal else dict(showgrid=False)))
    fig.update_yaxes(**(dict(showgrid=False, autorange="reversed") if horizontal else grid))
    return fig


def show_citation(receipt_id: int) -> None:
    """The source of an answer: the original image, what OCR read, and what was extracted."""
    r = api("GET", f"/receipts/{receipt_id}")
    if not r:
        return
    flag = " ⚠️ needs review" if r["needs_review"] else ""
    with st.expander(f"Receipt #{receipt_id} · {r['merchant'] or 'Unknown merchant'} · {money(r['total'])}{flag}"):
        left, right = st.columns([1, 1])
        if r["file_name"].lower().endswith(".pdf"):
            left.caption(f"PDF: {r['file_name']}")
        else:
            img = requests.get(f"{API}/receipts/{receipt_id}/file", timeout=30, headers=HEADERS)
            if img.ok:
                left.image(img.content, use_container_width=True)
        for issue in r["issues"]:
            right.warning(issue)
        right.markdown(f"**Date** {r['date'] or '—'}  ·  **Subtotal** {money(r['subtotal'])}  ·  "
                       f"**Tax** {money(r['tax'])}  ·  **Total** {money(r['total'])}")
        if r["items"]:
            right.dataframe([{"item": i["name"], "qty": i["quantity"] or "—", "amount": money(i["line_total"])} for i in r["items"]],
                            hide_index=True, use_container_width=True)
        right.text_area("OCR text", r["ocr_text"], height=180, disabled=True, key=f"ocr-{receipt_id}-{id(r)}")


st.title("🧾 Receipt Intelligence")
st.caption("Local and free: PaddleOCR + qwen2.5:3b via Ollama + SQLite. Nothing leaves this machine.")

tab_ask, tab_dash, tab_upload, tab_list = st.tabs(["Ask", "Dashboard", "Upload", "Receipts"])

# ---------------------------------------------------------------- ask
with tab_ask:
    q = st.chat_input("Ask about your spending, e.g. “Which store got the most money?”")
    if "history" not in st.session_state:
        st.session_state.history = []
    if q:
        with st.spinner("Thinking locally…"):
            a = api("POST", "/ask", json={"question": q}, timeout=180)
        if a:
            st.session_state.history.insert(0, a)
    for a in st.session_state.history:
        with st.chat_message("user"):
            st.write(a["question"])
        with st.chat_message("assistant"):
            st.write(a["answer"])
            st.caption(f"Tool: {a['route']['tool']} · period: {a['period']} · "
                       f"{'phrased by LLM, numbers verified' if a['used_llm'] else 'exact template'}"
                       + (f" · {a['note']}" if a["note"] else ""))
            if a["rows"]:
                with st.expander("Data behind this answer"):
                    st.dataframe(a["rows"], hide_index=True, use_container_width=True)
            if a["receipt_ids"]:
                st.markdown(f"**Sources** ({len(a['receipt_ids'])} receipt(s))")
                for rid in a["receipt_ids"][:5]:
                    show_citation(rid)
                if len(a["receipt_ids"]) > 5:
                    st.caption(f"…and {len(a['receipt_ids']) - 5} more.")

# ---------------------------------------------------------------- dashboard
with tab_dash:
    receipts = api("GET", "/receipts", params={"limit": 10000}) or []
    total = sum(Decimal(r["total"]) for r in receipts if r["total"])
    flagged = sum(r["needs_review"] for r in receipts)
    c1, c2, c3 = st.columns(3)
    c1.metric("Total spent", money(total))
    c2.metric("Receipts", len(receipts))
    c3.metric("Need review", flagged, help="The arithmetic checks didn't add up. Open them in the Receipts tab.")

    monthly = api("GET", "/stats/monthly") or {"rows": [], "note": ""}
    st.subheader("Spending per month")
    if monthly["rows"]:
        rows = monthly["rows"]
        st.plotly_chart(bar_chart([r["month"] for r in rows], [float(r["total"]) for r in rows]), use_container_width=True)
        with st.expander("Table view"):
            st.dataframe(rows, hide_index=True, use_container_width=True)
    else:
        st.info("No dated receipts yet.")
    if monthly["note"]:
        st.caption(monthly["note"])

    merchants = (api("GET", "/stats/merchants", params={"top_n": 10}) or {"rows": []})["rows"]
    st.subheader("Top merchants")
    if merchants:
        st.plotly_chart(bar_chart([m["merchant"] for m in merchants], [float(m["total"]) for m in merchants],
                                  horizontal=True, height=40 * len(merchants) + 40), use_container_width=True)
        with st.expander("Table view"):
            st.dataframe(merchants, hide_index=True, use_container_width=True)

# ---------------------------------------------------------------- upload
with tab_upload:
    files = st.file_uploader("Receipt photos or PDFs", type=["jpg", "jpeg", "png", "webp", "pdf"], accept_multiple_files=True)
    if files and st.button(f"Read {len(files)} receipt(s)", type="primary"):
        for f in files:
            with st.spinner(f"Reading {f.name} (OCR + local LLM, ~20 s)…"):
                res = api("POST", "/receipts", files={"file": (f.name, f.getvalue())}, timeout=300)
            if not res:
                continue
            r = res["receipt"]
            if res["duplicate"]:
                st.info(f"{f.name}: already uploaded as receipt #{res['receipt_id']}.")
            elif r["needs_review"]:
                st.warning(f"{f.name}: saved as #{res['receipt_id']}, total {money(r['total'])}, but please check: "
                           + "; ".join(r["issues"]))
            else:
                st.success(f"{f.name}: saved as #{res['receipt_id']}: {r['merchant'] or 'Unknown'}, total {money(r['total'])}")

# ---------------------------------------------------------------- list
with tab_list:
    only_flagged = st.toggle("Only receipts that need review")
    rows = api("GET", "/receipts", params={"limit": 500}) or []
    if only_flagged:
        rows = [r for r in rows if r["needs_review"]]
    st.dataframe([{**r, "total": money(r["total"])} for r in rows], hide_index=True, use_container_width=True)
    if rows:
        rid = st.selectbox("Open receipt", [r["receipt_id"] for r in rows])
        show_citation(rid)
