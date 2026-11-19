import { useEffect, useMemo, useRef, useState } from "react";
import api, { API, formatApiErrorDetail } from "@/lib/api";
import {
  Plus, PencilSimple, Trash, ChatCircleDots, Robot, PaperPlaneRight, Code,
  DotsThree, MagnifyingGlass, PlugsConnected, Warning, Brain, Paperclip, Microphone,
  Stop, X,
} from "@phosphor-icons/react";
import { toast } from "sonner";
import { confirmToast } from "@/lib/confirm-toast";
import AgenteWizard from "./AgenteWizard";
import TreinarAgente from "./TreinarAgente";
import { MediaContent, Transcricao } from "@/components/atendimento/shared";
import { useAcao } from "@/hooks/useAcao";
import { t } from "@/lib/textos";

// Função, e não constante: o texto depende da marca, resolvida na renderização.
const modoRotulo = () => ({
  fallback: `Entra quando nenhum ${t("robô")} atende`,
  primeiro: "Atende na frente",
  desligado: "Desligado",
});

/** Conversa de teste com um agente, sem WhatsApp e sem gravar nada.
 *
 * Mesma ideia do "Testar" do editor de fluxos: ver o agente responder antes de
 * apontá-lo para clientes de verdade. Bate no motor real, então também
 * exercita a credencial e o teto de IA da empresa — um teste que passasse por fora
 * desses dois não provaria nada sobre produção. */
function ChatTeste({ agente, onFechar }) {
  const [mensagens, setMensagens] = useState([]);
  const [texto, setTexto] = useState("");
  const [pensando, setPensando] = useState(false);
  // Foto ou áudio já enviado ao servidor, esperando o "enviar". O áudio volta
  // transcrito: é o mesmo texto que o agente vai ler.
  const [anexo, setAnexo] = useState(null);
  const [gravando, setGravando] = useState(false);
  const gravador = useRef(null);
  const inputArquivo = useRef(null);
  const fim = useRef(null);

  useEffect(() => { fim.current?.scrollIntoView({ behavior: "smooth" }); }, [mensagens, pensando]);
  // Fechar o teste no meio de uma gravação não pode deixar o microfone aberto.
  useEffect(() => () => gravador.current?.stream?.getTracks().forEach((t) => t.stop()), []);

  const [subirAnexo, subindo] = useAcao(async (arquivo, nome) => {
    const form = new FormData();
    form.append("file", arquivo, nome || arquivo.name);
    try {
      const { data } = await api.post(`/ai/agents/${agente.id}/test/anexo`, form);
      setAnexo(data);
    } catch (ex) {
      toast.error(formatApiErrorDetail(ex.response?.data?.detail));
    }
  });

  // O seletor não tem `accept`: arquivo fora da lista apareceria apagado no
  // seletor do sistema, sem explicação. O servidor recusa dizendo por quê.
  const escolherArquivo = (e) => {
    const arquivo = e.target.files?.[0];
    e.target.value = "";
    if (arquivo) subirAnexo(arquivo);
  };

  const colar = (e) => {
    const arquivo = [...(e.clipboardData?.files || [])].find((f) => f.type.startsWith("image/"));
    if (arquivo) {
      e.preventDefault();
      subirAnexo(arquivo, arquivo.name || "colada.png");
    }
  };

  // Gravar pelo microfone é o jeito de testar áudio sem ter um arquivo à mão,
  // e é o mais parecido com a nota de voz do WhatsApp.
  const alternarGravacao = async () => {
    if (gravando) {
      gravador.current?.stop();
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const rec = new MediaRecorder(stream);
      const pedacos = [];
      rec.ondataavailable = (ev) => { if (ev.data.size) pedacos.push(ev.data); };
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        setGravando(false);
        const tipo = (rec.mimeType || "audio/webm").split(";")[0];
        const ext = tipo.includes("ogg") ? "ogg" : tipo.includes("mp4") ? "m4a" : "webm";
        if (pedacos.length) subirAnexo(new Blob(pedacos, { type: tipo }), `gravacao.${ext}`);
      };
      gravador.current = rec;
      rec.start();
      setGravando(true);
    } catch {
      toast.error("O navegador não liberou o microfone. Permita o acesso ou anexe um arquivo de áudio.");
    }
  };

  const enviar = async (e) => {
    e.preventDefault();
    const conteudo = texto.trim();
    if ((!conteudo && !anexo) || pensando || subindo || gravando) return;
    const proximas = [...mensagens, { role: "user", content: conteudo, ...(anexo ? { anexo } : {}) }];
    setMensagens(proximas);
    setTexto("");
    setAnexo(null);
    setPensando(true);
    try {
      // Avisos e erros da tela não são conversa: mandá-los faria o agente ler
      // "Transferido para atendimento humano" como fala do contato.
      const { data } = await api.post(`/ai/agents/${agente.id}/test`, {
        mensagens: proximas.filter((m) => m.role === "user" || m.role === "assistant"),
      });
      setMensagens([
        ...proximas,
        // Ao transferir, o agente pode deixar uma frase para o contato; e quando
        // a trava segura uma confirmação de horário inventada, o contato recebe
        // um aviso neutro. Nos dois casos é isso que o cliente leria.
        ...(data.transferiu && data.texto ? [{ role: "assistant", content: data.texto }] : []),
        ...(data.segurada
          ? [{ role: "sistema", content: `Mensagem segurada, não enviada ao ${t("contato")}: "${data.segurada}"` }]
          : []),
        data.transferiu
          ? { role: "sistema", content: `Transferido para atendimento humano — ${data.motivo}` }
          : { role: "assistant", content: data.texto, fotos: data.fotos || [] },
        // No teste nada é gravado; numa conversa real ela terminaria aqui.
        ...(data.finalizou
          ? [{ role: "sistema", content: `O ${t("agente")} finalizou o atendimento (no teste nada é gravado).` }]
          : []),
      ]);
    } catch (ex) {
      setMensagens([
        ...proximas,
        { role: "erro", content: formatApiErrorDetail(ex.response?.data?.detail) },
      ]);
    } finally {
      setPensando(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
      onClick={onFechar}>
      <div onClick={(e) => e.stopPropagation()}
        className="bg-surface w-full max-w-lg zz-panel-hard flex flex-col overflow-hidden"
        style={{ height: "min(80vh, 640px)" }}
        data-testid="agente-chat-teste">
        <div className="border-b border-line p-4 flex items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="font-heading text-lg font-bold tracking-tight truncate">
              Testar {agente.nome}
            </div>
            <div className="text-[11px] text-ink-3">
              Nada é enviado por WhatsApp nem gravado no histórico.
            </div>
          </div>
          <button className="zz-btn zz-btn-secondary text-xs py-1.5 shrink-0" onClick={onFechar}>
            Fechar
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-3 bg-surface-2">
          {mensagens.length === 0 && (
            <div className="text-xs text-ink-3 text-center py-10">
              Escreva como se fosse um cliente e veja o que o {t("agente")} responde. Dá para mandar
              foto e áudio também, pelo clipe ou pelo microfone.
            </div>
          )}
          {mensagens.map((m, i) => (
            <div key={i} className={m.role === "user" ? "flex justify-end" : "flex justify-start"}>
              <div className={`max-w-[80%] px-3.5 py-2 text-sm rounded-2xl ${
                m.role === "user"
                  ? "bg-brand text-brand-fg"
                  : m.role === "assistant"
                    ? "bg-surface border border-line"
                    : m.role === "sistema"
                      ? "bg-warning-soft border border-warning/40 text-warning text-xs"
                      : "bg-danger-soft border border-danger/40 text-danger text-xs"
              }`}>
                {m.anexo && <AnexoTeste anexo={m.anexo} />}
                {m.content}
                {m.fotos?.length > 0 && (
                  // As fotos que o contato receberia, na ordem em que iriam.
                  <div className={`grid gap-1.5 ${m.content ? "mt-2" : ""} ${m.fotos.length > 1 ? "grid-cols-2" : ""}`}>
                    {m.fotos.map((id) => (
                      <img key={id} src={`${API}/media/${id}`} alt="" loading="lazy"
                        className="w-full aspect-[4/3] object-cover rounded-xl bg-surface-3" />
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
          {pensando && <div className="text-xs text-ink-3">Digitando…</div>}
          <div ref={fim} />
        </div>

        {anexo && (
          <div className="border-t border-line px-3 pt-3 flex items-start gap-2" data-testid="agente-chat-anexo">
            <div className="flex-1 min-w-0 rounded-xl border border-line bg-surface-2 p-2">
              <AnexoTeste anexo={anexo} />
            </div>
            <button type="button" className="zz-btn zz-btn-secondary text-xs py-1.5 shrink-0"
              onClick={() => setAnexo(null)} aria-label="Tirar anexo">
              <X size={12} weight="bold" />
            </button>
          </div>
        )}

        <form onSubmit={enviar} className="border-t border-line p-3 flex gap-2">
          <input ref={inputArquivo} type="file" className="hidden" onChange={escolherArquivo} />
          <button type="button" className="zz-btn zz-btn-secondary shrink-0" title="Anexar foto ou áudio"
            disabled={subindo || gravando || pensando} onClick={() => inputArquivo.current?.click()}
            data-testid="agente-chat-anexar">
            <Paperclip size={14} weight="bold" />
          </button>
          <button type="button" title={gravando ? "Parar e anexar" : "Gravar áudio"}
            className={`zz-btn shrink-0 ${gravando ? "bg-danger-solid text-danger-fg" : "zz-btn-secondary"}`}
            disabled={subindo || pensando} onClick={alternarGravacao} aria-pressed={gravando}
            data-testid="agente-chat-gravar">
            {gravando ? <Stop size={14} weight="fill" /> : <Microphone size={14} weight="bold" />}
          </button>
          <input className="zz-input" autoFocus
            placeholder={gravando ? "Gravando… toque em parar" : subindo ? "Enviando anexo…" : "Escreva como um cliente…"}
            value={texto} onChange={(e) => setTexto(e.target.value)} onPaste={colar}
            data-testid="agente-chat-input" />
          <button type="submit" className="zz-btn shrink-0"
            disabled={pensando || subindo || gravando || (!texto.trim() && !anexo)}>
            <PaperPlaneRight size={14} weight="bold" />
          </button>
        </form>
      </div>
    </div>
  );
}

/** Foto ou áudio do chat de teste, com o que o agente vai ler do áudio. */
function AnexoTeste({ anexo }) {
  return (
    <div className="mb-1 space-y-1">
      <div className="rounded-lg overflow-hidden bg-surface text-ink">
        <MediaContent media={{ id: anexo.id, kind: anexo.kind, filename: anexo.filename }} />
      </div>
      {anexo.transcricao && (
        <div className="rounded-lg bg-surface text-ink px-2 py-1">
          <Transcricao texto={anexo.transcricao} />
        </div>
      )}
      {anexo.transcricao_erro && (
        <div className="text-[11px] rounded-lg bg-warning-soft text-warning px-2 py-1">
          Não transcrito: {anexo.transcricao_erro}
        </div>
      )}
    </div>
  );
}

/** O prompt final montado a partir das escolhas. Existe para o admin conferir
 * o que o agente realmente recebe — sem isso, mexer em tom e restrição é
 * adivinhação. */
function VerPrompt({ agente, onFechar }) {
  const [prompt, setPrompt] = useState(null);
  useEffect(() => {
    api.get(`/ai/agents/${agente.id}/prompt`)
      .then((r) => setPrompt(r.data.instrucoes))
      .catch((ex) => toast.error(formatApiErrorDetail(ex.response?.data?.detail)));
  }, [agente.id]);
  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
      onClick={onFechar}>
      <div onClick={(e) => e.stopPropagation()}
        className="bg-surface w-full max-w-2xl zz-panel-hard overflow-hidden"
        data-testid="agente-prompt">
        <div className="border-b border-line p-4 flex items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="font-heading text-lg font-bold tracking-tight truncate">
              Instruções de {agente.nome}
            </div>
            <div className="text-[11px] text-ink-3">
              É exatamente isto que o modelo recebe a cada mensagem.
            </div>
          </div>
          <button className="zz-btn zz-btn-secondary text-xs py-1.5 shrink-0" onClick={onFechar}>
            Fechar
          </button>
        </div>
        <pre className="p-4 text-xs font-mono whitespace-pre-wrap overflow-y-auto bg-surface-2 text-ink-2"
          style={{ maxHeight: "60vh" }}>
          {prompt ?? "Carregando…"}
        </pre>
      </div>
    </div>
  );
}

/** Menu de ações secundárias do cartão. As ações raras saem de vista para o
 * cartão não virar uma fileira de seis botõezinhos. */
function MenuAcoes({ onEditar, onPrompt, onExcluir }) {
  const [aberto, setAberto] = useState(false);
  useEffect(() => {
    if (!aberto) return;
    const fechar = () => setAberto(false);
    window.addEventListener("click", fechar);
    return () => window.removeEventListener("click", fechar);
  }, [aberto]);

  const item = "w-full text-left px-3 py-2 text-sm hover:bg-surface-2 flex items-center gap-2";
  return (
    <div className="relative shrink-0" onClick={(e) => e.stopPropagation()}>
      <button onClick={() => setAberto((v) => !v)} aria-label="Mais ações"
        className="w-8 h-8 rounded-lg flex items-center justify-center text-ink-3 hover:bg-surface-2 hover:text-ink">
        <DotsThree size={20} weight="bold" />
      </button>
      {aberto && (
        <div className="absolute right-0 top-9 z-20 w-52 py-1 bg-surface rounded-xl zz-panel-hard border border-line">
          <button className={item} onClick={onEditar}>
            <PencilSimple size={15} /> Editar configuração
          </button>
          <button className={item} onClick={onPrompt}>
            <Code size={15} /> Ver instruções
          </button>
          <button className={`${item} text-danger`} onClick={onExcluir}>
            <Trash size={15} /> Excluir {t("agente")}
          </button>
        </div>
      )}
    </div>
  );
}

function Numero({ valor, rotulo, destaque }) {
  return (
    <div className="flex-1 min-w-0">
      <div className={`font-heading text-lg font-bold leading-none ${destaque ? "text-success" : "text-ink"}`}>
        {valor}
      </div>
      <div className="text-[10px] uppercase tracking-wider text-ink-3 mt-1 truncate">{rotulo}</div>
    </div>
  );
}

export default function ListaAgentes({ plataformaDisponivel }) {
  const [agentes, setAgentes] = useState([]);
  const [catalogo, setCatalogo] = useState(null);
  const [provedores, setProvedores] = useState([]);
  const [conexoes, setConexoes] = useState([]);
  const [departamentos, setDepartamentos] = useState([]);
  const [busca, setBusca] = useState("");
  const [editando, setEditando] = useState(null); // objeto do agente, ou "novo"
  const [testando, setTestando] = useState(null);
  const [treinando, setTreinando] = useState(null);
  const [vendoPrompt, setVendoPrompt] = useState(null);

  const carregar = () => api.get("/ai/agents").then((r) => setAgentes(r.data));

  useEffect(() => {
    carregar().catch(() => {});
    api.get("/ai/agents/catalog").then((r) => setCatalogo(r.data)).catch(() => {});
    api.get("/ai/providers").then((r) => setProvedores(r.data.provedores)).catch(() => {});
    api.get("/whatsapp/connections").then((r) => setConexoes(r.data)).catch(() => {});
    api.get("/departments").then((r) => setDepartamentos(r.data)).catch(() => {});
  }, []);

  const remover = async (a) => {
    if (!(await confirmToast(
      `Excluir o ${t("agente")} "${a.nome}"? As conversas que ele atende passam a cair na fila humana.`,
      { confirmLabel: "Excluir" }))) return;
    try {
      await api.delete(`/ai/agents/${a.id}`);
      setAgentes((as) => as.filter((x) => x.id !== a.id));
      toast.success(`${t("Agente")} excluído.`);
    } catch (ex) {
      toast.error(formatApiErrorDetail(ex.response?.data?.detail));
    }
  };

  const alternarAtivo = async (a) => {
    try {
      // O PATCH recebe o agente inteiro (é um PUT disfarçado), mas sem os
      // campos que o servidor controla nem os contadores calculados na leitura.
      const { id, tenant_id, created_at, updated_at, conversas, mascara, tem_chave,
              credencial_status, credencial_erro, credencial_em, ...resto } = a;
      const { data } = await api.patch(`/ai/agents/${a.id}`, { ...resto, ativo: !a.ativo });
      setAgentes((as) => as.map((x) => (x.id === a.id ? { ...data, conversas } : x)));
    } catch (ex) {
      toast.error(formatApiErrorDetail(ex.response?.data?.detail));
    }
  };

  const filtrados = useMemo(() => {
    const q = busca.trim().toLowerCase();
    if (!q) return agentes;
    return agentes.filter((a) =>
      [a.nome, a.empresa_nome, a.tipo].filter(Boolean).some((c) => c.toLowerCase().includes(q)));
  }, [agentes, busca]);

  const rotuloTipo = (a) => catalogo?.tipos.find((t) => t.id === a.tipo)?.rotulo || a.tipo;

  const rotuloModelo = (a) => {
    if (!a.provedor) return plataformaDisponivel ? "IA inclusa" : null;
    const p = provedores.find((x) => x.id === a.provedor);
    return p?.modelos.find((m) => m.id === a.modelo)?.rotulo || a.modelo;
  };

  /** Por que este agente não conseguiria responder agora. `null` = tudo certo.
   *  Fica no cartão, e não num aviso geral da página, porque a credencial é de
   *  cada agente: um pode estar pronto e o outro com a chave revogada. */
  const problema = (a) => {
    if (a.credencial_status === "erro") return "A chave de IA parou de funcionar";
    if (!a.tem_chave && !plataformaDisponivel) return "Sem chave de IA configurada";
    return null;
  };
  const rotuloTom = (id) => catalogo?.tons.find((t) => t.id === id)?.rotulo || id;

  const resumo = (a) => {
    if (a.tipo === "personalizado" && a.objetivo) return a.objetivo;
    const base = catalogo?.tipos.find((t) => t.id === a.tipo)?.descricao || "";
    return a.empresa_nome ? `${base} Atende pela ${a.empresa_nome}.` : base;
  };

  const canais = (a) => {
    if (!a.conexoes?.length) return "Todas as conexões";
    const nomes = conexoes.filter((c) => a.conexoes.includes(c.id)).map((c) => c.nome);
    return nomes.length ? nomes.join(", ") : `${a.conexoes.length} conexão(ões)`;
  };

  return (
    <div className="mt-6" data-testid="lista-agentes">
      {/* Sem título nem descrição próprios: o cabeçalho da página já diz que
          isto é a lista de agentes de IA e para que eles servem, e um segundo
          "Agentes / Quem atende automaticamente" logo abaixo era a mesma frase
          duas vezes. Do cabeçalho sobrou o que informa: quantos são e a busca. */}
      {agentes.length > 0 && (
        <div className="flex items-center gap-3 mb-4">
          <span className="text-sm text-ink-3 shrink-0" data-testid="agentes-total">
            {agentes.length} {agentes.length === 1 ? t("agente") : t("agentes")}
          </span>
          {agentes.length > 2 && (
            <div className="relative ml-auto w-full max-w-xs">
              <MagnifyingGlass size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-4" />
              <input className="zz-input pl-9" placeholder={`Buscar ${t("agentes")}…`}
                value={busca} onChange={(e) => setBusca(e.target.value)}
                data-testid="buscar-agente" />
            </div>
          )}
        </div>
      )}

      {/* Grade */}
      {agentes.length === 0 ? (
        <div className="zz-panel p-12 flex flex-col items-center text-center gap-3">
          <div className="w-14 h-14 rounded-2xl bg-brand-soft text-ink flex items-center justify-center">
            <Robot size={26} weight="bold" />
          </div>
          <div className="font-heading text-lg font-bold tracking-tight">Nenhum {t("agente")} ainda</div>
          <p className="text-ink-2 text-sm max-w-sm">
            Em três passos você define quem responde, com que tom, e até onde ele vai antes de
            chamar uma pessoa.
          </p>
          <button className="zz-btn mt-1" disabled={!catalogo} onClick={() => setEditando("novo")}>
            <Plus size={16} weight="bold" /> Criar o primeiro {t("agente")}
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
          {filtrados.map((a) => {
            const ligado = a.ativo && a.modo !== "desligado";
            const c = a.conversas || { atendendo: 0, transferidas: 0, total: 0 };
            return (
              <div key={a.id} className="zz-panel p-5 flex flex-col gap-4"
                data-testid={`agente-${a.id}`}>
                {/* Identidade */}
                <div className="flex items-start gap-3">
                  <div className="relative shrink-0">
                    <div className={`w-11 h-11 rounded-full flex items-center justify-center font-heading text-lg font-bold ${
                      ligado ? "bg-brand text-brand-fg" : "bg-surface-3 text-ink-3"
                    }`}>
                      {(a.nome || "?").trim().charAt(0).toUpperCase()}
                    </div>
                    <span className={`absolute -bottom-0.5 -right-0.5 w-3.5 h-3.5 rounded-full border-2 border-surface ${
                      ligado ? "bg-success-solid" : "bg-line-strong"
                    }`} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="font-bold truncate">{a.nome}</div>
                    <div className="text-xs text-ink-3 truncate">
                      {rotuloTipo(a)}{rotuloModelo(a) ? ` · ${rotuloModelo(a)}` : ""}
                    </div>
                  </div>
                  <MenuAcoes
                    onEditar={() => setEditando(a)}
                    onPrompt={() => setVendoPrompt(a)}
                    onExcluir={() => remover(a)}
                  />
                </div>

                <p className="text-sm text-ink-2 line-clamp-3 min-h-[3.75rem]">{resumo(a)}</p>

                {/* Números reais: saem de uma agregação sobre as conversas que
                    este agente atendeu, não de contador decorativo. */}
                <div className="flex items-start gap-3 py-3 border-y border-line">
                  <Numero valor={c.atendendo} rotulo="atendendo" destaque={c.atendendo > 0} />
                  <div className="w-px self-stretch bg-line" />
                  <Numero valor={c.transferidas} rotulo="transferidas" />
                  <div className="w-px self-stretch bg-line" />
                  <Numero valor={c.total} rotulo="no total" />
                </div>

                <div>
                  <div className="text-[10px] font-bold uppercase tracking-wider text-ink-3 mb-2">
                    Comportamento
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    <span className="px-2 py-1 rounded-full bg-surface-2 border border-line text-[11px] text-ink-2">
                      {modoRotulo()[a.modo] || a.modo}
                    </span>
                    {(a.tom || []).map((t) => (
                      <span key={t}
                        className="px-2 py-1 rounded-full bg-surface-2 border border-line text-[11px] text-ink-2">
                        {rotuloTom(t)}
                      </span>
                    ))}
                  </div>
                </div>

                <div className="flex items-center gap-1.5 text-xs text-ink-3">
                  <PlugsConnected size={14} />
                  <span className="truncate">{canais(a)}</span>
                </div>

                {problema(a) && (
                  <div className="flex items-start gap-2 rounded-lg border border-warning/40 bg-warning-soft p-2.5 text-[11px] text-warning">
                    <Warning size={14} weight="bold" className="shrink-0 mt-px" />
                    <span>{problema(a)} — as conversas continuam indo para a fila humana.</span>
                  </div>
                )}

                {/* Ações */}
                <div className="mt-auto space-y-2">
                  <div className="flex gap-2">
                    <button className="zz-btn zz-btn-secondary flex-1 justify-center"
                      onClick={() => alternarAtivo(a)} data-testid={`agente-pausar-${a.id}`}>
                      {a.ativo ? "Pausar" : "Ativar"}
                    </button>
                    <button className="zz-btn flex-1 justify-center"
                      onClick={() => setEditando(a)} data-testid={`agente-editar-${a.id}`}>
                      Configurar
                    </button>
                  </div>
                  <div className="flex gap-2">
                    <button className="zz-btn zz-btn-secondary flex-1 justify-center"
                      onClick={() => setTreinando(a)} data-testid={`agente-treinar-${a.id}`}>
                      <Brain size={15} weight="bold" /> Treinar
                      {(a.memoria || []).length > 0 && (
                        <span className="text-[11px] text-ink-3 font-normal">({a.memoria.length})</span>
                      )}
                    </button>
                    <button className="zz-btn zz-btn-secondary flex-1 justify-center"
                      onClick={() => setTestando(a)} data-testid={`agente-testar-${a.id}`}>
                      <ChatCircleDots size={15} weight="bold" /> Testar
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
          {filtrados.length === 0 ? (
            <div className="col-span-full zz-panel p-8 text-center text-sm text-ink-3">
              Nenhum {t("agente")} encontrado para “{busca}”.
            </div>
          ) : (
            // O criar vive aqui, e não no cabeçalho: fica ao lado do que já
            // existe, no fim da leitura, em vez de competir com o título.
            <button type="button" disabled={!catalogo}
              onClick={() => setEditando("novo")} data-testid="novo-agente-btn"
              className="rounded-2xl border border-dashed border-line-strong text-ink-3
                         min-h-56 flex flex-col items-center justify-center gap-2
                         hover:border-info hover:text-info hover:bg-info-soft
                         disabled:opacity-45 transition-colors">
              <Plus size={22} weight="bold" />
              <span className="text-sm font-bold">Criar {t("agente")}</span>
            </button>
          )}
        </div>
      )}

      {editando && catalogo && (
        <AgenteWizard
          catalogo={catalogo}
          provedores={provedores}
          plataformaDisponivel={plataformaDisponivel}
          conexoes={conexoes}
          departamentos={departamentos}
          agente={editando === "novo" ? null : editando}
          onFechar={() => setEditando(null)}
          onSalvo={() => { setEditando(null); carregar(); }}
        />
      )}
      {treinando && (
        <TreinarAgente
          agente={treinando}
          onFechar={() => setTreinando(null)}
          onMudou={() => carregar().catch(() => {})}
          onTestar={() => { setTestando(treinando); setTreinando(null); }}
        />
      )}
      {testando && <ChatTeste agente={testando} onFechar={() => setTestando(null)} />}
      {vendoPrompt && <VerPrompt agente={vendoPrompt} onFechar={() => setVendoPrompt(null)} />}
    </div>
  );
}
