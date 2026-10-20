export function KpiGrid({items}:{items:{label:string;value:string;note?:string}[]}){
  return <div className="metric-grid">{items.map(item=><section className="metric-card" key={item.label}><h2>{item.label}</h2><p className="metric-value">{item.value}</p>{item.note&&<p className="metric-caption">{item.note}</p>}</section>)}</div>
}
