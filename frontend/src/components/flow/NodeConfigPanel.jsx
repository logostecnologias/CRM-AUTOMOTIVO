import { useState, useEffect } from "react";
import { X, Trash, Plus } from "@phosphor-icons/react";
import api from "@/lib/api";
import { NODE_TYPES } from "./nodeTypes";

export default function NodeConfigPanel({ node, onChange, onDelete, onClose }) {
  const [data, setData] = useState(node?.data || {});
  const [bots, setBots] = useState([]);
  const [depts, setDepts] = useState([]);
  useEffect(() => setData(node?.data || {}), [node?.id]);
  useEffect(() => {
    if (node?.type === "transfer_bot") {
      api.get("/bots").then((r) => setBots(r.data)).catch(() => {});
    }
    if (node?.type === "human_handoff") {
      api.get("/departments").then((r) => setDepts(r.data)).catch(() => {});
    }
  }, [node?.type]);

  if (!node) return null;
  const meta = NODE_TYPES[node.type] || {};

  const update = (patch) => {
    const next = { ...data, ...patch };
    setData(next);
    onChange(node.id, next);
  };

  const updateOption = (idx, patch) => {
    const opts = [...(data.options || [])];
    opts[idx] = { ...opts[idx], ...patch };
    update({ options: opts });
  };

  const addOption = () => {
    const opts = [...(data.options || [])];
    const i = opts.length;
    opts.push({ id: `opt_${Date.now()}_${i}`, label: `Opção ${i + 1}` });
    update({ options: opts });
  };

  const removeOption = (idx) => {
    const opts = [...(data.options || [])];
    opts.splice(idx, 1);
    update({ options: opts });
  };

  return (
    <div className="w-[340px] border-l border-slate-900 bg-white flex flex-col h-full" data-testid="node-config-panel">
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-900">
        <div>
          <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500">Configuração</div>
          <div className="font-heading text-lg font-black tracking-tight">{meta.label}</div>
        </div>
        <button data-testid="close-config" onClick={onClose} className="p-1.5 hover:bg-slate-100">
          <X size={18} weight="bold" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        <Field label="Título do Bloco">
          <input className="zz-input" value={data.label || ""} onChange={(e) => update({ label: e.target.value })}
            data-testid="config-label" />
        </Field>

        {node.type === "start" && (
          <>
            <Field label="Gatilho de Disparo">
              <select className="zz-input" value={data.trigger || "first_message"}
                onChange={(e) => update({ trigger: e.target.value })}>
                <option value="first_message">Primeira mensagem do contato</option>
                <option value="keyword">Palavra-chave específica</option>
                <option value="no_response">Sem resposta há X tempo</option>
              </select>
            </Field>
            {data.trigger === "keyword" && (
              <Field label="Palavra ou Frase-chave" hint="O fluxo só inicia se a mensagem do contato contiver este texto">
                <input className="zz-input" value={data.trigger_keyword || ""}
                  onChange={(e) => update({ trigger_keyword: e.target.value })}
                  placeholder="ex: promoção" data-testid="config-trigger-keyword" />
              </Field>
            )}
            {data.trigger === "no_response" && (
              <Field label="Tempo sem resposta (minutos)">
                <input type="number" min="1" className="zz-input font-mono"
                  value={data.trigger_delay_minutes || 30}
                  onChange={(e) => update({ trigger_delay_minutes: parseInt(e.target.value) || 0 })}
                  data-testid="config-trigger-delay" />
              </Field>
            )}
          </>
        )}

        {node.type === "text" && (
          <Field label="Texto da Mensagem" hint="Use {nome_contato} ou {variavel} para variáveis dinâmicas">
            <textarea rows={6} className="zz-input font-mono" value={data.text || ""}
              onChange={(e) => update({ text: e.target.value })} data-testid="config-text" />
          </Field>
        )}

        {node.type === "menu" && (
          <>
            <Field label="Pergunta">
              <textarea rows={3} className="zz-input" value={data.text || ""}
                onChange={(e) => update({ text: e.target.value })} />
            </Field>
            <div>
              <div className="text-xs font-bold uppercase tracking-wider text-slate-600 mb-2">Opções</div>
              <div className="space-y-2">
                {(data.options || []).map((o, i) => (
                  <div key={o.id || i} className="flex gap-2 items-center">
                    <span className="text-xs font-mono text-slate-500 w-6">{i + 1}.</span>
                    <input className="zz-input" value={o.label}
                      onChange={(e) => updateOption(i, { label: e.target.value })}
                      data-testid={`config-option-${i}`} />
                    <button onClick={() => removeOption(i)} className="p-2 border border-slate-300 hover:border-red-500 hover:text-red-500">
                      <Trash size={14} />
                    </button>
                  </div>
                ))}
              </div>
              <button onClick={addOption} className="zz-btn zz-btn-secondary mt-3" data-testid="add-option">
                <Plus size={14} weight="bold" /> Adicionar opção
              </button>
            </div>
            <Field label="Mensagem de Resposta Inválida">
              <input className="zz-input" value={data.invalid_message || ""}
                onChange={(e) => update({ invalid_message: e.target.value })} />
            </Field>
          </>
        )}

        {node.type === "save_variable" && (
          <>
            <Field label="Nome da Variável">
              <input className="zz-input font-mono" value={data.variable_name || ""}
                onChange={(e) => update({ variable_name: e.target.value })} />
            </Field>
            <Field label="Origem do Valor">
              <select className="zz-input" value={data.source || "last_response"}
                onChange={(e) => update({ source: e.target.value })}>
                <option value="last_response">Última resposta do contato</option>
                <option value="fixed">Valor fixo</option>
              </select>
            </Field>
            {data.source === "fixed" && (
              <Field label="Valor Fixo">
                <input className="zz-input" value={data.value || ""}
                  onChange={(e) => update({ value: e.target.value })} />
              </Field>
            )}
          </>
        )}

        {node.type === "condition" && (
          <>
            <Field label="Variável">
              <input className="zz-input font-mono" value={data.variable_name || ""}
                onChange={(e) => update({ variable_name: e.target.value })} />
            </Field>
            <Field label="Operador">
              <select className="zz-input" value={data.operator || "equals"}
                onChange={(e) => update({ operator: e.target.value })}>
                <option value="equals">É igual a</option>
                <option value="contains">Contém</option>
                <option value="greater_than">Maior que</option>
                <option value="less_than">Menor que</option>
              </select>
            </Field>
            <Field label="Valor de Comparação">
              <input className="zz-input" value={data.value || ""}
                onChange={(e) => update({ value: e.target.value })} />
            </Field>
          </>
        )}

        {node.type === "media" && (
          <>
            <Field label="Tipo de Mídia">
              <select className="zz-input" value={data.media_type || "image"}
                onChange={(e) => update({ media_type: e.target.value })}>
                <option value="image">Imagem</option>
                <option value="audio">Áudio</option>
                <option value="video">Vídeo</option>
                <option value="document">Documento</option>
              </select>
            </Field>
            <Field label="URL da Mídia">
              <input className="zz-input" value={data.url || ""}
                onChange={(e) => update({ url: e.target.value })} placeholder="https://..." />
            </Field>
            <Field label="Legenda (opcional)">
              <input className="zz-input" value={data.caption || ""}
                onChange={(e) => update({ caption: e.target.value })} />
            </Field>
          </>
        )}

        {node.type === "delay" && (
          <Field label="Segundos de espera">
            <input type="number" min="0" max="3600" className="zz-input font-mono"
              value={data.seconds || 1}
              onChange={(e) => update({ seconds: parseInt(e.target.value) || 0 })} />
          </Field>
        )}

        {node.type === "webhook" && (
          <>
            <Field label="Método">
              <select className="zz-input" value={data.method || "GET"}
                onChange={(e) => update({ method: e.target.value })}>
                <option>GET</option><option>POST</option><option>PUT</option>
              </select>
            </Field>
            <Field label="URL">
              <input className="zz-input font-mono" value={data.url || ""}
                onChange={(e) => update({ url: e.target.value })} placeholder="https://api.exemplo.com/..." />
            </Field>
            <Field label="Salvar resposta na variável">
              <input className="zz-input font-mono" value={data.response_var || ""}
                onChange={(e) => update({ response_var: e.target.value })} />
            </Field>
          </>
        )}

        {node.type === "human_handoff" && (
          <Field label="Departamento" hint="Deixe em branco para usar o departamento padrão da conexão de WhatsApp.">
            <select className="zz-input" value={data.department_id || ""}
              data-testid="config-handoff-department"
              onChange={(e) => {
                const d = depts.find((x) => x.id === e.target.value);
                update({ department_id: e.target.value, department_name: d?.nome || "" });
              }}>
              <option value="">— padrão da conexão —</option>
              {depts.map((d) => (
                <option key={d.id} value={d.id}>{d.nome}</option>
              ))}
            </select>
          </Field>
        )}

        {node.type === "end" && (
          <div className="text-xs text-slate-600 bg-slate-50 border border-slate-200 p-3">
            Este bloco não requer configuração adicional.
          </div>
        )}

        {node.type === "transfer_bot" && (
          <Field label="Bot de destino" hint="A conversa continua no fluxo do bot selecionado.">
            <select className="zz-input" value={data.target_bot_id || ""}
              data-testid="config-target-bot"
              onChange={(e) => {
                const b = bots.find((x) => x.id === e.target.value);
                update({ target_bot_id: e.target.value, target_bot_name: b?.name || "" });
              }}>
              <option value="">— selecione —</option>
              {bots.map((b) => (
                <option key={b.id} value={b.id}>{b.name} {b.status !== "ativo" ? `(${b.status})` : ""}</option>
              ))}
            </select>
          </Field>
        )}
      </div>

      <div className="border-t border-slate-200 p-3">
        {node.type !== "start" && (
          <button data-testid="delete-node" onClick={() => onDelete(node.id)}
            className="zz-btn zz-btn-danger w-full justify-center">
            <Trash size={14} weight="bold" /> Excluir Bloco
          </button>
        )}
      </div>
    </div>
  );
}

function Field({ label, hint, children }) {
  return (
    <div>
      <label className="text-xs font-bold uppercase tracking-wider text-slate-600 block mb-1.5">{label}</label>
      {children}
      {hint && <div className="text-[11px] text-slate-500 mt-1">{hint}</div>}
    </div>
  );
}
