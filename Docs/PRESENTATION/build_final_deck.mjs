/**
 * Builds the final submission deck (4 slides) and renders it through the
 * presentation toolchain.
 *
 *   RUNTIME_NODE_MODULES=<node_modules> node Docs/PRESENTATION/build_final_deck.mjs
 *
 * PRESENTATION_SKILL_DIR points at the presentation skill's container_tools
 * directory and PRESENTATION_PYTHON at an interpreter that can run its
 * validators; both are required so no machine's paths are committed here.
 * The deck is the single source for slide text and speaker
 * notes: editing the PPTX directly leaves this file behind and the next build
 * silently reverts the change.
 */
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
// Resolved through RUNTIME_NODE_MODULES, matching build_weekly_mentor_report.mjs,
// so this builds from anywhere in the repository rather than only from a
// directory that happens to have the package linked.
const artifactSpecifier = process.env.RUNTIME_NODE_MODULES
  ? pathToFileURL(
      path.join(process.env.RUNTIME_NODE_MODULES, "@oai", "artifact-tool", "dist", "artifact_tool.mjs"),
    ).href
  : "@oai/artifact-tool";
const { Presentation, PresentationFile } = await import(artifactSpecifier);

// Derived from this file's own location so the build does not depend on where
// the repository was cloned.
const HERE = path.dirname(
  decodeURIComponent(new URL(import.meta.url).pathname).replace(/^\/([A-Za-z]:)/, "$1"),
);
const workspaceDir = path.resolve(HERE, "..", "..");
function required(name) {
  const value = process.env[name];
  if (!value) {
    throw new Error(
      `${name} is required. See the header comment for what each one points at.`,
    );
  }
  return value;
}

const SKILL_DIR = required("PRESENTATION_SKILL_DIR");
const TMP_DIR = path.join(workspaceDir, "tmp/final-presentation");
const DECK_VERSION = process.env.DECK_VERSION ?? "v12";
const FINAL_PPTX = path.join(
  workspaceDir,
  `Docs/PRESENTATION/2. 최종/09285_백준현_AI_Master_최종발표자료_${DECK_VERSION}.pptx`,
);
const RUNTIME_PYTHON = required("PRESENTATION_PYTHON");
const FONT = "Malgun Gothic";
const C = { navy:"#10243E", blue:"#1769E0", cyan:"#20B8C7", ink:"#172033", muted:"#657187", pale:"#EFF5FD", line:"#D7E1EF", green:"#138A62", amber:"#C77B00", red:"#C73C34", white:"#FFFFFF" };

await fs.mkdir(TMP_DIR, { recursive: true });
await fs.mkdir(path.dirname(FINAL_PPTX), { recursive: true });

const p = Presentation.create({ slideSize: { width: 1280, height: 720 } });

function box(slide, x, y, w, h, fill="none", line="none", radius=false) {
  return slide.shapes.add({ geometry: radius ? "roundRect" : "rect", position:{left:x,top:y,width:w,height:h}, fill: fill === "none" ? "none" : fill, line:{fill:line,width:line === "none" ? 0 : 1} });
}
function txt(slide, text, x, y, w, h, size=24, color=C.ink, bold=false, align="left") {
  const s = slide.shapes.add({ geometry:"textbox", position:{left:x,top:y,width:w,height:h}, fill:"none", line:{fill:"none",width:0} });
  s.text = text;
  s.text.style = { typeface:FONT, fontSize:size, color, bold, alignment:align, autoFit:"shrinkText", verticalAlignment:"middle", marginLeft:0, marginRight:0, marginTop:0, marginBottom:0 };
  return s;
}
function base(slide, title, no) {
  slide.background.fill = C.white;
  box(slide,0,0,20,720,C.blue,"none");
  txt(slide,title,60,44,1120,50,31,C.navy,true);
  box(slide,60,108,1160,2,C.line,"none");
  txt(slide,String(no).padStart(2,"0"),1172,655,48,24,14,C.muted,true,"right");
}
function pill(slide, text, x, y, w, color=C.blue, fill=C.pale) {
  box(slide,x,y,w,34,fill,"none",true);
  txt(slide,text,x+4,y+2,w-8,30,14,color,true,"center");
}
function flowNode(slide, title, sub, x, y, w, accent=C.blue) {
  box(slide,x,y,w,116,C.white,C.line,true);
  box(slide,x,y,8,116,accent,"none",true);
  txt(slide,title,x+20,y+17,w-30,32,19,C.navy,true);
  txt(slide,sub,x+20,y+51,w-30,50,14,C.muted,false);
}
function arrow(slide, x, y, w=34) {
  slide.shapes.add({ geometry:"rightArrow", position:{left:x,top:y,width:w,height:24}, fill:C.blue, line:{fill:"none",width:0} });
}
function notes(slide, text, sources=[]) {
  slide.speakerNotes.textFrame.setText(`${text}\n\n[근거]\n${sources.map(s=>`- ${s}`).join("\n")}`);
}

// 1. Cover
{
  const s=p.slides.add(); s.background.fill=C.navy;
  box(s,0,0,22,720,C.cyan,"none");
  txt(s,"AI Master Project",72,72,500,36,20,C.cyan,true);
  txt(s,"MailTaskAgent",72,155,800,82,52,C.white,true);
  txt(s,"메일을 업무로 해석하고 다음 행동을 결정하는 개인 업무관리 Agent",72,250,960,70,27,"#D9E6F8",false);
  box(s,72,390,1100,2,"#35506E","none");
  txt(s,"백준현  |  09285",72,430,420,40,22,C.white,true);
  txt(s,"AI Master 7기  |  멘토 이유경",72,474,520,34,18,"#B9C9DD",false);
  txt(s,"최종 발표",72,610,300,32,18,C.cyan,true);
  notes(s,"[시간 배분] 문제·기능 2분, 아키텍처 3분, 핵심 기술 과제 4분으로 약 9분이다. 10분 제한에 1분 여유를 남긴 배분이므로 슬라이드를 넘기기 전에 시간을 확인한다.",["Docs/PRESENTATION/2. 최종/09285_백준현_최종시연_스크립트.md"]);
}

// 2. Overview
{
  const s=p.slides.add(); base(s,"프로젝트 개요",2);
  txt(s,"같은 업무 요청이 여러 메일과 Thread에 흩어져 도착합니다",60,128,900,32,23,C.blue,true);
  txt(s,"무엇이 새 업무이고 무엇이 기존 업무의 변경인지 사람이 매번 판단해야 합니다. 놓치면 기한을 넘기고, 잘못 붙이면 엉뚱한 업무가 바뀝니다.",60,164,1150,42,16,C.ink,false);
  // The roles the code actually runs, in the order it runs them.
  const nodes=[
    ["Mail Analyzer","의미·Intent·기한 구조화\ngpt-4.1-mini",60,C.blue],
    ["Context Agent","가설 생성\n관계·대상·Action 후보 2~3개",300,C.cyan],
    ["Context Agent","가설 평가\n지지도 산출 후 하나 선택",540,"#7657D6"],
    ["Python Guard","후보·전이·중요 변경 검증\n미달 시 ASK_USER",780,C.amber],
    ["Reply Agent","회신 방식 판단·초안\n승인 후 Gmail 발송",1020,C.green]
  ];
  for (let i=0;i<nodes.length;i++) { const [a,b,x,c]=nodes[i]; flowNode(s,a,b,x,250,190,c); if(i<4) arrow(s,x+198,296,28); }
  txt(s,"핵심 기술",60,405,150,28,20,C.navy,true);
  txt(s,"회사 gpt-4.1-mini  ·  Python + Pydantic  ·  SQLite Task Context  ·  Gmail API  ·  Streamlit",205,405,975,28,16,C.muted,true);
  txt(s,"검증 결과",60,445,180,30,21,C.navy,true);
  const metrics=[["28/28","Action 단계"],["3/3","Agent Context Live"],["20/20","Gmail 수용시험"]];
  metrics.forEach(([v,l],i)=>{ const x=60+i*278; txt(s,v,x,481,220,42,32,i===2?C.green:C.blue,true,"center"); txt(s,l,x,523,220,24,15,C.muted,true,"center"); });
  txt(s,"보조 검증  |  pytest 228 passed  ·  중복 재조회 35/35",840,474,340,24,13,C.navy,true,"right");
  txt(s,"Reply Planning 3/3  ·  Draft 1/1  ·  사용자 승인 실제 Gmail 발송 1건",760,498,420,24,13,C.green,true,"right");
  txt(s,"자동 반영 비율  |  정의된 합성 15 Case에서 자동 반영 8/15(53.3%)  ·  사용자 확인 7/15(46.7%)",60,554,1160,22,14,C.navy,true);
  txt(s,"위 수치는 정의된 Case 범위의 결과이며 실제 Mailbox 전체 성능이 아닙니다. 사용자 체감 시간은 미측정입니다.",60,578,1160,18,11.5,C.muted,false);
  box(s,60,602,1160,44,C.pale,"none",true);
  txt(s,"핵심 메시지  |  규칙으로 열거할 수 없는 \"이 메일이 어느 업무인가\"만 Agent가 판단하고, 실행 권한은 Python과 사용자가 가집니다.",82,611,1110,28,16,C.navy,true);
  notes(s,"문제부터 말씀드리겠습니다. 하나의 업무가 여러 메일과 여러 Thread에 흩어져 도착하고, 기한 변경이나 자료 회신 같은 후속 메일은 표현이 매번 달라집니다. 그래서 사용자는 메일이 올 때마다 과거 메일을 다시 찾아, 이게 새 업무인지 기존 업무의 변경인지 직접 판단해야 합니다. 놓치면 기한을 넘기고, 잘못 붙이면 엉뚱한 업무의 상태가 바뀝니다. 제가 풀려는 것은 이 판단입니다.\n\n가운데 다섯 상자는 실제로 도는 역할입니다. 메일 분석기가 의미와 의도를 구조화하고, 컨텍스트 에이전트가 관계와 대상, 행동 후보를 두세 개 만듭니다. 같은 에이전트를 한 번 더 부르는데 이번엔 평가만 시킵니다. 만드는 호출과 고르는 호출이 다릅니다. 그다음 파이썬 가드가 후보와 상태 전이, 중요 변경을 검증하고 기준에 못 미치면 사용자 확인으로 넘깁니다. 마지막이 회신 에이전트입니다. 엘엘엠이 판단하는 자리와 파이썬이 통제하는 자리가 이 그림에서 갈립니다.\n\n아래 수치는 분모가 서로 다르니 합쳐 읽지 말아 주십시오. 28/28은 회사 LLM Live 15개 Case에서 나온 Action 단계, 3/3은 Task Context Agent 전용 Live, 20/20은 테스트 Gmail의 비식별 합성 메일 수용시험, pytest는 코드 회귀입니다. 회사 메일함 전체 정확도가 아닙니다. 체감 시간은 신뢰할 Baseline을 얻지 못해 추정치 대신 미측정으로 적었습니다. 측정하려면 같은 메일 묶음을 손으로 분류할 때와 이 도구를 쓸 때의 소요를 같은 사용자가 번갈아 재야 하는데, 사용자가 저 한 명이라 순서 효과를 걷어낼 방법이 없었습니다.",["Docs/AI_MASTER/02_문제정의및서비스기획.md","evidence/final_audit_live_2026-09-13_after_inbound_intent_guard.json","evidence/final_mvp_acceptance_2026-09-08.json"]);
}

// 3. Architecture
{
  const s=p.slides.add(); base(s,"기술 아키텍처와 Agent 판단 구조",3);
  txt(s,"M-01~M-05 Workflow는 안전한 실행 뼈대, 규칙으로 확정할 수 없는 관계·대상·Action은 Agent가 판단",60,126,1150,30,19,C.blue,true);
  const xs=[60,250,440,630,820,1010];
  const ns=[
    ["M-01","Mail Analyzer","의미·Intent·기한"],
    ["M-02","Task Retriever","SQLite Context top-k"],
    ["M-03","Context Agent","가설 생성·검증·평가"],
    ["Guard","Python Policy","Payload·전이 검증"],
    ["M-04","DB Tool","저장·상태 재조회"],
    ["M-05","Review·Trace","사용자 확인 화면"]
  ];
  ns.forEach(([id,t,d],i)=>{ box(s,xs[i],190,160,132,i===2?"#F3EFFF":C.white,i===2?"#7657D6":C.line,true); pill(s,id,xs[i]+18,204,90,i===2?"#7657D6":C.blue,i===2?"#EDE6FF":C.pale); txt(s,t,xs[i]+14,246,136,28,17,C.navy,true); txt(s,d,xs[i]+14,276,136,36,13,C.muted,false); if(i<5) arrow(s,xs[i]+166,242,20); });
  box(s,60,342,1160,88,C.pale,"none",true);
  txt(s,"Task 관계",82,350,120,28,16,C.navy,true);
  txt(s,"동일 Thread는 Metadata 규칙",205,350,260,28,15,C.muted,false);
  txt(s,"다른 Thread·다른 표현은 후보 2~3개를 비교해 관계·대상·Action 선택",475,350,710,28,15,"#7657D6",true);
  txt(s,"회신 실행",82,390,120,28,16,C.navy,true);
  txt(s,"Reply Agent 판단  →  사용자 입력  →  LLM 초안  →  승인 Gmail 발송  →  WAITING_REPLY",205,390,980,28,15,C.green,true);
  txt(s,"기술 선택 이유",60,450,180,28,20,C.navy,true);
  const choices=[
    ["gpt-4.1-mini","메일 의미와 관계를 Pydantic Schema로 구조화\n모델 간 우월성 비교는 수행하지 않음"],
    ["SQLite Task Context","개인 MVP의 활성 Task·최근 Mail·History만 제한 검색\nVector DB와 외부 Embedding은 사용하지 않음"],
    ["Python + Pydantic Guard","LangGraph 없이 단일 Agent + 결정론 Guard 구성\n후보 ID·상태 전이·중요 변경을 Python이 검증"]
  ];
  choices.forEach(([t,d],i)=>{ const x=60+i*386; txt(s,t,x,486,348,26,17,i===1?"#7657D6":C.blue,true); txt(s,d,x,518,348,54,14,C.muted,false); });
  box(s,60,590,1160,44,"#EEF9F5","none",true);
  txt(s,"M-01은 모든 Mail 의미를 LLM으로 구조화하고, 관계·Action 선택은 STRUCTURED_RAG 경로에만 적용합니다.",82,598,1110,27,16,C.navy,true);
  notes(s,"가장 중요한 설계 결정부터 말씀드리겠습니다. 모든 메일을 Agent에게 맡기지 않았습니다. 경로가 셋으로 갈립니다. 같은 Thread에 활성 업무가 정확히 하나면 규칙이 바로 연결하고 검색과 Agent 판단을 아예 호출하지 않습니다. 관련 업무를 찾아야 할 때만 RAG 경로로 가고, 업무 요청이 아니면 기존 규칙 경로로 처리합니다. 입력에 따라 호출 자체가 달라지는 것이 고정 Workflow와의 차이입니다.\n\nM-03을 한 번의 호출로 두지 않은 이유가 중요합니다. 후보와 승자를 한 응답에서 같이 받으면, 모델이 실제로 후보를 견주었는지 결론을 먼저 정하고 설명을 붙였는지 구분할 방법이 없습니다. 그래서 생성과 평가를 다른 호출로 나눴습니다. 생성 단계는 후보 두세 개를 근거와 함께 내고 점수는 매기지 않습니다. Python이 후보 ID와 관계 계약을 검증하고, 통과한 후보만 평가 단계로 넘어가 지지도를 받습니다. 상위 두 지지도의 차이는 Python이 계산합니다.\n\nM-02 검색은 외부 문서가 아니라 제 SQLite를 봅니다. 활성 업무 다섯 건, 각 업무의 최근 메일 세 건과 변경 이력 다섯 건, 그리고 사용자가 과거에 확정한 결정을 함께 가져옵니다. 지난 결정이 다음 판단의 근거로 다시 들어갑니다.\n\n기술 선택 이유입니다. Vector DB와 외부 Embedding은 쓰지 않았습니다. 개인의 활성 업무는 수십 건 규모라 SQLite 조회만으로 충분했고, 구성요소를 늘리는 비용이 더 컸습니다. 대신 검색이 어휘 겹침에 의존한다는 한계가 남습니다. 모델 간 비교 실험은 하지 않았으므로 최적이라고 주장하지 않습니다.\n\n랭그래프도 쓰지 않았습니다. 에이전트가 하나이고 상태가 Task 다섯 개와 Action 일곱 개로 닫혀 있어, 파이썬 상태와 가드만으로 검증이 더 쉬웠습니다. 분기와 중단, 재개가 복잡해지는 시점에 다시 검토하겠습니다.\n\n세 번째가 가장 오래 고민한 Python Guard입니다. LLM은 제안만 하고 데이터베이스를 직접 바꾸지 않습니다. Guard는 고른 업무 ID가 검색 후보 안에 있는지, 메일 의도와 Action이 맞는지, 생성에 필요한 값이 있는지를 확인하고, 하나라도 어긋나면 사용자 확인으로 올립니다. 완료·취소·기한 단축은 신뢰도와 무관하게 항상 승인을 거칩니다.",["Docs/AI_MASTER/04_상세설계및개발환경.md","src/mailtaskagent/workflow.py","src/mailtaskagent/task_context_agent.py","src/mailtaskagent/deliberation.py","src/mailtaskagent/decision.py"]);
}

// 4. Challenge and proof
{
  const s=p.slides.add(); base(s,"핵심 기술 과제와 검증",4);
  txt(s,"왜 고정 규칙과 단일 결론 Agent만으로 부족했는가",60,132,700,30,21,C.red,true);
  txt(s,"Agent가 결론 하나만 내면 후보를 견준 것인지 설명을 붙인 것인지 알 수 없습니다. 멘토 피드백도 \"Rule Base처럼 보인다\"였습니다.",60,166,1150,44,17,C.ink,false);
  box(s,60,228,1160,2,C.line,"none");
  txt(s,"실제 Agent 판단 흐름",60,246,260,28,20,C.navy,true);
  // Two explicit lines rather than one that wraps and orphans a syllable.
  txt(s,"적용 기법  |  Bounded Multi-Hypothesis Deliberation",60,268,1160,20,13,"#7657D6",true);
  txt(s,"Tree of Thoughts(Yao et al., NeurIPS 2023)의 후보 생성·평가 분리 아이디어를 참고하되, 후보 2~3개·평가 1회·재검색 1회로 제한했습니다. Full Tree of Thoughts 구현은 아닙니다.",60,288,1160,20,12.5,C.muted,false);
  const agentRows=[
    ["입력·검색", "현재 Mail + 활성 Task + 최근 Mail 3건 + History 5건"],
    ["가설 생성", "가능한 관계·대상·Action 후보 2~3개를 근거와 함께 제시 (점수는 매기지 않음)"],
    ["검증·평가", "Python이 후보 계약을 검증하고, 별도 평가 단계가 지지도를 매겨 하나를 선택"],
    ["재판단 · Self-Correction", "모호·저신뢰이거나 선택 차이가 작으면 Query Rewrite 후 재검색을 최대 1회 수행"],
    ["실행·관찰", "Python Guard 승인 또는 ASK_USER → DB 실행 → 실제 저장 상태 재조회"]
  ];
  agentRows.forEach(([a,b],i)=>{ const y=318+i*40; pill(s,String(i+1),60,y,38,C.white,i===2?"#7657D6":C.blue); txt(s,a,116,y,120,34,16,C.navy,true); txt(s,b,246,y,920,34,16,C.muted,false); });
  txt(s,"같은 Case·같은 코드에서 숙고만 껐다 켠 비교",60,520,860,28,19,"#7657D6",true);
  const live=[
    ["기존 15 Case", "15/15 · Action 28/28", "숙고 On·Off 동일, 시간만 증가"],
    ["숙고 전용 4 Case", "재현되는 차이 1건", "DLB-02: On 3/3 통과, Off 3/3 실패"],
    ["실제 Gmail 재현", "새 메일 4건 처리", "2건 Task 생성, 2건 ASK_USER"]
  ];
  live.forEach(([id,a,c],i)=>{ const x=60+i*386; txt(s,id,x,556,348,22,14,C.blue,true); txt(s,a,x,582,348,24,16,C.navy,true); txt(s,c,x,610,348,22,14,C.muted,false); });
  txt(s,"Next Step  |  Gmail 검증 결과를 바탕으로 Outlook·Graph Adapter와 사내 인증·운영 서버로 전환",60,636,1160,22,14,C.blue,true);
  txt(s,"실패  |  계약 위반 응답을 재시도 없이 실패 처리해 판단 4건 유실",60,662,620,22,14,C.red,true);
  txt(s,"개선  |  검증을 재시도 루프 안으로 이동, 유실 0건",760,662,460,22,14,C.green,true);
  notes(s,"이 슬라이드의 난제부터 말씀드리겠습니다. 저는 이미 Agent를 쓰고 있었는데, 그 Agent가 결론을 하나만 돌려줬습니다. 관계 하나, 대상 하나, 행동 하나에 설명 한 줄입니다. 이러면 모델이 후보를 실제로 견줬는지, 결론을 먼저 정하고 설명을 붙였는지 밖에서 구분할 방법이 없습니다. 멘토님 피드백도 매번 같았습니다. 룰 베이스처럼 보인다, 어떤 후보를 검토했는지 보여 달라. 막힌 곳은 판단의 품질이 아니라 검증 가능성이었습니다.\n\n그래서 적용한 기법이 화면에 적힌 제한적 다중 가설 숙고입니다. 트리 오브 소트를 구현한 것이 아니라, 후보 생성과 평가를 분리한다는 아이디어만 참고했습니다. 메일 한 건을 업무로 옮기는 판단은 단계가 깊지 않은 대신 틀렸을 때 비용이 업무 데이터 오변경이라, 후보 두세 개, 평가 한 번, 재검색 한 번으로 묶고 결정론적 가드와 사용자 승인으로 막는 쪽을 택했습니다. 핵심은 생성과 평가를 서로 다른 호출로 나눈 것입니다. 생성 단계는 점수를 매기지 않고, 평가 단계는 새로 만들지 못합니다. 그래서 화면에 남는 후보 목록이 사후 설명이 아니라 실제로 비교된 기록이 됩니다.\n\n효과는 같은 코드에서 기능만 껐다 켜서 측정했습니다. 기존 열다섯 개 Case는 양쪽이 똑같이 15/15, Action 28/28이고 소요시간만 약 삼십 퍼센트 늘었습니다. 숙고가 실제 발동하는 전용 네 개 케이스는 회차마다 출력이 달라져 각 설정을 세 번씩 돌렸고, 통과 수는 켠 쪽이 삼, 삼, 이, 끈 쪽이 이, 이, 이입니다. 세 번 모두 재현되는 차이는 한 건입니다. 요청자가 같고 대상 시스템만 다른 유사 업무가 둘 있을 때, 단일 결론 경로는 세 번 모두 둘 중 하나에 그대로 연결했고 두 단계 경로는 세 번 모두 사용자 확인으로 닫았습니다. 제가 개선했다고 말하는 범위는 이 한 건이고, 엘엘엠을 호출하지 않는 목 경로에서는 양쪽 모두 사 대 사로 차이가 없습니다.\n\n실패도 말씀드리겠습니다. 처음 구현에서 응답 검증을 재시도 루프 밖에 두었습니다. 모델이 필드 하나를 배열로 돌려준 것만으로 판단 전체가 실패했고, 저장해 둔 실제 Gmail 서른다섯 건을 다시 흘려보냈을 때 판단 네 건이 사라졌습니다. 합성 테스트가 아니라 실제 데이터 재생에서 잡혔고, 검증을 루프 안으로 옮긴 뒤 유실은 0건입니다.\n\n두 번째는 기대값과 동작 중 어느 쪽이 틀렸는지 따져야 했던 건입니다. 검색 결과 안에 명령을 심어 둔 케이스가 세 번 모두 기대값인 사용자 확인 대신 무시로 끝났습니다. 그 메일은 순수 주입이 아니라 정상 회신 내용과 주입된 명령이 섞인 혼합 메일이고, 정답도 업무 요청 참이었습니다. 원인은 제 프롬프트였습니다. Prompt Injection을 공지·광고와 같은 줄에 두고 업무 요청이 아닌 사유로 제시해서 모델이 메일 전체를 버렸습니다. 원칙은 본문의 명령을 실행하지 않는다이지 명령이 섞인 메일을 버린다가 아닙니다. 기대값은 그대로 두고 규칙만 분리했습니다. 수정 후 이 케이스는 세 번 모두 통과하고 숙고 전용 통과 수는 삼, 사, 사가 되었습니다. 명령만 들어 있는 순수 주입은 그대로 무시로 끝나 둘의 구분이 유지되고, 본문이 지시한 전체 완료 처리와 기록 삭제는 수정 전후 어느 회차에서도 일어나지 않았습니다.\n\n남은 한계도 말씀드리겠습니다. 화면의 신뢰도와 지지도는 모델의 자기보고 값이지 검증된 정답 확률이 아닙니다. 사용자 체감 시간은 신뢰할 Baseline을 얻지 못해 미측정으로 남겼습니다.",["evidence/deliberation_ab_2026-09-15.json","evidence/dlb04_injection_adjudication_2026-09-15.json","evidence/gmail_replay_deliberation_2026-09-15.json","evidence/final_audit_live_2026-09-13_after_inbound_intent_guard.json","tests/test_deliberation.py","tests/test_agent_deliberation.py"]);
}

const { finalizePresentation } = await import(pathToFileURL(path.join(SKILL_DIR,"container_tools/artifact_tool_utils.mjs")).href);
const candidatePath = path.join(TMP_DIR,"candidate.pptx");
await (await PresentationFile.exportPptx(p)).save(candidatePath);
const requirements = { explicitTotalSlideCount:4, requiredNativeTableOwnerSlides:[], requiredNativeChartOwnerSlides:[] };
const result = await finalizePresentation({
  ...requirements,
  workspaceDir,
  candidatePath,
  finalPath:FINAL_PPTX,
  pythonExecutable:RUNTIME_PYTHON,
  integrityValidatorPath:path.join(SKILL_DIR,"container_tools/inspect_presentation_package_integrity.py"),
  layoutValidatorPath:path.join(SKILL_DIR,"container_tools/inspect_presentation_layout_geometry.py"),
  layoutArgs:["--expected-slide-size-emu","12192000,6858000","--validate-heading-fit"],
  requiredNativeTableOwnerSlides:[],
  fontPolicy:{basis:"design",families:[FONT]},
  verifyArtifactToolImport:true,
  receiptPath:path.join(TMP_DIR,`validation-${DECK_VERSION}.json`)
});
console.log(JSON.stringify({final:FINAL_PPTX,result},null,2));
