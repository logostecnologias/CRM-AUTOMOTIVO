import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import {
  FloppyDisk, Plugs, Trash, UploadSimple, Eye, EyeSlash, CheckCircle, WarningCircle,
} from "@phosphor-icons/react";
import api, { API, formatApiErrorDetail } from "@/lib/api";
import { useAcao } from "@/hooks/useAcao";

// Ligação não atendida que vira conversa de WhatsApp.
//
// O número da empresa desvia para um número do Twilio quando ninguém atende;
// a gravação oferece "aperte 1", e a tecla abre a conversa pelo ZappZen. Tudo
// o que é do Twilio (conta, número) fica no primeiro bloco e é validado antes
// de gravar; o resto é sobre o que a pessoa ouve e o que ela recebe.

const STATUS = {
  recebida: { label: "Não apertou", classe: "bg-surface-2 text-ink-2 border-line" },
  pediu_whatsapp: { label: "Enviando…", classe: "bg-info-soft text-info border-info" },
  enviando: { label: "Enviando…", classe: "bg-info-soft text-info border-info" },
  enviada: { label: "WhatsApp enviado", classe: "bg-success-soft text-success border-success" },
  repetida: { label: "Já tinha recebido", classe: "bg-surface-2 text-ink-2 border-line" },
  sem_modelo: { label: "Sem modelo", classe: "bg-warning-soft text-warning border-warning" },
  falha: { label: "Falhou", classe: "bg-danger-soft text-danger border-danger" },
};

const MODOS = [
  ["agente", "Agente de IA", "O agente da conexão responde. Sem agente ligado, a conversa vai para a fila."],
  ["bot", "Robô", "Um robô do editor começa do nó Início."],
  ["fila", "Fila de atendimento", "Direto para a Central, para uma pessoa responder."],
];

// "Este mês" no fuso de quem olha: o corte vem do navegador, como em
// Atividades e Relatórios.
function periodoDoMes() {
  const hoje = new Date();
  const de = new Date(hoje.getFullYear(), hoje.getMonth(), 1);
  const ate = new Date(hoje.getFullYear(), hoje.getMonth() + 1, 1);
  return { de: de.toISOString(), ate: ate.toISOString() };
}

function quando(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleString("pt-BR", {
    day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}

function telefone(digitos) {
  if (!digitos) return "Número oculto";
  const d = String(digitos);
  if (d.startsWith("55") && (d.length === 12 || d.length === 13)) {
    const ddd = d.slice(2, 4);
    const resto = d.slice(4);
    return `(${ddd}) ${resto.slice(0, resto.length - 4)}-${resto.slice(-4)}`;
  }
  return `+${d}`;
}

export default function TelefonePage() {
  const [config, setConfig] = useState(null);
  const [form, setForm] = useState(null);
  const [cred, setCred] = useState({ account_sid: "", auth_token: "", numero: "" });
  const [verToken, setVerToken] = useState(false);
  const [conexoes, setConexoes] = useState([]);
  const [bots, setBots] = useState([]);
  const [resumo, setResumo] = useState(null);
  const [ligacoes, setLigacoes] = useState([]);

  const aplicar = useCallback((c) => {
    setConfig(c);
    setForm({
      ativo: !!c.ativo,
      whatsapp_connection_id: c.whatsapp_connection_id || "",
      template: c.template || { nome: "", idioma: "pt_BR", variaveis: [] },
      mensagem: c.mensagem || "",
      resposta_modo: c.resposta_modo || "agente",
      bot_id: c.bot_id || "",
      texto_pergunta: c.texto_pergunta || "",
      texto_confirmacao: c.texto_confirmacao || "",
      texto_sem_numero: c.texto_sem_numero || "",
    });
    setCred((x) => ({
      account_sid: c.account_sid || x.account_sid,
      auth_token: "",
      numero: c.numero || x.numero,
    }));
  }, []);

  const carregarHistorico = useCallback(() => {
    api.get("/voz/resumo", { params: periodoDoMes() }).then((r) => setResumo(r.data)).catch(() => {});
    api.get("/voz/ligacoes", { params: { limite: 30 } }).then((r) => setLigacoes(r.data)).catch(() => {});
  }, []);

  useEffect(() => {
    api.get("/voz/config").then((r) => aplicar(r.data))
      .catch((e) => toast.error(formatApiErrorDetail(e.response?.data?.detail)));
    api.get("/whatsapp/connections").then((r) => setConexoes(r.data)).catch(() => {});
    api.get("/bots").then((r) => setBots(r.data)).catch(() => {});
    carregarHistorico();
  }, [aplicar, carregarHistorico]);

  const [conectar, conectando] = useAcao(async () => {
    try {
      const r = await api.post("/voz/credenciais", {
        account_sid: cred.account_sid.trim(),
        auth_token: cred.auth_token.trim() || null,
        numero: cred.numero,
      });
      aplicar(r.data);
      if (r.data.aviso) toast.warning(r.data.aviso, { duration: 10000 });
      else toast.success("Conta Twilio conectada e número configurado");
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    }
  });

  const [salvar, salvando] = useAcao(async () => {
    try {
      const r = await api.put("/voz/config", {
        ...form,
        whatsapp_connection_id: form.whatsapp_connection_id || null,
        bot_id: form.resposta_modo === "bot" ? form.bot_id || null : null,
      });
      aplicar(r.data);
      toast.success("Configuração salva");
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    }
  });

  if (!config || !form) {
    return <div className="zz-page text-sm text-ink-3">Carregando…</div>;
  }

  const set = (patch) => setForm((f) => ({ ...f, ...patch }));
  const padrao = config.textos_padrao || {};
  // Sem conexão escolhida a mensagem sai pela primeira conectada; é dela que
  // vêm os modelos, então a lista acompanha a mesma regra do backend.
  const conexaoEfetiva = conexoes.find((c) => c.id === form.whatsapp_connection_id)
    || conexoes.find((c) => c.status === "conectado") || conexoes[0];

  return (
    <div className="zz-page" data-testid="telefone-page">
      <div className="mb-8">
        <h1 className="font-heading text-4xl font-black tracking-tighter">Telefone</h1>
        <p className="text-ink-2 mt-2 text-sm max-w-3xl">
          Quem liga e não é atendido ouve uma gravação. Se apertar 1, recebe uma
          mensagem no WhatsApp e a conversa continua por aqui, com o robô, o agente
          de IA ou a equipe.
        </p>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6 items-start">
        <div className="xl:col-span-2 space-y-6">
          <Bloco titulo="Conta Twilio"
            nota="Account SID e Auth Token ficam no painel do Twilio, na página inicial da conta (ou da subconta desta empresa). O número é o que foi comprado lá.">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <Campo label="Account SID">
                <input className="zz-input font-mono" data-testid="voz-sid"
                  placeholder="AC…" autoComplete="off" value={cred.account_sid}
                  onChange={(e) => setCred({ ...cred, account_sid: e.target.value })} />
              </Campo>
              <Campo label="Auth Token"
                nota={config.token_mascara ? `Guardado: ${config.token_mascara}. Em branco, mantém.` : null}>
                <div className="relative">
                  <input className="zz-input font-mono pr-10" data-testid="voz-token"
                    type={verToken ? "text" : "password"} autoComplete="new-password"
                    placeholder={config.token_mascara ? "••••••••" : ""}
                    value={cred.auth_token}
                    onChange={(e) => setCred({ ...cred, auth_token: e.target.value })} />
                  <button type="button" onClick={() => setVerToken(!verToken)}
                    className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-ink-3 hover:text-ink"
                    aria-label={verToken ? "Esconder" : "Mostrar"}>
                    {verToken ? <EyeSlash size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </Campo>
              <Campo label="Número do Twilio" nota="Com o código do país, ex.: +55 85 3333-4444.">
                <input className="zz-input font-mono" data-testid="voz-numero"
                  placeholder="+55 …" value={cred.numero}
                  onChange={(e) => setCred({ ...cred, numero: e.target.value })} />
              </Campo>
              <div className="flex items-end">
                <button className="zz-btn w-full sm:w-auto" onClick={conectar} disabled={conectando}
                  data-testid="voz-conectar">
                  <Plugs size={14} weight="bold" /> {conectando ? "Validando…" : "Validar e conectar"}
                </button>
              </div>
            </div>
            <div className="mt-4 text-sm flex items-center gap-2">
              {config.numero_configurado ? (
                <><CheckCircle size={16} weight="fill" className="text-success" />
                  <span>Número {config.numero} conectado: as ligações chegam ao ZappZen.</span></>
              ) : (
                <><WarningCircle size={16} weight="fill" className="text-warning" />
                  <span className="text-ink-2">Nenhum número conectado ainda.</span></>
              )}
            </div>
          </Bloco>

          <Bloco titulo="O que a pessoa ouve"
            nota="Grave com a sua voz: soa mais confiável que voz de robô e segura mais gente na linha. Sem áudio, a ligação usa voz sintética lendo o texto.">
            <label className="flex items-center gap-2 text-sm cursor-pointer mb-5">
              <input type="checkbox" checked={form.ativo} data-testid="voz-ativo"
                onChange={(e) => set({ ativo: e.target.checked })} />
              <span className="font-semibold">Atender as ligações com a gravação</span>
            </label>
            <div className="space-y-6">
              <Gravacao tipo="pergunta" titulo="Pergunta" config={config} onMudou={aplicar}
                texto={form.texto_pergunta} padrao={padrao.texto_pergunta}
                onTexto={(v) => set({ texto_pergunta: v })}
                dica="Precisa terminar pedindo para apertar 1." />
              <Gravacao tipo="confirmacao" titulo="Depois de apertar 1" config={config} onMudou={aplicar}
                texto={form.texto_confirmacao} padrao={padrao.texto_confirmacao}
                onTexto={(v) => set({ texto_confirmacao: v })} />
              <Campo label="Quando o número de quem liga está oculto"
                nota="Não há para quem mandar a mensagem, então a gravação só diz onde achar a empresa. Sempre em voz sintética.">
                <textarea rows={2} className="zz-input" value={form.texto_sem_numero}
                  placeholder={padrao.texto_sem_numero}
                  onChange={(e) => set({ texto_sem_numero: e.target.value })} />
              </Campo>
            </div>
          </Bloco>

          <Bloco titulo="A mensagem no WhatsApp"
            nota="Quem falou com a empresa nas últimas 24 horas recebe o texto abaixo, sem custo. Os outros só podem receber um modelo aprovado pela Meta: sem modelo, a mensagem não sai.">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <Campo label="Sai pela conexão">
                <select className="zz-input" value={form.whatsapp_connection_id}
                  data-testid="voz-conexao"
                  onChange={(e) => set({
                    whatsapp_connection_id: e.target.value,
                    template: { nome: "", idioma: "pt_BR", variaveis: [] },
                  })}>
                  <option value="">Automática (a primeira conectada)</option>
                  {conexoes.map((c) => <option key={c.id} value={c.id}>{c.nome}</option>)}
                </select>
              </Campo>
              <EscolhaDeModelo conexao={conexaoEfetiva} template={form.template}
                onChange={(t) => set({ template: t })} />
              <Campo label="Texto da mensagem" className="sm:col-span-2"
                nota="Vai como texto livre quando a janela de 24h está aberta, e é o que aparece no histórico da conversa. Use {empresa} e {numero}. Com modelo, escreva aqui o mesmo texto dele.">
                <textarea rows={3} className="zz-input" value={form.mensagem}
                  data-testid="voz-mensagem" placeholder={padrao.mensagem}
                  onChange={(e) => set({ mensagem: e.target.value })} />
              </Campo>
            </div>
          </Bloco>

          <Bloco titulo="Quem atende a resposta">
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              {MODOS.map(([valor, rotulo, nota]) => {
                const marcado = form.resposta_modo === valor;
                return (
                  <button key={valor} type="button" data-testid={`voz-modo-${valor}`}
                    onClick={() => set({ resposta_modo: valor })}
                    className={`text-left border rounded-lg p-3 transition-colors ${
                      marcado ? "border-info bg-info-soft ring-1 ring-info" : "border-line hover:bg-surface-2"}`}>
                    <div className="font-semibold text-sm">{rotulo}</div>
                    <div className="text-xs text-ink-2 mt-1">{nota}</div>
                  </button>
                );
              })}
            </div>
            {form.resposta_modo === "bot" && (
              <div className="mt-4 max-w-sm">
                <Campo label="Robô">
                  <select className="zz-input" value={form.bot_id} data-testid="voz-bot"
                    onChange={(e) => set({ bot_id: e.target.value })}>
                    <option value="">Selecione…</option>
                    {bots.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
                  </select>
                </Campo>
              </div>
            )}
          </Bloco>

          <div className="flex justify-end">
            <button className="zz-btn" onClick={salvar} disabled={salvando} data-testid="voz-salvar">
              <FloppyDisk size={14} weight="bold" /> {salvando ? "Salvando…" : "Salvar configuração"}
            </button>
          </div>
        </div>

        <div className="space-y-6">
          <Bloco titulo="Este mês">
            {resumo ? (
              <div className="grid grid-cols-2 gap-3">
                <Numero rotulo="Ligações" valor={resumo.recebidas} />
                <Numero rotulo="Apertaram 1" valor={resumo.pediram} />
                <Numero rotulo="WhatsApp enviado" valor={resumo.enviadas} />
                <Numero rotulo="Responderam" valor={resumo.responderam} />
                <Numero rotulo="Agendaram" valor={resumo.agendaram} />
                <Numero rotulo="Falhas" valor={resumo.falhas} alerta={resumo.falhas > 0} />
              </div>
            ) : <div className="text-sm text-ink-3">Carregando…</div>}
          </Bloco>

          <Bloco titulo="Como ligar o desvio"
            nota="No celular da empresa, disque o código e aperte ligar. O número é o do Twilio, com DDD.">
            <ul className="text-sm space-y-2">
              <li><span className="font-mono font-semibold">*61*número#</span>
                <span className="text-ink-2"> desvia só quando você não atende</span></li>
              <li><span className="font-mono font-semibold">*21*número#</span>
                <span className="text-ink-2"> desvia todas as ligações</span></li>
              <li><span className="font-mono font-semibold">##61#</span> ou <span className="font-mono font-semibold">##21#</span>
                <span className="text-ink-2"> desliga o desvio</span></li>
            </ul>
            <p className="text-[11px] text-ink-3 mt-3">
              Faça o primeiro teste ligando do seu próprio celular, passando pelo desvio:
              a mensagem precisa chegar no seu WhatsApp.
            </p>
          </Bloco>
        </div>
      </div>

      <section className="border border-line rounded-xl bg-surface mt-6">
        <div className="flex items-center justify-between px-5 py-4 border-b border-line">
          <h3 className="font-heading text-lg font-black tracking-tight">Últimas ligações</h3>
          <button className="zz-btn zz-btn-secondary text-xs" onClick={carregarHistorico}>Atualizar</button>
        </div>
        {ligacoes.length === 0 ? (
          <div className="p-6 text-sm text-ink-3 text-center">Nenhuma ligação recebida ainda.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wider text-ink-3">
                  <th className="px-5 py-2 font-bold">Quando</th>
                  <th className="px-5 py-2 font-bold">Quem ligou</th>
                  <th className="px-5 py-2 font-bold">Resultado</th>
                  <th className="px-5 py-2 font-bold">Respondeu</th>
                </tr>
              </thead>
              <tbody>
                {ligacoes.map((l) => {
                  const st = STATUS[l.status] || STATUS.recebida;
                  return (
                    <tr key={l.id} className="border-t border-line" data-testid={`ligacao-${l.id}`}>
                      <td className="px-5 py-2.5 font-mono text-xs text-ink-2 whitespace-nowrap">{quando(l.created_at)}</td>
                      <td className="px-5 py-2.5">
                        <div>{l.contato_nome && l.contato_nome !== l.numero ? l.contato_nome : telefone(l.numero)}</div>
                        {l.contato_nome && l.contato_nome !== l.numero && (
                          <div className="text-xs text-ink-3">{telefone(l.numero)}</div>)}
                      </td>
                      <td className="px-5 py-2.5">
                        <span className={`inline-block text-[11px] font-semibold border rounded-full px-2 py-0.5 ${st.classe}`}
                          title={l.erro || ""}>{st.label}</span>
                      </td>
                      <td className="px-5 py-2.5 text-ink-2">{l.respondeu_em ? quando(l.respondeu_em) : "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

// O arquivo de cada momento da ligação: subir, ouvir, remover. O texto ao lado
// é o que a voz sintética lê quando não há arquivo.
function Gravacao({ tipo, titulo, config, onMudou, texto, padrao, onTexto, dica }) {
  const entrada = useRef(null);
  const audio = config[`audio_${tipo}`];

  // `accept` largo de propósito: restringir a .mp3 deixaria o .ogg do WhatsApp
  // apagado no seletor do sistema, sem dizer por quê. O backend recusa o que o
  // Twilio não toca, explicando como converter.
  const [enviar, enviando] = useAcao(async (arquivo) => {
    const dados = new FormData();
    dados.append("arquivo", arquivo);
    try {
      const r = await api.post(`/voz/audio/${tipo}`, dados);
      onMudou(r.data);
      toast.success("Áudio salvo");
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    } finally {
      if (entrada.current) entrada.current.value = "";
    }
  });

  const [remover, removendo] = useAcao(async () => {
    try {
      const r = await api.delete(`/voz/audio/${tipo}`);
      onMudou(r.data);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    }
  });

  return (
    <div className="border border-line rounded-lg p-4" data-testid={`gravacao-${tipo}`}>
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <div className="font-semibold text-sm">{titulo}</div>
        <div className="flex gap-2">
          <input ref={entrada} type="file" className="hidden"
            onChange={(e) => e.target.files?.[0] && enviar(e.target.files[0])} />
          <button className="zz-btn zz-btn-secondary text-xs" disabled={enviando}
            onClick={() => entrada.current?.click()}>
            <UploadSimple size={12} weight="bold" /> {enviando ? "Enviando…" : audio ? "Trocar áudio" : "Enviar áudio"}
          </button>
          {audio && (
            <button className="zz-btn zz-btn-secondary text-xs text-danger" disabled={removendo}
              onClick={remover} aria-label="Remover áudio">
              <Trash size={12} weight="bold" />
            </button>
          )}
        </div>
      </div>
      {audio ? (
        <audio controls preload="none" className="w-full" src={`${API}/media/${audio.id}`} />
      ) : (
        <>
          <textarea rows={2} className="zz-input" value={texto} placeholder={padrao}
            onChange={(e) => onTexto(e.target.value)} />
          <p className="text-[11px] text-ink-3 mt-1">
            Sem áudio, a voz sintética lê este texto. MP3 ou WAV, até 5MB.{dica ? ` ${dica}` : ""}
          </p>
        </>
      )}
    </div>
  );
}

// Os modelos aprovados da conta da Meta. Na conexão não oficial não existe
// modelo, e a mensagem sai sempre como texto livre.
function EscolhaDeModelo({ conexao, template, onChange }) {
  const [modelos, setModelos] = useState(null);
  const [erro, setErro] = useState(null);
  const conexaoId = conexao?.id;
  const oficial = (conexao?.canal || "cloud_api") === "cloud_api";

  useEffect(() => {
    setModelos(null);
    setErro(null);
    if (!conexaoId || !oficial) return;
    api.get(`/whatsapp/connections/${conexaoId}/templates`)
      .then((r) => setModelos(r.data))
      .catch((e) => setErro(formatApiErrorDetail(e.response?.data?.detail) || "Não foi possível listar os modelos"));
  }, [conexaoId, oficial]);

  if (!conexao) {
    return (
      <div className="text-sm text-ink-2 border border-dashed border-line rounded-lg p-3">
        Conecte um número de WhatsApp primeiro.
      </div>
    );
  }
  if (!oficial) {
    return (
      <div className="text-sm text-ink-2 border border-dashed border-line rounded-lg p-3">
        Nesta conexão não há modelo: a mensagem sai sempre como texto.
      </div>
    );
  }

  const escolher = (chave) => {
    const m = (modelos || []).find((x) => `${x.nome}|${x.idioma}` === chave);
    if (!m) return onChange({ nome: "", idioma: "pt_BR", variaveis: [] });
    onChange({
      nome: m.nome, idioma: m.idioma,
      variaveis: Array.from({ length: m.variaveis }, (_, i) => (i === 0 ? "{empresa}" : "")),
    });
  };
  const escolhido = (modelos || []).find((m) => m.nome === template.nome && m.idioma === template.idioma);

  return (
    <div className="space-y-3">
      <Campo label="Modelo aprovado"
        nota={erro || "Cadastrado no painel da Meta. Prefira a categoria Utilidade: Marketing custa cerca de 8 vezes mais."}>
        <select className="zz-input" data-testid="voz-modelo"
          value={template.nome ? `${template.nome}|${template.idioma}` : ""}
          onChange={(e) => escolher(e.target.value)}>
          <option value="">{modelos === null && !erro ? "Carregando…" : "Nenhum (só texto livre)"}</option>
          {(modelos || []).map((m) => (
            <option key={`${m.nome}|${m.idioma}`} value={`${m.nome}|${m.idioma}`}>
              {m.nome} ({m.idioma}) · {String(m.categoria || "").toLowerCase()}
            </option>
          ))}
        </select>
      </Campo>
      {escolhido?.corpo && (
        <div className="text-xs text-ink-2 bg-surface-2 rounded-lg p-3 whitespace-pre-wrap">{escolhido.corpo}</div>
      )}
      {(template.variaveis || []).map((v, i) => (
        <Campo key={i} label={`Variável {{${i + 1}}}`} nota={i === 0 ? "Aceita {empresa} e {numero}." : null}>
          <input className="zz-input font-mono text-xs" value={v}
            onChange={(e) => onChange({
              ...template,
              variaveis: template.variaveis.map((x, k) => (k === i ? e.target.value : x)),
            })} />
        </Campo>
      ))}
    </div>
  );
}

function Numero({ rotulo, valor, alerta }) {
  return (
    <div className="border border-line rounded-lg p-3">
      <div className={`font-heading text-2xl font-black ${alerta ? "text-danger" : ""}`}>{valor ?? 0}</div>
      <div className="text-[11px] uppercase tracking-wider font-bold text-ink-3 mt-0.5">{rotulo}</div>
    </div>
  );
}

function Bloco({ titulo, nota, children }) {
  return (
    <section className="border border-line rounded-xl p-5 bg-surface">
      <h3 className="font-heading text-lg font-black tracking-tight">{titulo}</h3>
      {nota ? <p className="text-xs text-ink-2 mt-1 mb-4">{nota}</p> : <div className="mb-4" />}
      {children}
    </section>
  );
}

function Campo({ label, nota, className = "", children }) {
  return (
    <div className={className}>
      <label className="text-xs font-bold uppercase tracking-wider text-ink-2 block mb-1.5">{label}</label>
      {children}
      {nota && <p className="text-[11px] text-ink-3 mt-1">{nota}</p>}
    </div>
  );
}
