import { type ReactNode } from "react";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach,beforeEach,describe,expect,it,vi } from "vitest";
import { AnalysisPage } from "./AnalysisPage";
import { WatchlistPage } from "./WatchlistPage";
import { DashboardPage } from "./DashboardPage";
import { TodayPage } from "./TodayPage";
vi.mock("recharts",()=>{const Chart=({children}:{children?:ReactNode})=><div>{children}</div>;
 return Object.fromEntries(["Area","AreaChart","Bar","BarChart","Cell","Pie","PieChart","Line","LineChart","ResponsiveContainer","Tooltip","XAxis","YAxis"].map(n=>[n,Chart]));});
vi.mock("../components/TradeButton",()=>({TradeButton:()=>null}));
const assets=[{id:1,symbol:"AAPL",name:"Apple",currency:"USD",asset_type:"stock",risk_level:"medium",score:65,signal:"HOLD",signal_data_mode:"DEMO",is_real_data:true},
 {id:2,symbol:"MSFT",name:"Microsoft",currency:"USD",asset_type:"stock",risk_level:"medium",score:70,signal:"BUY",signal_data_mode:"REAL",is_real_data:false}];
const summary={id:21,job_id:11,signal_name:"score",timeframe:"D",horizon:5,verdict:"VALIDATO",fingerprint:"f",created_at:"2026-10-10T10:00:00Z"};
const latest={signal_name:"score",timeframe:"D",best:summary,horizons:{"1":null,"5":summary,"21":null}};
const signals=[{id:1,symbol:"AAPL",score:65,signal:"HOLD",technical_summary:"Segnale AAPL",data_mode:"REAL"},
 {id:2,symbol:"MSFT",score:70,signal:"BUY",technical_summary:"Segnale MSFT",data_mode:"DEMO"}];
const dashboard={initialized:true,assets_count:2,positions_count:0,signals_count:2,portfolio_value:10000,cash:10000,total_pnl:0,total_pnl_percent:0,
 data_status:{data_mode:"REAL",enable_real_data:true,provider_status:[],global_last_update:null},market_news_summary:{},latest_high_impact_news:[],
 signal_breakdown:{},asset_type_breakdown:{},top_position:null,risk_warnings_count:0,portfolio_snapshots:[],latest_backtest:null,
 top_assets:assets,risky_assets:[],latest_signals:signals};
const actions=[{type:"WATCH",symbol:"AAPL",title:"Osserva AAPL",reason:"Locale",priority:"LOW",score:65,data_mode:"REAL"},
 {type:"WATCH",symbol:"MSFT",title:"Osserva MSFT",reason:"Locale",priority:"LOW",score:70,data_mode:"DEMO"}];
function analysis(symbol:string){return {asset:assets.find(a=>a.symbol===symbol),score:65,technical_score:65,final_score:65,news_score:3,
 indicators:{},conditions:{},support_resistance:{},subscores:{},signal:"HOLD",risk_level:"medium",confidence:"media",reasons:[],summaries:{},
 technical_summary:"Analisi di "+symbol,data_mode:symbol==="AAPL"?"REAL":"DEMO"};}
function response(data:unknown,status=200){return new Response(JSON.stringify(data),{status,headers:{"Content-Type":"application/json"}});}
const fetchMock=vi.fn<typeof fetch>();
let handler:(path:string)=>Response|Promise<Response>;
beforeEach(()=>{
 fetchMock.mockReset();handler=p=>{
  if(p==="/lab/evidence/latest?signal_name=score&timeframe=D")return response(latest);
  if(p==="/assets")return response(assets);if(p==="/portfolio/recommendations")return response([]);
  if(p==="/dashboard")return response(dashboard);
  if(p==="/action-board")return response({data_mode:"REAL",headline:"Azioni locali",counts:{},actions});
  if(p==="/alerts/status")return response({enabled:false,configured:false,channel:"telegram"});
  if(p.startsWith("/technical-analysis/"))return response(analysis(p.split("/").at(-1)!));
  if(p.startsWith("/prices/"))return response({symbol:p.split("/").at(-1),currency:"USD",prices:[]});
  if(p==="/news/status")return response({enable_real_news:false});
  if(p.startsWith("/news/sentiment/"))return response({latest_news:[]});
  throw new Error("UNEXPECTED_OFFLINE_REQUEST "+p);
 };
 fetchMock.mockImplementation(async input=>{const u=new URL(String(input));return handler(u.pathname+u.search);});vi.stubGlobal("fetch",fetchMock);
});
afterEach(()=>vi.unstubAllGlobals());
function mount(page:ReactNode){return render(<MemoryRouter initialEntries={["/analysis?symbol=AAPL"]}>{page}</MemoryRouter>);}
function oneRequest(){expect(fetchMock.mock.calls.filter(([u])=>String(u).includes("/lab/evidence/latest"))).toHaveLength(1);}
async function flush(){await act(async()=>{for(let i=0;i<15;i++)await Promise.resolve();});}
describe("Posizioni Evidenza e origine record",()=>{
 it("Analisi: badge accanto allo score; cambia simbolo senza nuova richiesta",async()=>{
  mount(<AnalysisPage/>);await screen.findByText("Analisi di AAPL");
  const score=screen.getByText("Score tecnico").closest("article")!;
  expect(within(score).getByText("VALIDATO · 5g")).toBeInTheDocument();
  expect(within(score).queryByText(/DEMO/)).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole("combobox"),{target:{value:"MSFT"}});await screen.findByText("Analisi di MSFT");
  expect(within(screen.getByText("Score tecnico").closest("article")!).getByText("DEMO · non misurabile")).toBeInTheDocument();oneRequest();
 });
 it("Watchlist: badge nel header score, marker dall'origine del segnale",async()=>{
  mount(<WatchlistPage/>);await screen.findByText("VALIDATO · 5g");
  expect(within(screen.getByRole("heading",{name:"Score"}).parentElement!).getByText("VALIDATO · 5g")).toBeInTheDocument();
  const cards=screen.getAllByRole("button").filter(e=>e.textContent?.includes("Apple")||e.textContent?.includes("Microsoft"));
  expect(within(cards.find(e=>e.textContent?.includes("Apple"))!).getByText("DEMO")).toBeInTheDocument();
  expect(within(cards.find(e=>e.textContent?.includes("Microsoft"))!).queryByText("DEMO")).not.toBeInTheDocument();oneRequest();
 });
 it("Dashboard: tre badge header condividono una richiesta; marker seguono il record",async()=>{
  mount(<DashboardPage/>);await screen.findAllByText("VALIDATO · 5g");
  for(const title of ["Top score asset","Segnali recenti","Top 5 asset per score"]){
   const panel=screen.getByRole("heading",{name:title}).closest("section")!;
   expect(within(panel.querySelector("header")!).getByText("VALIDATO · 5g")).toBeInTheDocument();
  }
  const recent=screen.getByRole("heading",{name:"Segnali recenti"}).closest("section")!;
  expect(within(within(recent).getByText("AAPL").closest("article")!).queryByText("DEMO")).not.toBeInTheDocument();
  expect(within(within(recent).getByText("MSFT").closest("article")!).getByText("DEMO")).toBeInTheDocument();
  const top=screen.getByRole("heading",{name:"Top 5 asset per score"}).closest("section")!;
  expect(within(top).getAllByText("DEMO")).toHaveLength(1);
  fireEvent.click(screen.getByRole("button",{name:"Aggiorna"}));await flush();oneRequest();
 });
 it("Oggi: badge header azioni e marker dal modo azione, senza invii esterni",async()=>{
  mount(<TodayPage/>);await screen.findByText("VALIDATO · 5g");
  expect(within(screen.getByRole("heading",{name:"Azioni di oggi"}).parentElement!).getByText("VALIDATO · 5g")).toBeInTheDocument();
  expect(within(screen.getByText("Osserva AAPL").closest("article")!).queryByText("DEMO")).not.toBeInTheDocument();
  expect(within(screen.getByText("Osserva MSFT").closest("article")!).getByText("DEMO")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button",{name:"Analizza oggi"}));await flush();oneRequest();
  expect(fetchMock.mock.calls.filter(([,init])=>init?.method==="POST")).toHaveLength(0);
 });
 it("errore evidenza non nasconde lo score e non finge un report assente",async()=>{
  const base=handler;handler=p=>p.startsWith("/lab/evidence/latest")?response({detail:"Report non raggiungibile"},500):base(p);
  mount(<AnalysisPage/>);await screen.findByText("Analisi di AAPL");await flush();
  expect(screen.getByText("EVIDENZA NON DISPONIBILE")).toBeInTheDocument();
  expect(screen.getAllByText("65.0/100").length).toBeGreaterThan(0);oneRequest();
 });
 it("aborta latest allo smontaggio e scarta la risposta tardiva",async()=>{
  let resolve!:(r:Response)=>void;const base=handler;handler=p=>p.startsWith("/lab/evidence/latest")?new Promise(r=>{resolve=r;}):base(p);
  const view=mount(<AnalysisPage/>);await screen.findByText("Analisi di AAPL");view.unmount();
  expect(fetchMock.mock.calls.find(([u])=>String(u).includes("/lab/evidence/latest"))![1]?.signal?.aborted).toBe(true);
  await act(async()=>resolve(response(latest)));
 });
});
