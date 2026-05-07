"""Plotly chart builders.

Each function takes already-prepared pandas data and returns a fig.
Pages are responsible for assembling the dataframes from db.* calls."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from .constants import (
    DUTY_COLORS,
    LEAVE_DUTY_TYPES,
    NON_WORK_DUTY_TYPES,
    week_dates,
)
from .models import Assignment, Officer, Shift


# ---- Dataframe builders --------------------------------------------------- #

def assignments_df(
    assignments: list[Assignment],
    shifts: list[Shift],
    officers: list[Officer],
) -> pd.DataFrame:
    """Wide-ish frame with one row per (officer, date) including derived fields."""
    if not assignments:
        return pd.DataFrame(columns=[
            "email", "name", "on_date", "shift_code", "duty_type", "ward", "hours",
        ])
    s_by_code = {s.code: s for s in shifts}
    o_by_email = {o.email: o for o in officers}
    rows = []
    for a in assignments:
        s = s_by_code.get(a.shift_code)
        o = o_by_email.get(a.email)
        rows.append({
            "email": a.email,
            "name": o.name if o else a.email,
            "on_date": a.on_date,
            "shift_code": a.shift_code,
            "duty_type": s.duty_type if s else "?",
            "ward": s.ward if s else None,
            "hours": s.hours if s else 0,
        })
    return pd.DataFrame(rows)


# ---- Public roster grid --------------------------------------------------- #

def week_grid_figure(df: pd.DataFrame, monday: date) -> go.Figure:
    """Heatmap-ish grid: rows = officers, columns = days, cell = shift_code colored by duty_type."""
    days = week_dates(monday)
    day_labels = [d.strftime("%a %d/%m") for d in days]

    if df.empty:
        fig = go.Figure()
        fig.update_layout(title="No assignments yet for this week", height=200)
        return fig

    # Preserve the row order the caller chose (so ward grouping in the input
    # df is reflected in the chart). pivot_table defaults to sort=True which
    # would re-alphabetize the index and undo any grouping.
    ordered_names = df.drop_duplicates("name", keep="first")["name"].tolist()
    pivot = (
        df.pivot_table(index="name", columns="on_date", values="shift_code",
                       aggfunc="first", sort=False)
        .reindex(index=ordered_names, columns=days)
    )
    duty_pivot = (
        df.pivot_table(index="name", columns="on_date", values="duty_type",
                       aggfunc="first", sort=False)
        .reindex(index=ordered_names, columns=days)
    )

    # Build a numeric z-matrix from the duty_type so we can color via discrete map.
    duty_keys = list(DUTY_COLORS.keys())
    duty_idx = {d: i for i, d in enumerate(duty_keys)}
    z = duty_pivot.map(lambda d: duty_idx.get(d, -1) if pd.notna(d) else -1).values

    text = pivot.fillna("").astype(str).values
    colorscale = [
        [i / max(1, len(duty_keys) - 1), DUTY_COLORS[d]] for i, d in enumerate(duty_keys)
    ]

    fig = go.Figure(data=go.Heatmap(
        z=z, x=day_labels, y=list(pivot.index), text=text,
        texttemplate="%{text}", textfont={"size": 11},
        colorscale=colorscale, zmin=0, zmax=len(duty_keys) - 1,
        showscale=False, hovertemplate="%{y}<br>%{x}<br>%{text}<extra></extra>",
    ))
    fig.update_layout(
        height=max(220, 32 * len(pivot.index) + 80),
        margin=dict(l=120, r=10, t=10, b=10),  # comfortable for typical "Dr. Name" labels
        xaxis=dict(side="top"),
        yaxis=dict(autorange="reversed"),
    )
    return fig


# ---- Admin coverage chart ------------------------------------------------- #

def staff_per_station_per_day_figure(df: pd.DataFrame, min_per_ward: int = 1) -> go.Figure:
    """Stacked bar: per-day count of staff per ward (excluding non-work duty types)."""
    if df.empty:
        return go.Figure().update_layout(title="No data")
    work = df[~df["duty_type"].isin(NON_WORK_DUTY_TYPES)]
    if work.empty:
        return go.Figure().update_layout(title="No working assignments yet")
    grouped = (
        work.assign(ward=work["ward"].fillna(work["duty_type"]))
        .groupby(["on_date", "ward"]).size().reset_index(name="staff")
    )
    fig = px.bar(
        grouped, x="on_date", y="staff", color="ward", barmode="stack",
        title="Staff coverage per ward per day",
        labels={"on_date": "Date", "staff": "Headcount"},
    )
    fig.add_hline(y=min_per_ward, line_dash="dot", line_color="red",
                  annotation_text=f"min/ward={min_per_ward}", annotation_position="top right")
    fig.update_layout(height=380, margin=dict(l=10, r=10, t=40, b=10))
    return fig


HOURS_LOW = 60    # below this = under-utilized (yellow)
HOURS_HIGH = 64   # above this = over cap (red); 60-64 is the accepted band


def _hours_color(h: int) -> str:
    if h > HOURS_HIGH:
        return "#ef4444"  # red — over cap
    if h < HOURS_LOW:
        return "#f59e0b"  # amber — too few hours
    return "#0ea5e9"      # sky — within accepted band


def daily_category_counts(
    edited: pd.DataFrame,
    day_cols: list[str],
    days: list,
    shifts_by_code: dict,
) -> pd.DataFrame:
    """Build a (category × day) count grid from the editor's current state.

    Categorization:
    - EH/OH/OC/TAG → bucket by the shift's ward (W1, W2, …)
    - everything else → bucket by duty_type (MOPD, PERI, MC/EL, OFF, …)

    Rows sorted: numeric wards first (W1, W2, …), other ward strings, then
    non-ward categories alphabetically.
    """
    counts: dict[str, dict[object, int]] = {}
    for _, r in edited.iterrows():
        for d, dlabel in zip(days, day_cols):
            code = r[dlabel]
            if not code or code not in shifts_by_code:
                continue
            s = shifts_by_code[code]
            if s.duty_type in {"EH", "OH", "OC", "TAG"}:
                cat = s.ward or s.duty_type
            else:
                cat = s.duty_type
            row = counts.setdefault(cat, {d: 0 for d in days})
            row[d] = row.get(d, 0) + 1

    if not counts:
        return pd.DataFrame()

    df = pd.DataFrame(counts).T.fillna(0).astype(int).reindex(columns=days, fill_value=0)

    def sort_key(cat: str):
        if cat.startswith("W") and cat[1:].isdigit():
            return (0, 0, int(cat[1:]))
        if cat.startswith("W"):
            return (0, 1, cat)
        return (1, 0, cat)

    df = df.reindex(sorted(df.index, key=sort_key))
    df.columns = [d.strftime("%a %d/%m") for d in df.columns]
    df.index.name = "Category"
    return df


def hours_per_staff_figure(df: pd.DataFrame) -> go.Figure:
    """Horizontal bar chart of weekly hours per HO. Bars colored by threshold:
    blue 60-64 (accepted), amber <60 (too few), red >64 (over cap). Dotted
    lines mark both bounds of the accepted band."""
    if df.empty:
        return go.Figure().update_layout(title="No data")
    by_staff = df.groupby("name", as_index=False)["hours"].sum().sort_values("hours", ascending=True)
    by_staff["color"] = by_staff["hours"].apply(_hours_color)
    fig = go.Figure(go.Bar(
        x=by_staff["hours"], y=by_staff["name"], orientation="h",
        marker_color=by_staff["color"],
        text=by_staff["hours"], textposition="outside",
    ))
    fig.add_vline(x=HOURS_LOW, line_dash="dot", line_color="#92400e",
                  annotation_text=f"{HOURS_LOW}h target", annotation_position="bottom right")
    fig.add_vline(x=HOURS_HIGH, line_dash="dot", line_color="#dc2626",
                  annotation_text=f"{HOURS_HIGH}h cap", annotation_position="top right")
    fig.update_layout(
        title="Working hours this period",
        xaxis_title="Hours", yaxis_title=None,
        height=max(300, 22 * len(by_staff) + 80),
        margin=dict(l=10, r=10, t=40, b=10),
    )
    return fig


# ---- Per-officer self-service charts -------------------------------------- #

def station_mix_donut(df_for_one_officer: pd.DataFrame) -> go.Figure:
    if df_for_one_officer.empty:
        return go.Figure().update_layout(title="No assignments")
    grouped = (
        df_for_one_officer.assign(label=df_for_one_officer["ward"].fillna(df_for_one_officer["duty_type"]))
        .groupby("label").size().reset_index(name="days")
    )
    fig = px.pie(grouped, names="label", values="days", hole=0.5, title="Days per station")
    fig.update_layout(height=320, margin=dict(l=10, r=10, t=40, b=10))
    return fig


def leave_dates_figure(df_for_one_officer: pd.DataFrame) -> go.Figure:
    """Timeline of EL/MC dates: one marker per leave day, hover shows date+code."""
    leaves = df_for_one_officer[df_for_one_officer["duty_type"].isin(LEAVE_DUTY_TYPES)]
    if leaves.empty:
        fig = go.Figure()
        fig.update_layout(title="No EL/MC days taken yet", height=180,
                          margin=dict(l=10, r=10, t=40, b=10))
        return fig
    leaves = leaves.sort_values("on_date").assign(label=lambda d: d["shift_code"])
    fig = go.Figure(go.Scatter(
        x=leaves["on_date"], y=[1] * len(leaves), mode="markers+text",
        text=leaves["on_date"].astype(str).str.slice(5),  # MM-DD
        textposition="top center", textfont={"size": 11},
        marker=dict(size=18, color=DUTY_COLORS["MC/EL"], symbol="circle",
                    line=dict(color="#7f1d1d", width=1)),
        hovertemplate="<b>%{x|%a %d %b %Y}</b><br>%{customdata}<extra></extra>",
        customdata=leaves["shift_code"],
    ))
    fig.update_yaxes(visible=False, range=[0.5, 1.6])
    fig.update_xaxes(title=None, showgrid=True)
    fig.update_layout(
        title=f"EL/MC days — {len(leaves)} taken",
        height=200, margin=dict(l=10, r=10, t=40, b=20),
        showlegend=False,
    )
    return fig


def leave_progress_figure(used: int, cap: int = 10) -> go.Figure:
    pct = min(100, int(round(100 * used / max(1, cap))))
    color = "#22c55e"
    if used >= cap:
        color = "#ef4444"
    elif used >= int(0.8 * cap):
        color = "#f59e0b"
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=used,
        title={"text": f"EL/MC used (cap {cap})"},
        gauge={
            "axis": {"range": [0, cap]},
            "bar": {"color": color},
            "steps": [
                {"range": [0, int(0.8 * cap)], "color": "#dcfce7"},
                {"range": [int(0.8 * cap), cap], "color": "#fef3c7"},
            ],
        },
    ))
    fig.update_layout(height=280, margin=dict(l=10, r=10, t=40, b=10))
    return fig


# ---- Helpers used by pages ------------------------------------------------ #

def count_leaves(df_for_one_officer: pd.DataFrame) -> int:
    if df_for_one_officer.empty:
        return 0
    return int(df_for_one_officer["duty_type"].isin(LEAVE_DUTY_TYPES).sum())


def days_in_posting(officer: Officer, today: date | None = None) -> int:
    today = today or date.today()
    return max(0, (today - officer.posting_start_date).days)


def total_hours(df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    return int(df["hours"].sum())


def date_range_for_posting(officer: Officer, today: date | None = None) -> tuple[date, date]:
    today = today or date.today()
    return (officer.posting_start_date, today + timedelta(days=0))
