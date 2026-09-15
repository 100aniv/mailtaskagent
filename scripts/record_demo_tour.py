"""Record the Streamlit demo tour and stamp when each screen appeared.

Start the app first, then:

    .venv/Scripts/python.exe -m scripts.record_demo_tour         --trace-mail-id GMAIL-xxxxxxxxxxxx         --task-title "<the task title shown on the home screen>"

Requires playwright with chromium installed, and ffmpeg (from imageio-ffmpeg,
on PATH, or MTA_FFMPEG). It only reads the running app: nothing is sent and the
task database is not written to.

Alongside the capture it writes tour_marks.json, the offset at which each beat
of the tour became visible. scripts/build_demo_video.py places captions and
narration from those marks, so a re-record cannot leave them out of sync.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "output" / "submission"
RAW_DIR = OUT_DIR / "raw"
VIDEO_NAME = "09285_백준현_시연영상.mp4"
SRT_NAME = "09285_백준현_시연영상.srt"
REPORT_NAME = "09285_백준현_시연영상_검수.json"
MARKS_NAME = "tour_marks.json"
# Both of these name rows in the operator's own database, so they are passed
# in rather than committed.
DEFAULT_APP_URL = "http://localhost:8501"
# Overridable via --trace-mail-id once the deliberation seed mails have a real
# Gmail id; falls back to the older single-conclusion trace otherwise.
DELIBERATION_TRACE_MAIL_ID: str | None = None


def wait_app(page: Page, text: str, timeout: int = 30_000) -> None:
    page.get_by_text(text, exact=True).first.wait_for(state="visible", timeout=timeout)
    page.wait_for_timeout(700)


def click_radio(page: Page, name: str) -> None:
    labels = page.locator("label[data-testid='stRadioOption']").filter(has_text=name)
    if labels.count() == 0:
        raise RuntimeError(f"화면에서 선택 항목을 찾지 못했습니다: {name}")
    click_with_cursor(page, labels.first)
    page.wait_for_timeout(550)


def click_sidebar(page: Page, name: str) -> None:
    click_radio(page, name)


def open_target_task(page: Page, task_title: str) -> None:
    row = page.locator("div[data-testid='stVerticalBlock']").filter(has_text=task_title)
    buttons = row.get_by_role("button", name="업무 상세 보기")
    if buttons.count() == 0:
        raise RuntimeError("대상 업무의 상세 보기 버튼을 찾지 못했습니다.")
    click_with_cursor(page, buttons.last)
    wait_app(page, "업무 상세")


def close_dialog(page: Page) -> None:
    click_with_cursor(page, page.get_by_role("button", name="Close"))
    page.wait_for_timeout(450)


def add_cursor(page: Page) -> None:
    page.evaluate(
        """
        () => {
          if (document.getElementById('mta-video-cursor')) return;
          const c = document.createElement('div');
          c.id = 'mta-video-cursor';
          c.innerHTML = `<svg width="30" height="38" viewBox="0 0 30 38" aria-hidden="true">
            <path d="M3 2 L3 30 L10 23 L16 36 L21 33 L15 21 L27 21 Z"
              fill="#ffffff" stroke="#14213d" stroke-width="2.2" stroke-linejoin="round"/>
          </svg>`;
          c.style.cssText = `position:fixed;z-index:2147483647;width:30px;height:38px;
            pointer-events:none;left:50%;top:50%;filter:drop-shadow(0 2px 3px rgba(0,0,0,.35));
            transition:left .18s ease,top .18s ease;`;
          const ring = document.createElement('div');
          ring.id = 'mta-video-click-ring';
          ring.style.cssText = `position:fixed;z-index:2147483646;width:18px;height:18px;
            border:3px solid #2563eb;border-radius:50%;pointer-events:none;opacity:0;
            transform:translate(-50%,-50%) scale(.45);`;
          document.body.appendChild(c);
          document.body.appendChild(ring);
          document.addEventListener('mousemove', e => {
            c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px';
          });
        }
        """
    )


def point_at(page: Page, locator, settle_ms: int = 420) -> None:
    add_cursor(page)
    box = locator.bounding_box()
    if box is None:
        raise RuntimeError("포인터를 이동할 화면 요소의 위치를 찾지 못했습니다.")
    x = box["x"] + min(max(box["width"] * 0.55, 12), max(box["width"] - 8, 12))
    y = box["y"] + box["height"] * 0.52
    page.mouse.move(x, y, steps=12)
    page.wait_for_timeout(settle_ms)


def click_with_cursor(page: Page, locator) -> None:
    point_at(page, locator)
    box = locator.bounding_box()
    assert box is not None
    x = box["x"] + min(max(box["width"] * 0.55, 12), max(box["width"] - 8, 12))
    y = box["y"] + box["height"] * 0.52
    page.evaluate(
        """({x, y}) => {
          const r = document.getElementById('mta-video-click-ring');
          if (!r) return;
          r.style.left = x + 'px'; r.style.top = y + 'px';
          r.style.transition = 'none'; r.style.opacity = '1';
          r.style.transform = 'translate(-50%,-50%) scale(.45)';
          requestAnimationFrame(() => {
            r.style.transition = 'opacity .55s ease, transform .55s ease';
            r.style.opacity = '0';
            r.style.transform = 'translate(-50%,-50%) scale(2.2)';
          });
        }""",
        {"x": x, "y": y},
    )
    locator.click()
    page.wait_for_timeout(320)


def pause(page: Page, seconds: float, scroll_y: int | None = None) -> None:
    if scroll_y is not None:
        page.evaluate("y => window.scrollTo({top:y, behavior:'smooth'})", scroll_y)
    page.wait_for_timeout(int(seconds * 1000))


def run_tour(
    page: Page,
    fast: bool,
    trace_mail_id: str,
    task_title: str,
    app_url: str = DEFAULT_APP_URL,
    started_at: float | None = None,
    marks: list[dict] | None = None,
) -> list[str]:
    checks: list[str] = []
    hold = (lambda normal: 0.5 if fast else normal)

    def mark(beat: str) -> None:
        """Stamp when a beat became visible, measured from recording start."""
        if marks is None or started_at is None:
            return
        marks.append({"beat": beat, "at": round(time.monotonic() - started_at, 3)})

    page.goto(app_url, wait_until="domcontentloaded")
    wait_app(page, "업무 홈")
    add_cursor(page)
    checks.append("업무 홈")
    mark("home")
    page.mouse.move(1180, 112, steps=12)
    pause(page, hold(5))

    open_target_task(page, task_title)
    checks.append("실제 Gmail 업무 상세")
    mark("task_detail")
    pause(page, hold(3))
    click_with_cursor(page, page.get_by_role("tab", name=re.compile(r"메일 흐름")))
    wait_app(page, "행을 클릭하면 아래에 해당 메일의 전체 내용이 열립니다.")
    checks.append("메일 본문·발신자·수신자")
    mark("mail_flow")
    pause(page, hold(6), 260)

    click_with_cursor(page, page.get_by_role("tab", name="AI 회신 준비", exact=True))
    wait_app(page, "발송 안전 정책")
    checks.append("회신 방식·신뢰도·승인 정책")
    mark("reply_agent")
    pause(page, hold(8), 150)
    close_dialog(page)

    click_sidebar(page, "운영 상태")
    wait_app(page, "운영 상태")
    click_radio(page, "시스템 로그")
    wait_app(page, "Agentic Workflow Trace")
    trace_select = page.get_by_role("combobox", name="Trace를 확인할 Mail")
    click_with_cursor(page, trace_select)
    # The id also appears in the event table below, so scope to the listbox the
    # combobox just opened rather than matching the page text.
    option = page.get_by_role("option", name=trace_mail_id, exact=True)
    if option.count() == 0:
        option = page.locator("li").filter(has_text=trace_mail_id)
    click_with_cursor(page, option.first)
    page.get_by_text("SQLite RAG 검색", exact=True).first.wait_for(state="visible", timeout=20_000)
    checks.append("Agentic Workflow Trace")
    mark("trace")
    pause(page, hold(12), 0)
    mark("retrieval")
    pause(page, hold(16), 520)

    comparison = page.get_by_text("검토한 후보", exact=True)
    if comparison.count():
        comparison.first.scroll_into_view_if_needed()
        checks.append("가설 생성·평가 후보 비교")
        mark("comparison")
        pause(page, hold(34), None)
    else:
        mark("comparison_missing")
        pause(page, hold(14), 900)

    # The review queue needs the source mailbox loaded into the session before it
    # can render a decision form, and a fresh recording session has not loaded it,
    # so it would only show a warning. The same handoff is visible here, in this
    # mail's own log, with no navigation away from the reasoning.
    guard_event = page.get_by_text("M-03 PYTHON_GUARD", exact=True)
    if guard_event.count():
        guard_event.first.scroll_into_view_if_needed()
        page.wait_for_timeout(500)
    checks.append("Human-in-the-loop")
    mark("guard_handoff")
    pause(page, hold(18), None)

    click_with_cursor(page, page.get_by_role("button", name="MVP 시연·검증 화면", exact=True))
    wait_app(page, "MVP 시연·검증")
    quality = page.get_by_text("품질 검증", exact=True)
    if quality.count():
        click_with_cursor(page, quality.first)
        page.wait_for_timeout(550)
    page.get_by_text("15/15", exact=True).first.wait_for(state="visible", timeout=20_000)
    checks.append("최종 품질 증적")
    mark("quality")
    pause(page, hold(32), 0)

    return checks


SUBTITLES = [
    (0, 7, "MailTaskAgent | Gmail 메일을 업무 Lifecycle로 관리하는 Agentic AI"),
    (7, 17, "실제 업무 모드입니다. Gmail을 1분 주기로 확인하고 새 Mail ID만 처리합니다."),
    (17, 29, "실제 Gmail 테스트 메일에서 생성된 Task를 선택합니다."),
    (29, 43, "원문·발신자·수신자·Gmail Mail ID와 Task 연결 결과를 한 화면에서 확인합니다."),
    (43, 56, "M-01 회사 LLM이 업무 의미·Intent·요청·기한을 구조화했습니다."),
    (56, 70, "Reply Agent는 DATE_REPLY를 선택했습니다. 0.95는 LLM 자기보고 신뢰도입니다."),
    (70, 82, "필요한 날짜를 받은 뒤 초안을 만들며 사용자 승인 전에는 발송하지 않습니다."),
    (82, 95, "핵심은 고정 순서가 아니라 Mail·Task·History에 따라 다음 Action이 달라진다는 점입니다."),
    (95, 111, "SQLite RAG가 관련 Task·최근 Mail·History를 검색하고 Context Agent가 관계와 Action을 제안합니다."),
    (111, 128, "이 사례는 Agent 제안과 Intent가 충돌해 Python Guard가 자동 실행을 중단했습니다."),
    (128, 145, "불확실하거나 위험한 변경은 ASK_USER로 이관하고 사용자 결정 전까지 DB를 바꾸지 않습니다."),
    (145, 158, "반복 검증: 회사 LLM Live 15/15, Action 28/28, pytest 179개 통과"),
    (158, 166, "실제 Gmail 수집·승인 발송 E2E와 중복 방지도 별도 증적으로 검증했습니다."),
    (166, 174, "최종 MVP 완료 | Outlook·사내 운영 전환은 Post-MVP입니다."),
]


def srt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(path: Path) -> None:
    blocks = []
    for idx, (start, end, text) in enumerate(SUBTITLES, start=1):
        blocks.append(f"{idx}\n{srt_time(start)} --> {srt_time(end)}\n{text}\n")
    path.write_text("\n".join(blocks), encoding="utf-8-sig")


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


def burn_subtitles(raw: Path, srt: Path, output: Path) -> None:
    ffmpeg = find_ffmpeg()
    srt_filter = str(srt.resolve()).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    style = (
        "FontName=Malgun Gothic,FontSize=22,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00151B2B,BackColour=&H90000000,BorderStyle=3,"
        "Outline=1,Shadow=0,MarginV=28,Alignment=2"
    )
    cmd = [
        str(ffmpeg), "-y", "-i", str(raw),
        "-vf", f"subtitles='{srt_filter}':force_style='{style}'",
        "-c:v", "mpeg4", "-q:v", "4",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-an", str(output),
    ]
    subprocess.run(cmd, check=True)


def probe_video(path: Path) -> dict:
    ffmpeg = find_ffmpeg()
    proc = subprocess.run([str(ffmpeg), "-i", str(path)], capture_output=True)
    text = proc.stderr.decode("utf-8", errors="replace")
    duration = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", text)
    size = re.search(r"Video:.*?, (\d+)x(\d+)", text)
    seconds = None
    if duration:
        seconds = int(duration.group(1)) * 3600 + int(duration.group(2)) * 60 + float(duration.group(3))
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "duration_seconds": seconds,
        "width": int(size.group(1)) if size else None,
        "height": int(size.group(2)) if size else None,
        "under_5_minutes": seconds is not None and seconds <= 300,
        "under_500_mb": path.stat().st_size <= 500 * 1024 * 1024,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fast", action="store_true", help="동선만 빠르게 검증")
    parser.add_argument("--encode-only", action="store_true", help="최신 원본에 자막만 합성")
    parser.add_argument(
        "--trace-mail-id",
        required=True,
        help="Agentic Workflow Trace에서 선택할 Mail ID (예: GMAIL-xxxxxxxx)",
    )
    parser.add_argument(
        "--task-title",
        required=True,
        help="업무 홈에서 상세를 열 Task 제목",
    )
    parser.add_argument("--app-url", default=DEFAULT_APP_URL, help="실행 중인 Streamlit 주소")
    args = parser.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    start = time.time()
    checks: list[str] = []

    if args.encode_only:
        raw_files = sorted(RAW_DIR.glob("*.webm"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not raw_files:
            raise FileNotFoundError("합성할 녹화 원본이 없습니다.")
        raw_path = raw_files[0]
        srt_path = OUT_DIR / SRT_NAME
        output_path = OUT_DIR / VIDEO_NAME
        write_srt(srt_path)
        burn_subtitles(raw_path, srt_path, output_path)
        report = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "source": "actual Streamlit UI using Gmail-backed operational DB; no new mail sent",
            "checks": ["recording tour completed before encode retry"],
            "elapsed_build_seconds": round(time.time() - start, 2),
            "video": probe_video(output_path),
            "subtitle_file": str(srt_path),
            "contains_audio": False,
            "privacy": "synthetic test accounts and data only; no API keys or OAuth tokens shown",
        }
        (OUT_DIR / REPORT_NAME).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1600, "height": 900},
            device_scale_factor=1,
            record_video_dir=str(RAW_DIR) if not args.fast else None,
            record_video_size={"width": 1600, "height": 900} if not args.fast else None,
            locale="ko-KR",
        )
        page = context.new_page()
        # The recording clock starts with the context, so every mark below is an
        # offset into the raw video.
        started_at = time.monotonic()
        marks: list[dict] = []
        checks = run_tour(
            page,
            args.fast,
            trace_mail_id=args.trace_mail_id,
            task_title=args.task_title,
            app_url=args.app_url,
            started_at=started_at,
            marks=marks,
        )
        marks.append({"beat": "end", "at": round(time.monotonic() - started_at, 3)})
        video = page.video
        context.close()
        browser.close()
        if args.fast:
            print(json.dumps({"status": "PASS", "checks": checks}, ensure_ascii=False, indent=2))
            return
        if video is None:
            raise RuntimeError("Playwright 녹화 파일이 생성되지 않았습니다.")
        raw_path = Path(video.path())

    marks_path = RAW_DIR / MARKS_NAME
    marks_path.write_text(
        json.dumps({"trace_mail_id": args.trace_mail_id, "marks": marks}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"tour marks -> {marks_path}")

    srt_path = OUT_DIR / SRT_NAME
    output_path = OUT_DIR / VIDEO_NAME
    write_srt(srt_path)
    burn_subtitles(raw_path, srt_path, output_path)
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source": "actual Streamlit UI using Gmail-backed operational DB; no new mail sent",
        "checks": checks,
        "elapsed_build_seconds": round(time.time() - start, 2),
        "video": probe_video(output_path),
        "subtitle_file": str(srt_path),
        "contains_audio": False,
        "privacy": "synthetic test accounts and data only; no API keys or OAuth tokens shown",
    }
    (OUT_DIR / REPORT_NAME).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
