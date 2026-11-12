import {useEffect,useMemo,useState} from "react";
const get=u=>fetch(u).then(r=>r.json());
const MAIN={QB:["attempts","completions","passing_yards","passing_tds","rushing_yards"],RB:["carries","rushing_yards","targets","receptions","receiving_yards"],
  WR:["targets","receptions","receiving_yards","receiving_tds"],TE:["targets","receptions","receiving_yards","receiving_tds"]};
const avg=(rows,c)=>rows.length?(rows.reduce((a,r)=>a+(r[c]||0),0)/rows.length).toFixed(1):"–";
function Table({rows,cols,first,label}){
  return <div className="t"><table><thead><tr><th>{label}</th>{cols.map(c=><th key={c}>{c.replace("_"," ")}</th>)}</tr></thead><tbody>
    {rows.map((r,i)=><tr key={i}><td>{first(r)}</td>{cols.map(c=><td key={c}>{r[c]}</td>)}</tr>)}
    <tr className="avg"><td>Średnia ({rows.length})</td>{cols.map(c=><td key={c}>{avg(rows,c)}</td>)}</tr></tbody></table></div>;
}
export default function App(){
  const [players,setPlayers]=useState([]),[q,setQ]=useState(""),[p,setP]=useState(null),[log,setLog]=useState([]),[opp,setOpp]=useState(""),[def,setDef]=useState(null);
  useEffect(()=>{get("/data/players.json").then(setPlayers)},[]);
  useEffect(()=>{if(p)get(`/data/logs/${p.player_id}.json`).then(setLog)},[p]);
  useEffect(()=>{if(opp)get(`/data/defense/${opp}.json`).then(setDef);else setDef(null)},[opp]);
  const teams=useMemo(()=>[...new Set(players.map(x=>x.team))].sort(),[players]);
  const found=useMemo(()=>q.length<2?[]:players.filter(x=>x.name.toLowerCase().includes(q.toLowerCase())).slice(0,8),[q,players]);
  const cols=p?MAIN[p.pos]:[];
  const vsOpp=log.filter(r=>r.opponent_team===opp);
  const others=def?def.recent.filter(r=>r.position===p?.pos&&r.player_display_name!==p?.name):[];
  return <main>
    <h1>NFL Edge</h1>
    <input placeholder="Szukaj zawodnika (min. 2 litery)" value={q} onChange={e=>setQ(e.target.value)} aria-label="Szukaj zawodnika"/>
    <select value={opp} onChange={e=>setOpp(e.target.value)} aria-label="Obrona przeciwnika"><option value="">Wybierz obronę przeciwnika</option>{teams.map(t=><option key={t}>{t}</option>)}</select>
    <div>{found.map(x=><button key={x.player_id} onClick={()=>{setP(x);setQ("")}} style={{marginRight:6,marginBottom:6}}>{x.name} <span className="mu">{x.pos} {x.team}</span></button>)}</div>
    {!p&&<p className="mu">Wyszukaj zawodnika, aby zobaczyć log meczów.</p>}
    {p&&<><h2>{p.name} – log meczów</h2>
      <Table rows={[...log].reverse()} cols={cols} label="Mecz" first={r=>`${r.season} T${r.week} vs ${r.opponent_team}`}/></>}
    {p&&opp&&<><h2>{p.name} przeciwko {opp} (historia)</h2>
      {vsOpp.length?<Table rows={vsOpp} cols={cols} label="Mecz" first={r=>`${r.season} T${r.week}`}/>:<p className="mu">Brak meczów przeciwko {opp} w pobranych sezonach.</p>}</>}
    {p&&def&&<><h2>Obrona {opp} – średnio oddaje pozycji {p.pos} (ostatnie 8 meczów)</h2>
      <Table rows={[def.allowed[p.pos]||{}]} cols={cols} label="Na mecz" first={()=>"Suma pozycji"}/>
      <h2>Inni {p.pos} przeciwko {opp}</h2>
      <Table rows={others} cols={cols} label="Zawodnik" first={r=>`${r.player_display_name} (T${r.week})`}/></>}
  </main>;
}
