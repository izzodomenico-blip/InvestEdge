import { Component, type ReactNode } from "react";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MachineLearningPage } from "./MachineLearningPage";
vi.mock("recharts", () => {
 const Chart = ({children}:{children?: ReactNode}) => <div>{children}</div>;
 return Object.fromEntries(["PolarAngleAxis","RadialBar","RadialBarChart","ResponsiveContainer"].map(name=>[name,Chart]));
});
class Boundary extends Component<{children:ReactNode},{failed:boolean}> {
 state={failed:false}; static getDerivedStateFromError(){return {failed:true};}
 render(){return this.state.failed ? <p>PAGE_CRASHED</p> : this.props.children;}
}
const result = { model_id: 4, pipeline_version: "features-v1", data_mode: "REAL", training_run: null,
 metrics: {accuracy:null,f1_score:0,roc_auc:null,samples:null, top_features_positive:[{feature:"rsi_14",importance:1},{feature:"news_sentiment",importance:2}]},
 features_used:["rsi_14","volatility_30d"], warnings:[] };
const prediction = { id:1, symbol:"AAPL", model_id:4, pipeline_version:"features-v1",data_mode:"DEMO",
 horizon_days:14,target_type:"POSITIVE_RETURN",prediction_date:"2026-10-10",probability_positive:.63,
 probability_outperform:null,probability_drawdown:null,predicted_label:"POSITIVE",confidence:"MEDIUM",explanation:{},warnings:[] };
function job(status:string, overrides:Record<string,unknown>={}) {
 return {id:11,kind:"ML_TRAIN",status,params:{},progress:0,result:null,result_ref:null,error_code:null,
 error_message:null,cancel_requested:false,created_at:"2026-10-10",started_at:null,finished_at:null,...overrides};
}
function response(data:unknown,status=200){return new Response(JSON.stringify(data),{status,headers:{"Content-Type":"application/json"}});}
const fetchMock=vi.fn<typeof fetch>();
let handler:(path:string,init?:RequestInit)=>Response|Promise<Response>;
beforeEach(()=>{
 fetchMock.mockReset();
 handler=(path)=>{
  if(path==="/assets")return response([{id:1,symbol:"AAPL",name:"Apple"}]);
  if(path==="/ml/status")return response({models_count:1,latest_model:null,latest_training_run:null,
   available_targets:[],available_model_types:[],ml_ready:true,message:""});
  if(path==="/ml/train")return response(job("SUCCEEDED",{result,result_ref:"4"}),202);
  if(path==="/ml/predict/AAPL")return response(prediction);
  throw new Error("UNEXPECTED_OFFLINE_REQUEST "+path);
 };
 fetchMock.mockImplementation(async (input,init)=>handler(new URL(String(input)).pathname,init));
 vi.stubGlobal("fetch",fetchMock);vi.spyOn(console,"error").mockImplementation(()=>undefined);
});
afterEach(()=>{vi.useRealTimers();vi.unstubAllGlobals();});
async function mount(){const view=render(<Boundary><MachineLearningPage/></Boundary>);await screen.findByRole("button",{name:"Prevedi"});await flush();return view;}
async function flush(){await act(async()=>{for(let i=0;i<16;i++)await Promise.resolve();});}
async function tick(){await act(async()=>{await vi.advanceTimersByTimeAsync(1000);});}
function override(extra:typeof handler){const base=handler;handler=(p,i)=>p.startsWith("/lab/jobs")||p==="/ml/train"?extra(p,i):base(p,i);}
describe("ML su job offline",()=>{
 it("attende QUEUED/RUNNING/SUCCEEDED e protegge dal doppio avvio",async()=>{
  let polls=0;override(p=>p==="/ml/train"?response(job("QUEUED"),202):
   response(++polls===1?job("RUNNING",{progress:.25}):job("SUCCEEDED",{progress:1,result,result_ref:"4"})));
  await mount();vi.useFakeTimers();const submit=screen.getByRole("button",{name:"Addestra modello"});
  fireEvent.click(submit);fireEvent.click(submit);await flush();
  expect(screen.queryByText("PAGE_CRASHED")).not.toBeInTheDocument();
  expect(screen.getByText(/Accodato/)).toBeInTheDocument();await tick();expect(screen.getByText(/25%/)).toBeInTheDocument();
  await tick();expect(screen.getByText(/Pipeline: features-v1/)).toBeInTheDocument();
  expect(fetchMock.mock.calls.filter(([url])=>String(url).endsWith("/ml/train"))).toHaveLength(1);
  expect(JSON.parse(String(fetchMock.mock.calls.find(([url])=>String(url).endsWith("/ml/train"))![1]!.body)).data_mode).toBe("REAL");
 });
 it("conserva modalità e pipeline del risultato e non mostra feature news",async()=>{
  await mount();fireEvent.click(screen.getByRole("button",{name:"Addestra modello"}));await flush();
  fireEvent.change(screen.getByLabelText("Modalità training"),{target:{value:"DEMO"}});
  expect(screen.getByText(/Training salvato: REAL/)).toBeInTheDocument();
  expect(screen.getByText("rsi_14")).toBeInTheDocument();expect(screen.queryByText("news_sentiment")).not.toBeInTheDocument();
  const panel=within(screen.getByText("Performance del modello").closest("section")!);
  expect(panel.getAllByText("N/D").length).toBeGreaterThanOrEqual(3);expect(panel.getByText("0.000")).toBeInTheDocument();
 });
 it("invia DEMO esplicitamente senza trasformarlo in REAL",async()=>{
  await mount();fireEvent.change(screen.getByLabelText("Modalità training"),{target:{value:"DEMO"}});
  fireEvent.click(screen.getByRole("button",{name:"Addestra modello"}));await flush();
  expect(JSON.parse(String(fetchMock.mock.calls.find(([url])=>String(url).endsWith("/ml/train"))![1]!.body)).data_mode).toBe("DEMO");
 });
 it("gestisce 409 pipeline e cancella la previsione precedente",async()=>{
  await mount();fireEvent.click(screen.getByRole("button",{name:"Prevedi"}));await flush();expect(screen.getByText(/Previsione salvata: DEMO/)).toBeInTheDocument();
  const base=handler;handler=(p,i)=>p.startsWith("/ml/predict/")?response({detail:{reason_code:"MODEL_PIPELINE_MISMATCH",message:"vecchio"}},409):base(p,i);
  fireEvent.click(screen.getByRole("button",{name:"Prevedi"}));await flush();
  expect(screen.getByRole("alert")).toHaveTextContent("Modello creato con una pipeline precedente: riaddestralo.");
  expect(screen.queryByText(/Previsione salvata:/)).not.toBeInTheDocument();
 });
 it.each([["FAILED","Dati insufficienti",{error_code:"ML_INSUFFICIENT_DATA",error_message:"Dati insufficienti"}],
 ["CANCELLED","Elaborazione annullata",{}],["INTERRUPTED","Elaborazione interrotta",{}]])("gestisce %s",async(status,text,extras)=>{
  override(()=>response(job(status,extras),202));await mount();fireEvent.click(screen.getByRole("button",{name:"Addestra modello"}));await flush();
  expect(screen.queryByText("PAGE_CRASHED")).not.toBeInTheDocument();expect(screen.getByRole("alert")).toHaveTextContent(text);
  expect(screen.getByRole("button",{name:"Addestra modello"})).toBeEnabled();
 });
 it("rifiuta SUCCEEDED senza risultato inline",async()=>{
  override(()=>response(job("SUCCEEDED",{result_ref:"4"}),202));await mount();fireEvent.click(screen.getByRole("button",{name:"Addestra modello"}));await flush();
  expect(screen.getByRole("alert")).toBeInTheDocument();expect(screen.queryByText("PAGE_CRASHED")).not.toBeInTheDocument();
 });
 it("rende errore polling e permette un nuovo training",async()=>{
  override(p=>p==="/ml/train"?response(job("QUEUED"),202):response({detail:"Polling offline fallito"},500));
  await mount();vi.useFakeTimers();fireEvent.click(screen.getByRole("button",{name:"Addestra modello"}));await flush();await tick();
  expect(screen.getByRole("alert")).toHaveTextContent("Polling offline fallito");
  expect(screen.getByRole("button",{name:"Addestra modello"})).toBeEnabled();
 });
 it("annulla cooperativamente e attende lo stato terminale",async()=>{
  let cancelled=false;override(p=>p==="/ml/train"?response(job("QUEUED"),202):
   p.endsWith("/cancel")?(cancelled=true,response(job("RUNNING",{cancel_requested:true}))):response(job(cancelled?"CANCELLED":"RUNNING")));
  await mount();vi.useFakeTimers();fireEvent.click(screen.getByRole("button",{name:"Addestra modello"}));await flush();
  fireEvent.click(screen.getByRole("button",{name:"Annulla training"}));await flush();
  expect(screen.getByText(/Annullamento richiesto/)).toBeInTheDocument();await tick();
  expect(screen.getByRole("alert")).toHaveTextContent("Elaborazione annullata");
 });
 it("accetta completamento durante annullamento 409",async()=>{
  let done=false;override(p=>p==="/ml/train"?response(job("QUEUED"),202):
   p.endsWith("/cancel")?(done=true,response({detail:{reason_code:"JOB_NOT_CANCELLABLE",message:"Finito"}},409)):
   response(done?job("SUCCEEDED",{result,result_ref:"4"}):job("RUNNING")));
  await mount();vi.useFakeTimers();fireEvent.click(screen.getByRole("button",{name:"Addestra modello"}));await flush();
  fireEvent.click(screen.getByRole("button",{name:"Annulla training"}));await flush();await tick();
  expect(screen.getByText(/Training salvato: REAL/)).toBeInTheDocument();expect(screen.queryByRole("alert")).not.toBeInTheDocument();
 });
 it.each(["POST","GET"])("aborta %s allo smontaggio senza annullare il job server",async(method)=>{
  let resolve!:(r:Response)=>void;
  override(p=>p==="/ml/train"&&method==="GET"?response(job("QUEUED"),202):new Promise(r=>{resolve=r;}));
  const view=await mount();vi.useFakeTimers();fireEvent.click(screen.getByRole("button",{name:"Addestra modello"}));await flush();
  if(method==="GET")await tick();view.unmount();
  const call=fetchMock.mock.calls.filter(([,init])=>(init?.method??"GET")===method).at(-1)!;expect(call[1]?.signal?.aborted).toBe(true);
  await act(async()=>resolve(response(job("SUCCEEDED",{result,result_ref:"4"}))));
  expect(fetchMock.mock.calls.filter(([url])=>String(url).endsWith("/cancel"))).toHaveLength(0);
 });
 it("aborta previsione allo smontaggio",async()=>{
  let resolve!:(r:Response)=>void;const base=handler;handler=(p,i)=>p.startsWith("/ml/predict/")?new Promise(r=>{resolve=r;}):base(p,i);
  const view=await mount();fireEvent.click(screen.getByRole("button",{name:"Prevedi"}));await flush();view.unmount();
  expect(fetchMock.mock.calls.find(([url])=>String(url).includes("/ml/predict/"))![1]?.signal?.aborted).toBe(true);
  await act(async()=>resolve(response(prediction)));
 });
});

describe("ML: risposte tardive e recupero",()=>{
 it("ignora una risposta cancel tardiva dopo l'avvio di un nuovo job",async()=>{
  let cancelResolve!:(r:Response)=>void;let starts=0;
  override(p=>p==="/ml/train"?response(job("QUEUED",{id:++starts===1?11:12}),202):
    p.endsWith("/cancel")?new Promise(r=>{cancelResolve=r;}):
    p.endsWith("/11")?response(job("SUCCEEDED",{result,result_ref:"4"})):
    response(job("RUNNING",{id:12,progress:.2})));
  await mount();vi.useFakeTimers();fireEvent.click(screen.getByRole("button",{name:"Addestra modello"}));await flush();
  fireEvent.click(screen.getByRole("button",{name:"Annulla training"}));await flush();await tick();
  fireEvent.click(screen.getByRole("button",{name:"Addestra modello"}));await flush();
  await act(async()=>cancelResolve(response(job("CANCELLED"))));
  expect(screen.getByText(/Accodato/)).toBeInTheDocument();expect(screen.getByRole("button",{name:"Annulla training"})).toBeEnabled();
  await tick();expect(screen.getByText(/20%/)).toBeInTheDocument();
 });
 it("un errore cancel permette di riprovare mentre il job continua",async()=>{
  override(p=>p==="/ml/train"?response(job("QUEUED"),202):p.endsWith("/cancel")?
    response({detail:"Cancel temporaneamente fallito"},500):response(job("RUNNING",{progress:.3})));
  await mount();vi.useFakeTimers();fireEvent.click(screen.getByRole("button",{name:"Addestra modello"}));await flush();
  fireEvent.click(screen.getByRole("button",{name:"Annulla training"}));await flush();
  expect(screen.getByRole("alert")).toHaveTextContent("Cancel temporaneamente fallito");
  expect(screen.getByRole("button",{name:"Annulla training"})).toBeEnabled();await tick();expect(screen.getByText(/30%/)).toBeInTheDocument();
 });
 it("conserva training salvato quando il refresh status fallisce",async()=>{
  let statusCalls=0;const base=handler;handler=(p,i)=>p==="/ml/status"&&++statusCalls>1?
   response({detail:"Stato offline"},500):base(p,i);
  await mount();fireEvent.click(screen.getByRole("button",{name:"Addestra modello"}));await flush();
  expect(screen.getByText(/Training salvato: REAL/)).toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent("Training salvato, ma lo stato ML non è aggiornato");
 });
 it("impedisce horizon non valido prima del POST",async()=>{
  await mount();fireEvent.change(screen.getByLabelText("Orizzonte (sedute)"),{target:{value:"0"}});
  fireEvent.click(screen.getByRole("button",{name:"Addestra modello"}));await flush();
  expect(screen.getByRole("alert")).toHaveTextContent("Orizzonte non valido");
  expect(fetchMock.mock.calls.filter(([u])=>String(u).endsWith("/ml/train"))).toHaveLength(0);
 });
});

it("una risposta status iniziale tardiva non sovrascrive il modello appena salvato",async()=>{
 let resolve!:(r:Response)=>void;let count=0;const base=handler;
 handler=(p,i)=>p==="/ml/status"&&++count===1?new Promise(r=>{resolve=r;}):base(p,i);
 await mount();fireEvent.click(screen.getByRole("button",{name:"Addestra modello"}));await flush();
 expect(screen.getByRole("button",{name:"Prevedi"})).toBeEnabled();
 await act(async()=>resolve(response({models_count:0,ml_ready:false,message:"vuoto",latest_model:null,latest_training_run:null,available_targets:[],available_model_types:[]})));
 expect(screen.getByRole("button",{name:"Prevedi"})).toBeEnabled();
 expect(screen.queryByText("Addestra prima un modello.")).not.toBeInTheDocument();
});

it("il refresh sceglie un asset disponibile anche se lo stato iniziale è ancora in attesa",async()=>{
 let resolve!:(r:Response)=>void;let count=0;const base=handler;
 handler=(p,i)=>p==="/ml/status"&&++count===1?new Promise(r=>{resolve=r;}):
   p==="/assets"?response([{id:2,symbol:"MSFT",name:"Microsoft"}]):
   p==="/ml/predict/MSFT"?response({...prediction,symbol:"MSFT"}):base(p,i);
 await mount();fireEvent.click(screen.getByRole("button",{name:"Addestra modello"}));await flush();
 fireEvent.click(screen.getByRole("button",{name:"Prevedi"}));await flush();
 expect(fetchMock.mock.calls.filter(([u])=>String(u).endsWith("/ml/predict/MSFT"))).toHaveLength(1);
 expect(fetchMock.mock.calls.filter(([u])=>String(u).endsWith("/ml/predict/AAPL"))).toHaveLength(0);
 await act(async()=>resolve(response({models_count:0,ml_ready:false,message:"",available_targets:[],available_model_types:[]})));
 expect(screen.getByLabelText("Asset da prevedere")).toHaveValue("MSFT");
});
