import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import api from "@/lib/api";
import Modal from "@/components/ui/Modal";
import { useAcao } from "@/hooks/useAcao";
import { confirmToast } from "@/lib/confirm-toast";
import { formatBRL } from "@/lib/currency";
import { MARCAS, valida as validaMarca } from "@/lib/marca";
import { rotuloPapel } from "@/lib/papeis";
import { haQuanto, plural } from "@/components/painel/Indicadores";
import { rotuloDoProblema } from "@/components/superadmin/comum";
import {
  Copy, PauseCircle, PlayCircle, SignIn, Trash, WhatsappLogo,
} from "@phosphor-icons/react";

/**
 * A ficha de uma empresa para o super admin.
 *
 * O que antes exigia entrar na empresa em modo suporte para descobrir: o email
 * de quem administra (a pergunta mais comum do suporte), as conexões e o
 * estado de cada uma, e o uso do plano, pela mesma conta que o cliente vê em
 * Ajustes. Plano, marca, suspensão e exclusão também moram aqui, em vez de
 * selects soltos em cada linha da lista.
 */

async function copiar(texto) {
  try {
    await navigator.clipboard.writeText(texto);
    toast.success("Copiado");
  } catch {
    toast.error("Não foi possível copiar. Selecione o texto e copie à mão.");
  }
}

function Secao({ titulo, children, acao }) {
  return (
    <section>
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-xs font-bold uppercase tracking-wider text-ink-3">{titulo}</h3>
        {acao}
      </div>
      {children}
    </section>
  );
}

function LinhaUso({ linha }) {
  const { usado, limite, label, janela } = linha;
  const ilimitado = limite === null || limite === undefined;
  const pct = ilimitado ? 0 : Math.min(100, Math.round((usado / limite) * 100));
  const estourou = !ilimitado && usado > limite;
  const cheio = !ilimitado && usado >= limite;
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <span>{label}{janela && <span className="text-ink-3 text-xs"> · no {janela}</span>}</span>
        <span className={`font-mono text-xs ${estourou ? "text-danger font-bold" : "text-ink-2"}`}>
          {usado.toLocaleString("pt-BR")}{" "}
          <span className="text-ink-3">{ilimitado ? "· ilimitado" : `de ${limite.toLocaleString("pt-BR")}`}</span>
        </span>
      </div>
      {!ilimitado && (
        <div className="h-1.5 mt-1 bg-surface-3 rounded-full overflow-hidden">
          <div className={`h-full ${cheio ? "bg-danger" : pct >= 80 ? "bg-warning" : "bg-brand"}`}
            style={{ width: `${pct}%` }} />
        </div>
      )}
    </div>
  );
}

export default function EmpresaDetalhe({ id, plans, onFechar, onMudou, entrar, entrando }) {
  const [e, setE] = useState(null);

  const carregar = useCallback(
    () => api.get(`/admin/tenants/${id}`).then((r) => setE(r.data))
      .catch(() => toast.error("Não foi possível carregar a empresa")),
    [id],
  );
  useEffect(() => { carregar(); }, [carregar]);

  const [mudar, mudando] = useAcao(async (campos, aviso) => {
    try {
      const { data } = await api.patch(`/admin/tenants/${id}`, campos);
      if (data.plan_warnings?.length) {
        toast.warning(`Plano alterado, mas a empresa está acima do limite: ${data.plan_warnings.join(" · ")}`,
          { duration: 8000 });
      } else {
        toast.success(aviso);
      }
      await carregar();
      onMudou();
    } catch (ex) {
      toast.error(ex.response?.data?.detail || "Não foi possível salvar");
    }
  });

  const [excluir, excluindo] = useAcao(async () => {
    if (!(await confirmToast(`Excluir ${e.name} e TODOS os dados vinculados? Não há como desfazer.`,
      { confirmLabel: "Excluir tudo" }))) return;
    const { data } = await api.delete(`/admin/tenants/${id}`);
    // A exclusão não deixa rastro depois de rodar: o total é a única conferência.
    const n = Object.values(data?.apagados || {}).reduce((a, b) => a + b, 0);
    toast.success(n ? `Empresa excluída, ${n} registros removidos` : "Empresa excluída");
    onMudou();
    onFechar();
  });

  if (!e) {
    return (
      <Modal titulo="Empresa" onFechar={onFechar} largo>
        <div className="text-sm text-ink-3 py-8 text-center">Carregando…</div>
      </Modal>
    );
  }

  const ativa = e.status === "active";
  const problemas = e.saude?.problemas || [];

  return (
    <Modal
      titulo={e.name}
      descricao={`Criada em ${new Date(e.created_at).toLocaleDateString("pt-BR")} · ${ativa ? "ativa" : "suspensa"}`}
      onFechar={onFechar}
      largo
      testId="empresa-detalhe"
      corpoClasse="space-y-6"
      rodape={
        <div className="flex items-center justify-between gap-2 flex-1 flex-wrap">
          <div className="flex gap-2">
            <button onClick={() => mudar({ status: ativa ? "suspended" : "active" },
              ativa ? "Empresa suspensa: a equipe dela perde o acesso na hora" : "Empresa reativada")}
              disabled={mudando} className="zz-btn zz-btn-secondary text-xs" data-testid="empresa-suspender">
              {ativa ? <><PauseCircle size={14} weight="bold" /> Suspender</> : <><PlayCircle size={14} weight="bold" /> Reativar</>}
            </button>
            <button onClick={excluir} disabled={excluindo}
              className="zz-btn zz-btn-secondary text-xs text-danger" data-testid="empresa-excluir">
              <Trash size={14} weight="bold" /> Excluir
            </button>
          </div>
          <button onClick={() => entrar(e)} disabled={entrando} className="zz-btn text-xs"
            data-testid="empresa-entrar">
            <SignIn size={14} weight="bold" /> Entrar na empresa
          </button>
        </div>
      }
    >
      {problemas.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {problemas.map((p) => (
            <span key={p.tipo}
              className={`text-xs px-2 py-0.5 rounded-full border ${p.nivel === "alto"
                ? "bg-danger-soft border-danger text-danger"
                : p.nivel === "medio" ? "bg-warning-soft border-warning text-warning" : "bg-surface-2 border-line text-ink-2"}`}>
              {rotuloDoProblema(p)}
            </span>
          ))}
        </div>
      )}

      <Secao titulo={`Equipe · ${plural(e.usuarios.length, "pessoa", "pessoas")}`}>
        <ul className="border border-line rounded-lg divide-y divide-line">
          {e.usuarios.length === 0 && (
            <li className="px-3 py-3 text-sm text-danger">Nenhum usuário: ninguém consegue entrar nesta empresa.</li>
          )}
          {e.usuarios.map((u) => (
            <li key={u.id} className="flex items-center gap-3 px-3 py-2">
              <div className="min-w-0 flex-1">
                <div className="text-sm truncate">
                  {u.name}
                  {u.status === "suspended" && <span className="text-xs text-danger"> · suspenso</span>}
                </div>
                <div className="text-xs text-ink-3 font-mono truncate">{u.email}</div>
              </div>
              <span className="text-xs text-ink-3 shrink-0">{rotuloPapel(u.role)}</span>
              <button onClick={() => copiar(u.email)} title="Copiar email"
                className="p-1.5 rounded-md text-ink-3 hover:text-ink hover:bg-surface-2">
                <Copy size={14} />
              </button>
            </li>
          ))}
        </ul>
        <p className="text-xs text-ink-3 mt-1.5">
          A senha não fica guardada, só o hash. Para passar uma nova ao cliente, entre na empresa e defina em Usuários.
        </p>
      </Secao>

      <Secao titulo="WhatsApp">
        {e.conexoes.length === 0 ? (
          <div className="text-sm text-ink-3 border border-line rounded-lg px-3 py-3">
            Nenhuma conexão cadastrada.
          </div>
        ) : (
          <ul className="border border-line rounded-lg divide-y divide-line">
            {e.conexoes.map((c) => {
              const noAr = c.status === "conectado";
              return (
                <li key={c.id} className="flex items-center gap-3 px-3 py-2">
                  <WhatsappLogo size={16} className={noAr ? "text-success" : "text-danger"} />
                  <div className="min-w-0 flex-1">
                    <div className="text-sm truncate">{c.nome || "Sem nome"}</div>
                    <div className="text-xs text-ink-3 truncate">
                      {[c.numero_exibicao || c.numero, c.ultimo_erro].filter(Boolean).join(" · ") || "sem número"}
                    </div>
                  </div>
                  <span className={`text-xs font-medium ${noAr ? "text-success" : "text-danger"}`}>
                    {noAr ? "no ar" : "fora do ar"}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
        {e.saude && (
          <p className="text-xs text-ink-3 mt-1.5">
            {plural(e.saude.mensagens_7d, "mensagem", "mensagens")} e{" "}
            {plural(e.saude.conversas_7d, "conversa nova", "conversas novas")} nos últimos 7 dias
            {e.saude.ultima_mensagem ? `, a última ${haQuanto(e.saude.ultima_mensagem)}` : ""}.
          </p>
        )}
      </Secao>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Secao titulo="Plano">
          <select className="zz-input h-9 text-sm" value={e.plan_id || ""} disabled={mudando}
            data-testid="empresa-plano"
            onChange={(ev) => ev.target.value && ev.target.value !== e.plan_id
              && mudar({ plan_id: ev.target.value }, "Plano atualizado")}>
            {!e.plan_id && <option value="" disabled>sem plano</option>}
            {plans.map((p) => (
              <option key={p.id} value={p.id}>{p.nome} · {formatBRL(p.preco_mensal)}</option>
            ))}
          </select>
        </Secao>
        <Secao titulo="Marca">
          <select className="zz-input h-9 text-sm" value={validaMarca(e.marca)} disabled={mudando}
            data-testid="empresa-marca"
            onChange={(ev) => ev.target.value !== validaMarca(e.marca)
              && mudar({ marca: ev.target.value },
                `${e.name} agora vê o painel ${MARCAS[ev.target.value].nome}. Vale no próximo carregamento de quem estiver dentro.`)}>
            {Object.values(MARCAS).map((m) => <option key={m.id} value={m.id}>{m.nome}</option>)}
          </select>
        </Secao>
      </div>

      <Secao titulo="Uso do plano">
        <div className="space-y-3 border border-line rounded-lg p-3">
          {e.uso.map((l) => <LinhaUso key={l.chave} linha={l} />)}
        </div>
      </Secao>
    </Modal>
  );
}
