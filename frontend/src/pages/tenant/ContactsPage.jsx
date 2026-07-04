import { useEffect, useState } from "react";
import api from "@/lib/api";

export default function ContactsPage() {
  const [contacts, setContacts] = useState([]);
  useEffect(() => { api.get("/contacts").then((r) => setContacts(r.data)); }, []);

  return (
    <div className="p-8" data-testid="contacts-page">
      <div className="mb-8">
        <div className="text-[10px] font-bold tracking-[0.25em] uppercase text-slate-500 mb-2">Base</div>
        <h1 className="font-heading text-4xl font-black tracking-tighter">Contatos</h1>
      </div>

      {contacts.length === 0 ? (
        <div className="border border-dashed border-slate-300 bg-white p-16 text-center">
          <div className="font-heading text-2xl font-black tracking-tighter mb-2">Nenhum contato ainda.</div>
          <div className="text-sm text-slate-600">Contatos serão criados automaticamente quando alguém enviar a primeira mensagem.</div>
        </div>
      ) : (
        <div className="border border-slate-200 bg-white">
          <div className="grid grid-cols-12 px-4 py-2 border-b border-slate-200 text-[10px] font-bold uppercase tracking-wider text-slate-500">
            <div className="col-span-4">Nome</div>
            <div className="col-span-4">Número</div>
            <div className="col-span-4">Adicionado</div>
          </div>
          {contacts.map((c) => (
            <div key={c.id} className="grid grid-cols-12 px-4 py-3 border-b border-slate-100 hover:bg-slate-50" data-testid={`contact-${c.id}`}>
              <div className="col-span-4 font-semibold">{c.nome}</div>
              <div className="col-span-4 font-mono text-sm text-slate-700">{c.numero_whatsapp}</div>
              <div className="col-span-4 text-xs text-slate-500 font-mono">{new Date(c.created_at).toLocaleString("pt-BR")}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
