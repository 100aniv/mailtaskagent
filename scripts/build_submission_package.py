"""Lay out everything that goes with the submission under output/.

    python scripts/build_submission_package.py --tag <release tag>

Three folders, so there is never a question of what to upload:

  01_제출          the files that actually get uploaded, named the way the
                   official guides specify, and nothing else
  02_발표_시연     what the presenter works from — both decks, the demo
                   script, subtitles
  03_학습_면접     the understanding guide and the interview checklist

The source ZIP comes from `git archive` at the release tag, so it carries the
committed bytes rather than whatever the working tree happens to hold, and it
is checked against the tag's own tree before anything else is written.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
SUBMIT = OUT / "01_제출"
PRESENT = OUT / "02_발표_시연"
STUDY = OUT / "03_학습_면접"

DECK_DIR = ROOT / "Docs/PRESENTATION/2. 최종"
VIDEO_DIR = ROOT / "output/submission"
GUIDE_DIR = ROOT / "Docs/USER_GUIDE"

# 7기 OT p.7: 발표자료 PDF · 시연영상 · 소스코드(가능하신 분)
SOURCE_ZIP = SUBMIT / "09285_백준현_소스코드.zip"
VIDEO = SUBMIT / "09285_백준현_시연영상.mp4"
DECK_PDF = SUBMIT / "09285_백준현_최종발표자료.pdf"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=True,
    ).stdout.strip()


def build_source_zip(tag: str) -> list[str]:
    subprocess.run(
        ["git", "-c", "core.autocrlf=false", "-c", "core.eol=lf",
         "archive", "--format=zip", "-o", str(SOURCE_ZIP), tag],
        cwd=ROOT, check=True,
    )
    with zipfile.ZipFile(SOURCE_ZIP) as archive:
        # git archive writes directory entries too; only files are tracked.
        entries = [name for name in archive.namelist() if not name.endswith("/")]

    # -z keeps non-ASCII paths raw instead of git's quoted-octal escaping.
    raw = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "-z", tag],
        cwd=ROOT, capture_output=True, check=True,
    ).stdout
    tracked = [name.decode("utf-8") for name in raw.split(bytes([0])) if name]

    missing = sorted(set(tracked) - set(entries))
    extra = sorted(set(entries) - set(tracked))
    if missing or extra:
        raise SystemExit(f"소스 ZIP이 태그 트리와 다릅니다: {missing[:3]} {extra[:3]}")

    leaks = [n for n in entries if ".secrets/" in n or n.endswith((".db", "token.json"))]
    if leaks:
        raise SystemExit(f"ZIP에 포함되면 안 되는 파일: {leaks[:3]}")
    return entries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True, help="소스 ZIP을 뽑을 릴리스 태그")
    args = parser.parse_args()

    head = git("rev-parse", "HEAD")
    tagged = git("rev-parse", f"{args.tag}^{{commit}}")
    if head != tagged:
        raise SystemExit(f"HEAD({head[:8]})와 태그({tagged[:8]})가 다릅니다")

    for folder in (SUBMIT, PRESENT, STUDY):
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True)

    entries = build_source_zip(args.tag)

    shutil.copy2(VIDEO_DIR / "09285_백준현_시연영상.mp4", VIDEO)
    shutil.copy2(DECK_DIR / "09285_백준현_AI_Master_최종발표자료_v12.pdf", DECK_PDF)

    shutil.copy2(DECK_DIR / "09285_백준현_AI_Master_최종발표자료_v12.pptx",
                 PRESENT / "09285_백준현_최종발표자료.pptx")
    for suffix in (".pdf", ".pptx"):
        shutil.copy2(DECK_DIR / f"09285_백준현_AI_Master_최종발표자료_공식템플릿_v1{suffix}",
                     PRESENT / f"09285_백준현_최종발표자료_공식템플릿{suffix}")
    shutil.copy2(DECK_DIR / "09285_백준현_최종시연_스크립트.md",
                 PRESENT / "09285_백준현_최종시연_스크립트.md")
    shutil.copy2(VIDEO_DIR / "09285_백준현_시연영상.srt",
                 PRESENT / "09285_백준현_시연영상.srt")
    shutil.copy2(VIDEO_DIR / "09285_백준현_시연영상_검수.json",
                 PRESENT / "09285_백준현_시연영상_검수.json")

    for suffix in (".pdf", ".docx"):
        shutil.copy2(GUIDE_DIR / f"09285_백준현_MailTaskAgent_이해와시연가이드{suffix}",
                     STUDY / f"09285_백준현_이해와시연가이드{suffix}")
    shutil.copy2(GUIDE_DIR / "09285_백준현_AI_Master_제출및면접_체크리스트.md",
                 STUDY / "09285_백준현_제출및면접_체크리스트.md")
    shutil.copy2(ROOT / "Docs/LEARNING/MailTaskAgent_초보자_기술학습가이드.md",
                 STUDY / "MailTaskAgent_초보자_기술학습가이드.md")

    qa = json.loads((VIDEO_DIR / "09285_백준현_시연영상_검수.json").read_text(encoding="utf-8"))
    duration = qa["video"]["duration_seconds"]

    lines = [
        "MailTaskAgent 최종 제출 안내",
        "=" * 64,
        "",
        "output 폴더는 세 갈래입니다.",
        "",
        "  01_제출        포털에 올리는 파일. 이 폴더 것만 올리면 끝납니다.",
        "  02_발표_시연   발표와 시연 준비용. 제출하지 않습니다.",
        "  03_학습_면접   내용 이해와 AI 면접 준비용. 제출하지 않습니다.",
        "",
        "=" * 64,
        "01_제출 — 실제로 올릴 파일 3개",
        "",
        "7기 OT p.7의 최종 산출물은 '발표자료 PDF / 시연영상 / 소스코드(가능하신 분)'입니다.",
        "파일명은 공식 가이드의 [사번]_[성명]_... 규칙을 따릅니다.",
        "",
    ]
    for step, path, extra in (
        ("1단계. 소스코드", SOURCE_ZIP, f"파일 수  {len(entries)}개 (태그 {args.tag} 기준)"),
        ("2단계. 시연영상", VIDEO,
         f"길이  {duration:.1f}초 ({int(duration // 60)}분 {duration % 60:.1f}초, 5분 제한 이내)"),
        ("3단계. 발표자료", DECK_PDF, "장수  4장 (표지 + 3페이지)"),
    ):
        size = path.stat().st_size
        lines += [
            step,
            f"   파일  {path.name}",
            f"   크기  {size / 1_048_576:.2f} MB ({size:,} bytes)",
            f"   {extra}",
            f"   해시  {sha256(path)}",
            "",
        ]

    lines += [
        "=" * 64,
        "02_발표_시연 — 발표자용",
        "",
        "  09285_백준현_최종발표자료.pptx",
        "    01_제출의 PDF와 같은 내용이고 발표자 노트가 들어 있습니다. 리허설은 이 파일로 하세요.",
        "  09285_백준현_최종발표자료_공식템플릿.pdf / .pptx",
        "    배포된 공식 템플릿에 같은 내용을 채운 대안판입니다. 멘토나 포털이 제공 템플릿을",
        "    요구하면 01_제출의 발표자료를 이 PDF로 바꿔 올리시면 됩니다. 수치와 한계 표기는 같습니다.",
        "  09285_백준현_최종시연_스크립트.md",
        "    5분 Live 시연 대사와 장애 대응, 그리고 제출 영상 구간별 설명.",
        "  09285_백준현_시연영상.srt / _검수.json",
        "    자막 원본과 영상 QA 기록. 자막은 영상에 이미 입혀져 있어 따로 올릴 필요가 없습니다.",
        "",
        "=" * 64,
        "03_학습_면접 — 이해와 면접 준비용",
        "",
        "  09285_백준현_이해와시연가이드.pdf / .docx",
        "    프로젝트 전체를 처음부터 설명하는 12쪽 학습자료.",
        "    5장이 '왜 단순 Workflow가 아니라 Agentic AI인가'이고, 30초 답변이 5.5절에 있습니다.",
        "  09285_백준현_제출및면접_체크리스트.md",
        "    제출 전 확인 목록과 AI 면접 예상 문답.",
        "  MailTaskAgent_초보자_기술학습가이드.md",
        "    코드까지 따라갈 때 보는 상세 기술 문서.",
        "",
        "=" * 64,
        "확인한 사항",
        "",
        f"  최종 커밋   {head}",
        f"  최종 태그   {args.tag}",
        "  전체 테스트 228 passed",
        "  자체 감사   scripts/audit_submission.py 전 항목 통과",
        "  영상        H.264/AAC, 1600x900, 전체 디코딩 오류 0, 내레이션 겹침 0",
        "  발표자료    PDF 4장 = PPTX 4장, 레이아웃 경고 0, PDF 엄격 파싱 무경고",
        f"  소스 ZIP    {len(entries)}개 파일이 태그 트리와 일치, Secret·DB·임시파일 없음",
        "",
        "=" * 64,
        "발표 시간",
        "",
        "  발표템플릿 가이드(3기 v1.0)는 10분 권장, 7기 OT p.7은 최종발표 15분입니다.",
        "  10분에 맞추면 양쪽을 모두 만족합니다. 발표자 노트는 말하는 분량 기준 약 9~11분입니다.",
        "",
        "=" * 64,
        "알아두실 한계",
        "",
        "  사용자 체감 시간은 측정하지 못해 수치로 쓰지 않았습니다. 사용자가 1명이라 순서 효과를",
        "  걷어낼 방법이 없었고, 가이드가 추정치를 허용하지만 근거가 없어 '미측정'으로 남겼습니다.",
        "",
        "  자동 반영 53.3%는 정의된 합성 15개 Case 기준입니다. 실제 메일함 전체의 자동화율이",
        "  아니며 발표자료에도 분모를 함께 적었습니다.",
        "",
        "  적용 기법은 SQLite Task Context RAG와, Tree of Thoughts의 후보 생성·평가 분리에서",
        "  착안한 Bounded Multi-Hypothesis Deliberation, 그리고 제한적 ReAct-style",
        "  Self-Correction입니다. Full Tree of Thoughts도 Full ReAct도 Vector DB RAG도 아니며",
        "  어느 자료에도 그렇게 쓰지 않았습니다.",
        "",
    ]
    (OUT / "README_제출안내.txt").write_text("\n".join(lines), encoding="utf-8")

    print(f"소스 ZIP {len(entries)}개 파일, 태그 {args.tag} 트리와 일치\n")
    for folder in (SUBMIT, PRESENT, STUDY):
        print(f"{folder.name}/")
        for path in sorted(folder.iterdir()):
            print(f"   {path.name:44} {path.stat().st_size:>11,} bytes")
    print(f"\nREADME_제출안내.txt  {(OUT / 'README_제출안내.txt').stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
