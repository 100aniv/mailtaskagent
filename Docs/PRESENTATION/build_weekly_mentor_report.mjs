// Builds the 2026-08-27 weekly mentor progress report deck.
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

const artifactSpecifier = process.env.RUNTIME_NODE_MODULES
  ? pathToFileURL(path.join(process.env.RUNTIME_NODE_MODULES, "@oai", "artifact-tool", "dist", "artifact_tool.mjs")).href
  : "@oai/artifact-tool";
const { Presentation, PresentationFile } = await import(artifactSpecifier);

const ROOT = "C:/Users/bback/Desktop/AI Master/MailTaskAgent";
const OUT = path.join(ROOT, "Docs/PRESENTATION/MailTaskAgent_주간멘토보고_2026-08-27.pptx");
const RENDER = path.join(ROOT, "tmp/weekly_mentor_report/rendered");
const W = 1280;
const H = 720;
const FONT = "Malgun Gothic";
const C = {
  ink: "#12213D",
  navy: "#13264A",
  blue: "#4169E1",
  cyan: "#6DCBF4",
  green: "#1E8A67",
  amber: "#D28B26",
  coral: "#DB5D68",
  sub: "#66738A",
  line: "#D9DFEA",
  soft: "#F4F6FA",
  pale: "#EAF0FF",
  white: "#FFFFFF",
};

function text(slide, value, x, y, w, h, size = 20, options = {}) {
  const shape = slide.shapes.add({
    geometry: "textbox",
    name: options.name,
    position: { left: x, top: y, width: w, height: h },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  shape.text = value;
  shape.text.style = {
    fontSize: size,
    typeface: FONT,
    color: options.color ?? C.ink,
    bold: Boolean(options.bold),
    alignment: options.align ?? "left",
    verticalAlignment: options.valign ?? "top",
    autoFit: options.autoFit ?? "shrinkText",
  };
  return shape;
}

function box(slide, x, y, w, h, fill = C.soft, stroke = C.line, radius = "rounded-xl") {
  return slide.shapes.add({
    geometry: "roundRect",
    position: { left: x, top: y, width: w, height: h },
    fill,
    line: { style: "solid", fill: stroke, width: 1 },
    borderRadius: radius,
  });
}

function rule(slide, x, y, w, color = C.line, width = 1) {
  return slide.shapes.add({
    geometry: "straightConnector1",
    position: { left: x, top: y, width: w, height: 0 },
    fill: "none",
    line: { style: "solid", fill: color, width },
  });
}

function arrow(slide, x, y, w, color = C.blue, width = 2) {
  return slide.shapes.add({
    geometry: "straightConnector1",
    position: { left: x, top: y, width: w, height: 0 },
    fill: "none",
    line: { style: "solid", fill: color, width },
    head: { type: "arrow", width: "sm", length: "sm" },
  });
}

function dot(slide, x, y, d, fill = C.blue, stroke = C.white) {
  return slide.shapes.add({
    geometry: "ellipse",
    position: { left: x, top: y, width: d, height: d },
    fill,
    line: { style: "solid", fill: stroke, width: 2 },
  });
}

function header(presentation, title, number, kicker = "WEEKLY MENTOR REPORT") {
  const slide = presentation.slides.add();
  slide.background.fill = C.white;
  text(slide, kicker, 48, 28, 430, 22, 13, { bold: true, color: C.blue });
  text(slide, title, 48, 66, 1160, 58, 38, { bold: true });
  rule(slide, 48, 132, 1160, C.line, 1);
  text(slide, String(number).padStart(2, "0"), 1176, 672, 44, 18, 12, { color: C.sub, align: "right" });
  return slide;
}

function notes(slide, body, sources) {
  slide.speakerNotes.textFrame.setText(`${body}\n\n[Sources]\n${sources.map((source) => `- ${source}`).join("\n")}`);
}

async function imageBytes(filePath) {
  const bytes = await fs.readFile(filePath);
  return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
}

function sectionTag(slide, value, x, y, w, color = C.blue) {
  box(slide, x, y, w, 30, color, color, "rounded-lg");
  text(slide, value, x + 10, y + 6, w - 20, 18, 13, { bold: true, color: C.white, align: "center" });
}

const p = Presentation.create({ slideSize: { width: W, height: H } });

// 1 — Cover, based on Codex Grid cover-image-field silhouette.
{
  const slide = p.slides.add();
  slide.background.fill = C.white;
  text(slide, "AI MASTER · WEEKLY MENTOR REPORT", 48, 42, 500, 24, 14, { bold: true, color: C.blue });
  text(slide, "MailTaskAgent", 48, 126, 548, 76, 58, { bold: true });
  text(slide, "메일을 Task Lifecycle로 전환하는\nAgentic AI Core 진행 보고", 48, 224, 548, 100, 32, { bold: true });
  rule(slide, 48, 360, 116, C.blue, 5);
  text(slide, "Node · Action · Human-in-the-loop · Audit", 48, 390, 540, 38, 20, { color: C.sub });
  text(slide, "2026.08.27", 48, 648, 200, 24, 15, { color: C.sub });

  box(slide, 640, 42, 592, 586, C.pale, "#D7E0FA", "rounded-2xl");
  const mockup = await imageBytes(path.join(ROOT, "prototype/final_ui_mockup.png"));
  slide.images.add({
    blob: mockup,
    contentType: "image/png",
    alt: "MailTaskAgent 운영 UI 콘셉트",
    fit: "contain",
    geometry: "roundRect",
    borderRadius: "rounded-xl",
    position: { left: 666, top: 70, width: 540, height: 522 },
  });
  notes(slide, "최종 발표 자료가 아니라 이번 주 기술 진행과 멘토 피드백을 받기 위한 보고 자료다. 우측 화면은 구현 완료 화면이 아니라 운영 UI TO-BE 콘셉트다.", [
    "Docs/AI_MASTER/01_역량및기술스택.md",
    "Docs/AI_MASTER/07_E2E서비스개발.md",
    "prototype/final_ui_mockup.png",
  ]);
}

// 2 — Outcome snapshot.
{
  const slide = header(p, "이번 주에는 Core E2E의 ‘판단–실행–추적’ 고리가 연결됐습니다", 2);
  text(slide, "메일 분석 결과가 화면에 보이는 데서 끝나지 않고, 기존 Task와 상태를 조회해 Action을 결정하고 안전하게 반영합니다.", 48, 158, 1110, 52, 22, { color: C.sub });
  text(slide, "Mail", 58, 262, 126, 42, 29, { bold: true });
  arrow(slide, 182, 286, 104, C.blue, 3);
  text(slide, "Context", 310, 262, 150, 42, 29, { bold: true });
  arrow(slide, 458, 286, 104, C.blue, 3);
  text(slide, "Action", 586, 262, 140, 42, 29, { bold: true });
  arrow(slide, 722, 286, 104, C.blue, 3);
  text(slide, "Validation", 850, 262, 178, 42, 29, { bold: true });
  arrow(slide, 1024, 286, 88, C.blue, 3);
  text(slide, "History", 1120, 262, 120, 42, 27, { bold: true, align: "right" });

  rule(slide, 48, 388, 1160, C.line, 1);
  const stats = [
    ["M-01~M-05", "공통 Node 연결"],
    ["7 Actions", "실행 경로 구현"],
    ["15 / 15", "회사 LLM Live Case"],
    ["42 passed", "자동 회귀 테스트"],
  ];
  stats.forEach((item, index) => {
    const x = 48 + index * 290;
    if (index > 0) rule(slide, x - 24, 444, 0, C.line, 1);
    text(slide, item[0], x, 438, 250, 54, 34, { bold: true, color: index === 2 ? C.green : C.blue });
    text(slide, item[1], x, 500, 250, 30, 17, { color: C.sub });
  });
  box(slide, 48, 576, 1160, 62, C.navy, C.navy, "rounded-xl");
  text(slide, "핵심 변화: LLM이 직접 DB를 수정하지 않고, Python 검증과 사용자 확인을 통과한 결과만 저장합니다.", 74, 594, 1110, 26, 20, { bold: true, color: C.white, align: "center" });
  notes(slide, "현재까지의 핵심 진척을 한 장으로 설명한다. Vertical Slice의 CREATE/UPDATE를 유지하면서 7 Action, 사용자 확인, 로그, 품질 검증까지 확장했다.", [
    "README.md",
    "Docs/AI_MASTER/05_POC모듈구현.md",
    "Docs/IMPLEMENTATION/08_멘토_시연_브리핑.md",
  ]);
}

// 3 — Agentic loop and nodes.
{
  const slide = header(p, "Agentic AI는 상태를 보고 다음 Action을 결정합니다", 3);
  const xs = [48, 278, 508, 738, 968];
  const names = ["M-01", "M-02", "M-03", "M-04", "M-05"];
  const heads = ["Mail Analyzer", "Task Matcher", "Action Decision", "State & History", "Review & UI"];
  const bodies = [
    "업무 여부·Intent\n요청·기한·근거",
    "conversation_id 우선\n후보·점수·근거",
    "현재 Task 상태를 보고\n7 Action 중 선택",
    "Validation 이후\nTransaction으로 저장",
    "ASK_USER 확정\nDashboard·로그",
  ];
  for (let i = 0; i < xs.length - 1; i += 1) arrow(slide, xs[i] + 190, 328, 40, C.blue, 2);
  xs.forEach((x, index) => {
    box(slide, x, 226, 190, 208, index === 2 ? C.navy : C.soft, index === 2 ? C.navy : C.line, "rounded-xl");
    text(slide, names[index], x + 18, 246, 74, 24, 14, { bold: true, color: index === 2 ? C.cyan : C.blue });
    text(slide, heads[index], x + 18, 286, 154, 48, 21, { bold: true, color: index === 2 ? C.white : C.ink });
    text(slide, bodies[index], x + 18, 348, 154, 62, 17, { color: index === 2 ? "#DCE6FA" : C.sub });
  });
  rule(slide, 140, 504, 920, C.line, 2);
  dot(slide, 134, 497, 15, C.blue);
  dot(slide, 1056, 497, 15, C.blue);
  text(slide, "새 후속 Mail이 들어오면 저장된 Task 상태와 History가 다시 Context가 됩니다.", 198, 530, 840, 36, 21, { bold: true, align: "center" });
  text(slide, "Observe", 48, 600, 170, 26, 16, { bold: true, color: C.blue });
  text(slide, "→ Reason → Decide → Act → Verify → Memory", 142, 600, 900, 26, 16, { bold: true, color: C.sub });
  notes(slide, "Node는 별도 서버가 아니라 한 건의 Mail이 통과하는 논리 책임 단위다. Task 상태와 History가 다음 Mail 판단의 Context가 되므로 단순 분류보다 Agentic한 폐루프를 가진다.", [
    "Docs/AI_MASTER/04_상세설계및개발환경.md",
    "src/mailtaskagent/workflow.py",
    "src/mailtaskagent/decision.py",
  ]);
}

// 4 — Role boundaries.
{
  const slide = header(p, "정확성과 안전성은 LLM·Python·사용자 역할 분리에서 나옵니다", 4);
  const lanes = [
    { y: 176, h: 118, fill: C.pale, color: C.blue, role: "LLM · M-01", detail: "메일 의미와 Intent를 구조화", flow: "요청 · 기한 · 완료/취소 표현 · 회신 필요 · 판단 근거" },
    { y: 318, h: 150, fill: "#ECF7F3", color: C.green, role: "PYTHON · M-02/M-03 + APPLICATION", detail: "후보 검색 → 최종 Action → Validation → DB 반영", flow: "Metadata/Token Matching · 7 Action · 5 Status · Transaction Rollback" },
    { y: 492, h: 118, fill: "#FFF1F3", color: C.coral, role: "USER · M-05", detail: "중요하거나 애매한 제안을 확정", flow: "기존 Task 연결 · 신규 Task · 무시 · 완료/취소/기한 단축 승인" },
  ];
  lanes.forEach((lane) => {
    box(slide, 48, lane.y, 1160, lane.h, lane.fill, lane.fill, "rounded-xl");
    text(slide, lane.role, 74, lane.y + 20, 330, 28, 18, { bold: true, color: lane.color });
    text(slide, lane.detail, 410, lane.y + 18, lane.y === 318 ? 510 : 740, 34, 23, { bold: true });
    text(slide, lane.flow, 410, lane.y + 62, lane.y === 318 ? 510 : 740, 34, 17, { color: C.sub });
  });
  box(slide, 946, 336, 218, 110, C.navy, C.navy, "rounded-xl");
  text(slide, "DB 변경 권한", 964, 354, 180, 24, 15, { bold: true, color: C.cyan, align: "center" });
  text(slide, "검증된 Python\nLogic에만 부여", 964, 386, 180, 46, 20, { bold: true, color: C.white, align: "center" });
  notes(slide, "LLM 출력은 제안이자 구조화 정보다. 최종 Action과 DB 변경은 Python이 결정하며, 중요한 상태 변경은 사용자가 확정한다.", [
    "Docs/AI_MASTER/04_상세설계및개발환경.md",
    "Docs/AI_MASTER/05_POC모듈구현.md",
    "src/mailtaskagent/llm_client.py",
    "src/mailtaskagent/storage.py",
  ]);
}

// 5 — Action and state model.
{
  const slide = header(p, "7개 Action과 5개 Status로 Task Lifecycle을 제어합니다", 5);
  const actionGroups = [
    { x: 48, w: 242, title: "새 업무", items: "CREATE_TASK", color: C.blue },
    { x: 308, w: 366, title: "진행·연결·대기", items: "UPDATE_TASK\nLINK_TO_TASK\nSET_WAITING", color: C.green },
    { x: 692, w: 242, title: "종료 제안", items: "MARK_COMPLETED", color: C.amber },
    { x: 952, w: 256, title: "안전 Gate", items: "ASK_USER\nIGNORE", color: C.coral },
  ];
  actionGroups.forEach((group) => {
    text(slide, group.title, group.x, 166, group.w, 28, 16, { bold: true, color: group.color });
    box(slide, group.x, 204, group.w, 150, C.soft, C.line, "rounded-xl");
    text(slide, group.items, group.x + 16, 230, group.w - 32, 98, group.title === "종료 제안" ? 18 : 21, { bold: true });
  });
  text(slide, "STATUS FLOW", 48, 410, 180, 24, 14, { bold: true, color: C.blue });
  const statuses = ["TODO", "IN_PROGRESS", "WAITING_REPLY", "COMPLETED"];
  const sx = [48, 332, 616, 958];
  statuses.forEach((status, index) => {
    box(slide, sx[index], 460, index === 3 ? 250 : 226, 72, index === 3 ? C.navy : C.pale, index === 3 ? C.navy : "#D7E0FA", "rounded-xl");
    text(slide, status, sx[index] + 14, 483, (index === 3 ? 222 : 198), 26, 18, { bold: true, color: index === 3 ? C.white : C.blue, align: "center" });
    if (index < statuses.length - 1) arrow(slide, sx[index] + (index === 2 ? 226 : 226), 496, sx[index + 1] - sx[index] - 226, C.blue, 2);
  });
  box(slide, 616, 566, 250, 54, "#FFF1F3", "#F2CBD0", "rounded-xl");
  text(slide, "CANCELLED · 사용자 승인", 630, 582, 222, 22, 16, { bold: true, color: C.coral, align: "center" });
  text(slide, "↳", 566, 565, 42, 32, 26, { bold: true, color: C.coral, align: "center" });
  notes(slide, "Action과 Status를 구분한다. Action은 이번 Mail에 대한 결정이고 Status는 Task의 현재 상태다. 완료·취소·기한 단축 같은 중요 변경은 사용자 확인을 통과한다.", [
    "AGENTS.md",
    "Docs/AI_MASTER/04_상세설계및개발환경.md",
    "src/mailtaskagent/models.py",
  ]);
}

// 6 — Scenarios and validation cases.
{
  const slide = header(p, "3개 사용자 시나리오를 15개 경계 Case로 검증합니다", 6);
  const rows = [
    { y: 170, id: "SC-001", title: "신규 업무 요청", value: "Mail → CREATE_TASK → TODO", cases: "명확한 기한 · 기한 없음 · 조치 불필요 공지 · 중복 방지", color: C.blue },
    { y: 316, id: "SC-002", title: "후속 Mail 연결·변경", value: "기존 Task → UPDATE / LINK / WAITING", cases: "기한 연장·단축 · 정보 연결 · 회신 대기·재개 · 완료·취소", color: C.green },
    { y: 462, id: "SC-003", title: "불확실한 Mail 확인", value: "ASK_USER → 사용자가 최종 결정", cases: "후보 복수 · 다른 Thread · 모호한 기한 · 불명확 완료 · Prompt Injection", color: C.coral },
  ];
  rows.forEach((row) => {
    sectionTag(slide, row.id, 48, row.y, 104, row.color);
    text(slide, row.title, 174, row.y - 2, 280, 32, 22, { bold: true });
    text(slide, row.value, 174, row.y + 42, 410, 32, 17, { bold: true, color: row.color });
    rule(slide, 606, row.y - 8, 0, C.line, 1);
    text(slide, row.cases, 642, row.y + 2, 530, 66, 18, { color: C.sub });
    if (row.y < 462) rule(slide, 48, row.y + 112, 1160, C.line, 1);
  });
  box(slide, 48, 606, 1160, 48, C.navy, C.navy, "rounded-xl");
  text(slide, "15개는 기능 15개가 아니라, 정상·예외·보안 조건을 재현하는 합성·비식별 평가 Dataset입니다.", 70, 619, 1116, 22, 17, { bold: true, color: C.white, align: "center" });
  notes(slide, "사용자 시나리오와 검증 Case를 구분한다. SC-001~003은 사용자 여정이고, 15개 Business/Security Case는 각 여정의 경계 조건이다.", [
    "Docs/AI_MASTER/03_시나리오수립.md",
    "data/scenario_expectations.json",
    "data/dummy_mails.json",
  ]);
}

// 7 — Current UI and automatic ingestion explanation.
{
  const slide = header(p, "현재 UI는 Mail·Task·Review·Log·품질 검증을 연결합니다", 7);
  const current = await imageBytes(path.join(ROOT, "prototype/current_streamlit_ui.png"));
  slide.images.add({
    blob: current,
    contentType: "image/png",
    alt: "현재 Streamlit MailTaskAgent 업무 대시보드",
    fit: "contain",
    geometry: "roundRect",
    borderRadius: "rounded-xl",
    position: { left: 48, top: 162, width: 742, height: 464 },
  });
  text(slide, "현재 구현", 834, 166, 160, 26, 16, { bold: true, color: C.green });
  const bullets = [
    "업무 현황 · Task History",
    "메일 처리함 · 15건 Batch 재현",
    "확인 필요 · ASK_USER",
    "운영 로그 · M-01~M-05",
    "품질 검증 · Mock / Live 분리",
  ];
  bullets.forEach((item, index) => {
    dot(slide, 838, 222 + index * 58, 12, index === 2 ? C.coral : C.blue);
    text(slide, item, 864, 214 + index * 58, 330, 32, 18, { bold: index === 2 });
  });
  box(slide, 824, 532, 384, 94, C.pale, "#D7E0FA", "rounded-xl");
  text(slide, "운영 시에는 Mail Adapter가 자동 호출", 846, 550, 340, 26, 18, { bold: true, color: C.blue });
  text(slide, "현재 버튼은 합성 Mail 유입을 재현하는 데모 Trigger", 846, 584, 340, 26, 16, { color: C.sub });
  notes(slide, "사용자가 매 Mail마다 분석 버튼을 누르는 제품 설계가 아니다. 현재 Batch 버튼은 합성 Mail Source에서 신규 메일 15건이 들어오는 상황을 재현한다. 실제 Mail Adapter는 Core 안정화 이후 입력 경계에 연결한다.", [
    "src/mailtaskagent/ui.py",
    "Docs/IMPLEMENTATION/08_멘토_시연_브리핑.md",
    "prototype/current_streamlit_ui.png",
  ]);
}

// 8 — Observability and audit.
{
  const slide = header(p, "멘토 피드백을 반영해 Agent 판단 근거와 처리 단계를 추적합니다", 8);
  text(slide, "PROCESSING EVENT", 48, 164, 240, 24, 14, { bold: true, color: C.blue });
  const stages = ["MAIL_INPUT", "SCHEMA_VALIDATION", "M-01 LLM_ANALYSIS", "M-02 TASK_MATCHING", "M-03 ACTION_DECISION", "ACTION_VALIDATION", "M-04 DB_TRANSACTION", "PROCESS_COMPLETED"];
  stages.forEach((stage, index) => {
    const y = 204 + index * 48;
    dot(slide, 54, y + 6, 12, index === 4 ? C.coral : C.blue);
    if (index < stages.length - 1) rule(slide, 59, y + 18, 0, C.line, 2);
    text(slide, stage, 82, y, 350, 26, 17, { bold: index === 4, color: index === 4 ? C.coral : C.ink });
    text(slide, "시각 · 성공/실패 · 소요 시간", 440, y, 250, 26, 15, { color: C.sub });
  });
  rule(slide, 722, 178, 0, C.line, 1);
  text(slide, "AUDIT HISTORY", 760, 164, 240, 24, 14, { bold: true, color: C.green });
  const audit = ["Source Mail ID", "선택된 Agent Action", "변경 전 값 → 변경 후 값", "Agent 판단 근거", "사용자 최종 결정", "처리 시각 · 오류/중단 여부"];
  audit.forEach((item, index) => {
    box(slide, 760, 208 + index * 62, 418, 44, index === 4 ? "#FFF1F3" : C.soft, index === 4 ? "#F2CBD0" : C.line, "rounded-lg");
    text(slide, item, 780, 219 + index * 62, 378, 22, 17, { bold: index === 4, color: index === 4 ? C.coral : C.ink });
  });
  text(slide, "Secret Redaction", 760, 594, 160, 24, 15, { bold: true, color: C.coral });
  text(slide, "API Key · Authorization Header · Token은 UI·로그·DB에 저장하지 않음", 922, 590, 276, 40, 15, { color: C.sub });
  notes(slide, "운영 로그에는 Mail 입력부터 완료까지 단계별 Processing Event를 표시한다. Audit History에는 실제 Task 변경 전후와 판단 근거, 사용자 결정을 남긴다. Secret은 저장 전에 제거한다.", [
    "src/mailtaskagent/ui.py",
    "src/mailtaskagent/storage.py",
    "Docs/AI_MASTER/06_테스트및고도화.md",
  ]);
}

// 9 — Evidence and caveats, Codex Grid metric-led silhouette.
{
  const slide = header(p, "현재 증적은 Core Workflow의 일관된 동작을 보여줍니다", 9);
  text(slide, "회사 LLM Live 평가와 Mock 회귀를 분리해 동일한 기대 Action으로 비교했습니다.", 48, 154, 1060, 34, 20, { color: C.sub });
  const metrics = [
    { x: 48, stat: "15 / 15", label: "회사 LLM Live Case", detail: "실행 오류 0건", color: C.green },
    { x: 432, stat: "28 / 28", label: "Action 단계 일치", detail: "현재 Dataset 기준 100%", color: C.blue },
    { x: 816, stat: "42", label: "pytest passed", detail: "회귀·안전·Review 포함", color: C.blue },
  ];
  metrics.forEach((metric) => {
    box(slide, metric.x, 236, 344, 236, C.soft, C.soft, "rounded-xl");
    text(slide, metric.stat, metric.x + 24, 278, 296, 76, 46, { bold: true, color: metric.color });
    text(slide, metric.label, metric.x + 24, 378, 296, 30, 19, { bold: true });
    text(slide, metric.detail, metric.x + 24, 422, 296, 24, 16, { color: C.sub });
  });
  text(slide, "53.955초", 48, 524, 220, 36, 27, { bold: true, color: C.amber });
  text(slide, "Live 15개 평가 총 처리시간", 250, 528, 310, 28, 17, { color: C.sub });
  rule(slide, 48, 578, 1160, C.line, 1);
  text(slide, "측정 전", 48, 604, 104, 24, 14, { bold: true, color: C.coral });
  text(slide, "업무 분류·핵심 필드·Task ID 정확도, 사람 수동 Baseline, 비용 KPI는 완료 수치로 작성하지 않았습니다.", 164, 598, 1038, 34, 17, { color: C.sub });
  notes(slide, "15/15와 28/28은 현재 정의한 합성 Dataset의 E2E 결과다. 사용자 확인율 46.7%는 위험 경계 Case를 의도적으로 많이 넣은 평가 구성의 결과이며 실제 운영 메일 비율 예측이 아니다.", [
    "evidence/live_evaluation_2026-08-26.json",
    "Docs/AI_MASTER/06_테스트및고도화.md",
    "Docs/IMPLEMENTATION/06_테스트_전략_및_케이스.md",
  ]);
}

// 10 — TO-BE product UI.
{
  const slide = header(p, "TO-BE는 ‘오늘의 업무’를 바로 관리하는 운영 UI입니다", 10);
  const mockup = await imageBytes(path.join(ROOT, "prototype/final_ui_mockup.png"));
  slide.images.add({
    blob: mockup,
    contentType: "image/png",
    alt: "MailTaskAgent 최종 운영 UI 콘셉트",
    fit: "contain",
    geometry: "roundRect",
    borderRadius: "rounded-xl",
    position: { left: 48, top: 158, width: 852, height: 488 },
  });
  const callouts = [
    ["01", "자동 Mail 동기화", "새 Mail은 별도 분석 클릭 없이 처리"],
    ["02", "오늘의 우선 업무", "기한·회신 대기·진행 상태 중심"],
    ["03", "Agent 확인 필요", "자동 변경을 멈춘 제안만 집중 확인"],
    ["04", "활동 기록", "원본 Mail과 변경 근거를 추적"],
  ];
  callouts.forEach((item, index) => {
    const y = 168 + index * 112;
    text(slide, item[0], 934, y, 48, 24, 14, { bold: true, color: C.blue });
    text(slide, item[1], 986, y - 2, 222, 28, 18, { bold: true });
    text(slide, item[2], 934, y + 34, 274, 50, 15, { color: C.sub });
    if (index < callouts.length - 1) rule(slide, 934, y + 92, 274, C.line, 1);
  });
  text(slide, "※ 운영 UI 콘셉트이며 현재 구현 완료 화면과 구분", 934, 616, 274, 28, 13, { color: C.coral });
  notes(slide, "TO-BE 화면은 Streamlit Core 구조를 버리는 것이 아니라, 동일 기능을 일상 업무 중심 정보구조로 다듬는 방향이다. 자동 동기화는 Mail Adapter가 연결된 이후의 사용자 경험이다.", [
    "prototype/final_ui_mockup.html",
    "prototype/final_ui_mockup.png",
    "Docs/AI_MASTER/07_E2E서비스개발.md",
  ]);
}

// 11 — Next steps and mentor asks.
{
  const slide = header(p, "Core를 마감한 뒤 실제 Mail 연동을 판단하겠습니다", 11);
  const phases = [
    { x: 48, w: 344, color: C.blue, phase: "NOW · CORE 마감", body: "Ground Truth 세부 KPI\n수동 처리시간 Baseline\nMatching·상태 정책 보강\nUI 사용성 정리\n최종 Demo 증적" },
    { x: 424, w: 344, color: C.green, phase: "OPTION · 일정 여유", body: "테스트 Gmail Adapter\nRead-only 입력 경계\n동일 M-01~M-05 재사용\nCore 회귀 테스트 유지" },
    { x: 800, w: 408, color: C.sub, phase: "POST-MVP · 사내 적용", body: "Outlook / Microsoft Graph\nn8n · 사내 서버/VM\n인증·권한·운영 알림\n운영 DB·배포" },
  ];
  phases.forEach((phase) => {
    text(slide, phase.phase, phase.x, 166, phase.w, 26, 15, { bold: true, color: phase.color });
    box(slide, phase.x, 204, phase.w, 244, C.soft, C.line, "rounded-xl");
    text(slide, phase.body, phase.x + 24, 236, phase.w - 48, 184, 21, { bold: true });
  });
  text(slide, "멘토에게 확인받고 싶은 3가지", 48, 506, 390, 34, 24, { bold: true });
  const asks = [
    "① 현재 Core Scope가 Agentic AI 목표에 충분한가?",
    "② ASK_USER 기준과 완료·취소 승인 정책이 적절한가?",
    "③ 남은 기간은 KPI 정교화와 UI 중 어디에 더 집중해야 하는가?",
  ];
  asks.forEach((ask, index) => text(slide, ask, 48, 558 + index * 34, 1140, 28, 18, { bold: index === 0, color: index === 0 ? C.blue : C.ink }));
  notes(slide, "완성을 최우선으로 Core 범위를 유지한다. 테스트 Gmail은 Core E2E와 KPI가 안정화되고 일정이 남을 경우에만 진행한다. Outlook/Graph와 사내 운영환경은 Post-MVP다.", [
    "Docs/AI_MASTER/01_역량및기술스택.md",
    "Docs/AI_MASTER/07_E2E서비스개발.md",
    "Docs/IMPLEMENTATION/05_3단계_최종_E2E_구현범위.md",
    "Docs/IMPLEMENTATION/07_4단계_Post_MVP_사내확장.md",
  ]);
}

await fs.mkdir(path.dirname(OUT), { recursive: true });
await fs.mkdir(RENDER, { recursive: true });
for (const [index, slide] of p.slides.items.entries()) {
  const stem = `slide-${String(index + 1).padStart(2, "0")}`;
  const png = await p.export({ slide, format: "png", scale: 1 });
  await fs.writeFile(path.join(RENDER, `${stem}.png`), new Uint8Array(await png.arrayBuffer()));
  const layout = await slide.export({ format: "layout" });
  await fs.writeFile(path.join(RENDER, `${stem}.layout.json`), await layout.text());
}
const montage = await p.export({ format: "webp", montage: true, scale: 1 });
await fs.writeFile(path.join(ROOT, "tmp/weekly_mentor_report/montage.webp"), new Uint8Array(await montage.arrayBuffer()));
const pptx = await PresentationFile.exportPptx(p);
await pptx.save(OUT);
console.log(OUT);
