import { useState } from "react";
import { toast } from "sonner";
import { Plus, Trash, PencilSimple } from "@phosphor-icons/react";
import api, { formatApiErrorDetail } from "@/lib/api";
import { confirmToast } from "@/lib/confirm-toast";
import { useAcao } from "@/hooks/useAcao";
import Modal from "@/components/ui/Modal";
import { t } from "@/lib/textos";
import { DIAS_GRADE, moeda } from "./comum";
import { CampoHora } from "./CampoHora";

// Serviços e profissionais: o cadastro que a agenda inteira consulta.
//
// A grade de horários fica no **profissional**, não na empresa: a Ana atende de
// manhã e o Bruno à tarde, e uma grade única da empresa obrigaria os dois a
// terem o mesmo expediente. A empresa entra por cima com os feriados (aba
// Configuração), que fecham todo mundo de uma vez.

const GRADE_VAZIA = [[], [], [], [], [], [], []];

// ---------------------------------------------------------------------------
// Grade semanal
// ---------------------------------------------------------------------------

function GradeSemanal({ grade, onChange }) {
  const g = grade && grade.length === 7 ? grade : GRADE_VAZIA;

  const mexer = (dia, fn) => {
    const nova = g.map((d, i) => (i === dia ? fn([...(d || [])]) : d || []));
    onChange(nova);
  };

  return (
    <div className="space-y-2" data-testid="grade-semanal">
      {DIAS_GRADE.map((nome, i) => {
        const janelas = g[i] || [];
        return (
          <div key={nome}
            className="grid grid-cols-1 sm:grid-cols-[110px_1fr] gap-2 items-start border border-line rounded-lg p-3">
            <div className="flex items-center justify-between sm:block">
              <span className="text-sm font-semibold">{nome}</span>
              {janelas.length === 0 && (
                <span className="text-[11px] text-ink-3 sm:block">Não atende</span>
              )}
            </div>
            <div className="space-y-2">
              {janelas.map((j, k) => (
                <div key={k} className="flex items-center gap-2">
                  <CampoHora valor={j.inicio} testid={`grade-${i}-${k}-inicio`}
                    onChange={(v) => mexer(i, (d) => {
                      d[k] = { ...d[k], inicio: v };
                      return d;
                    })} />
                  <span className="text-ink-3 text-xs">às</span>
                  <CampoHora valor={j.fim} testid={`grade-${i}-${k}-fim`}
                    onChange={(v) => mexer(i, (d) => {
                      d[k] = { ...d[k], fim: v };
                      return d;
                    })} />
                  <button className="zz-btn-icon" title="Remover este horário"
                    onClick={() => mexer(i, (d) => { d.splice(k, 1); return d; })}>
                    <Trash size={14} weight="bold" />
                  </button>
                </div>
              ))}
              <button className="zz-btn zz-btn-secondary text-[11px] py-1"
                data-testid={`grade-add-${i}`}
                onClick={() => mexer(i, (d) => [...d, { inicio: "09:00", fim: "18:00" }])}>
                <Plus size={12} weight="bold" /> Horário
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Serviços
// ---------------------------------------------------------------------------

export function Servicos({ servicos, recursos, onMudou }) {
  const [editando, setEditando] = useState(null);

  const salvar = async () => {
    const corpo = {
      nome: editando.nome,
      duracao_min: Number(editando.duracao_min) || 30,
      preco: editando.preco === "" ? null : Number(editando.preco),
      descricao: editando.descricao || null,
      ativo: editando.ativo !== false,
      ordem: Number(editando.ordem) || 0,
      recursos: editando.recursos || [],
    };
    try {
      if (editando.id) await api.patch(`/agenda/services/${editando.id}`, corpo);
      else await api.post("/agenda/services", corpo);
      setEditando(null);
      toast.success(`${t("Serviço")} salvo`);
      onMudou();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    }
  };

  // Dois cliques na lixeira abriam duas confirmações, e a segunda exclusão
  // voltava 404 com toast de erro em cima de uma operação que tinha dado certo.
  const [excluir, excluindo] = useAcao(async (s) => {
    if (!(await confirmToast(`Excluir "${s.nome}"?`, { confirmLabel: "Excluir" }))) return;
    try {
      await api.delete(`/agenda/services/${s.id}`);
      onMudou();
    } catch (e) {
      // 409 é o serviço com horário marcado à frente. A mensagem do backend já
      // diz quantos e sugere desativar: repeti-la aqui é o que evita alguém
      // achar que o botão está quebrado.
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    }
  });

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <p className="text-sm text-ink-2">
          O que a {t("empresa")} agenda. A <strong>duração</strong> é o que define os horários
          oferecidos: uma coloração de 2h não é oferecida às 17h num expediente que fecha às 18h.
        </p>
        <button className="zz-btn shrink-0 ml-4" data-testid="novo-servico"
          onClick={() => setEditando({
            nome: "", duracao_min: 30, preco: "", descricao: "", ativo: true,
            ordem: servicos.length, recursos: [],
          })}>
          <Plus size={14} weight="bold" /> Novo {t("serviço")}
        </button>
      </div>

      {servicos.length === 0 ? (
        <Vazio texto={`Nenhum ${t("serviço")} cadastrado. Sem pelo menos um, o bot e o ${t("agente de IA")} não têm o que agendar.`} />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {servicos.map((s) => (
            <div key={s.id} className={`border border-line rounded-xl p-4 bg-surface ${
              s.ativo === false ? "opacity-60" : ""}`} data-testid="cartao-servico">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="font-semibold truncate">{s.nome}</div>
                  <div className="text-xs text-ink-3 mt-0.5">
                    {s.duracao_min} min{s.preco ? ` · ${moeda(s.preco)}` : ""}
                    {s.ativo === false ? " · desativado" : ""}
                  </div>
                </div>
                <div className="flex gap-1 shrink-0">
                  <button className="zz-btn-icon" onClick={() => setEditando({ ...s, preco: s.preco ?? "" })}>
                    <PencilSimple size={14} weight="bold" />
                  </button>
                  <button className="zz-btn-icon" onClick={() => excluir(s)} disabled={excluindo}>
                    <Trash size={14} weight="bold" />
                  </button>
                </div>
              </div>
              {s.descricao && <p className="text-xs text-ink-2 mt-2">{s.descricao}</p>}
              <div className="text-[11px] text-ink-3 mt-2">
                {s.recursos?.length
                  ? `Atendem: ${recursos.filter((r) => s.recursos.includes(r.id))
                      .map((r) => r.nome).join(", ") || ": "}`
                  : "Atendido por todos os profissionais"}
              </div>
            </div>
          ))}
        </div>
      )}

      {editando && (
        <Modal titulo={editando.id ? `Editar ${t("serviço")}` : `Novo ${t("serviço")}`}
          onFechar={() => setEditando(null)} onSalvar={salvar}>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <Campo label="Nome">
              <input className="zz-input" value={editando.nome} data-testid="servico-nome"
                onChange={(e) => setEditando({ ...editando, nome: e.target.value })} />
            </Campo>
            <Campo label="Duração (minutos)">
              <input type="number" min="5" step="5" className="zz-input font-mono"
                value={editando.duracao_min} data-testid="servico-duracao"
                onChange={(e) => setEditando({ ...editando, duracao_min: e.target.value })} />
            </Campo>
            <Campo label="Preço (opcional)">
              <input type="number" min="0" step="0.01" className="zz-input font-mono"
                value={editando.preco}
                onChange={(e) => setEditando({ ...editando, preco: e.target.value })} />
            </Campo>
            <Campo label="Ordem na lista">
              <input type="number" className="zz-input font-mono" value={editando.ordem}
                onChange={(e) => setEditando({ ...editando, ordem: e.target.value })} />
            </Campo>
          </div>
          <Campo label="Descrição">
            <input className="zz-input" value={editando.descricao || ""}
              placeholder={`Aparece na lista que o ${t("contato")} recebe no WhatsApp.`}
              onChange={(e) => setEditando({ ...editando, descricao: e.target.value })} />
          </Campo>
          <Campo label={`Quem atende este ${t("serviço")}`}>
            <div className="flex flex-wrap gap-2">
              {recursos.map((r) => {
                const marcado = (editando.recursos || []).includes(r.id);
                return (
                  <button key={r.id}
                    className={`border rounded-lg px-3 py-1.5 text-xs transition-colors ${
                      marcado ? "border-info bg-info-soft ring-1 ring-info"
                        : "border-line hover:bg-surface-2"}`}
                    onClick={() => setEditando({
                      ...editando,
                      recursos: marcado
                        ? editando.recursos.filter((x) => x !== r.id)
                        : [...(editando.recursos || []), r.id],
                    })}>
                    {r.nome}
                  </button>
                );
              })}
            </div>
            <p className="text-[11px] text-ink-3 mt-1.5">
              Nenhum marcado = todos atendem. É o padrão, para um profissional novo não
              nascer de fora de todos os {t("serviços")}.
            </p>
          </Campo>
          <Ativo valor={editando.ativo !== false}
            onChange={(v) => setEditando({ ...editando, ativo: v })}
            nota="Desativado, some do bot e da tela de marcação, mas os horários já marcados continuam valendo." />
        </Modal>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Profissionais
// ---------------------------------------------------------------------------

export function Profissionais({ recursos, usuarios, config, onMudou }) {
  const [editando, setEditando] = useState(null);

  const salvar = async () => {
    const corpo = {
      nome: editando.nome,
      tipo: editando.tipo || "pessoa",
      descricao: editando.descricao || null,
      ativo: editando.ativo !== false,
      user_id: editando.user_id || null,
      intervalo_min: editando.intervalo_min === "" ? null : Number(editando.intervalo_min),
      grade: editando.grade,
      excecoes: (editando.excecoes || []).filter((e) => e.data),
    };
    try {
      if (editando.id) await api.patch(`/agenda/resources/${editando.id}`, corpo);
      else await api.post("/agenda/resources", corpo);
      setEditando(null);
      toast.success("Profissional salvo");
      onMudou();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    }
  };

  const [excluir, excluindo] = useAcao(async (r) => {
    if (!(await confirmToast(`Excluir "${r.nome}"?`, { confirmLabel: "Excluir" }))) return;
    try {
      await api.delete(`/agenda/resources/${r.id}`);
      onMudou();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    }
  });

  const resumoGrade = (g) => {
    const dias = (g || []).map((d, i) => (d?.length ? DIAS_GRADE[i].slice(0, 3) : null))
      .filter(Boolean);
    return dias.length ? dias.join(", ") : "sem horário configurado";
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <p className="text-sm text-ink-2">
          Quem (ou o quê) ocupa um horário: pessoa, sala ou equipamento. Cada um tem a
          própria grade: é dela que saem os horários que o bot oferece.
        </p>
        <button className="zz-btn shrink-0 ml-4" data-testid="novo-profissional"
          onClick={() => setEditando({
            nome: "", tipo: "pessoa", ativo: true, user_id: "", intervalo_min: "",
            grade: null, excecoes: [],
          })}>
          <Plus size={14} weight="bold" /> Novo profissional
        </button>
      </div>

      {recursos.length === 0 ? (
        <Vazio texto="Nenhum profissional cadastrado. Sem pelo menos um, não há horário livre para oferecer." />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {recursos.map((r) => (
            <div key={r.id} className={`border border-line rounded-xl p-4 bg-surface ${
              r.ativo === false ? "opacity-60" : ""}`} data-testid="cartao-profissional">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="font-semibold truncate">{r.nome}</div>
                  <div className="text-xs text-ink-3 mt-0.5 capitalize">
                    {r.tipo}{r.ativo === false ? " · desativado" : ""}
                  </div>
                </div>
                <div className="flex gap-1 shrink-0">
                  <button className="zz-btn-icon"
                    onClick={() => setEditando({ ...r, intervalo_min: r.intervalo_min ?? "" })}>
                    <PencilSimple size={14} weight="bold" />
                  </button>
                  <button className="zz-btn-icon" onClick={() => excluir(r)} disabled={excluindo}>
                    <Trash size={14} weight="bold" />
                  </button>
                </div>
              </div>
              <div className="text-[11px] text-ink-3 mt-2">Atende: {resumoGrade(r.grade)}</div>
              {r.excecoes?.length > 0 && (
                <div className="text-[11px] text-warning mt-1">
                  {r.excecoes.length} exceção(ões) de data
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {editando && (
        <Modal titulo={editando.id ? "Editar profissional" : "Novo profissional"}
          onFechar={() => setEditando(null)} onSalvar={salvar} largo>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            <Campo label="Nome">
              <input className="zz-input" value={editando.nome} data-testid="profissional-nome"
                onChange={(e) => setEditando({ ...editando, nome: e.target.value })} />
            </Campo>
            <Campo label="Tipo">
              <select className="zz-input" value={editando.tipo || "pessoa"}
                onChange={(e) => setEditando({ ...editando, tipo: e.target.value })}>
                <option value="pessoa">Pessoa</option>
                <option value="sala">Sala</option>
                <option value="equipamento">Equipamento</option>
              </select>
            </Campo>
            <Campo label="Usuário do sistema">
              <select className="zz-input" value={editando.user_id || ""}
                onChange={(e) => setEditando({ ...editando, user_id: e.target.value })}>
                <option value="">: nenhum, </option>
                {usuarios.map((u) => (
                  <option key={u.id} value={u.id}>{u.name || u.email}</option>
                ))}
              </select>
            </Campo>
          </div>

          <Campo label={`Folga entre atendimentos (minutos), em branco usa a da ${t("empresa")} (${config.intervalo_min || 0})`}>
            <input type="number" min="0" className="zz-input font-mono max-w-[160px]"
              value={editando.intervalo_min}
              onChange={(e) => setEditando({ ...editando, intervalo_min: e.target.value })} />
          </Campo>

          <div>
            <div className="text-xs font-bold uppercase tracking-wider text-ink-2 mb-2">
              Dias e horários de atendimento
            </div>
            <GradeSemanal grade={editando.grade}
              onChange={(g) => setEditando({ ...editando, grade: g })} />
          </div>

          <div>
            <div className="flex items-center justify-between mb-2">
              <div>
                <div className="text-xs font-bold uppercase tracking-wider text-ink-2">
                  Exceções de data
                </div>
                <p className="text-[11px] text-ink-3">
                  Folga, férias ou um horário diferente num dia. Ganha da grade acima
                  e perde para o feriado da {t("empresa")}, em Configuração.
                </p>
              </div>
              <button className="zz-btn zz-btn-secondary text-xs shrink-0"
                data-testid="add-excecao"
                onClick={() => setEditando({
                  ...editando,
                  excecoes: [...(editando.excecoes || []),
                             { data: "", fechado: true, motivo: "", janelas: [] }],
                })}>
                <Plus size={12} weight="bold" /> Exceção
              </button>
            </div>
            <div className="space-y-2">
              {(editando.excecoes || []).map((ex, i) => {
                const mexer = (patch) => setEditando({
                  ...editando,
                  excecoes: editando.excecoes.map((x, k) => (k === i ? { ...x, ...patch } : x)),
                });
                return (
                  <div key={i} className="border border-line rounded-lg p-3 space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <input type="date" className="zz-input font-mono max-w-[170px]"
                        value={ex.data} onChange={(e) => mexer({ data: e.target.value })} />
                      <select className="zz-input max-w-[190px]" value={ex.fechado ? "1" : "0"}
                        onChange={(e) => mexer({ fechado: e.target.value === "1" })}>
                        <option value="1">Não atende</option>
                        <option value="0">Horário especial</option>
                      </select>
                      <input className="zz-input flex-1 min-w-[140px]" placeholder="Motivo (opcional)"
                        value={ex.motivo || ""} onChange={(e) => mexer({ motivo: e.target.value })} />
                      <button className="zz-btn-icon" onClick={() => setEditando({
                        ...editando,
                        excecoes: editando.excecoes.filter((_, k) => k !== i),
                      })}>
                        <Trash size={14} weight="bold" />
                      </button>
                    </div>
                    {!ex.fechado && (
                      <div className="space-y-2 pl-1">
                        {(ex.janelas || []).map((j, k) => (
                          <div key={k} className="flex items-center gap-2">
                            <CampoHora valor={j.inicio}
                              onChange={(v) => mexer({
                                janelas: ex.janelas.map((x, n) =>
                                  (n === k ? { ...x, inicio: v } : x)),
                              })} />
                            <span className="text-ink-3 text-xs">às</span>
                            <CampoHora valor={j.fim}
                              onChange={(v) => mexer({
                                janelas: ex.janelas.map((x, n) =>
                                  (n === k ? { ...x, fim: v } : x)),
                              })} />
                            <button className="zz-btn-icon" onClick={() => mexer({
                              janelas: ex.janelas.filter((_, n) => n !== k),
                            })}>
                              <Trash size={14} weight="bold" />
                            </button>
                          </div>
                        ))}
                        <button className="zz-btn zz-btn-secondary text-[11px] py-1"
                          onClick={() => mexer({
                            janelas: [...(ex.janelas || []), { inicio: "09:00", fim: "13:00" }],
                          })}>
                          <Plus size={12} weight="bold" /> Horário
                        </button>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          <Ativo valor={editando.ativo !== false}
            onChange={(v) => setEditando({ ...editando, ativo: v })}
            nota="Desativado, para de aparecer como opção: os horários já marcados continuam na agenda." />
        </Modal>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------

function Vazio({ texto }) {
  return (
    <div className="border border-dashed border-line rounded-xl p-10 text-center text-sm text-ink-3">
      {texto}
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

function Ativo({ valor, onChange, nota }) {
  return (
    <label className="flex items-start gap-2 text-sm cursor-pointer">
      <input type="checkbox" checked={valor} className="mt-0.5"
        onChange={(e) => onChange(e.target.checked)} />
      <span>Ativo<span className="block text-[11px] text-ink-3">{nota}</span></span>
    </label>
  );
}
