import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { CalendarBlank, MagnifyingGlass, Warning, X } from "@phosphor-icons/react";
import api, { formatApiErrorDetail } from "@/lib/api";
import { hora, moeda, rotuloDia, somaDias, hojeNaEmpresa } from "./comum";
import { t } from "@/lib/textos";

// Marcação manual: a recepção atendendo o telefone.
//
// A ordem das perguntas é a mesma do nó de Agendamento do bot (serviço →
// profissional → dia → horário), e os horários vêm da **mesma** rota que o bot
// consulta. Duas listas diferentes fariam a tela oferecer um horário que o bot
// recusa segundos depois, e o contrário, que é pior: a recepção marcaria por
// cima de algo que o robô acabou de reservar.
//
// O contato é escolhido por busca ou cadastrado ali mesmo, pelo número: quem
// está com o cliente no telefone não vai abrir outra tela para cadastrar antes
// de marcar, e sairia da ligação sem horário nenhum.

export default function NovoAgendamento({ servicos, recursos, fuso, onFechar, onSalvo }) {
  const [servicoId, setServicoId] = useState(servicos[0]?.id || "");
  const [recursoId, setRecursoId] = useState("");
  const [dia, setDia] = useState(() => hojeNaEmpresa(fuso));
  const [horarios, setHorarios] = useState([]);
  const [carregandoHorarios, setCarregando] = useState(false);
  const [escolhido, setEscolhido] = useState(null);
  const [busca, setBusca] = useState("");
  const [achados, setAchados] = useState([]);
  const [contato, setContato] = useState(null);
  const [novo, setNovo] = useState({ nome: "", numero: "" });
  const [observacoes, setObservacoes] = useState("");
  const [avisar, setAvisar] = useState(true);
  const [salvando, setSalvando] = useState(false);

  const servico = servicos.find((s) => s.id === servicoId);
  // Serviço com lista de profissionais vazia é atendido por todos: mesma regra
  // do backend, e o padrão ao cadastrar.
  const atendem = recursos.filter(
    (r) => !servico?.recursos?.length || servico.recursos.includes(r.id));

  const buscarHorarios = useCallback(() => {
    if (!servicoId || !dia) return;
    setCarregando(true);
    setEscolhido(null);
    api.get("/agenda/slots", { params: { service_id: servicoId, dia, resource_id: recursoId || undefined } })
      .then((r) => setHorarios(r.data.horarios || []))
      .catch((e) => {
        setHorarios([]);
        toast.error(formatApiErrorDetail(e.response?.data?.detail));
      })
      .finally(() => setCarregando(false));
  }, [servicoId, dia, recursoId]);

  useEffect(() => { buscarHorarios(); }, [buscarHorarios]);

  useEffect(() => {
    const termo = busca.trim();
    if (termo.length < 2) { setAchados([]); return; }
    const t = setTimeout(() => {
      api.get("/contacts", { params: { q: termo, limit: 8 } })
        .then((r) => setAchados(r.data.items || [])).catch(() => {});
    }, 300);
    return () => clearTimeout(t);
  }, [busca]);

  const salvar = async () => {
    if (!escolhido) return toast.error("Escolha um horário");
    if (!contato && !novo.numero.trim())
      return toast.error(`Escolha um ${t("contato")} ou informe o WhatsApp`);
    setSalvando(true);
    try {
      const r = await api.post("/agenda/appointments", {
        service_id: servicoId,
        // O profissional sai do próprio horário escolhido: no modo "qualquer"
        // é a lista de horários que já diz quem está livre naquela hora.
        resource_id: escolhido.resource_id,
        inicio: escolhido.inicio,
        contact_id: contato?.id || null,
        contact_nome: contato ? null : novo.nome,
        contact_numero: contato ? null : novo.numero,
        observacoes: observacoes || null,
        avisar,
      });
      toast.success(
        avisar && r.data.aviso_enviado === false
          ? "Horário marcado, mas a confirmação não pôde ser enviada pelo WhatsApp"
          : "Horário marcado",
      );
      onSalvo();
    } catch (e) {
      // 409 aqui é o caso real de corrida: alguém (ou o bot) marcou entre a
      // consulta e o clique. Recarregar a lista é o que a pessoa faria a
      // seguir de qualquer forma.
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
      if (e.response?.status === 409) buscarHorarios();
    } finally {
      setSalvando(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
      data-testid="novo-agendamento">
      <div className="bg-surface border border-line rounded-2xl w-full max-w-3xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b border-line">
          <div>
            <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-ink-3">Agenda</div>
            <h2 className="font-heading text-2xl font-black tracking-tighter">Novo agendamento</h2>
          </div>
          <button onClick={onFechar} className="zz-btn-icon" data-testid="fechar-novo-agendamento">
            <X size={18} weight="bold" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-6 space-y-5">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            <Campo label={t("Serviço")}>
              <select className="zz-input" value={servicoId} data-testid="agendamento-servico"
                onChange={(e) => { setServicoId(e.target.value); setRecursoId(""); }}>
                {servicos.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.nome} · {s.duracao_min} min{s.preco ? ` · ${moeda(s.preco)}` : ""}
                  </option>
                ))}
              </select>
            </Campo>
            <Campo label="Profissional">
              <select className="zz-input" value={recursoId} data-testid="agendamento-recurso"
                onChange={(e) => setRecursoId(e.target.value)}>
                <option value="">Qualquer um disponível</option>
                {atendem.map((r) => <option key={r.id} value={r.id}>{r.nome}</option>)}
              </select>
            </Campo>
            <Campo label="Dia">
              <input type="date" className="zz-input" value={dia} data-testid="agendamento-dia"
                onChange={(e) => setDia(e.target.value)} />
            </Campo>
          </div>

          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-bold uppercase tracking-wider text-ink-2">
                Horários livres
              </span>
              <div className="flex gap-1">
                {[-1, 1].map((n) => (
                  <button key={n} className="zz-btn zz-btn-secondary text-[11px] py-1"
                    onClick={() => setDia(somaDias(dia, n))}>
                    {n < 0 ? "Dia anterior" : "Próximo dia"}
                  </button>
                ))}
              </div>
            </div>
            {carregandoHorarios ? (
              <div className="text-xs text-ink-3 py-6 text-center">Consultando a agenda…</div>
            ) : horarios.length === 0 ? (
              <div className="text-xs text-ink-2 bg-surface-2 border border-line rounded-lg p-4 flex gap-2">
                <CalendarBlank size={16} weight="bold" className="shrink-0 mt-0.5" />
                <span>
                  Nada livre em {rotuloDia(dia)}. Pode ser folga, feriado, agenda cheia, ou a
                  antecedência mínima, se o dia for hoje.
                </span>
              </div>
            ) : (
              <div className="flex flex-wrap gap-2" data-testid="agendamento-horarios">
                {horarios.map((h) => {
                  const marcado = escolhido?.inicio === h.inicio;
                  return (
                    <button key={h.inicio} onClick={() => setEscolhido(h)}
                      className={`border rounded-lg px-3 py-2 text-left transition-colors ${
                        marcado
                          ? "border-info bg-info-soft ring-1 ring-info"
                          : "border-line hover:border-line-strong hover:bg-surface-2"}`}>
                      <div className="font-mono font-bold text-sm">{hora(h.inicio, fuso)}</div>
                      {!recursoId && (
                        <div className="text-[10px] text-ink-3">{h.resource_nome}</div>
                      )}
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          <div className="border-t border-line pt-5">
            <span className="text-xs font-bold uppercase tracking-wider text-ink-2 block mb-2">
              Para quem
            </span>
            {contato ? (
              <div className="flex items-center justify-between border border-info bg-info-soft ring-1 ring-info rounded-lg p-3">
                <div>
                  <div className="font-semibold text-sm">{contato.nome}</div>
                  <div className="text-[11px] font-mono text-ink-3">{contato.numero_whatsapp}</div>
                </div>
                <button className="zz-btn zz-btn-secondary text-xs" onClick={() => setContato(null)}>
                  Trocar
                </button>
              </div>
            ) : (
              <div className="space-y-3">
                <div className="relative">
                  <MagnifyingGlass size={14} weight="bold"
                    className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-3" />
                  <input className="zz-input pl-8" placeholder={`Buscar ${t("contato")} por nome ou número`}
                    value={busca} data-testid="agendamento-busca-contato"
                    onChange={(e) => setBusca(e.target.value)} />
                </div>
                {achados.length > 0 && (
                  <div className="border border-line rounded-lg divide-y divide-line max-h-40 overflow-y-auto">
                    {achados.map((c) => (
                      <button key={c.id} onClick={() => { setContato(c); setBusca(""); setAchados([]); }}
                        className="w-full text-left px-3 py-2 hover:bg-surface-2">
                        <div className="text-sm">{c.nome}</div>
                        <div className="text-[11px] font-mono text-ink-3">{c.numero_whatsapp}</div>
                      </button>
                    ))}
                  </div>
                )}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <Campo label="Ou cadastre agora: nome">
                    <input className="zz-input" value={novo.nome} data-testid="agendamento-novo-nome"
                      onChange={(e) => setNovo({ ...novo, nome: e.target.value })} />
                  </Campo>
                  <Campo label="WhatsApp">
                    <input className="zz-input font-mono" placeholder="(11) 99999-8888"
                      value={novo.numero} data-testid="agendamento-novo-numero"
                      onChange={(e) => setNovo({ ...novo, numero: e.target.value })} />
                  </Campo>
                </div>
              </div>
            )}
          </div>

          <Campo label="Observações">
            <textarea rows={2} className="zz-input" value={observacoes}
              placeholder={`Fica só na agenda: o ${t("contato")} não recebe.`}
              onChange={(e) => setObservacoes(e.target.value)} />
          </Campo>

          <label className="flex items-start gap-2 text-sm cursor-pointer">
            <input type="checkbox" checked={avisar} data-testid="agendamento-avisar"
              onChange={(e) => setAvisar(e.target.checked)} className="mt-0.5" />
            <span>
              Avisar o {t("contato")} pelo WhatsApp
              <span className="block text-[11px] text-ink-3">
                Manda a confirmação com {t("serviço")}, dia e profissional. O lembrete automático,
                se estiver ligado, sai depois de qualquer jeito.
              </span>
            </span>
          </label>

          {escolhido && (
            <div className="text-xs bg-surface-2 border border-line rounded-lg p-3 flex gap-2">
              <Warning size={14} weight="bold" className="shrink-0 mt-0.5 text-ink-3" />
              <span>
                Vai marcar <strong>{servico?.nome}</strong> em{" "}
                <strong>{rotuloDia(dia)} às {hora(escolhido.inicio, fuso)}</strong> com{" "}
                <strong>{escolhido.resource_nome}</strong>.
              </span>
            </div>
          )}
        </div>

        <div className="border-t border-line px-6 py-4 flex justify-end gap-2">
          <button className="zz-btn zz-btn-secondary" onClick={onFechar}>Cancelar</button>
          <button className="zz-btn" onClick={salvar} disabled={salvando || !escolhido}
            data-testid="agendamento-salvar">
            {salvando ? "Marcando…" : "Marcar horário"}
          </button>
        </div>
      </div>
    </div>
  );
}

function Campo({ label, children }) {
  return (
    <div>
      <label className="text-xs font-bold uppercase tracking-wider text-ink-2 block mb-1.5">
        {label}
      </label>
      {children}
    </div>
  );
}
