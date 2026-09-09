"""Presentation kit for the MailTaskAgent Streamlit UI.

This module owns the visual language only: design tokens, the injected
stylesheet and small helpers that return HTML fragments. It must not import
storage, workflow or any agent logic, so screen code can be rearranged freely
without touching the decision path.
"""

from __future__ import annotations

from html import escape as _escape

import streamlit as st

# --------------------------------------------------------------------------
# tones
# --------------------------------------------------------------------------

TONES = frozenset(
    {"neutral", "accent", "danger", "warning", "hold", "review", "success", "info"}
)

PRIORITY_TONES = {"P1": "danger", "P2": "warning", "P3": "accent", "P4": "neutral"}

PRIORITY_TEXT = {
    "P1": "즉시 처리",
    "P2": "우선 처리",
    "P3": "예정 업무",
    "P4": "일반 업무",
}

STATUS_TONES = {
    "TODO": "info",
    "IN_PROGRESS": "accent",
    "WAITING_REPLY": "hold",
    "COMPLETED": "success",
    "CANCELLED": "neutral",
}


def esc(value) -> str:
    """HTML-escape any value for safe interpolation."""

    return _escape("" if value is None else str(value))


def _tone(tone: str) -> str:
    return tone if tone in TONES else "neutral"


# --------------------------------------------------------------------------
# fragments
# --------------------------------------------------------------------------


def badge(text, tone: str = "neutral") -> str:
    """A solid state pill. Use for one-word states such as a Task status."""

    return f'<span class="ui-badge ui-badge--{_tone(tone)}">{esc(text)}</span>'


def chip(key: str, value, tone: str = "neutral") -> str:
    """A two-part pill: a category name and its value.

    The category is always spelled out, so a chip never depends on colour
    alone to say what kind of fact it carries.
    """

    return (
        f'<span class="ui-chip ui-chip--{_tone(tone)}">'
        f'<span class="ui-chip__k">{esc(key)}</span>'
        f'<span class="ui-chip__v">{esc(value)}</span></span>'
    )


def chips(items) -> str:
    rendered = "".join(item for item in items if item)
    return f'<span class="ui-chips">{rendered}</span>' if rendered else ""


def rank(level: str) -> str:
    """The priority rank marker: a coloured tile that also spells out P1..P4."""

    key = str(level).upper()
    return (
        f'<span class="ui-rank ui-rank--{PRIORITY_TONES.get(key, "neutral")}">'
        f"{esc(key)}</span>"
    )


def priority_chip(level: str, label: str | None = None) -> str:
    key = str(level).upper()
    text = label or PRIORITY_TEXT.get(key, key)
    return chip("우선순위", f"{key} {text}", PRIORITY_TONES.get(key, "neutral"))


def title(text, size: str = "md") -> str:
    return f'<span class="ui-title ui-title--{size}">{esc(text)}</span>'


def muted(text) -> str:
    return f'<span class="ui-muted">{esc(text)}</span>'


def strong(text) -> str:
    return f'<span class="ui-strong">{esc(text)}</span>'


def num(text) -> str:
    return f'<span class="ui-num">{esc(text)}</span>'


def dot(tone: str = "neutral") -> str:
    return f'<span class="ui-dot ui-dot--{_tone(tone)}"></span>'


# --------------------------------------------------------------------------
# blocks
# --------------------------------------------------------------------------


def page_header(heading: str, description: str = "", meta: str = "") -> None:
    """The single title treatment used at the top of every screen."""

    description_html = (
        f'<p class="ui-page__desc">{esc(description)}</p>' if description else ""
    )
    meta_html = f'<div class="ui-page__meta">{meta}</div>' if meta else ""
    st.markdown(
        f'<header class="ui-page">'
        f'<h1 class="ui-page__title">{esc(heading)}</h1>'
        f"{description_html}{meta_html}</header>",
        unsafe_allow_html=True,
    )


def section(heading: str, description: str = "", aside: str = "") -> None:
    """A section rule with a heading, an optional hint and an optional aside."""

    description_html = (
        f'<span class="ui-section__desc">{esc(description)}</span>'
        if description
        else ""
    )
    aside_html = f'<span class="ui-section__aside">{aside}</span>' if aside else ""
    st.markdown(
        f'<div class="ui-section">'
        f'<span class="ui-section__title">{esc(heading)}</span>'
        f"{description_html}{aside_html}</div>",
        unsafe_allow_html=True,
    )


def stat_cards(items) -> None:
    """A row of headline figures.

    `items` are `(label, value, hint, tone)` tuples; hint and tone optional.
    """

    cards = []
    for item in items:
        label, value = item[0], item[1]
        hint = item[2] if len(item) > 2 else ""
        tone = _tone(item[3]) if len(item) > 3 else "neutral"
        hint_html = f'<div class="ui-stat__hint">{esc(hint)}</div>' if hint else ""
        cards.append(
            f'<div class="ui-stat ui-stat--{tone}">'
            f'<div class="ui-stat__label">{esc(label)}</div>'
            f'<div class="ui-stat__value">{esc(value)}</div>'
            f"{hint_html}</div>"
        )
    st.markdown(
        f'<div class="ui-stats" style="--ui-cols:{len(cards)}">'
        f'{"".join(cards)}</div>',
        unsafe_allow_html=True,
    )


def note(text: str, tone: str = "info", heading: str = "") -> None:
    """An inline callout. Quieter than st.info and consistent across screens."""

    heading_html = (
        f'<span class="ui-note__title">{esc(heading)}</span>' if heading else ""
    )
    st.markdown(
        f'<div class="ui-note ui-note--{_tone(tone)}">{heading_html}'
        f'<span class="ui-note__body">{esc(text)}</span></div>',
        unsafe_allow_html=True,
    )


def empty_state(heading: str, description: str = "") -> None:
    description_html = (
        f'<span class="ui-empty__desc">{esc(description)}</span>' if description else ""
    )
    st.markdown(
        f'<div class="ui-empty"><span class="ui-empty__title">{esc(heading)}</span>'
        f"{description_html}</div>",
        unsafe_allow_html=True,
    )


def facts(pairs, columns: int = 3) -> str:
    """A definition grid of `(label, value_html)` pairs."""

    cells = "".join(
        f'<div class="ui-fact"><dt>{esc(label)}</dt><dd>{value}</dd></div>'
        for label, value in pairs
    )
    return f'<dl class="ui-facts" style="--ui-cols:{columns}">{cells}</dl>'


def table(columns, rows, aligns=None) -> None:
    """A static table.

    Rendered as plain HTML so it grows with its content instead of adding a
    second scrollbar inside the page.
    """

    aligns = aligns or ["left"] * len(columns)
    head = "".join(
        f'<th style="text-align:{align}">{esc(name)}</th>'
        for name, align in zip(columns, aligns)
    )
    body = []
    for row in rows:
        cells = "".join(
            f'<td style="text-align:{align}">{cell}</td>'
            for cell, align in zip(row, aligns)
        )
        body.append(f"<tr>{cells}</tr>")
    st.markdown(
        f'<div class="ui-table-wrap"><table class="ui-table">'
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody>"
        f"</table></div>",
        unsafe_allow_html=True,
    )


def meter(value: float, threshold: float, *, caption: str = "") -> str:
    """A confidence meter with the auto-apply threshold marked on the track.

    The wording deliberately calls this the model's own reported score, never
    a measured accuracy or a probability of success.
    """

    ratio = max(0.0, min(1.0, float(value)))
    mark = max(0.0, min(1.0, float(threshold)))
    passed = ratio >= mark
    verdict = "기준 충족" if passed else "기준 미달"
    tone = "success" if passed else "warning"
    caption_html = (
        f'<div class="ui-meter__caption">{esc(caption)}</div>' if caption else ""
    )
    return (
        f'<div class="ui-meter ui-meter--{tone}">'
        f'<div class="ui-meter__head">'
        f'<span class="ui-meter__label">LLM 자기보고 신뢰도</span>'
        f'<span class="ui-meter__value">{ratio:.2f}</span></div>'
        f'<div class="ui-meter__track"><i style="width:{ratio * 100:.1f}%"></i>'
        f'<b style="left:{mark * 100:.1f}%"></b></div>'
        f'<div class="ui-meter__foot">자동 반영 기준 {mark:.2f} · {verdict}</div>'
        f"{caption_html}</div>"
    )


def flow(steps) -> str:
    """A left-to-right chain of decision steps.

    `steps` are `(label, value_html, tone)` tuples.
    """

    cells = []
    for index, (label, value, tone) in enumerate(steps):
        arrow = '<span class="ui-flow__arrow"></span>' if index else ""
        cells.append(
            f'{arrow}<span class="ui-flow__step ui-flow__step--{_tone(tone)}">'
            f'<span class="ui-flow__label">{esc(label)}</span>'
            f'<span class="ui-flow__value">{value}</span></span>'
        )
    return f'<div class="ui-flow">{"".join(cells)}</div>'


def card(body_html: str, *, tone: str = "neutral", title_html: str = "") -> str:
    heading = f'<div class="ui-card__head">{title_html}</div>' if title_html else ""
    return f'<div class="ui-card ui-card--{_tone(tone)}">{heading}{body_html}</div>'


def brand(name: str, tagline: str) -> None:
    initial = esc(name[:1].upper() or "M")
    st.markdown(
        f'<div class="ui-brand"><span class="ui-brand__mark">{initial}</span>'
        f'<span class="ui-brand__text"><b>{esc(name)}</b>'
        f"<i>{esc(tagline)}</i></span></div>",
        unsafe_allow_html=True,
    )


def sidebar_status(rows) -> None:
    """A compact status block for the sidebar footer.

    `rows` are `(tone, label, value)` tuples.
    """

    items = "".join(
        f'<div class="ui-sbstat__row">{dot(tone)}'
        f'<span class="ui-sbstat__label">{esc(label)}</span>'
        f'<span class="ui-sbstat__value">{esc(value)}</span></div>'
        for tone, label, value in rows
    )
    st.markdown(f'<div class="ui-sbstat">{items}</div>', unsafe_allow_html=True)


# --------------------------------------------------------------------------
# stylesheet
# --------------------------------------------------------------------------

_STYLES = """
<style>
/* ==========================================================================
   0 · TOKENS
   Light product theme: white and cool grey surfaces, slate text, a single
   indigo accent. Red, amber, yellow and violet are reserved for priority,
   risk and review states.
   ========================================================================== */
:root{
  --ui-bg:#f3f5f9;
  --ui-surface:#ffffff;
  --ui-surface-2:#f8fafc;
  --ui-surface-3:#eef2f8;

  --ui-line:#e3e8f0;
  --ui-line-2:#cfd7e5;
  --ui-ring:rgba(59,91,219,.30);

  --ui-ink:#101828;
  --ui-ink-2:#475467;
  --ui-ink-3:#667085;
  --ui-ink-inv:#e8edf9;

  --ui-accent:#3b5bdb;
  --ui-accent-hi:#2f4ab8;
  --ui-accent-soft:#eef2ff;
  --ui-accent-ink:#2f4ab8;
  --ui-accent-line:#d6ddfb;

  --ui-nav:#141d2f;
  --ui-nav-2:#1e293e;
  --ui-nav-3:#2a3a58;
  --ui-nav-line:#2c3a52;

  --ui-danger:#d92d20; --ui-danger-soft:#fef3f2; --ui-danger-ink:#b42318; --ui-danger-line:#fecdc9;
  --ui-warning:#e8590c; --ui-warning-soft:#fff5ed; --ui-warning-ink:#b54708; --ui-warning-line:#fcd9bd;
  --ui-hold:#b8940a;    --ui-hold-soft:#fefaea;    --ui-hold-ink:#8a6d12;    --ui-hold-line:#f3e5a6;
  --ui-review:#7839ee;  --ui-review-soft:#f6f2ff;  --ui-review-ink:#5b25ba;  --ui-review-line:#e3d5fb;
  --ui-success:#067647; --ui-success-soft:#ecfdf3; --ui-success-ink:#067647; --ui-success-line:#c2eed4;
  --ui-info:#175cd3;    --ui-info-soft:#eff6ff;    --ui-info-ink:#175cd3;    --ui-info-line:#cfe0fb;
  --ui-neutral:#98a2b3; --ui-neutral-soft:#f2f4f7; --ui-neutral-ink:#475467; --ui-neutral-line:#e4e7ec;

  --ui-fs-2xs:.7rem; --ui-fs-xs:.775rem; --ui-fs-sm:.83rem; --ui-fs-md:.9rem;
  --ui-fs-lg:.975rem; --ui-fs-xl:1.1rem; --ui-fs-2xl:1.45rem; --ui-fs-3xl:1.75rem;

  --ui-1:.25rem; --ui-2:.375rem; --ui-3:.5rem; --ui-4:.75rem;
  --ui-5:1rem; --ui-6:1.25rem; --ui-7:1.75rem; --ui-8:2.25rem;

  --ui-r-xs:4px; --ui-r-sm:6px; --ui-r-md:8px; --ui-r-lg:12px; --ui-r-pill:999px;
  --ui-shadow:0 1px 2px rgba(16,24,40,.05);
  --ui-shadow-2:0 2px 6px rgba(16,24,40,.06);
  --ui-max:1240px;
  --ui-gap:1rem;
}

/* ==========================================================================
   1 · STREAMLIT FRAME
   ========================================================================== */
html, body, [class*="css"]{
  font-family:"Pretendard","Noto Sans KR","Malgun Gothic",-apple-system,"Segoe UI",sans-serif;
  -webkit-font-smoothing:antialiased;
}
.stApp{background:var(--ui-bg); color:var(--ui-ink);}
[data-testid="stMainBlockContainer"], .block-container{
  max-width:var(--ui-max);
  padding-top:2.75rem;
  padding-bottom:var(--ui-8);
  padding-inline:clamp(1rem,2.4vw,2.5rem);
}
[data-testid="stMain"]{overflow-x:clip;}
[data-testid="stMarkdownContainer"], [data-testid="stCaptionContainer"]{
  word-break:keep-all; overflow-wrap:anywhere; line-height:1.6;
}
/* Streamlit cancels a heading's / caption's own padding with a negative
   bottom margin on the container; both are zeroed together here. */
[data-testid="stMarkdownContainer"]:has(> [data-testid="stHeadingWithActionElements"]){margin-bottom:0;}
[data-testid="stCaptionContainer"]{margin-bottom:0; color:var(--ui-ink-2); font-size:var(--ui-fs-sm);}
[data-testid="stCaptionContainer"] p:last-child{margin-bottom:0;}
[class*="st-key-ui-"] [data-testid="stColumn"]{min-width:0;}
[data-testid="stMainBlockContainer"] hr{
  border:0; border-top:1px solid var(--ui-line); margin:var(--ui-7) 0 var(--ui-6);
}

/* Streamlit headings are only used where a native widget owns them. */
[data-testid="stHeading"] h1,
[data-testid="stHeading"] h2,
[data-testid="stHeading"] h3{
  font-size:var(--ui-fs-xl); font-weight:650; letter-spacing:-.01em;
  color:var(--ui-ink); padding:0; margin:0 0 var(--ui-3);
}
[data-testid="stMarkdown"] h3{font-size:var(--ui-fs-xl); font-weight:650; padding:0; margin:var(--ui-6) 0 var(--ui-2);}
[data-testid="stMarkdown"] h4{font-size:var(--ui-fs-lg); font-weight:650; padding:0; margin:var(--ui-5) 0 var(--ui-2);}
[data-testid="stMarkdown"] h5{font-size:var(--ui-fs-md); font-weight:650; padding:0; margin:var(--ui-5) 0 var(--ui-2);}

/* ==========================================================================
   2 · BUTTONS
   1.62 exposes the kind through data-testid; `kind` never reaches the DOM.
   ========================================================================== */
[data-testid^="stBaseButton-primary"]{
  background:var(--ui-accent); border-color:var(--ui-accent); color:#fff;
  font-weight:600; border-radius:var(--ui-r-md); box-shadow:var(--ui-shadow);
}
[data-testid^="stBaseButton-primary"]:hover{background:var(--ui-accent-hi); border-color:var(--ui-accent-hi); color:#fff;}
[data-testid^="stBaseButton-secondary"]{
  background:var(--ui-surface); border-color:var(--ui-line-2); color:var(--ui-ink-2);
  font-weight:550; border-radius:var(--ui-r-md); box-shadow:none;
}
[data-testid^="stBaseButton-secondary"]:hover{
  background:var(--ui-accent-soft); border-color:var(--ui-accent); color:var(--ui-accent-ink);
}
[data-testid^="stBaseButton-tertiary"]{color:var(--ui-accent-ink); font-weight:550;}
[data-testid^="stBaseButton-tertiary"]:hover{color:var(--ui-accent-hi); background:var(--ui-accent-soft);}
[data-testid^="stBaseButton-"]:focus-visible{box-shadow:0 0 0 3px var(--ui-ring);}

/* ==========================================================================
   3 · WIDGETS
   ========================================================================== */
[data-testid="stMetric"]{
  background:var(--ui-surface); border:1px solid var(--ui-line);
  border-radius:var(--ui-r-lg); padding:var(--ui-4) var(--ui-5); box-shadow:var(--ui-shadow);
}
[data-testid="stMetricLabel"]{color:var(--ui-ink-2); font-size:var(--ui-fs-sm); font-weight:550;}
[data-testid="stMetricValue"]{color:var(--ui-ink); font-size:var(--ui-fs-3xl); font-weight:700; line-height:1.1; font-variant-numeric:tabular-nums;}

[data-testid="stAlertContainer"]{
  border-radius:var(--ui-r-md); border-left:3px solid transparent;
  font-size:var(--ui-fs-md); line-height:1.6;
}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentInfo"]){background:var(--ui-info-soft); border-left-color:var(--ui-info); color:var(--ui-info-ink);}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentWarning"]){background:var(--ui-warning-soft); border-left-color:var(--ui-warning); color:var(--ui-warning-ink);}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentSuccess"]){background:var(--ui-success-soft); border-left-color:var(--ui-success); color:var(--ui-success-ink);}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentError"]){background:var(--ui-danger-soft); border-left-color:var(--ui-danger); color:var(--ui-danger-ink);}

[data-testid="stTabs"]{margin-top:var(--ui-2);}
[data-testid="stTab"]{font-weight:550; font-size:var(--ui-fs-md); color:var(--ui-ink-2); padding-inline:var(--ui-4);}
[data-testid="stTab"][aria-selected="true"],[data-testid="stTab"][data-selected="true"]{color:var(--ui-accent-ink); font-weight:650;}
[data-testid="stTab"] .react-aria-SelectionIndicator{background-color:var(--ui-accent) !important;}

[data-testid="stExpander"]{border-color:var(--ui-line); border-radius:var(--ui-r-lg); background:var(--ui-surface);}
[data-testid="stExpanderDetails"]{border-top-color:var(--ui-line); padding:var(--ui-5);}
[data-testid="stForm"]{border:1px solid var(--ui-line); border-radius:var(--ui-r-lg); padding:var(--ui-5); background:var(--ui-surface);}
[data-testid="stDataFrame"]{border:1px solid var(--ui-line); border-radius:var(--ui-r-md); overflow:hidden;}
div[data-testid="stStatusWidget"]{border-radius:var(--ui-r-lg);}

[data-testid="stRadioOption"]:has(input:checked) > div > div > div:first-child{background:var(--ui-accent);}
/* A horizontal radio used as a view switch reads better as a segmented
   control. Scoped by widget key so ordinary radios keep their dots. */
.st-key-monitoring_view [data-testid="stRadioGroup"]{
  gap:0; background:var(--ui-surface-3); border:1px solid var(--ui-line);
  border-radius:var(--ui-r-md); padding:3px; display:inline-flex;
}
.st-key-monitoring_view [data-testid="stRadioOption"]{
  padding:5px 14px; border-radius:var(--ui-r-sm); margin:0;
}
.st-key-monitoring_view [data-testid="stRadioOption"] > div > div > div:first-child{display:none;}
.st-key-monitoring_view [data-testid="stRadioOption"] p{font-size:var(--ui-fs-sm); color:var(--ui-ink-2);}
.st-key-monitoring_view [data-testid="stRadioOption"][data-selected="true"],
.st-key-monitoring_view [data-testid="stRadioOption"]:has(input:checked){
  background:var(--ui-surface); box-shadow:var(--ui-shadow);
}
.st-key-monitoring_view [data-testid="stRadioOption"][data-selected="true"] p,
.st-key-monitoring_view [data-testid="stRadioOption"]:has(input:checked) p{
  color:var(--ui-ink); font-weight:650;
}
[data-testid="stMultiSelectTagsContainer"] > span > span{background:var(--ui-accent); border-radius:var(--ui-r-sm);}
[data-testid="stCheckbox"] label[data-selected="true"] > div:not([data-testid]){background:var(--ui-accent); border-color:var(--ui-accent);}
[data-testid="stProgress"] div[role="progressbar"] > div{background:var(--ui-accent);}

/* ==========================================================================
   4 · SIDEBAR
   ========================================================================== */
[data-testid="stSidebar"]{background:var(--ui-nav); border-right:0; width:264px;}
[data-testid="stSidebarUserContent"]{padding-top:var(--ui-5);}
[data-testid="stSidebar"] :is(h1,h2,h3,p,label){color:var(--ui-ink-inv);}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"]{color:#8e9dba;}
[data-testid="stSidebar"] hr{border-color:var(--ui-nav-line); margin:var(--ui-4) 0;}
[data-testid="stSidebar"] [data-testid="stAlertContainer"] :is(h1,h2,h3,p,label,div){color:inherit;}
[data-testid="stSidebar"] [data-testid="stExpander"]{background:var(--ui-nav-2); border-color:var(--ui-nav-line); color:var(--ui-ink-inv);}
[data-testid="stSidebar"] [data-testid="stExpanderDetails"]{border-top-color:var(--ui-nav-line); padding:var(--ui-4);}
[data-testid="stSidebar"] [data-testid="stExpander"] summary,
[data-testid="stSidebar"] [data-testid="stExpander"] summary *{color:var(--ui-ink-inv);}
[data-testid="stSidebar"] [data-testid^="stBaseButton-"]{
  border-color:var(--ui-nav-line); color:var(--ui-ink-inv); background:var(--ui-nav-2);
}
[data-testid="stSidebar"] [data-testid^="stBaseButton-"]:hover{
  background:var(--ui-nav-3); border-color:var(--ui-accent); color:#fff;
}
[data-testid="stSidebar"] [data-testid="stRadioGroup"],
[data-testid="stSidebar"] div[role="radiogroup"]{gap:2px;}
[data-testid="stSidebar"] [data-testid="stRadioOption"]{
  min-height:40px; padding:8px 12px; border-radius:var(--ui-r-md);
}
[data-testid="stSidebar"] [data-testid="stRadioOption"]:hover{background:var(--ui-nav-2);}
[data-testid="stSidebar"] [data-testid="stRadioOption"][data-selected="true"],
[data-testid="stSidebar"] [data-testid="stRadioOption"]:has(input:checked){
  background:var(--ui-nav-3); box-shadow:inset 2px 0 0 var(--ui-accent);
}
[data-testid="stSidebar"] [data-testid="stRadioOption"][data-selected="true"] p{font-weight:650;}
/* Hides the radio indicator so the menu reads as navigation. If a Streamlit
   upgrade changes this internal structure the dot simply reappears. */
[data-testid="stSidebar"] [data-testid="stRadioOption"] > div > div > div:first-child{display:none;}

.ui-brand{display:flex; align-items:center; gap:10px; padding:2px 4px var(--ui-4);}
.ui-brand__mark{
  width:32px; height:32px; border-radius:9px; background:var(--ui-accent);
  color:#fff; font-weight:700; font-size:15px; display:grid; place-items:center; flex:none;
}
.ui-brand__text b{display:block; color:#fff; font-size:14.5px; font-weight:650; line-height:1.25;}
.ui-brand__text i{display:block; color:#8e9dba; font-size:11.5px; font-style:normal; margin-top:1px;}

.ui-sbstat{
  border:1px solid var(--ui-nav-line); background:var(--ui-nav-2);
  border-radius:var(--ui-r-md); padding:10px 12px; display:grid; gap:7px;
}
.ui-sbstat__row{display:flex; align-items:center; gap:7px; font-size:11.5px;}
.ui-sbstat__label{color:#8e9dba;}
.ui-sbstat__value{color:#dbe3f5; margin-left:auto; font-weight:600;}

/* ==========================================================================
   5 · PAGE AND SECTION
   ========================================================================== */
.ui-page{margin:0 0 var(--ui-6);}
[data-testid="stMarkdown"] .ui-page__title,
.ui-page__title{
  font-size:var(--ui-fs-2xl); font-weight:700; letter-spacing:-.018em;
  color:var(--ui-ink); margin:0; padding:0; line-height:1.25;
}
[data-testid="stMarkdown"] .ui-page__desc,
.ui-page__desc{margin:6px 0 0; font-size:var(--ui-fs-md); color:var(--ui-ink-2); line-height:1.55;}
.ui-page__meta{margin-top:12px;}

.ui-section{display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; margin:var(--ui-7) 0 var(--ui-3);}
.ui-section__title{font-size:var(--ui-fs-lg); font-weight:650; color:var(--ui-ink); letter-spacing:-.008em;}
.ui-section__desc{font-size:var(--ui-fs-sm); color:var(--ui-ink-3);}
.ui-section__aside{margin-left:auto; font-size:var(--ui-fs-sm); color:var(--ui-ink-3);}

/* ==========================================================================
   6 · INLINE PRIMITIVES
   ========================================================================== */
.ui-badge{
  display:inline-flex; align-items:center; height:20px; padding:0 8px;
  border-radius:var(--ui-r-pill); font-size:var(--ui-fs-2xs); font-weight:650;
  line-height:1; white-space:nowrap; vertical-align:1px;
  background:var(--ui-neutral-soft); color:var(--ui-neutral-ink);
  border:1px solid var(--ui-neutral-line);
}
.ui-badge--accent{background:var(--ui-accent-soft); color:var(--ui-accent-ink); border-color:var(--ui-accent-line);}
.ui-badge--danger{background:var(--ui-danger-soft); color:var(--ui-danger-ink); border-color:var(--ui-danger-line);}
.ui-badge--warning{background:var(--ui-warning-soft); color:var(--ui-warning-ink); border-color:var(--ui-warning-line);}
.ui-badge--hold{background:var(--ui-hold-soft); color:var(--ui-hold-ink); border-color:var(--ui-hold-line);}
.ui-badge--review{background:var(--ui-review-soft); color:var(--ui-review-ink); border-color:var(--ui-review-line);}
.ui-badge--success{background:var(--ui-success-soft); color:var(--ui-success-ink); border-color:var(--ui-success-line);}
.ui-badge--info{background:var(--ui-info-soft); color:var(--ui-info-ink); border-color:var(--ui-info-line);}

.ui-chips{display:inline-flex; flex-wrap:wrap; gap:6px; align-items:center;}
.ui-chip{
  display:inline-flex; align-items:stretch; height:21px; border-radius:var(--ui-r-sm);
  overflow:hidden; font-size:var(--ui-fs-2xs); line-height:21px; white-space:nowrap;
  border:1px solid var(--ui-neutral-line); background:var(--ui-surface);
}
.ui-chip__k{padding:0 6px; background:var(--ui-neutral-soft); color:var(--ui-ink-3); font-weight:600; letter-spacing:.01em;}
.ui-chip__v{padding:0 7px; color:var(--ui-ink); font-weight:650;}
.ui-chip--accent{border-color:var(--ui-accent-line);}
.ui-chip--accent .ui-chip__k{background:var(--ui-accent-soft); color:var(--ui-accent-ink);}
.ui-chip--accent .ui-chip__v{color:var(--ui-accent-ink);}
.ui-chip--danger{border-color:var(--ui-danger-line);}
.ui-chip--danger .ui-chip__k{background:var(--ui-danger-soft); color:var(--ui-danger-ink);}
.ui-chip--danger .ui-chip__v{color:var(--ui-danger-ink);}
.ui-chip--warning{border-color:var(--ui-warning-line);}
.ui-chip--warning .ui-chip__k{background:var(--ui-warning-soft); color:var(--ui-warning-ink);}
.ui-chip--warning .ui-chip__v{color:var(--ui-warning-ink);}
.ui-chip--hold{border-color:var(--ui-hold-line);}
.ui-chip--hold .ui-chip__k{background:var(--ui-hold-soft); color:var(--ui-hold-ink);}
.ui-chip--hold .ui-chip__v{color:var(--ui-hold-ink);}
.ui-chip--review{border-color:var(--ui-review-line);}
.ui-chip--review .ui-chip__k{background:var(--ui-review-soft); color:var(--ui-review-ink);}
.ui-chip--review .ui-chip__v{color:var(--ui-review-ink);}
.ui-chip--success{border-color:var(--ui-success-line);}
.ui-chip--success .ui-chip__k{background:var(--ui-success-soft); color:var(--ui-success-ink);}
.ui-chip--success .ui-chip__v{color:var(--ui-success-ink);}
.ui-chip--info{border-color:var(--ui-info-line);}
.ui-chip--info .ui-chip__k{background:var(--ui-info-soft); color:var(--ui-info-ink);}
.ui-chip--info .ui-chip__v{color:var(--ui-info-ink);}

.ui-rank{
  display:inline-grid; place-items:center; width:30px; height:22px; border-radius:var(--ui-r-sm);
  font-size:var(--ui-fs-2xs); font-weight:700; letter-spacing:.02em;
  background:var(--ui-neutral-soft); color:var(--ui-neutral-ink); border:1px solid var(--ui-neutral-line);
}
.ui-rank--danger{background:var(--ui-danger-soft); color:var(--ui-danger-ink); border-color:var(--ui-danger-line);}
.ui-rank--warning{background:var(--ui-warning-soft); color:var(--ui-warning-ink); border-color:var(--ui-warning-line);}
.ui-rank--accent{background:var(--ui-accent-soft); color:var(--ui-accent-ink); border-color:var(--ui-accent-line);}

.ui-dot{display:inline-block; width:7px; height:7px; border-radius:50%; background:var(--ui-neutral); flex:none;}
.ui-dot--accent{background:var(--ui-accent);}
.ui-dot--danger{background:var(--ui-danger);}
.ui-dot--warning{background:var(--ui-warning);}
.ui-dot--hold{background:var(--ui-hold);}
.ui-dot--review{background:var(--ui-review);}
.ui-dot--success{background:var(--ui-success);}
.ui-dot--info{background:var(--ui-info);}

.ui-title{display:block; color:var(--ui-ink); font-weight:650; line-height:1.35; letter-spacing:-.006em;}
.ui-title--sm{font-size:var(--ui-fs-md);}
.ui-title--md{font-size:var(--ui-fs-lg);}
.ui-title--lg{font-size:var(--ui-fs-xl);}
.ui-muted{color:var(--ui-ink-3);}
.ui-strong{color:var(--ui-ink); font-weight:650;}
.ui-num{font-variant-numeric:tabular-nums;}

/* ==========================================================================
   7 · STATS, NOTES, EMPTY, FACTS
   ========================================================================== */
.ui-stats{display:grid; grid-template-columns:repeat(var(--ui-cols,4),minmax(0,1fr)); gap:12px; margin:0 0 var(--ui-2);}
.ui-stat{
  background:var(--ui-surface); border:1px solid var(--ui-line); border-radius:var(--ui-r-lg);
  padding:14px 16px; box-shadow:var(--ui-shadow); position:relative; overflow:hidden;
}
.ui-stat::before{content:""; position:absolute; inset:0 auto 0 0; width:3px; background:var(--ui-neutral);}
.ui-stat--danger::before{background:var(--ui-danger);}
.ui-stat--warning::before{background:var(--ui-warning);}
.ui-stat--hold::before{background:var(--ui-hold);}
.ui-stat--review::before{background:var(--ui-review);}
.ui-stat--success::before{background:var(--ui-success);}
.ui-stat--accent::before{background:var(--ui-accent);}
.ui-stat--info::before{background:var(--ui-info);}
.ui-stat__label{font-size:var(--ui-fs-xs); color:var(--ui-ink-2); font-weight:550;}
.ui-stat__value{font-size:var(--ui-fs-3xl); font-weight:700; line-height:1.15; color:var(--ui-ink); font-variant-numeric:tabular-nums; margin-top:4px;}
.ui-stat__hint{font-size:var(--ui-fs-2xs); color:var(--ui-ink-3); margin-top:4px;}

.ui-note{
  display:flex; gap:8px; align-items:baseline; flex-wrap:wrap;
  border:1px solid var(--ui-neutral-line); border-left:3px solid var(--ui-neutral);
  background:var(--ui-neutral-soft); border-radius:var(--ui-r-md);
  padding:10px 14px; margin:var(--ui-2) 0 var(--ui-4); font-size:var(--ui-fs-sm); line-height:1.6;
}
.ui-note__title{font-weight:650;}
.ui-note__body{color:var(--ui-ink-2);}
.ui-note--info{background:var(--ui-info-soft); border-color:var(--ui-info-line); border-left-color:var(--ui-info);}
.ui-note--info .ui-note__title{color:var(--ui-info-ink);}
.ui-note--accent{background:var(--ui-accent-soft); border-color:var(--ui-accent-line); border-left-color:var(--ui-accent);}
.ui-note--accent .ui-note__title{color:var(--ui-accent-ink);}
.ui-note--warning{background:var(--ui-warning-soft); border-color:var(--ui-warning-line); border-left-color:var(--ui-warning);}
.ui-note--warning .ui-note__title{color:var(--ui-warning-ink);}
.ui-note--danger{background:var(--ui-danger-soft); border-color:var(--ui-danger-line); border-left-color:var(--ui-danger);}
.ui-note--danger .ui-note__title{color:var(--ui-danger-ink);}
.ui-note--success{background:var(--ui-success-soft); border-color:var(--ui-success-line); border-left-color:var(--ui-success);}
.ui-note--success .ui-note__title{color:var(--ui-success-ink);}
.ui-note--review{background:var(--ui-review-soft); border-color:var(--ui-review-line); border-left-color:var(--ui-review);}
.ui-note--review .ui-note__title{color:var(--ui-review-ink);}
.ui-note--hold{background:var(--ui-hold-soft); border-color:var(--ui-hold-line); border-left-color:var(--ui-hold);}
.ui-note--hold .ui-note__title{color:var(--ui-hold-ink);}

.ui-empty{
  display:block; border:1px dashed var(--ui-line-2); border-radius:var(--ui-r-lg);
  background:var(--ui-surface-2); padding:22px 18px; text-align:center;
}
.ui-empty__title{display:block; font-size:var(--ui-fs-md); font-weight:600; color:var(--ui-ink-2);}
.ui-empty__desc{display:block; font-size:var(--ui-fs-sm); color:var(--ui-ink-3); margin-top:4px;}

.ui-facts{display:grid; grid-template-columns:repeat(var(--ui-cols,3),minmax(0,1fr)); gap:10px 18px; margin:0;}
.ui-fact dt{font-size:var(--ui-fs-2xs); color:var(--ui-ink-3); font-weight:600; margin:0 0 3px;}
.ui-fact dd{margin:0; font-size:var(--ui-fs-md); color:var(--ui-ink); font-weight:600;}

/* ==========================================================================
   8 · TABLE
   ========================================================================== */
.ui-table-wrap{
  border:1px solid var(--ui-line); border-radius:var(--ui-r-lg);
  background:var(--ui-surface); overflow-x:auto; box-shadow:var(--ui-shadow);
}
.ui-table{width:100%; border-collapse:collapse; font-size:var(--ui-fs-sm);}
.ui-table th{
  text-align:left; font-size:var(--ui-fs-2xs); font-weight:650; color:var(--ui-ink-3);
  background:var(--ui-surface-2); padding:9px 14px; border-bottom:1px solid var(--ui-line);
  white-space:nowrap;
}
.ui-table td{padding:11px 14px; border-top:1px solid var(--ui-line); color:var(--ui-ink-2); vertical-align:top;}
.ui-table tbody tr:first-child td{border-top:0;}
.ui-table tbody tr:hover{background:var(--ui-surface-2);}
.ui-table .ui-strong, .ui-table .ui-title{color:var(--ui-ink);}

/* ==========================================================================
   9 · ROW LIST
   ========================================================================== */
.ui-list{border:1px solid var(--ui-line); border-radius:var(--ui-r-lg); background:var(--ui-surface); box-shadow:var(--ui-shadow); overflow:hidden;}
[class*="st-key-ui-list"]{
  border:1px solid var(--ui-line); border-radius:var(--ui-r-lg);
  background:var(--ui-surface); box-shadow:var(--ui-shadow); padding:0 var(--ui-5); gap:0;
}
[class*="st-key-ui-list"] [data-testid="stLayoutWrapper"] > [data-testid="stVerticalBlock"]{
  border-bottom:1px solid var(--ui-line); padding:14px 0; gap:var(--ui-2);
}
[class*="st-key-ui-list"] [data-testid="stLayoutWrapper"]:last-child > [data-testid="stVerticalBlock"]{border-bottom:0;}
[class*="st-key-ui-list"] [data-testid^="stBaseButton-"]{min-height:32px; padding-block:2px; font-size:var(--ui-fs-sm);}

.ui-row{display:grid; grid-template-columns:auto 1fr; gap:12px; align-items:start;}
.ui-row__mark{padding-top:2px;}
.ui-row__body{min-width:0;}
.ui-row__top{display:flex; align-items:baseline; gap:8px; flex-wrap:wrap;}
.ui-row__title{font-size:var(--ui-fs-lg); font-weight:650; color:var(--ui-ink); line-height:1.35; letter-spacing:-.006em;}
.ui-row__meta{margin-top:7px;}
.ui-row__desc{margin-top:6px; font-size:var(--ui-fs-sm); color:var(--ui-ink-3); line-height:1.55;
  display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden;}

/* ==========================================================================
   10 · CARD, FLOW, METER
   ========================================================================== */
.ui-card{
  background:var(--ui-surface); border:1px solid var(--ui-line);
  border-radius:var(--ui-r-lg); padding:16px 18px; box-shadow:var(--ui-shadow);
}
.ui-card--accent{border-left:3px solid var(--ui-accent);}
.ui-card--warning{background:var(--ui-warning-soft); border-color:var(--ui-warning-line);}
.ui-card--danger{background:var(--ui-danger-soft); border-color:var(--ui-danger-line);}
.ui-card--review{border-left:3px solid var(--ui-review);}
.ui-card__head{margin-bottom:10px; padding-bottom:10px; border-bottom:1px solid var(--ui-line);}

.ui-flow{display:flex; align-items:stretch; gap:0; flex-wrap:wrap;}
.ui-flow__step{
  display:flex; flex-direction:column; gap:4px; min-width:0; flex:1 1 150px;
  border:1px solid var(--ui-line); border-radius:var(--ui-r-md);
  background:var(--ui-surface); padding:10px 12px;
}
.ui-flow__step--accent{border-color:var(--ui-accent-line); background:var(--ui-accent-soft);}
.ui-flow__step--warning{border-color:var(--ui-warning-line); background:var(--ui-warning-soft);}
.ui-flow__step--danger{border-color:var(--ui-danger-line); background:var(--ui-danger-soft);}
.ui-flow__step--success{border-color:var(--ui-success-line); background:var(--ui-success-soft);}
.ui-flow__step--review{border-color:var(--ui-review-line); background:var(--ui-review-soft);}
.ui-flow__label{font-size:var(--ui-fs-2xs); font-weight:650; color:var(--ui-ink-3); letter-spacing:.02em;}
.ui-flow__value{font-size:var(--ui-fs-md); font-weight:650; color:var(--ui-ink); line-height:1.35;}
.ui-flow__arrow{
  align-self:center; flex:none; width:18px; height:1px; background:var(--ui-line-2);
  position:relative; margin:0 2px;
}
.ui-flow__arrow::after{
  content:""; position:absolute; right:0; top:-3px;
  border-left:5px solid var(--ui-line-2); border-top:3.5px solid transparent; border-bottom:3.5px solid transparent;
}

.ui-meter{margin:10px 0 0;}
.ui-meter__head{display:flex; align-items:baseline; gap:8px;}
.ui-meter__label{font-size:var(--ui-fs-2xs); color:var(--ui-ink-3); font-weight:600;}
.ui-meter__value{margin-left:auto; font-size:var(--ui-fs-lg); font-weight:700; font-variant-numeric:tabular-nums; color:var(--ui-ink);}
.ui-meter__track{position:relative; height:6px; border-radius:3px; background:var(--ui-surface-3); margin:6px 0 5px; overflow:visible;}
.ui-meter__track i{display:block; height:100%; border-radius:3px; background:var(--ui-neutral);}
.ui-meter--success .ui-meter__track i{background:var(--ui-success);}
.ui-meter--warning .ui-meter__track i{background:var(--ui-warning);}
.ui-meter__track b{position:absolute; top:-3px; width:2px; height:12px; background:var(--ui-ink-2); border-radius:1px;}
.ui-meter__foot{font-size:var(--ui-fs-2xs); color:var(--ui-ink-2); font-weight:600;}
.ui-meter__caption{font-size:var(--ui-fs-2xs); color:var(--ui-ink-3); margin-top:3px; line-height:1.5;}

/* ==========================================================================
   11 · TIMELINE
   ========================================================================== */
.ui-tl{position:relative; margin:0; padding:0 0 0 26px; list-style:none;}
.ui-tl::before{content:""; position:absolute; left:5px; top:8px; bottom:8px; width:2px; background:var(--ui-line-2); border-radius:1px;}
.ui-tl__item{position:relative; padding:0 0 20px;}
.ui-tl__item:last-child{padding-bottom:0;}
.ui-tl__item::before{
  content:""; position:absolute; left:-26px; top:4px; width:12px; height:12px;
  border-radius:50%; background:var(--ui-surface); border:3px solid var(--ui-line-2);
}
.ui-tl__item--in::before{border-color:var(--ui-accent);}
.ui-tl__item--out::before{border-color:var(--ui-review);}
.ui-tl__head{display:flex; align-items:baseline; gap:8px; flex-wrap:wrap;}
.ui-tl__subject{font-size:var(--ui-fs-md); font-weight:650; color:var(--ui-ink);}
.ui-tl__time{margin-left:auto; font-size:var(--ui-fs-2xs); color:var(--ui-ink-3); font-variant-numeric:tabular-nums;}
.ui-tl__meta{margin-top:5px; font-size:var(--ui-fs-xs); color:var(--ui-ink-3);}

/* ==========================================================================
   12 · TRACE
   ========================================================================== */
.ui-trace{display:grid; grid-template-columns:auto 1fr auto; gap:10px 12px; align-items:baseline;}
.ui-trace__phase{font-size:var(--ui-fs-2xs); font-weight:650; color:var(--ui-ink-3); letter-spacing:.02em; white-space:nowrap;}
.ui-trace__step{font-size:var(--ui-fs-sm); font-weight:650; color:var(--ui-ink);}
.ui-trace__msg{grid-column:2 / 4; font-size:var(--ui-fs-sm); color:var(--ui-ink-2); line-height:1.6; margin-top:-4px;}
.ui-trace__meta{grid-column:2 / 4; margin-top:2px;}
.ui-trace__time{grid-column:2 / 4; font-size:var(--ui-fs-2xs); color:var(--ui-ink-3); font-variant-numeric:tabular-nums;}

/* ==========================================================================
   13 · MAIL CARD AND STATUS BAR
   ========================================================================== */
.ui-mail{
  border:1px solid var(--ui-line); border-radius:var(--ui-r-lg); background:var(--ui-surface);
  padding:16px 18px; box-shadow:var(--ui-shadow);
}
.ui-mail__meta{font-size:var(--ui-fs-2xs); color:var(--ui-ink-3);}
.ui-mail__subject{display:block; font-size:var(--ui-fs-lg); font-weight:650; color:var(--ui-ink); margin:6px 0 2px;}
.ui-mail__from{font-size:var(--ui-fs-xs); color:var(--ui-ink-3);}
.ui-mail__body{margin-top:12px; padding-top:12px; border-top:1px solid var(--ui-line); font-size:var(--ui-fs-md); color:var(--ui-ink-2); line-height:1.7; white-space:pre-wrap;}

.ui-bar{
  display:flex; align-items:center; gap:18px; flex-wrap:wrap;
  background:var(--ui-surface); border:1px solid var(--ui-line);
  border-left:3px solid var(--ui-success); border-radius:var(--ui-r-lg);
  padding:11px 16px; font-size:var(--ui-fs-sm); color:var(--ui-ink-2);
}
.ui-bar--warning{border-left-color:var(--ui-warning);}
.ui-bar--danger{border-left-color:var(--ui-danger);}
.ui-bar__item{display:flex; align-items:center; gap:7px;}
.ui-bar__item b{color:var(--ui-ink); font-weight:650;}
.ui-bar__sep{width:1px; height:14px; background:var(--ui-line);}

/* ==========================================================================
   14 · RESPONSIVE
   ========================================================================== */
@media (max-width:1200px){
  .ui-stats{grid-template-columns:repeat(2,minmax(0,1fr));}
  .ui-facts{grid-template-columns:repeat(2,minmax(0,1fr));}
  .ui-flow{flex-direction:column;}
  .ui-flow__arrow{display:none;}
}
@media (max-width:820px){
  .ui-stats{grid-template-columns:repeat(1,minmax(0,1fr));}
  .ui-bar__sep{display:none;}
}
</style>
"""


def inject_styles() -> None:
    st.markdown(_STYLES, unsafe_allow_html=True)
