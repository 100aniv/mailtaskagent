// Rebuilds the mentor-review deck and its temporary slide renders.
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

const artifactSpecifier = process.env.RUNTIME_NODE_MODULES
  ? pathToFileURL(path.join(process.env.RUNTIME_NODE_MODULES, "@oai", "artifact-tool", "dist", "artifact_tool.mjs")).href
  : "@oai/artifact-tool";
const { Presentation, PresentationFile } = await import(artifactSpecifier);

const OUT = "Docs/PRESENTATION/MailTaskAgent_멘토리뷰_2026-08-26.pptx";
const RENDER_DIR = "tmp/presentation_build/rendered";
const W = 1280, H = 720;
const C = { ink: "#111827", sub: "#687386", rule: "#D8DDE6", panel: "#F1F3F6", blue: "#3D67E8", pale: "#EDF1FF", green: "#20866B", amber: "#A86D14", red: "#B84755", white: "#FFFFFF", navy: "#19243C" };

function addText(slide, text, x, y, w, h, size=22, opts={}) {
  const s = slide.shapes.add({ geometry: "textbox", position: { left:x, top:y, width:w, height:h }, fill:"none", line:{style:"solid",fill:"none",width:0}, name: opts.name });
  s.text = text;
  s.text.style = { fontSize:size, typeface:"Arial", color:opts.color||C.ink, bold:!!opts.bold, alignment:opts.align||"left", verticalAlignment:opts.valign||"top", autoFit:"shrinkText" };
  return s;
}
function addBox(slide,x,y,w,h,fill=C.panel,line=C.rule,radius="rounded-xl") {
  return slide.shapes.add({geometry:"roundRect",position:{left:x,top:y,width:w,height:h},fill,line:{style:"solid",fill:line,width:1},borderRadius:radius});
}
function addRule(slide,x,y,w,color=C.rule,width=1){return slide.shapes.add({geometry:"straightConnector1",position:{left:x,top:y,width:w,height:0},fill:"none",line:{style:"solid",fill:color,width}})}
function baseSlide(p,title,num,eyebrow="MAILTASKAGENT"){
  const s=p.slides.add(); s.background.fill=C.white;
  addText(s,eyebrow,42,26,260,24,12,{bold:true,color:C.blue});
  addText(s,title,42,58,1160,66,38,{bold:true});
  addText(s,String(num).padStart(2,"0"),1180,670,50,20,12,{color:C.sub,align:"right"});
  return s;
}
function notes(slide,body,sources){slide.speakerNotes.textFrame.setText(`${body}\n\n[Sources]\n${sources.map(s=>`- ${s}`).join("\n")}`);}
async function imageBytes(path){const b=await fs.readFile(path);return b.buffer.slice(b.byteOffset,b.byteOffset+b.byteLength)}

const p=Presentation.create({slideSize:{width:W,height:H}});

// 1. Cover — Codex Grid cover-image-field silhouette.
{
  const s=p.slides.add(); s.background.fill=C.white;
  addText(s,"AI MASTER · MENTOR REVIEW",42,38,420,24,13,{bold:true,color:C.blue});
  addText(s,"MailTaskAgent",42,142,570,72,58,{bold:true});
  addText(s,"메일을 읽고, 기존 업무와 연결한 뒤,\n다음 Action을 결정하는 개인 업무관리 Agent",42,238,550,116,28,{color:C.sub});
  addRule(s,42,392,220,C.blue,4);
  addText(s,"회사 LLM Live · Human-in-the-loop · SQLite History · Streamlit",42,420,560,54,18,{color:C.ink});
  const hero=addBox(s,660,42,578,588,C.pale,"#D9E1FF","rounded-2xl");
  addText(s,"MAIL",710,96,160,36,18,{bold:true,color:C.blue});
  addText(s,"→",854,172,80,70,54,{bold:true,color:C.blue,align:"center"});
  addText(s,"TASK",956,96,180,36,18,{bold:true,color:C.blue,align:"right"});
  addText(s,"읽는다",700,268,160,40,25,{bold:true}); addText(s,"연결한다",890,268,180,40,25,{bold:true});
  addText(s,"행동한다",700,374,180,40,25,{bold:true}); addText(s,"기록한다",900,374,170,40,25,{bold:true});
  addText(s,"CREATE · UPDATE · WAITING\nASK USER · HISTORY",700,484,430,72,22,{bold:true,color:C.blue});
  addText(s,"2026.08.26",42,650,180,24,14,{color:C.sub}); addText(s,"01",1180,670,50,20,12,{color:C.sub,align:"right"});
  notes(s,"오늘은 최종 발표가 아니라 현재 Core E2E의 구조, 실제 증적, 운영 UI 방향을 이해하기 위한 리뷰다.",["Docs/AI_MASTER/01~07","Docs/IMPLEMENTATION/08_멘토_시연_브리핑.md"]);
}

// 2. Problem / solution.
{
  const s=baseSlide(p,"메일보다 어려운 것은 ‘업무의 변화’를 따라가는 일입니다",2);
  addText(s,"AS-IS",42,164,150,28,18,{bold:true,color:C.red});
  addText(s,"메일에서 요청을 찾고\n과거 Thread를 다시 열고\n기한·대기·완료를 수동 반영",42,206,510,154,30,{bold:true});
  addText(s,"업무 누락 · 변경 미반영 · 회신 대기 장기화",42,390,510,40,19,{color:C.sub});
  addText(s,"TO-BE",670,164,150,28,18,{bold:true,color:C.blue});
  addText(s,"새 Mail과 현재 Task를 함께 보고\n다음 Action과 근거를 제안\n중요 변경은 사람에게 확인",670,206,530,154,30,{bold:true});
  addText(s,"자동화보다 ‘안전한 상태관리’가 우선",670,390,530,40,19,{color:C.blue,bold:true});
  addRule(s,42,480,1156,C.rule,1);
  addText(s,"핵심 정의",42,515,150,28,17,{bold:true});
  addText(s,"MailTaskAgent는 메일 요약기가 아니라 Task Lifecycle을 관리하는 Agentic Workflow입니다.",230,510,930,64,25,{bold:true});
  notes(s,"문제는 메일 분류 자체가 아니라 후속 메일이 들어올 때 기존 업무 상태를 계속 갱신해야 하는 데 있다.",["Docs/AI_MASTER/02_문제정의및서비스기획.md"]);
}

// 3. Workflow diagram — connectors first behind nodes.
{
  const s=baseSlide(p,"Mail은 5개 공통 모듈과 하나의 안전 Gate를 통과합니다",3);
  const xs=[42,230,418,606,794,982], y=250, bw=154, bh=112;
  for(let i=0;i<xs.length-1;i++){
    s.shapes.add({geometry:"straightConnector1",position:{left:xs[i]+bw,top:y+55,width:xs[i+1]-xs[i]-bw,height:0},fill:"none",line:{style:"solid",fill:C.blue,width:2},head:{type:"arrow",width:"sm",length:"sm"}});
  }
  const titles=["M-01","M-02","M-03","VALIDATE","M-04","M-05"];
  const bodies=["Mail 분석\nIntent·기한","Task 후보\n점수·근거","Action 결정\n7개 중 선택","Schema·상태\n안전 검사","Task·History\nDB Transaction","사용자 확인\nDashboard"];
  xs.forEach((x,i)=>{addBox(s,x,y,bw,bh,i===3?"#FFF5E7":(i===5?C.navy:C.pale),i===3?"#F0C47E":(i===5?C.navy:"#D9E1FF"));addText(s,titles[i],x+14,y+16,bw-28,24,15,{bold:true,color:i===5?C.white:(i===3?C.amber:C.blue)});addText(s,bodies[i],x+14,y+48,bw-28,54,16,{bold:true,color:i===5?C.white:C.ink});});
  addText(s,"회사 LLM API",42,418,240,30,18,{bold:true,color:C.blue});
  addText(s,"의미 구조화만 담당",42,452,240,30,17,{color:C.sub});
  addText(s,"Python Application Logic",418,418,330,30,18,{bold:true,color:C.green});
  addText(s,"후보 검색 · Action · DB 변경",418,452,330,30,17,{color:C.sub});
  addText(s,"Human-in-the-loop",794,418,300,30,18,{bold:true,color:C.red});
  addText(s,"완료·취소·모호성 자동 반영 차단",794,452,410,30,17,{color:C.sub});
  addText(s,"LLM은 DB를 직접 수정하지 않습니다.",42,574,1110,42,28,{bold:true});
  notes(s,"Node는 별도 서버가 아니라 한 건의 Mail을 처리하는 논리 단계다. LLM 의미 분석과 실제 DB 변경 권한을 분리했다.",["Docs/AI_MASTER/04_상세설계및개발환경.md","src/mailtaskagent/workflow.py","src/mailtaskagent/decision.py"]);
}

// 4. Three scenarios / 15 cases.
{
  const s=baseSlide(p,"사용자 시나리오는 3개, 이를 흔드는 검증 Case는 15개입니다",4);
  const cols=[42,446,850];
  const blocks=[
    ["SC-001","신규 업무 생성","명확한 요청 · 기한 없음\n일반 공지 · 중복 Mail","BC-01~03 · BC-15"],
    ["SC-002","기존 업무 갱신","기한 연장·단축 · 정보 연결\n회신 대기·재개 · 완료·취소","BC-04~09 · BC-14"],
    ["SC-003","사용자 확인","불명확 완료 · 후보 복수\n다른 Thread · 모호한 기한","BC-10~13 · SEC-01"]
  ];
  blocks.forEach((b,i)=>{addText(s,b[0],cols[i],164,180,28,17,{bold:true,color:C.blue});addText(s,b[1],cols[i],210,330,42,28,{bold:true});addRule(s,cols[i],274,320,C.rule,1);addText(s,b[2],cols[i],302,340,98,19,{color:C.sub});addText(s,b[3],cols[i],434,300,32,17,{bold:true,color:C.ink});});
  addBox(s,42,520,1156,82,C.navy,C.navy,"rounded-xl");
  addText(s,"15개 실행 단위는 새 기능 목록이 아니라 정상·예외·안전 조건을 재현하는 평가 Dataset입니다.",70,546,1100,34,22,{bold:true,color:C.white,align:"center"});
  notes(s,"시나리오와 테스트 Case를 구분한다. 사용자 여정은 3개이며, 15개는 그 여정을 흔드는 조건이다.",["Docs/AI_MASTER/03_시나리오수립.md","data/scenario_expectations.json"]);
}

// 5. Responsibility split.
{
  const s=baseSlide(p,"정확성은 LLM 하나가 아니라 역할 분리에서 나옵니다",5);
  const x=[42,445,848], fills=[C.pale,"#ECF7F3","#FFF1F3"], colors=[C.blue,C.green,C.red];
  const title=["LLM","APPLICATION LOGIC","USER"];
  const body=["메일 의미·Intent 구조화\n요청·기한·완료·취소 해석\nJSON Structured Output","동일 Thread·후보 검색\n7 Action·상태 전이 검증\nSQLite Transaction","후보 연결·신규·무시\n완료·취소·기한 단축 승인\nTask 직접 수정"];
  const foot=["직접 DB 변경 금지","검증된 변경만 저장","최종 통제권 보유"];
  x.forEach((v,i)=>{addBox(s,v,176,350,332,fills[i],fills[i]);addText(s,title[i],v+24,204,300,34,19,{bold:true,color:colors[i]});addText(s,body[i],v+24,264,300,132,23,{bold:true});addText(s,foot[i],v+24,458,300,28,17,{bold:true,color:colors[i]});});
  addText(s,"원본 Mail ID · 변경 전/후 · 판단 근거 · 사용자 결정 · 처리 시각",42,566,1156,42,25,{bold:true,align:"center"});
  notes(s,"이 구조가 Agent의 핵심 안전성이다. LLM은 의미를 해석하고 Python이 실행을 검증하며 사람은 중요 변경을 확정한다.",["Docs/AI_MASTER/05_POC모듈구현.md","src/mailtaskagent/llm_client.py","src/mailtaskagent/storage.py"]);
}

// 6. Current vs product UI.
{
  const s=baseSlide(p,"현재 Core UI는 운영 구조를 갖췄고, 다음은 사용성 완성입니다",6);
  const current=await imageBytes("prototype/current_streamlit_ui.png");
  const target=await imageBytes("prototype/final_ui_mockup.png");
  addText(s,"현재 구현 · Core 기능이 연결된 제품형 UI",42,148,550,28,18,{bold:true,color:C.green});
  addText(s,"목표 화면 · 매일 쓰는 운영 UI 콘셉트",654,148,544,28,18,{bold:true,color:C.blue});
  s.images.add({blob:current,contentType:"image/png",alt:"현재 Streamlit 시연 화면",fit:"contain",position:{left:42,top:184,width:550,height:344},geometry:"roundRect",borderRadius:"rounded-xl"});
  s.images.add({blob:target,contentType:"image/png",alt:"운영용 MailTaskAgent UI 컨셉",fit:"contain",position:{left:654,top:184,width:544,height:344},geometry:"roundRect",borderRadius:"rounded-xl"});
  addText(s,"업무 현황 · 메일 처리함 · 확인 필요 · 운영 로그",42,550,550,30,18,{color:C.sub,align:"center"});
  addText(s,"오늘 업무 · 자동 동기화 · 확인 필요 · 활동 기록",654,550,544,30,18,{bold:true,color:C.blue,align:"center"});
  notes(s,"현재 Streamlit에도 제품형 탭과 Core Workflow가 연결되어 있고 데모 도구는 별도로 분리돼 있다. 목표 UI는 자동 동기화 이후 사용자가 오늘의 업무와 확인 필요 항목을 더 빠르게 파악하도록 사용성을 고도화한 방향이다.",["src/mailtaskagent/ui.py","prototype/current_streamlit_ui.png","prototype/final_ui_mockup.html","prototype/final_ui_mockup.png"]);
}

// 7. Usage timeline — Codex Grid timeline silhouette.
{
  const s=baseSlide(p,"운영에서는 Mail Source가 Agent를 자동 호출합니다",7);
  const xs=[42,274,506,738,970], labels=["01 SYNC","02 ANALYZE","03 DECIDE","04 REVIEW","05 MANAGE"], heads=["새 Mail 도착","의미 구조화","Task 반영","필요 시 확인","업무 관리"], desc=["Mail Source가\n공통 Schema로 전달","회사 LLM이\nIntent·기한 추출","기존 Task 연결\n또는 신규 생성","중요·애매한 변경\n사용자가 확정","기한·대기·이력\nDashboard 확인"];
  addRule(s,48,300,1120,C.rule,2);
  xs.forEach((x,i)=>{s.shapes.add({geometry:"ellipse",position:{left:x,top:293,width:15,height:15},fill:i===3?C.red:C.blue,line:{style:"solid",fill:C.white,width:2}});addText(s,labels[i],x,214,180,24,14,{bold:true,color:i===3?C.red:C.blue});addText(s,heads[i],x,338,190,34,21,{bold:true});addText(s,desc[i],x,388,190,76,18,{color:C.sub});});
  addBox(s,42,520,1156,72,C.pale,"#D9E1FF","rounded-xl");
  addText(s,"현재 합성 Mail ‘전체 자동 정리’ 버튼은 자동 수집 Adapter가 맡게 될 입력 Trigger를 재현합니다.",66,542,1100,30,20,{bold:true,color:C.blue,align:"center"});
  notes(s,"현재 버튼은 제품 설계가 아니라 합성 Mail Source의 도착을 재현하는 Trigger다. Mail Adapter가 붙으면 사용자가 매번 분석을 누르지 않는다.",["Docs/IMPLEMENTATION/08_멘토_시연_브리핑.md","Docs/AI_MASTER/07_E2E서비스개발.md"]);
}

// 8. Safety cases.
{
  const s=baseSlide(p,"Agent는 애매할수록 더 많이 자동화하지 않고 멈춥니다",8);
  const y=[174,306,438];
  const left=["후보 Task 2개","‘다음 주 중’","완료·취소·기한 단축"];
  const mid=["임의 연결 금지","임의 날짜 생성 금지","중요 상태 자동 변경 금지"];
  const right=["ASK_USER → 후보 비교","ASK_USER → 날짜 확인","제안 → 사용자 승인/수정/거절"];
  y.forEach((v,i)=>{addText(s,left[i],42,v,300,38,23,{bold:true});addText(s,"→",360,v-3,60,44,30,{bold:true,color:C.red,align:"center"});addText(s,mid[i],438,v,340,38,21,{bold:true,color:C.red});addText(s,"→",790,v-3,60,44,30,{bold:true,color:C.blue,align:"center"});addText(s,right[i],866,v,330,42,20,{bold:true,color:C.blue});if(i<2)addRule(s,42,v+82,1156,C.rule,1);});
  addText(s,"사용자 결정 전 DB 중요 변경 0건 · 모든 변경은 History로 추적",42,586,1156,36,23,{bold:true,align:"center"});
  notes(s,"자동처리율보다 안전한 중단이 우선이다. 사용자 확인 비율이 높은 이유도 위험 Case를 의도적으로 많이 넣었기 때문이다.",["Docs/AI_MASTER/06_테스트및고도화.md","tests/test_workflow.py"]);
}

// 9. Metrics — Codex Grid metric-led silhouette.
{
  const s=baseSlide(p,"현재 증적은 ‘Core가 연결돼 동작한다’는 수준까지 확보했습니다",9);
  addText(s,"회사 LLM Live와 자동 회귀를 분리해 같은 기대값으로 검증했습니다.",42,126,900,38,20,{color:C.sub});
  const x=[42,445,848], stat=["15 / 15","28 / 28","42"], lab=["Live 실행 단위 통과","Action 단계 일치","pytest passed"];
  x.forEach((v,i)=>{addBox(s,v,250,350,260,C.panel,C.panel,"rounded-xl");addText(s,stat[i],v+26,298,300,90,48,{bold:true,color:C.blue});addText(s,lab[i],v+26,420,300,44,20,{bold:true});});
  addText(s,"주의",42,558,80,26,16,{bold:true,color:C.red});
  addText(s,"100%는 현재 정의된 합성 Dataset의 E2E Action 결과입니다. 분류·필드·Task ID·수동 시간 KPI는 별도 측정이 남았습니다.",132,552,1066,50,18,{color:C.sub});
  notes(s,"성과를 과장하지 않는다. 현재 15개 합성 실행 단위에서 E2E Action은 모두 맞았지만 세부 필드 정확도와 시간 단축률은 아직 측정 전이다.",["evidence/live_evaluation_2026-08-26.json","Docs/AI_MASTER/06_테스트및고도화.md","pytest result: 42 passed"]);
}

// 10. Current status and next review.
{
  const s=baseSlide(p,"Core MVP 이후 실제 Mail 연동과 운영 확장을 판단합니다",10);
  addText(s,"현재 완료",42,156,300,30,18,{bold:true,color:C.green});
  addText(s,"회사 LLM Live\n7 Action · 5 State\nASK_USER 승인 흐름\nSQLite Task·History\n운영 로그·품질 검증\nTask 직접 수정\nGitHub 복구 지점",42,204,500,270,24,{bold:true});
  addText(s,"남은 Core 마감",650,156,300,30,18,{bold:true,color:C.amber});
  addText(s,"세부 Ground Truth·KPI\n수동 대비 처리시간\n상태 정책·Matching 보강\nAI Master 05~07 최종 증적\n운영 UI 사용성·디자인 고도화\nDemo 캡처·영상",650,204,510,250,24,{bold:true});
  addRule(s,42,510,1156,C.rule,1);
  addText(s,"오늘 리뷰 질문",42,544,190,28,17,{bold:true,color:C.blue});
  addText(s,"① Core 범위가 충분한가?   ② 사용자 확인 정책이 적절한가?   ③ 운영 UI 우선순위는 무엇인가?",236,538,950,42,21,{bold:true});
  notes(s,"Core 마감을 최우선으로 하고, 일정이 남으면 테스트 Gmail Adapter를 검토한다. Outlook·사내 인프라는 Post-MVP 경계다.",["Docs/AI_MASTER/07_E2E서비스개발.md","Docs/IMPLEMENTATION/05_3단계_최종_E2E_구현범위.md"]);
}

await fs.mkdir("Docs/PRESENTATION",{recursive:true});
await fs.mkdir(RENDER_DIR,{recursive:true});
for (const [i,s] of p.slides.items.entries()) {
  const png=await p.export({slide:s,format:"png",scale:1});
  await fs.writeFile(`${RENDER_DIR}/slide-${String(i+1).padStart(2,"0")}.png`,new Uint8Array(await png.arrayBuffer()));
  const layout=await s.export({format:"layout"});
  await fs.writeFile(`${RENDER_DIR}/slide-${String(i+1).padStart(2,"0")}.layout.json`,await layout.text());
}
const montage=await p.export({format:"webp",montage:true,scale:1});
await fs.writeFile("tmp/presentation_build/montage.webp",new Uint8Array(await montage.arrayBuffer()));
const pptx=await PresentationFile.exportPptx(p);
await pptx.save(OUT);
