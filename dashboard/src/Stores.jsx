import React, {useEffect, useState} from 'react';

export default function Stores({req}) {
  const [stores, setStores] = useState([]), [name, setName] = useState('');
  const [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const [requestId, setRequestId] = useState(() => sessionStorage.getItem('store-request-id') || (globalThis.crypto?.randomUUID?.() ?? ("req-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2))));
  async function refresh() {
    try { setStores(await req('/stores')); } catch (e) { setError(e.message); }
  }
  useEffect(() => { refresh(); const id = setInterval(refresh, 5000); return () => clearInterval(id); }, []);
  async function create(e) {
    e.preventDefault(); setBusy(true); setError('');
    sessionStorage.setItem('store-request-id', requestId);
    try {
      await req('/stores', {method:'POST', body: JSON.stringify({name, request_id:requestId})});
      setName(''); const next = (globalThis.crypto?.randomUUID?.() ?? ("req-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2))); setRequestId(next); sessionStorage.setItem('store-request-id', next);
      await refresh();
    } catch(e) {setError(e.message);} finally {setBusy(false);}
  }
  async function action(s, retry=false) {
    if (!retry && !confirm(`Permanently delete ${s.name}, its orders and volumes?`)) return;
    try { setError(''); await req(`/stores/${s.id}${retry?'/retry':''}`, {method:retry?'POST':'DELETE'}); await refresh(); }
    catch(e) {setError(e.message);}
  }
  return <>
    <p className="muted">Create independent WooCommerce stores. Each store receives its own database, storage and MCP tools. Status refreshes every five seconds.</p>
    {error && <div className="alert">{error}</div>}
    <form className="panel add" onSubmit={create}>
      <input aria-label="Store name" placeholder="Store name, e.g. North Store" value={name} onChange={e=>setName(e.target.value)} required maxLength={100}/>
      <button disabled={busy}>{busy?'Queuing…':'Create store'}</button>
    </form>
    <div className="panel table">{stores.length ? stores.map(s=><div className="row" key={s.id}>
      <div className="grow"><b>{s.name}</b><small>{s.phase} · {new Date(s.created_at).toLocaleString()}</small>
        <small>Tools: store-{s.id}__*</small>
        {s.status==='Ready' && <a href={s.url} target="_blank" rel="noreferrer">Open storefront ↗</a>}
        {s.error && <p className="alert">{s.error}</p>}
      </div>
      <span className={`badge ${s.status==='Ready'?'on':'off'}`}>{s.status}</span>
      {s.status==='Failed' && <button onClick={()=>action(s,true)}>Retry</button>}
      {s.status!=='Deleting' && <button className="ghost" onClick={()=>action(s)}>Delete</button>}
    </div>) : <p className="muted">No stores yet. Create your first store above.</p>}</div>
  </>;
}
