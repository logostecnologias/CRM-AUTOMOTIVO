import { useEffect, useState } from "react";
import { toast } from "sonner";
import { UsersThree } from "@phosphor-icons/react";
import api from "@/lib/api";
import { useAcao } from "@/hooks/useAcao";
import { t } from "@/lib/textos";

// Aviso no grupo de WhatsApp da equipe quando um negócio entra numa etapa
// (ver backend/aviso_grupo.py). Fica em Ajustes, ao lado da Conversions API,
// porque os dois são "o que acontece quando o negócio anda".
//
// O número que avisa é o de uma conexão WuzAPI, e ele precisa estar no grupo:
// a tela aceita o link de convite (o que o cliente tem) e também lista os
// grupos em que o número já está.

const sem = (s) => (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

export default function AvisoGrupo({ Bloco, Campo }) {
  const [cfg, setCfg] = useState(null);
  const [form, setForm] = useState(null);
  const [grupos, setGrupos] = useState(null);
  const [link, setLink] = useState("");

  const aplicar = (data) => {
    setCfg(data);
    let etapas = data.etapas;
    if (!etapas.length) {
      // Sugestão para quem ainda não escolheu: a etapa de visita agendada.
      const sugerida = data.etapas_funil.find((e) => sem(e.nome).includes("visita") && sem(e.nome).includes("agend"));
      etapas = sugerida ? [sugerida.id] : [];
    }
    setForm({
      ativo: data.ativo,
      connection_id: data.connection_id || data.conexoes[0]?.id || "",
      grupo_jid: data.grupo_jid || "",
      grupo_nome: data.grupo_nome || "",
      etapas,
    });
  };

  useEffect(() => {
    api.get("/aviso-grupo").then((r) => aplicar(r.data)).catch(() => setCfg(false));
  }, []);

  const [carregarGrupos, carregando] = useAcao(async () => {
    try {
      const r = await api.get("/aviso-grupo/grupos", { params: { connection_id: form.connection_id } });
      setGrupos(r.data);
      if (!r.data.length) toast.info("Esse número ainda não está em nenhum grupo. Use o link de convite abaixo.");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Não foi possível listar os grupos");
    }
  });

  const [entrar, entrando] = useAcao(async () => {
    try {
      const r = await api.post("/aviso-grupo/entrar", { connection_id: form.connection_id, link });
      setGrupos(r.data.grupos);
      if (r.data.jid) {
        setForm((f) => ({ ...f, grupo_jid: r.data.jid, grupo_nome: r.data.nome || f.grupo_nome }));
        toast.success(`Número adicionado ao grupo${r.data.nome ? ` "${r.data.nome}"` : ""}. Agora é só salvar.`);
      } else {
        toast.success("Pedido de entrada enviado. Escolha o grupo na lista quando ele aparecer.");
      }
      setLink("");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Não foi possível entrar no grupo");
    }
  });

  const [salvar, salvando] = useAcao(async (ev) => {
    ev?.preventDefault?.();
    try {
      const r = await api.put("/aviso-grupo", form);
      aplicar(r.data);
      toast.success(form.ativo ? "Aviso no grupo ligado" : "Configuração salva");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Não foi possível salvar");
    }
  });

  const [testar, testando] = useAcao(async () => {
    try {
      await api.post("/aviso-grupo/teste");
      toast.success("Mensagem de teste enviada ao grupo");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Falha no teste");
    }
  });

  if (cfg === false) return null;

  return (
    <Bloco icone={UsersThree} titulo="Aviso no grupo da equipe"
      hint={`Quando um ${t("negócio")} entra numa das etapas escolhidas (ex.: Visita agendada), o sistema manda no grupo de WhatsApp da equipe: ${t("contato")}, carro, valor, horário e quem registrou. Vale para tudo que move o ${t("negócio")}: o ${t("agente de IA")}, o funil e os botões da conversa.`}>
      {!cfg || !form ? <div className="text-sm text-ink-3">Carregando…</div> : cfg.conexoes.length === 0 ? (
        <div className="text-sm text-ink-2">
          Precisa de uma conexão de WhatsApp pelo QR code (WuzAPI). A API oficial do WhatsApp não envia mensagem para grupo.
        </div>
      ) : (
        <form onSubmit={salvar} className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Campo label="Número que avisa" hint="Ele precisa estar no grupo.">
            <select className="zz-input h-9" value={form.connection_id} data-testid="aviso-conexao"
              onChange={(e) => { setForm({ ...form, connection_id: e.target.value, grupo_jid: "", grupo_nome: "" }); setGrupos(null); }}>
              {cfg.conexoes.map((c) => (
                <option key={c.id} value={c.id}>{c.nome || c.numero || c.id}{c.numero ? ` · ${c.numero}` : ""}</option>
              ))}
            </select>
          </Campo>
          <Campo label="Grupo"
            hint={form.grupo_jid ? `Escolhido: ${form.grupo_nome || form.grupo_jid}` : "Nenhum grupo escolhido ainda."}>
            {grupos ? (
              <select className="zz-input h-9" value={form.grupo_jid} data-testid="aviso-grupo"
                onChange={(e) => {
                  const g = grupos.find((x) => x.jid === e.target.value);
                  setForm({ ...form, grupo_jid: e.target.value, grupo_nome: g?.nome || "" });
                }}>
                <option value="">Escolha o grupo…</option>
                {form.grupo_jid && !grupos.some((g) => g.jid === form.grupo_jid) && (
                  <option value={form.grupo_jid}>{form.grupo_nome || form.grupo_jid}</option>
                )}
                {grupos.map((g) => <option key={g.jid} value={g.jid}>{g.nome}</option>)}
              </select>
            ) : (
              <button type="button" className="zz-btn zz-btn-secondary h-9 w-full" onClick={carregarGrupos}
                disabled={carregando || !form.connection_id} data-testid="aviso-carregar">
                {carregando ? "Buscando…" : "Buscar os grupos deste número"}
              </button>
            )}
          </Campo>
          <div className="sm:col-span-2">
            <Campo label="O número ainda não está no grupo?"
              hint="Cole o link de convite (Grupo → Convidar via link). Se o grupo exige aprovação, um admin precisa aceitar.">
              <div className="flex gap-2">
                <input className="zz-input h-9 flex-1" value={link} placeholder="https://chat.whatsapp.com/…"
                  data-testid="aviso-link" onChange={(e) => setLink(e.target.value)} />
                <button type="button" className="zz-btn zz-btn-secondary h-9" onClick={entrar}
                  disabled={entrando || !link.trim()} data-testid="aviso-entrar">
                  {entrando ? "Entrando…" : "Entrar no grupo"}
                </button>
              </div>
            </Campo>
          </div>
          <div className="sm:col-span-2">
            <Campo label="Avisar quando entrar em">
              <div className="flex flex-wrap gap-x-4 gap-y-2 pt-1">
                {cfg.etapas_funil.map((e) => (
                  <label key={e.id} className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={form.etapas.includes(e.id)}
                      onChange={(ev) => setForm({
                        ...form,
                        etapas: ev.target.checked ? [...form.etapas, e.id] : form.etapas.filter((x) => x !== e.id),
                      })} />
                    {e.nome}
                  </label>
                ))}
              </div>
            </Campo>
          </div>
          <Campo label="Envio">
            <label className="flex items-center gap-2 text-sm pt-2">
              <input type="checkbox" checked={form.ativo} data-testid="aviso-ativo"
                onChange={(e) => setForm({ ...form, ativo: e.target.checked })} />
              Avisar no grupo
            </label>
          </Campo>
          <div className="text-xs text-ink-3 self-end">
            {cfg.ultimo_erro
              ? <span className="text-danger">Último erro: {cfg.ultimo_erro}</span>
              : cfg.ultimo_envio ? `Último aviso: ${new Date(cfg.ultimo_envio).toLocaleString("pt-BR")}` : null}
          </div>
          <div className="sm:col-span-2 flex justify-end gap-2">
            <button type="button" className="zz-btn zz-btn-secondary" onClick={testar}
              disabled={testando || !cfg.grupo_jid} data-testid="aviso-testar"
              title={cfg.grupo_jid ? "" : "Salve o grupo primeiro"}>
              {testando ? "Enviando…" : "Enviar teste"}
            </button>
            <button type="submit" className="zz-btn" disabled={salvando} data-testid="aviso-salvar">
              {salvando ? "Salvando…" : "Salvar"}
            </button>
          </div>
        </form>
      )}
    </Bloco>
  );
}
