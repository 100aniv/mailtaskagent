"""Check the submission against both official guides, mechanically.

Written because problems kept surfacing one at a time across review rounds. Each
check below corresponds to a line in the presentation guide or the demo video
guide, or to an internal rule the project set for itself, so a clean run means
every stated requirement was actually looked at rather than remembered.

    .venv/Scripts/python.exe -m scripts.audit_submission --deck-version v12

Exits non-zero if anything fails. Warnings do not fail the run but are printed,
because some of them are deliberate choices that should stay visible.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
DRAWING_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"

FAILURES: list[str] = []
WARNINGS: list[str] = []
PASSES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    (PASSES if ok else FAILURES).append(f"{name}{' | ' + detail if detail else ''}")
    return ok


def warn(name: str, detail: str = "") -> None:
    WARNINGS.append(f"{name}{' | ' + detail if detail else ''}")



def _project_python() -> Path:
    """The interpreter this project's dependencies are installed into."""
    if sys.platform == "win32":
        return ROOT / ".venv" / "Scripts" / "python.exe"
    return ROOT / ".venv" / "bin" / "python"


def _ensure_project_environment() -> None:
    """Re-exec under .venv when started from an interpreter that lacks the project.

    Running the audit with a bare `python` picks up whichever interpreter is on
    PATH. That one has no project dependencies, so pytest collects a fraction of
    the suite and the audit reports failures that are about the environment
    rather than the submission.
    """
    import importlib.util

    if all(importlib.util.find_spec(name) for name in ("mailtaskagent", "pytest")):
        return

    venv = _project_python()
    if not venv.exists():
        raise SystemExit(
            "This audit needs the project virtualenv.\n"
            f"Expected it at: {venv}\n"
            "Create it, install requirements.txt, then run:\n"
            f"  {venv} -m scripts.audit_submission"
        )
    if Path(sys.executable).resolve() == venv.resolve():
        raise SystemExit(
            f"Running under {venv} but the project still cannot be imported.\n"
            "Install requirements.txt into that environment first."
        )
    completed = subprocess.run(
        [str(venv), "-m", "scripts.audit_submission", *sys.argv[1:]], cwd=ROOT
    )
    raise SystemExit(completed.returncode)


def _make_output_encodable() -> None:
    """A cp949 console cannot print every character these checks may contain.

    The script used to die on the first unencodable byte, after the checks had
    run, which left the exit code describing the print and not the audit.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


def slide_text(pptx: Path) -> list[str]:
    """Text of each slide, in slide order."""
    archive = zipfile.ZipFile(pptx)
    names = sorted(
        (n for n in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
        key=lambda n: int(re.findall(r"\d+", n)[0]),
    )
    out = []
    for name in names:
        root = ET.fromstring(archive.read(name))
        out.append(
            " ".join(
                "".join(node.text or "" for node in para.iter(DRAWING_NS + "t"))
                for para in root.iter(DRAWING_NS + "p")
            )
        )
    return out


def notes_text(pptx: Path) -> str:
    archive = zipfile.ZipFile(pptx)
    body = []
    for name in archive.namelist():
        if re.fullmatch(r"ppt/notesSlides/notesSlide\d+\.xml", name):
            root = ET.fromstring(archive.read(name))
            body.append(
                " ".join(
                    "".join(node.text or "" for node in para.iter(DRAWING_NS + "t"))
                    for para in root.iter(DRAWING_NS + "p")
                )
            )
    return " ".join(body)


def audit_deck(version: str) -> None:
    pptx = ROOT / "Docs/PRESENTATION/2. 최종" / f"09285_백준현_AI_Master_최종발표자료_{version}.pptx"
    pdf = pptx.with_name(pptx.stem + ".pdf")
    if not check("발표자료 PPTX 존재", pptx.exists(), str(pptx.name)):
        return
    check("발표자료 PDF 존재", pdf.exists(), pdf.name)
    if pdf.exists():
        # The PDF is built from exported PNGs, so it silently goes stale when the
        # deck is rebuilt and the slides are not re-exported. This caught exactly
        # that once.
        check(
            "PDF가 PPTX보다 최신",
            pdf.stat().st_mtime >= pptx.stat().st_mtime,
            "PPTX를 다시 빌드한 뒤 슬라이드를 다시 내보내지 않았습니다",
        )

    slides = slide_text(pptx)
    notes = notes_text(pptx)
    everything = " ".join(slides)

    # --- guide: 장표 구성 표지 + 3페이지 ---
    check("장표 4장", len(slides) == 4, f"{len(slides)}장")
    if pdf.exists():
        pages = len(re.findall(rb"/Type\s*/Page[^s]", pdf.read_bytes()))
        check("PDF 4페이지", pages == 4, f"{pages}페이지")

    # --- guide: 표지는 과제명·멘티(성명+사번)·멘토 ---
    cover = slides[0]
    check("표지 과제명", "MailTaskAgent" in cover)
    check("표지 사번", "09285" in cover)
    check("표지 멘토", "멘토" in cover)

    # --- guide: 문제 정의는 솔루션이 아니라 문제여야 한다 ---
    overview = slides[1]
    solution_shaped = ("로 관리" in overview[:120]) or ("시스템을 만들었" in overview)
    check("문제 정의가 솔루션 문장이 아님", not solution_shaped,
          "개요 첫 문장이 만든 것을 설명하고 있음" if solution_shaped else "")

    # --- guide: 핵심 기능을 Agent 구성 흐름으로 ---
    agent_roles = sum(term in overview for term in ("Mail Analyzer", "Context Agent", "Reply Agent"))
    check("핵심 기능이 Agent 구성 흐름", agent_roles >= 3, f"역할 {agent_roles}개 표기")

    # --- guide: 수치 3개 (정확도 / 자동화율 / 사용자 체감) ---
    check("성과 수치 정확도", "28/28" in overview)
    check("성과 수치 자동화율", "53.3%" in overview)
    check("자동화율 분모 명시", "15 Case" in overview, "분모 없이 쓰면 전체 성능으로 읽힘")
    if "미측정" in overview:
        warn("사용자 체감 지표는 미측정", "측정 데이터가 없어 추정치도 쓰지 않음. 의도적 선택")

    # --- guide: 실제 기술명 사용 ---
    architecture = slides[2]
    check("실제 기술명 표기", "gpt-4.1-mini" in architecture and "SQLite" in architecture)
    check("LangGraph 미사용을 선택으로 명시", "LangGraph" in architecture)
    check("LangGraph 답변 준비", "랭그래프" in notes or "LangGraph" in notes)

    # --- guide: Workflow와 Agent 역할 구분 ---
    check("Workflow와 Agent 역할 구분", "실행 뼈대" in architecture)

    # --- guide: 고급 기법은 레퍼런스와 함께 ---
    hurdle = slides[3]
    check("기법 이름 명시", "Bounded Multi-Hypothesis Deliberation" in hurdle)
    check("레퍼런스 표기", "Yao et al." in hurdle and "2023" in hurdle)
    check("Self-Correction 명시", "Self-Correction" in everything or "Query Rewrite" in hurdle)

    # --- project rule: never claim to have implemented ToT ---
    overclaim = re.search(r"Tree of Thoughts[^.。]{0,20}(구현했|적용했)(?!.{0,10}아닙)", everything)
    check("Full ToT 구현 주장 없음", overclaim is None)
    check("Full ToT가 아님을 명시", "구현은 아닙니다" in hurdle or "구현이 아닙니다" in hurdle)

    # --- guide: 성장 가능성 = 실패 + 다음 단계 ---
    check("실패 경험 명시", "실패" in hurdle)
    check("다음 단계 명시", "Next Step" in hurdle)

    # --- guide: 평가 렌즈 문제 해결 전략 ---
    check("핵심 메시지 존재", "핵심 메시지" in overview)


def audit_video() -> None:
    qa_path = ROOT / "output/submission/09285_백준현_시연영상_검수.json"
    mp4 = ROOT / "output/submission/09285_백준현_시연영상.mp4"
    srt = ROOT / "output/submission/09285_백준현_시연영상.srt"
    if not check("영상 검수 JSON 존재", qa_path.exists()):
        return
    qa = json.loads(qa_path.read_text(encoding="utf-8"))
    video = qa["video"]

    # --- guide: 5분 이내, 500MB 이하, MP4 ---
    check("영상 5분 이내", video["duration_seconds"] <= 300, f"{video['duration_seconds']:.1f}s")
    check("영상 500MB 이하", video["bytes"] <= 500 * 1024 * 1024, f"{video['bytes']:,} bytes")
    check("파일명 규칙 [사번]_[성명]_시연영상.mp4", mp4.name == "09285_백준현_시연영상.mp4")
    check("H.264 코덱", "H.264" in video["video_codec"])
    check("전체 디코딩 오류 0", video["full_decode_error_lines"] == 0)

    # --- guide: 반드시 포함할 3구간 ---
    spans = qa["section_spans_seconds"]
    for key, label, floor in (
        ("scenario_intro", "시나리오 소개", 25.0),
        ("agent_reasoning_log_core", "Agent 추론 로그", 70.0),
        ("final_result_confirmation", "최종 결과 확인", 30.0),
    ):
        span = spans.get(key)
        if not check(f"영상 구간 {label} 존재", bool(span)):
            continue
        length = span[1] - span[0]
        check(f"영상 구간 {label} 길이", length >= floor, f"{length:.1f}s (>= {floor:.0f})")

    intro = spans["scenario_intro"]
    if intro[1] - intro[0] > 40:
        warn("시나리오 소개가 40초 초과", f"{intro[1]-intro[0]:.1f}s, 가이드 예시는 30초")

    console = qa["overlay_windows_seconds"]["processing_events_console"]
    check("읽히는 콘솔 구간 25초 이상", console[1] - console[0] >= 25,
          f"{console[1]-console[0]:.1f}s")

    # --- guide: ToT / Self-Correction 을 로그 중심으로 설명 ---
    if check("자막 파일 존재", srt.exists()):
        captions = srt.read_text(encoding="utf-8-sig")
        check("자막에 기법명", "Bounded Multi-Hypothesis Deliberation" in captions)
        check("자막에 Full ToT 아님", "Full ToT" in captions)
        check("자막에 Self-Correction", "Self-Correction" in captions)
        check("자막에 Workflow 역할", "실행 뼈대" in captions)

    # --- project rule: no raw chain of thought, no secrets ---
    check("원시 CoT 미노출 기록", qa.get("console_evidence", {}).get("raw_chain_of_thought_exposed") is False)
    check("Secret 미노출 기록", qa.get("console_evidence", {}).get("secrets_exposed") is False)


def audit_consistency(version: str) -> None:
    pptx = ROOT / "Docs/PRESENTATION/2. 최종" / f"09285_백준현_AI_Master_최종발표자료_{version}.pptx"
    srt = ROOT / "output/submission/09285_백준현_시연영상.srt"
    script = ROOT / "Docs/PRESENTATION/2. 최종/09285_백준현_최종시연_스크립트.md"

    counts: dict[str, set[str]] = {}
    if pptx.exists():
        counts["발표자료"] = set(re.findall(r"(\d{3}) passed", " ".join(slide_text(pptx))))
    if srt.exists():
        counts["자막"] = set(re.findall(r"(\d{3}) passed", srt.read_text(encoding="utf-8-sig")))
    if script.exists():
        counts["시연 스크립트"] = set(re.findall(r"(\d{3}) passed", script.read_text(encoding="utf-8")))

    actual = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--collect-only"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    collected = re.search(r"(\d+) tests? collected", actual.stdout or "")
    live = collected.group(1) if collected else None

    stated = {v for values in counts.values() for v in values}
    check("테스트 수치 아티팩트 간 일치", len(stated) <= 1, f"{counts}")
    if live and stated:
        check("표기 수치가 실제 테스트 수와 일치", live in stated, f"실제 {live} / 표기 {stated}")

    docs = list((ROOT / "Docs").rglob("*.md")) + [ROOT / "README.md"]
    audit_log = "10_최종감사_및_제출진행.md"
    # Every regression count the project has actually recorded, oldest first.
    # A document may cite any of these as history; anything else is a stale
    # claim about the current suite and fails the audit.
    RECORDED_BASELINES = {
        "122", "136", "149", "158", "168", "170", "171", "179", "214", "224",
    }

    def has_stale_count(text: str) -> bool:
        found = set(re.findall(r"(\d{3}) passed", text))
        return bool(found - stated - RECORDED_BASELINES)

    stale = [
        p.name for p in docs
        if p.name != audit_log and stated and has_stale_count(p.read_text(encoding="utf-8"))
    ]
    check("문서에 옛 테스트 수치 없음", not stale, ", ".join(stale[:4]))

    # --- documents must not point at a superseded deck or an old cut ---
    prose = [
        ROOT / "Docs/PRESENTATION/README.md",
        ROOT / "Docs/IMPLEMENTATION/10_최종감사_및_제출진행.md",
        ROOT / "Docs/IMPLEMENTATION/11_최종_제출가이드_충족점검.md",
        ROOT / "Docs/USER_GUIDE/09285_백준현_AI_Master_제출및면접_체크리스트.md",
        ROOT / "Docs/PRESENTATION/2. 최종/09285_백준현_최종시연_스크립트.md",
    ]
    older = [f"v{n}" for n in range(3, int(version.lstrip("v")))]
    wrong_version = []
    for path in prose:
        if not path.exists():
            continue
        body = path.read_text(encoding="utf-8")
        for tag in older:
            # "작업 이력" lines legitimately list superseded versions.
            for line in body.splitlines():
                if f"최종발표자료_{tag}" in line and "작업 이력" not in line:
                    wrong_version.append(f"{path.name}:{tag}")
                elif f"4장 {tag} " in line:
                    wrong_version.append(f"{path.name}:{tag}")
    check("문서가 최신 발표자료를 가리킴", not wrong_version, ", ".join(sorted(set(wrong_version))[:4]))

    qa_path = ROOT / "output/submission/09285_백준현_시연영상_검수.json"
    if qa_path.exists():
        qa = json.loads(qa_path.read_text(encoding="utf-8"))
        seconds = qa["video"]["duration_seconds"]
        current = f"{int(seconds // 60)}분 {seconds % 60:.1f}초"
        stale_len = []
        for path in prose:
            if not path.exists():
                continue
            body = path.read_text(encoding="utf-8")
            for match in re.finditer(r"(\d)분 (\d{1,2}\.\d)초", body):
                if match.group(0) != current:
                    stale_len.append(f"{path.name}:{match.group(0)}")
        check("문서의 영상 길이가 현재 영상과 일치", not stale_len,
              f"현재 {current} / 발견 {sorted(set(stale_len))[:3]}")

    # --- AI_MASTER heading order must match the official form ---
    form = ROOT / "Docs/AI_MASTER/기존 양식"
    if form.exists():
        def headings(path: Path) -> list[str]:
            return [l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.startswith("#")]
        mismatched = [
            ref.name for ref in sorted(form.glob("*.md"))
            if headings(ref) != headings(ROOT / "Docs/AI_MASTER" / ref.name)
        ]
        check("AI_MASTER Heading 순서 양식 일치", not mismatched, ", ".join(mismatched))


def audit_repo() -> None:
    tracked = subprocess.run(
        ["git", "-c", "core.quotepath=false", "ls-files"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
        check=True,
    ).stdout.splitlines()

    leaks = []
    for rel in tracked:
        path = ROOT / rel
        if not path.exists() or path.stat().st_size > 2_000_000:
            continue
        try:
            body = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if re.search(r"C:[\\/]Users[\\/]bback", body):
            leaks.append(rel)
    check("추적 파일에 기계 경로 없음", not leaks, ", ".join(leaks[:3]))

    secrets = [
        rel for rel in tracked
        if re.search(r"(^|/)\.secrets/|token\.json$|credentials\.json$", rel)
    ]
    check("Secret 파일 미추적", not secrets, ", ".join(secrets[:3]))

    junk = [rel for rel in tracked if "~$" in rel or rel.endswith((".mov", ".building.mp4"))]
    check("임시·참고 바이너리 미추적", not junk, ", ".join(junk[:3]))

    # --- guide: 파일명 규칙은 실제로 올리는 파일에 적용된다 ---
    submit_dir = ROOT / "output/01_제출"
    if submit_dir.exists():
        names = {path.name for path in submit_dir.iterdir() if path.is_file()}
        check(
            "제출 폴더 영상 파일명 [사번]_[성명]_시연영상.mp4",
            "09285_백준현_시연영상.mp4" in names,
            ", ".join(sorted(n for n in names if n.endswith(".mp4"))),
        )
        # OT p.7: 발표자료 PDF · 시연영상 · 소스코드(가능하신 분)
        check(
            "제출 폴더 발표자료가 PDF",
            "09285_백준현_최종발표자료.pdf" in names,
            ", ".join(sorted(n for n in names if n.endswith((".pdf", ".pptx")))),
        )
        present = ROOT / "output/02_발표_시연"
        check(
            "PPTX는 발표용으로 02_발표_시연에 보존",
            (present / "09285_백준현_최종발표자료.pptx").exists(),
        )
        check(
            "공식 템플릿판도 함께 보존",
            (present / "09285_백준현_최종발표자료_공식템플릿.pdf").exists(),
        )
        study = ROOT / "output/03_학습_면접"
        check(
            "학습자료 PDF 보존",
            (study / "09285_백준현_이해와시연가이드.pdf").exists(),
        )
        check(
            "제출 폴더에 군더더기 없음",
            len(names) == 3,
            ", ".join(sorted(names)),
        )
        check(
            "제출 폴더에 소스 ZIP 존재",
            any(n.endswith(".zip") for n in names),
            ", ".join(sorted(n for n in names if n.endswith(".zip"))),
        )

    # --- git이 바이너리를 텍스트로 오인하면 체크아웃마다 파일이 깨진다 ---
    eol = subprocess.run(
        ["git", "ls-files", "--eol"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
        check=True,
    ).stdout
    binary_suffixes = (
        ".pdf", ".pptx", ".potx", ".docx", ".dotx", ".xlsx", ".zip", ".mp4",
        ".mov", ".webm", ".mp3", ".wav", ".png", ".jpg", ".jpeg", ".gif",
        ".ico", ".ttf", ".otf", ".woff", ".woff2", ".db",
    )
    converted = []
    for row in eol.splitlines():
        parts = row.split("\t", 1)
        if len(parts) != 2:
            continue
        flags, name = parts
        if name.lower().rstrip('"').endswith(binary_suffixes) and not (
            "i/-text" in flags or "attr/-text" in flags
        ):
            converted.append(name)
    check(
        "바이너리 파일에 줄바꿈 변환 없음",
        not converted,
        ", ".join(converted[:3]),
    )

    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
        check=True,
    ).stdout.strip()
    check("추적 파일 변경 없음", not dirty, dirty.splitlines()[0] if dirty else "")


def main() -> int:
    _ensure_project_environment()
    _make_output_encodable()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deck-version", default="v12")
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args()

    audit_deck(args.deck_version)
    audit_video()
    audit_consistency(args.deck_version)
    audit_repo()

    if not args.skip_tests:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        tail = (result.stdout or "").strip().splitlines()
        check("pytest 전체 통과", result.returncode == 0, tail[-1] if tail else "")

    print(f"PASS {len(PASSES)}")
    for item in FAILURES:
        print(f"  FAIL  {item}")
    for item in WARNINGS:
        print(f"  WARN  {item}")
    print("\nRESULT:", "CLEAN" if not FAILURES else f"{len(FAILURES)} FAILURE(S)")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
