import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Bell, Car, MagnifyingGlass, SidebarSimple, User, Timer, CheckSquareOffset } from "@phosphor-icons/react";
import api from "@/lib/api";
import { t } from "@/lib/textos";

// Barra do topo: recolher o menu, a busca de tudo (contato e carro) e o sino.
// A busca usa as mesmas rotas das telas (`/contacts?q=`, `/estoque/veiculos?q=`),
// então acha o que a tela acharia, com as mesmas permissões.
function BuscaGlobal() {
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [res, setRes] = useState({ contatos: [], veiculos: [] });
  const [aberto, setAberto] = useState(false);
  const [sel, setSel] = useState(0);
  const caixa = useRef(null);
  const campo = useRef(null);

  // Ctrl+K (ou Cmd+K) põe o cursor na busca de qualquer tela.
  useEffect(() => {
    const atalho = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        campo.current?.focus();
      }
    };
    const fora = (e) => { if (caixa.current && !caixa.current.contains(e.target)) setAberto(false); };
    window.addEventListener("keydown", atalho);
    document.addEventListener("mousedown", fora);
    return () => { window.removeEventListener("keydown", atalho); document.removeEventListener("mousedown", fora); };
  }, []);

  useEffect(() => {
    const termo = q.trim();
    if (termo.length < 2) { setRes({ contatos: [], veiculos: [] }); return undefined; }
    const id = setTimeout(async () => {
      const [c, v] = await Promise.allSettled([
        api.get("/contacts", { params: { q: termo, limit: 5 } }),
        api.get("/estoque/veiculos", { params: { q: termo } }),
      ]);
      setRes({
        contatos: c.status === "fulfilled" ? (c.value.data.items || []).slice(0, 5) : [],
        veiculos: v.status === "fulfilled" ? (v.value.data || []).slice(0, 5) : [],
      });
      setSel(0);
    }, 250);
    return () => clearTimeout(id);
  }, [q]);

  const itens = [
    ...res.contatos.map((c) => ({
      id: `c-${c.id}`, icone: User, titulo: c.nome || c.numero_whatsapp, detalhe: c.numero_whatsapp,
      ir: `/app/contacts?contato=${c.id}`,
    })),
    ...res.veiculos.map((v) => ({
      id: `v-${v.id}`, icone: Car,
      titulo: [v.marca, v.modelo, v.versao, v.ano_modelo].filter(Boolean).join(" "), detalhe: v.placa,
      ir: `/app/estoque?veiculo=${v.id}`,
    })),
  ];

  const ir = (item) => {
    if (!item) return;
    setAberto(false);
    setQ("");
    navigate(item.ir);
  };

  return (
    <div className="zz-busca-global" ref={caixa}>
      <MagnifyingGlass size={15} />
      <input ref={campo} className="zz-input h-9 text-sm" value={q}
        placeholder={`Buscar ${t("contato")}, telefone ou carro…  (Ctrl+K)`}
        onFocus={() => setAberto(true)}
        onChange={(e) => { setQ(e.target.value); setAberto(true); }}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") { e.preventDefault(); setSel((s) => Math.min(s + 1, itens.length - 1)); }
          else if (e.key === "ArrowUp") { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)); }
          else if (e.key === "Enter") ir(itens[sel]);
          else if (e.key === "Escape") { setAberto(false); e.currentTarget.blur(); }
        }}
        aria-label="Busca geral" data-testid="busca-global" />
      {aberto && q.trim().length >= 2 && (
        <div className="zz-busca-lista" role="listbox">
          {itens.length === 0 && <div className="px-3 py-2 text-xs text-ink-3">Nada encontrado</div>}
          {itens.map((item, i) => {
            const Icone = item.icone;
            return (
              <button key={item.id} type="button" role="option" aria-selected={i === sel}
                className="zz-busca-item" onMouseEnter={() => setSel(i)} onClick={() => ir(item)}>
                <Icone size={15} className="text-ink-3 shrink-0" />
                <span className="truncate flex-1">{item.titulo}</span>
                {item.detalhe && <span className="font-mono text-[11px] text-ink-3 shrink-0">{item.detalhe}</span>}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

// O sino junta o que pede ação agora: fila esperando e atividades atrasadas.
// Os números são os mesmos dos selos do menu (mesmos hooks, no AppShell).
function Sino({ aguardando, atrasadas }) {
  const navigate = useNavigate();
  const [aberto, setAberto] = useState(false);
  const caixa = useRef(null);
  useEffect(() => {
    const fora = (e) => { if (caixa.current && !caixa.current.contains(e.target)) setAberto(false); };
    document.addEventListener("mousedown", fora);
    return () => document.removeEventListener("mousedown", fora);
  }, []);
  const total = (aguardando || 0) + (atrasadas || 0);
  const ir = (para) => { setAberto(false); navigate(para); };
  return (
    <div className="relative" ref={caixa}>
      <button type="button" className="zz-btn-icon relative" onClick={() => setAberto((a) => !a)}
        aria-label={`Avisos${total ? `: ${total}` : ""}`} data-testid="sino">
        <Bell size={17} />
        {total > 0 && <span className="zz-sino-ponto">{total > 99 ? "99+" : total}</span>}
      </button>
      {aberto && (
        <div className="zz-busca-lista !left-auto right-0 w-72">
          {total === 0 && <div className="px-3 py-3 text-sm text-ink-3">Tudo em dia.</div>}
          {aguardando > 0 && (
            <button type="button" className="zz-busca-item" onClick={() => ir("/app/inbox")}>
              <Timer size={15} className="text-warning shrink-0" />
              <span className="flex-1">{aguardando} conversa{aguardando > 1 ? "s" : ""} aguardando atendimento</span>
            </button>
          )}
          {atrasadas > 0 && (
            <button type="button" className="zz-busca-item" onClick={() => ir("/app/atividades")}>
              <CheckSquareOffset size={15} className="text-danger shrink-0" />
              <span className="flex-1">{atrasadas} {t("atividade")}{atrasadas > 1 ? "s" : ""} atrasada{atrasadas > 1 ? "s" : ""}</span>
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export default function BarraTopo({ recolhida, onAlternar, aguardando, atrasadas, comBusca = true }) {
  return (
    <header className="zz-topo" data-testid="barra-topo">
      <button type="button" className="zz-btn-icon" onClick={onAlternar}
        aria-label={recolhida ? "Abrir o menu" : "Recolher o menu"} aria-pressed={recolhida}
        title={recolhida ? "Abrir o menu" : "Recolher o menu"} data-testid="menu-recolher">
        <SidebarSimple size={17} />
      </button>
      {comBusca ? <BuscaGlobal /> : <div className="flex-1" />}
      <div className="ml-auto flex items-center gap-2">
        <Sino aguardando={aguardando} atrasadas={atrasadas} />
      </div>
    </header>
  );
}
