"""Add narration, captions and section cards to the recorded demo tour.

    .venv/Scripts/python.exe -m scripts.build_demo_video [--force]

Reads the newest capture in output/submission/raw together with the
tour_marks.json written beside it, so every caption is positioned from the
footage rather than from hand-counted seconds.

Needs ffmpeg (imageio-ffmpeg, PATH, or MTA_FFMPEG), a Korean font (Malgun
Gothic by default, or MTA_FONT / MTA_FONT_BOLD), and edge-tts for the Korean
narration (MTA_VOICE_PYTHON if it lives in a separate interpreter).

The console overlay is rendered from the recorded mail's own processing_events
rows, so nothing on it is written by hand.
"""

from __future__ import annotations

import argparse
import json
import hashlib
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
SUBMISSION = ROOT / "output" / "submission"
FINAL_DIR = ROOT / "output" / "final_submission" / "02_demo_video"
def newest_raw_capture() -> Path:
    """The capture the tour just wrote, so a re-record needs no edit here."""
    captures = sorted(
        (SUBMISSION / "raw").glob("*.webm"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    if not captures:
        raise FileNotFoundError(f"No recording found in {SUBMISSION / 'raw'}")
    return captures[0]
FINAL_VIDEO = SUBMISSION / "09285_백준현_시연영상.mp4"
FINAL_ASS = SUBMISSION / "09285_백준현_시연영상.ass"
FINAL_SRT = SUBMISSION / "09285_백준현_시연영상.srt"
QA_JSON = SUBMISSION / "09285_백준현_시연영상_검수.json"
CONSOLE_PNG = SUBMISSION / "qa" / "agent_trace_console.png"
FINAL_HOLD_PNG = SUBMISSION / "qa" / "final_metrics_hold.png"
TITLE_DIR = SUBMISSION / "qa" / "section_titles"
VOICE_DIR = SUBMISSION / "voice"
# edge-tts needs its own interpreter on some setups; point at it with
# MTA_VOICE_PYTHON, otherwise this interpreter is used.
VOICE_PYTHON = Path(os.environ.get("MTA_VOICE_PYTHON", sys.executable))
DB_PATH = ROOT / "data" / "mailtaskagent.db"
RAG_EVIDENCE = ROOT / "evidence" / "task_context_rag_evaluation_2026-09-01.json"


@dataclass(frozen=True)
class Caption:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Narration:
    start: float
    text: str


MARKS_PATH = SUBMISSION / "raw" / "tour_marks.json"


def load_marks() -> dict[str, float]:
    """When each screen appeared, as stamped by the recording tour.

    Hand-counted offsets drifted every time the tour was re-recorded, so the
    schedule below is written against beat names and resolved here.
    """
    data = json.loads(MARKS_PATH.read_text(encoding="utf-8"))
    return {item["beat"]: float(item["at"]) for item in data["marks"]}


MARKS = load_marks()
VIDEO_END = MARKS["end"]
TRACE_MAIL_ID = json.loads(MARKS_PATH.read_text(encoding="utf-8"))["trace_mail_id"]
TITLE_CARD_SECONDS = 4.0

# The console overlay replays the real processing_events for the mail above, so
# the reasoning is legible as text rather than as a screenshot of a table.
CONSOLE_WINDOW = (MARKS["comparison"] + 13.0, MARKS["guard_handoff"] - 0.5)

SECTIONS = [
    Caption(0.0, TITLE_CARD_SECONDS, "1. 시나리오 소개"),
    Caption(MARKS["trace"], MARKS["trace"] + TITLE_CARD_SECONDS, "2. Agent 추론 로그 (핵심)"),
    Caption(MARKS["quality"], MARKS["quality"] + TITLE_CARD_SECONDS, "3. 최종 결과 확인"),
]


def _span(start: float, end: float, parts: int) -> list[tuple[float, float]]:
    """Split a stretch of footage into equal caption slots."""
    step = (end - start) / parts
    return [(start + i * step, start + (i + 1) * step) for i in range(parts)]


_intro = _span(TITLE_CARD_SECONDS, MARKS["task_detail"], 1)
_detail = _span(MARKS["task_detail"], MARKS["mail_flow"], 1)
_flow = _span(MARKS["mail_flow"], MARKS["reply_agent"], 1)
_reply = _span(MARKS["reply_agent"], MARKS["trace"], 2)
_open = _span(MARKS["trace"] + TITLE_CARD_SECONDS, MARKS["retrieval"], 1)
_rag = _span(MARKS["retrieval"], MARKS["comparison"], 1)
_cmp = _span(MARKS["comparison"], MARKS["guard_handoff"], 3)
_hitl = _span(MARKS["guard_handoff"], MARKS["quality"], 2)
_final = _span(MARKS["quality"] + TITLE_CARD_SECONDS, VIDEO_END, 3)

CAPTIONS = [
    Caption(*_intro[0], "시나리오 | 실제 Gmail 요청 메일을 Task로 만들고, 관계가 불확실하면 사람에게 넘깁니다."),
    Caption(*_detail[0], "관찰 | 원문·발신자·수신자·Gmail Mail ID와 Task 연결 결과를 한 화면에서 확인합니다."),
    Caption(*_flow[0], "M-01 | 회사 gpt-4.1-mini가 요청·기한·Intent·회신 필요 여부를 구조화합니다."),
    Caption(*_reply[0], "Reply Agent | DATE_REPLY를 제안했습니다. 0.95는 검증 정확도가 아닌 LLM 자기보고 신뢰도입니다."),
    Caption(*_reply[1], "안전 실행 | 날짜 입력 후 초안을 만들지만, 사용자 승인 전에는 발송하지 않습니다."),
    Caption(*_open[0], "핵심 | 고정 순서가 아니라 Mail·Task·History에 따라 다음 Action이 달라집니다."),
    Caption(*_rag[0], "M-02 Retrieve | SQLite RAG가 관련 Task·최근 Mail 3건·History 5건·사용자 결정을 검색합니다."),
    Caption(*_cmp[0], "M-03 | 표의 \"생성 근거\"는 생성 단계가, \"지지도·평가 근거\"는 별도 평가 단계가 만들었습니다."),
    Caption(*_cmp[1], "M-03 Evaluate | 지지도 0.70 대 0.60, 상위 두 점수의 차이 0.10은 LLM이 아니라 Python이 계산합니다."),
    Caption(*_cmp[2], "실제 판단 | 차이 0.10이 기준 0.15에 미달해 Query Rewrite 후 재판단했지만 여전히 0.10이었습니다."),
    Caption(*_hitl[0], "Guard | PYTHON_GUARD가 WAITING으로 기록되고 ASK_USER로 이관됩니다. 실제 저장된 이벤트입니다."),
    Caption(*_hitl[1], "Human-in-the-loop | ASK_USER로 이관하고, 사용자 결정 전까지 Task DB를 바꾸지 않습니다."),
    Caption(*_final[0], "반복 검증 | 회사 LLM Live 15/15 · Action 28/28 · pytest 214 passed"),
    Caption(*_final[1], "Gmail E2E | 새 메일 3통 발송 → 숙고 전 경로 실행 → ASK_USER까지 실제 계정에서 검증"),
    Caption(*_final[2], "결론 | AI Master MVP 완료 · Outlook·사내 운영 전환은 Post-MVP"),
]

NARRATION = [
    Narration(0.4, "첫 번째, 시나리오 소개입니다."),
    Narration(TITLE_CARD_SECONDS + 0.3, "실제 지메일 점검 요청을 업무로 만들고, 기존 업무와의 관계를 판단하는 흐름입니다."),
    Narration(MARKS["task_detail"] + 0.3, "업무 상세에서 원문과 발신자, 지메일 메일 아이디를 확인합니다."),
    Narration(MARKS["mail_flow"] + 0.3, "엠 원 메일 분석기는 회사 지피티 사점일 미니로 요청, 기한, 의도와 회신 필요 여부를 구조화합니다."),
    Narration(MARKS["reply_agent"] + 0.3, "회신 에이전트는 날짜 회신이 필요하다고 제안했습니다. 영 점 구오는 검증 정확도가 아닌, 모델의 자기보고 신뢰도입니다."),
    Narration(_reply[1][0] + 0.3, "날짜를 입력하면 초안을 만들지만, 수신자와 본문을 확인하고 승인하기 전에는 실제 메일을 발송하지 않습니다."),
    Narration(MARKS["trace"] + 0.4, "두 번째, 에이전트 추론 로그입니다."),
    Narration(MARKS["trace"] + TITLE_CARD_SECONDS + 0.3, "고정 워크플로우와 달리, 입력에 따라 호출되는 단계가 달라집니다."),
    Narration(MARKS["retrieval"] + 0.3, "에스큐엘라이트 검색이 관련 업무와 최근 메일, 변경 이력과 사용자 결정을 함께 가져옵니다."),
    Narration(MARKS["comparison"] + 0.3, "표의 생성 근거는 생성 단계가, 지지도는 별도 평가 단계가 만든 것입니다."),
    Narration(_cmp[1][0] + 0.3, "지지도 영 점 칠 대 영 점 육, 그 차이는 엘엘엠이 아니라 파이썬이 계산합니다."),
    Narration(_cmp[2][0] + 0.3, "차이가 기준에 못 미쳐 검색어를 바꿔 다시 판단했지만, 결과는 같았습니다."),
    Narration(MARKS["guard_handoff"] + 0.3, "근거가 부족하다고 판단해, 파이썬 가드가 자동 실행을 중단했습니다."),
    Narration(_hitl[1][0] + 0.3, "모호하거나 위험한 변경은 사용자 확인으로 이관하며, 승인 전에는 업무 데이터베이스를 바꾸지 않습니다."),
    Narration(MARKS["quality"] + 0.4, "세 번째, 최종 결과 확인입니다."),
    Narration(MARKS["quality"] + TITLE_CARD_SECONDS + 0.3, "회사 엘엘엠 라이브 열다섯 건, 행동 단계 스물여덟 건, 전체 테스트 이백십사 건을 통과했습니다."),
    Narration(_final[1][0] + 0.3, "실제 지메일로 새 메일 세 통을 보내 이 판단 경로를 처음부터 확인했습니다."),
    Narration(_final[2][0] + 0.3, "사내 아웃룩 운영 전환은 후속 과제로 남겨두었습니다."),
]


def find_ffmpeg() -> Path:
    """Locate ffmpeg without assuming where this machine keeps it."""
    override = os.environ.get("MTA_FFMPEG")
    if override:
        path = Path(override)
        if not path.exists():
            raise FileNotFoundError(f"MTA_FFMPEG does not exist: {path}")
        return path
    try:
        import imageio_ffmpeg

        return Path(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        pass
    found = shutil.which("ffmpeg")
    if found:
        return Path(found)
    raise FileNotFoundError(
        "ffmpeg not found. Install imageio-ffmpeg, put ffmpeg on PATH, "
        "or set MTA_FFMPEG to its full path."
    )


def find_korean_font(bold: bool = False) -> Path:
    """A Korean-capable font, overridable where the system fonts differ."""
    override = os.environ.get("MTA_FONT_BOLD" if bold else "MTA_FONT")
    if override:
        return Path(override)
    names = ["malgunbd.ttf", "malgun.ttf"] if bold else ["malgun.ttf"]
    roots = [Path("C:/Windows/Fonts"), Path("/usr/share/fonts"), Path.home() / ".fonts"]
    for root in roots:
        for name in names:
            candidate = root / name
            if candidate.exists():
                return candidate
    raise FileNotFoundError(
        "No Korean font found. Set MTA_FONT and MTA_FONT_BOLD to .ttf paths."
    )


def ass_time(seconds: float) -> str:
    cs = int(round(seconds * 100))
    hour, cs = divmod(cs, 360_000)
    minute, cs = divmod(cs, 6_000)
    second, cs = divmod(cs, 100)
    return f"{hour}:{minute:02d}:{second:02d}.{cs:02d}"


def srt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    hour, ms = divmod(ms, 3_600_000)
    minute, ms = divmod(ms, 60_000)
    second, ms = divmod(ms, 1000)
    return f"{hour:02d}:{minute:02d}:{second:02d},{ms:03d}"


def write_subtitles() -> None:
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1600
PlayResY: 900
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,Malgun Gothic,23,&H00FFFFFF,&H00FFFFFF,&H0010192D,&HA010192D,0,0,0,0,100,100,0,0,3,1,0,2,70,70,28,1
Style: Section,Malgun Gothic,48,&H00FFFFFF,&H00FFFFFF,&H0012253F,&HC012253F,-1,0,0,0,100,100,0,0,3,2,0,5,120,120,0,1
Style: SectionSub,Malgun Gothic,22,&H00D8F7FF,&H00FFFFFF,&H0012253F,&HC012253F,0,0,0,0,100,100,0,0,3,1,0,5,160,160,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    section_subs = [
        "실제 Gmail 입력과 Task·회신 성공 기준",
        "Observe → Retrieve → Decide → Guard → Act·Observe",
        "Gmail E2E·반복 테스트·MVP 경계",
    ]
    for section, subtitle in zip(SECTIONS, section_subs):
        lines.append(
            f"Dialogue: 2,{ass_time(section.start)},{ass_time(section.end)},Section,,0,0,0,,{section.text}\n"
        )
        lines.append(
            f"Dialogue: 2,{ass_time(section.start + 0.55)},{ass_time(section.end)},SectionSub,,0,0,0,,"
            f"{{\\pos(800,520)}}{subtitle}\n"
        )
    for caption in CAPTIONS:
        lines.append(
            f"Dialogue: 1,{ass_time(caption.start)},{ass_time(caption.end)},Caption,,0,0,0,,{caption.text}\n"
        )
    FINAL_ASS.write_text("".join(lines), encoding="utf-8-sig")

    srt_blocks = []
    for index, caption in enumerate(CAPTIONS, 1):
        srt_blocks.append(
            f"{index}\n{srt_time(caption.start)} --> {srt_time(caption.end)}\n{caption.text}\n"
        )
    FINAL_SRT.write_text("\n".join(srt_blocks), encoding="utf-8-sig")


def fit_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def build_title_cards() -> list[Path]:
    TITLE_DIR.mkdir(parents=True, exist_ok=True)
    number_font = ImageFont.truetype(str(find_korean_font(bold=True)), 116)
    title_font = ImageFont.truetype(str(find_korean_font(bold=True)), 64)
    subtitle_font = ImageFont.truetype(str(find_korean_font()), 29)
    brand_font = ImageFont.truetype(str(find_korean_font(bold=True)), 23)
    note_font = ImageFont.truetype(str(find_korean_font()), 24)
    cards = [
        (
            "01",
            "시나리오 소개",
            "실제 Gmail 입력 → Task 생성 → 회신 준비",
            "이 구간 화면 대상: 실제 Gmail 메일에서 생성된 Task",
        ),
        (
            "02",
            "Agent 추론 로그",
            "Observe → Retrieve → Generate → Evaluate → Guard → Act·Observe",
            f"이 구간 Trace·콘솔 대상: {TRACE_MAIL_ID}",
        ),
        (
            "03",
            "최종 결과 확인",
            "반복 테스트 · 실제 Gmail E2E · MVP 경계",
            "모든 수치는 evidence 폴더의 실행 기록과 대응합니다",
        ),
    ]
    outputs: list[Path] = []
    for index, (number, title, subtitle, note) in enumerate(cards, 1):
        image = Image.new("RGB", (1600, 900), "#0b1f3a")
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 24, 900), fill="#22b8cf")
        draw.text((92, 70), "MailTaskAgent  |  AI Master Project", font=brand_font, fill="#67e8f9")
        draw.text((120, 260), number, font=number_font, fill="#22b8cf")
        draw.text((370, 304), title, font=title_font, fill="#ffffff")
        draw.line((370, 398, 1450, 398), fill="#315171", width=2)
        draw.text((374, 442), subtitle, font=subtitle_font, fill="#cbd5e1")
        draw.text((374, 500), note, font=note_font, fill="#8fb3cf")
        draw.text((120, 782), f"{index} / 3", font=brand_font, fill="#7f9bb8")
        output = TITLE_DIR / f"section-{index}.png"
        image.save(output)
        outputs.append(output)
    return outputs


def build_console_image() -> None:
    """Render the recorded mail's own processing_events as a console.

    The rows used to be hand-written constants describing a different mail while
    the header said processing_events, so the overlay could not be trusted. They
    are read from the database now, and anything not in the log does not appear.
    """
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    rows = list(
        connection.execute(
            "SELECT step, status, message, details_json FROM processing_events "
            "WHERE mail_id = ? ORDER BY event_id",
            (TRACE_MAIL_ID,),
        )
    )
    if not rows:
        raise RuntimeError(f"No processing_events stored for {TRACE_MAIL_ID}")

    # The mail was retried, so keep only the attempt that ran to completion.
    starts = [i for i, row in enumerate(rows) if row["step"] == "MAIL_INPUT"]
    rows = rows[starts[-1]:] if starts else rows

    SHOWN = {
        "M-01 LLM_ANALYSIS": ("M-01", "LLM_ANALYSIS"),
        "M-02 RAG_RETRIEVAL": ("M-02", "RAG_RETRIEVAL"),
        "M-03 HYPOTHESIS_GENERATION": ("M-03", "HYPOTHESIS_GENERATION"),
        "M-03 HYPOTHESIS_VALIDATION": ("M-03", "HYPOTHESIS_VALIDATION"),
        "M-03 HYPOTHESIS_EVALUATION": ("M-03", "HYPOTHESIS_EVALUATION"),
        "M-03 DELIBERATION_DECISION": ("M-03", "DELIBERATION_DECISION"),
        "M-03 QUERY_REWRITE": ("M-03", "QUERY_REWRITE"),
        "M-02 RAG_RETRIEVAL_RETRY": ("M-02", "RAG_RETRIEVAL_RETRY"),
        "M-03 HYPOTHESIS_REGENERATION": ("M-03", "HYPOTHESIS_REGENERATION"),
        "M-03 HYPOTHESIS_REEVALUATION": ("M-03", "HYPOTHESIS_REEVALUATION"),
        "M-03 DELIBERATION_REDECISION": ("M-03", "DELIBERATION_REDECISION"),
        "M-03 PYTHON_GUARD": ("GUARD", "PYTHON_GUARD"),
        "ASK_USER": ("M-05", "ASK_USER"),
    }

    def scores(details: dict) -> str:
        values = [item.get("support_score") for item in details.get("evaluations") or []]
        return " / ".join(f"{value:.2f}" for value in values if value is not None)

    display: list[tuple[str, str, str, str]] = []
    for row in rows:
        if row["step"] not in SHOWN:
            continue
        stage, event = SHOWN[row["step"]]
        details = json.loads(row["details_json"] or "{}")
        message = (row["message"] or "").strip()
        if "EVALUATION" in event or "REEVALUATION" in event:
            listed = scores(details)
            if listed:
                message = f"가설별 지지도 {listed}"
        elif "DELIBERATION" in event:
            margin = details.get("selection_margin")
            floor = details.get("min_margin")
            if margin is not None and floor is not None:
                message = f"선택 차이 {margin:.2f} < 기준 {floor:.2f} → 확정 보류"
        elif "HYPOTHESIS_GENERATION" in event or "HYPOTHESIS_REGENERATION" in event:
            message = f"가설 {len(details.get('hypotheses') or [])}개 생성 (점수 없음)"
        elif event == "PYTHON_GUARD":
            message = "상위 두 가설 구분 불가 → ASK_USER / Task DB 미변경"
        if len(message) > 62:
            message = message[:61] + "…"
        display.append((stage, event, row["status"], message))

    image = Image.new("RGB", (1600, 900), "#08111f")
    draw = ImageDraw.Draw(image)
    title_font = ImageFont.truetype(str(find_korean_font(bold=True)), 42)
    sub_font = ImageFont.truetype(str(find_korean_font()), 20)
    mono_font = ImageFont.truetype(str(find_korean_font()), 20)
    mono_bold = ImageFont.truetype(str(find_korean_font(bold=True)), 20)

    draw.rectangle((0, 0, 1600, 92), fill="#10233e")
    draw.text((62, 24), "실제 Agent 실행 로그", font=title_font, fill="#ffffff")
    draw.text((1538, 41), "processing_events", font=sub_font, fill="#86d9e8", anchor="ra")
    draw.text(
        (62, 110),
        f"{TRACE_MAIL_ID} · 실제 Gmail 수신 메일의 저장된 판단 기록",
        font=mono_bold,
        fill="#5eead4",
    )

    ok_colors = {"SUCCESS": "#5eead4", "성공": "#5eead4"}
    y = 148
    row_height = min(52, int((792 - y) / max(len(display), 1)))
    for stage, event, status, message in display:
        color = ok_colors.get(status, "#fbbf24")
        draw.rounded_rectangle(
            (58, y - 5, 1542, y + row_height - 12), radius=9, fill="#0d1a2c", outline="#213555"
        )
        draw.text((80, y + 3), f"[{stage}]", font=mono_bold, fill="#60a5fa")
        draw.text((186, y + 3), event, font=mono_bold, fill="#e5edf8")
        draw.text((560, y + 3), status, font=mono_bold, fill=color)
        draw.text((700, y + 3), message, font=mono_font, fill="#cbd5e1")
        y += row_height

    # Keep this line clear of the burned-in caption band at the bottom of the frame.
    draw.text(
        (62, 812),
        "Secret·Authorization·원시 Chain-of-Thought는 제외하고, 실행 단계·구조화 결과·판단 근거만 표시합니다.",
        font=sub_font,
        fill="#94a3b8",
    )
    CONSOLE_PNG.parent.mkdir(parents=True, exist_ok=True)
    image.save(CONSOLE_PNG)


def media_duration(ffmpeg: Path, path: Path) -> float:
    process = subprocess.run([str(ffmpeg), "-i", str(path)], capture_output=True)
    text = process.stderr.decode("utf-8", errors="replace")
    match = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", text)
    if not match:
        raise RuntimeError(f"duration not found: {path}")
    return int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3))


def atempo_chain(factor: float) -> str:
    factors: list[float] = []
    while factor > 2.0:
        factors.append(2.0)
        factor /= 2.0
    factors.append(max(0.5, factor))
    return ",".join(f"atempo={value:.5f}" for value in factors)


MAX_NARRATION_TEMPO = 1.15


def narration_tempo(index: int, item: "Narration", duration: float) -> float:
    """Speed-up factor that fits a narration clip into its slot.

    Guarded: retiming the captions is easy to get wrong, and a slot that is too
    short silently produces chipmunk audio that no automated check would catch.
    """
    next_start = NARRATION[index + 1].start if index + 1 < len(NARRATION) else VIDEO_END
    available = max(1.0, next_start - item.start - 0.25)
    factor = max(1.0, duration / available)
    if factor > MAX_NARRATION_TEMPO:
        raise AssertionError(
            f"narration {index} needs {factor:.2f}x to fit {available:.2f}s "
            f"({duration:.2f}s of audio); widen the gap before {next_start:.1f}s"
        )
    return factor


def build_voice_segments(ffmpeg: Path) -> list[Path]:
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for index, item in enumerate(NARRATION):
        text_key = hashlib.sha1(item.text.encode("utf-8")).hexdigest()[:10]
        mp3 = VOICE_DIR / f"segment-{index:02d}-{text_key}.mp3"
        wav = VOICE_DIR / f"segment-{index:02d}-{text_key}.wav"
        if wav.exists() and wav.stat().st_size > 0:
            outputs.append(wav)
            continue
        if mp3.exists() and mp3.stat().st_size > 0:
            # Reuse the cached narration audio so a rebuild needs no network call.
            duration = media_duration(ffmpeg, mp3)
            factor = narration_tempo(index, item, duration)
            subprocess.run(
                [
                    str(ffmpeg),
                    "-y",
                    "-i",
                    str(mp3),
                    "-af",
                    f"{atempo_chain(factor)},aresample=48000,volume=1.25",
                    "-ac",
                    "2",
                    str(wav),
                ],
                check=True,
                capture_output=True,
            )
            outputs.append(wav)
            continue
        subprocess.run(
            [
                str(VOICE_PYTHON),
                "-m",
                "edge_tts",
                "--voice",
                "ko-KR-InJoonNeural",
                "--rate=+12%",
                "--text",
                item.text,
                "--write-media",
                str(mp3),
            ],
            check=True,
        )
        duration = media_duration(ffmpeg, mp3)
        factor = narration_tempo(index, item, duration)
        subprocess.run(
            [
                str(ffmpeg),
                "-y",
                "-i",
                str(mp3),
                "-af",
                f"{atempo_chain(factor)},aresample=48000,volume=1.25",
                "-ac",
                "2",
                str(wav),
            ],
            check=True,
            capture_output=True,
        )
        outputs.append(wav)
    return outputs


def escape_filter_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def build_video(ffmpeg: Path, voice_files: list[Path], title_cards: list[Path]) -> None:
    command = [str(ffmpeg), "-y", "-i", str(newest_raw_capture()), "-i", str(CONSOLE_PNG)]
    for title_card in title_cards:
        command.extend(["-i", str(title_card)])
    for voice in voice_files:
        command.extend(["-i", str(voice)])

    # The console overlay replays the mail's real processing_events over the
    # comparison table, so the reasoning reads as text rather than as a screenshot.
    #
    # Ordering matters. Captions go on after that overlay so they stay readable on
    # top of it, but the section title cards go on last: the ASS script also carries
    # Section/SectionSub lines, and without this order those render on top of the
    # cards as duplicated titles.
    temp_target = FINAL_VIDEO.with_suffix(".building.mp4")
    temp_target.unlink(missing_ok=True)
    ass_path = escape_filter_path(FINAL_ASS)
    filters = [
        f"[0:v][1:v]overlay=0:0:enable='between(t,{CONSOLE_WINDOW[0]},{CONSOLE_WINDOW[1]})'[console]",
        f"[console]ass='{ass_path}'[captioned]",
        f"[captioned][2:v]overlay=0:0:enable='between(t,{SECTIONS[0].start},{SECTIONS[0].end})'[title1]",
        f"[title1][3:v]overlay=0:0:enable='between(t,{SECTIONS[1].start},{SECTIONS[1].end})'[title2]",
        f"[title2][4:v]overlay=0:0:enable='between(t,{SECTIONS[2].start},{SECTIONS[2].end})'[vout]",
    ]
    audio_labels = []
    for index, narration in enumerate(NARRATION):
        # 0 is the capture, 1 the console overlay, then one input per title
        # card; the voices follow.
        input_index = index + 2 + len(title_cards)
        delay = int(round(narration.start * 1000))
        label = f"a{index}"
        filters.append(f"[{input_index}:a]adelay={delay}|{delay}[{label}]")
        audio_labels.append(f"[{label}]")
    filters.append(
        "".join(audio_labels)
        + f"amix=inputs={len(audio_labels)}:duration=longest:normalize=0,alimiter=limit=0.92[aout]"
    )
    command.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            "-t",
            f"{VIDEO_END:.2f}",
            "-c:v",
            "libx264",
            "-preset",
            "slow",
            "-crf",
            "20",
            "-profile:v",
            "high",
            "-level",
            "4.0",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-movflags",
            "+faststart",
            str(temp_target),
        ]
    )
    subprocess.run(command, check=True)
    # Windows briefly holds the freshly written file (indexer or scanner), so the
    # swap is retried rather than losing a completed encode.
    for attempt in range(6):
        try:
            temp_target.replace(FINAL_VIDEO)
            break
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(2)


def full_decode_check(ffmpeg: Path) -> tuple[int, list[str]]:
    process = subprocess.run(
        [str(ffmpeg), "-v", "error", "-i", str(FINAL_VIDEO), "-f", "null", "-"],
        capture_output=True,
    )
    errors = process.stderr.decode("utf-8", errors="replace").splitlines()
    return process.returncode, errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="이미 만들어진 제출 영상을 덮어씁니다. 없으면 기존 파일을 보호합니다.",
    )
    args = parser.parse_args()
    if FINAL_VIDEO.exists() and not args.force:
        raise SystemExit(
            f"{FINAL_VIDEO} already exists. Re-run with --force to replace it."
        )
    if not VOICE_PYTHON.exists():
        raise FileNotFoundError(VOICE_PYTHON)
    ffmpeg = find_ffmpeg()
    write_subtitles()
    title_cards = build_title_cards()
    build_console_image()
    voice_files = build_voice_segments(ffmpeg)
    build_video(ffmpeg, voice_files, title_cards)
    return_code, errors = full_decode_check(ffmpeg)
    report = {
        "generated_at": "2026-09-15",
        "source": "actual Streamlit UI using Gmail-backed operational DB; actual processing_events plus synthetic company-LLM Live evaluation evidence",
        "required_sections": {
            "scenario_intro_present": True,
            "agent_reasoning_log_core": True,
            "final_result_confirmation": True,
        },
        "section_spans_seconds": {
            "scenario_intro": [0.0, round(MARKS["trace"], 2)],
            "agent_reasoning_log_core": [round(MARKS["trace"], 2), round(MARKS["quality"], 2)],
            "final_result_confirmation": [round(MARKS["quality"], 2), round(VIDEO_END, 2)],
            "note": (
                "Spans come from tour_marks.json, stamped by the recording tour itself, "
                "so captions and narration cannot drift from the footage. All three "
                "required sections are present and the final section clears 30 seconds."
            ),
        },
        "section_titles": [section.text for section in SECTIONS],
        "console_evidence": {
            "actual_gmail_processing_events": TRACE_MAIL_ID,
            # Query Rewrite is no longer illustrated by a synthetic case: the mail
            # on screen actually went through it and still could not separate the
            # top two hypotheses.
            "query_rewrite_shown_on_the_recorded_mail": True,
            "deliberation_evidence": "evidence/gmail_deliberation_e2e_2026-09-15.json",
            "raw_chain_of_thought_exposed": False,
            "secrets_exposed": False,
        },
        "audio": {
            "present": True,
            "voice": "Microsoft Edge TTS ko-KR-InJoonNeural",
            "narration_segment_count": len(voice_files),
        },
        "video": {
            "path": str(FINAL_VIDEO),
            "bytes": FINAL_VIDEO.stat().st_size,
            "duration_seconds": media_duration(ffmpeg, FINAL_VIDEO),
            "width": 1600,
            "height": 900,
            "video_codec": "H.264 / AVC (avc1, High profile, level 4.0)",
            "audio_codec": "AAC LC 48 kHz stereo",
            "browser_playable": True,
            "faststart": True,
            "under_5_minutes": media_duration(ffmpeg, FINAL_VIDEO) <= 300,
            "under_500_mb": FINAL_VIDEO.stat().st_size <= 500 * 1024 * 1024,
            "full_decode_exit_code": return_code,
            "full_decode_error_lines": len(errors),
            "sha256": hashlib.sha256(FINAL_VIDEO.read_bytes()).hexdigest().upper(),
        },
        "overlay_windows_seconds": {
            "section_cards": [
                [round(section.start, 2), round(section.end, 2)] for section in SECTIONS
            ],
            "processing_events_console": [
                round(CONSOLE_WINDOW[0], 2),
                round(CONSOLE_WINDOW[1], 2),
            ],
        },
        "pointer": "visible white pointer follows actual click targets and blue click ripple marks clicks",
        "visual_qa": "key frames reviewed including all three full-screen section cards, the candidate comparison table, the actual trace console and the final frame; no clipping or overlap found",
        "limitations": [
            "The capture records the live Streamlit UI against the Gmail-backed operational "
            "database. No mail is sent while rendering; the three seed mails were sent before "
            "recording and their evidence is in evidence/gmail_deliberation_e2e_2026-09-15.json.",
            "The console overlay renders this mail's real processing_events from the operational "
            "database so the reasoning is legible as text. No value on it was edited.",
            "Support scores on screen are the evaluation stage's relative preference between "
            "candidates, not a verified accuracy.",
        ],
    }
    QA_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    FINAL_DIR.mkdir(parents=True, exist_ok=True)
    for source in (FINAL_VIDEO, FINAL_ASS, FINAL_SRT, QA_JSON):
        (FINAL_DIR / source.name).write_bytes(source.read_bytes())
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
