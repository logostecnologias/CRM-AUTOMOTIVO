import { useState, useEffect } from "react";
import { X, Trash, Plus } from "@phosphor-icons/react";
import api from "@/lib/api";
import {
  NODE_TYPES, MENU_FORMATOS, LIMITES_MENU, validarMenu,
  FORMATO_TEXTO, FORMATO_LISTA, GATILHOS,
} from "./nodeTypes";

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
    // O id nasce aqui e nunca muda: ele é o `sourceHandle` da aresta que sai
    // desta opção e, nos formatos interativos, é também o id do botão/linha
    // que volta no webhook quando o contato toca. Regerá-lo ao editar o
    // rótulo cortaria a ligação com a saída do nó.
    opts.push({ id: `opt_${Date.now()}_${i}`, label: `Opção ${i + 1}`, descricao: "" });
    update({ options: opts });
  };

  const removeOption = (idx) => {
    const opts = [...(data.options || [])];
    opts.splice(idx, 1);
    update({ options: opts });
  };

  return (
    <div className="w-[340px] border-l border-line-strong bg-surface flex flex-col h-full" data-testid="node-config-panel">
      <div className="flex items-center justify-between px-4 py-3 border-b border-line-strong">
        <div>
          <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-ink-3">Configuração</div>
          <div className="font-heading text-lg font-black tracking-tight">{meta.label}</div>
        </div>
        <button data-testid="close-config" onClick={onClose} className="p-1.5 hover:bg-surface-2">
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
                {GATILHOS.map((g) => (
                  <option key={g.valor} value={g.valor}>{g.opcao}</option>
                ))}
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

        {node.type === "menu" && (() => {
          const formato = data.formato || FORMATO_TEXTO;
          const interativo = formato !== FORMATO_TEXTO;
          const lista = formato === FORMATO_LISTA;
          const problemas = validarMenu(data);
          const tetoOpcoes = lista ? LIMITES_MENU.itensLista : LIMITES_MENU.botoes;
          const tetoRotulo = lista ? LIMITES_MENU.rotuloItem : LIMITES_MENU.rotuloBotao;
          const opcoes = data.options || [];
          const meta = MENU_FORMATOS.find((f) => f.valor === formato);
          return (
            <>
              <Field label="Como o menu aparece no WhatsApp" hint={meta?.ajuda}>
                <select className="zz-input" value={formato} data-testid="config-menu-formato"
                  onChange={(e) => update({ formato: e.target.value })}>
                  {MENU_FORMATOS.map((f) => (
                    <option key={f.valor} value={f.valor}>{f.label}</option>
                  ))}
                </select>
              </Field>

              {problemas.length > 0 && (
                <div className="text-xs bg-danger border border-danger text-ink p-3 rounded-lg space-y-1"
                  data-testid="config-menu-problemas">
                  <div className="font-bold">Assim a mensagem não chega ao contato:</div>
                  {problemas.map((prob, i) => <div key={i}>· {prob}</div>)}
                  <div className="text-ink-2">
                    O WhatsApp descarta a mensagem sem avisar. Enquanto não for corrigido,
                    o fluxo não publica e o menu sai como texto numerado.
                  </div>
                </div>
              )}

              {interativo && (
                <Field label="Título (opcional)" hint="Linha em destaque acima da pergunta.">
                  <input className="zz-input" value={data.titulo || ""}
                    onChange={(e) => update({ titulo: e.target.value })}
                    data-testid="config-menu-titulo" />
                </Field>
              )}

              <Field label="Pergunta">
                <textarea rows={3} className="zz-input" value={data.text || ""}
                  onChange={(e) => update({ text: e.target.value })} />
              </Field>

              {lista && (
                <Field label="Texto do botão que abre a lista"
                  hint={`Aparece no lugar de "Ver opções". Até ${LIMITES_MENU.botaoLista} caracteres.`}>
                  <input className="zz-input" value={data.botao_texto || ""}
                    maxLength={LIMITES_MENU.botaoLista}
                    onChange={(e) => update({ botao_texto: e.target.value })}
                    placeholder="Ver opções" data-testid="config-menu-botao-texto" />
                </Field>
              )}

              {interativo && (
                <Field label="Rodapé (opcional)" hint="Linha pequena no pé da mensagem.">
                  <input className="zz-input" value={data.rodape || ""}
                    onChange={(e) => update({ rodape: e.target.value })}
                    data-testid="config-menu-rodape" />
                </Field>
              )}

              <div>
                <div className="flex items-center justify-between mb-2">
                  <div className="text-xs font-bold uppercase tracking-wider text-ink-2">Opções</div>
                  {interativo && (
                    <div className={`text-[11px] font-mono ${opcoes.length > tetoOpcoes ? "text-danger font-bold" : "text-ink-3"}`}>
                      {opcoes.length}/{tetoOpcoes}
                    </div>
                  )}
                </div>
                <div className="space-y-2">
                  {opcoes.map((o, i) => {
                    const rotulo = o.label || "";
                    const longo = interativo && rotulo.length > tetoRotulo;
                    return (
                      <div key={o.id || i} className="flex gap-2 items-start">
                        <span className="text-xs font-mono text-ink-3 w-6 pt-3">{i + 1}.</span>
                        <div className="flex-1 space-y-1">
                          <input className={`zz-input ${longo ? "border-danger" : ""}`} value={rotulo}
                            onChange={(e) => updateOption(i, { label: e.target.value })}
                            data-testid={`config-option-${i}`} />
                          {interativo && (
                            <div className={`text-[10px] font-mono text-right ${longo ? "text-danger font-bold" : "text-ink-4"}`}>
                              {rotulo.length}/{tetoRotulo}
                            </div>
                          )}
                          {lista && (
                            <input className="zz-input text-xs" value={o.descricao || ""}
                              maxLength={LIMITES_MENU.descItem}
                              onChange={(e) => updateOption(i, { descricao: e.target.value })}
                              placeholder="Descrição (opcional)"
                              data-testid={`config-option-desc-${i}`} />
                          )}
                        </div>
                        <button onClick={() => removeOption(i)}
                          className="p-3 border border-line hover:border-danger hover:text-danger rounded-lg">
                          <Trash size={14} />
                        </button>
                      </div>
                    );
                  })}
                </div>
                <button onClick={addOption} className="zz-btn zz-btn-secondary mt-3" data-testid="add-option">
                  <Plus size={14} weight="bold" /> Adicionar opção
                </button>
              </div>

              <Field label="Mensagem de Resposta Inválida"
                hint="Vale também nos formatos com botão: o contato pode digitar em vez de tocar.">
                <input className="zz-input" value={data.invalid_message || ""}
                  onChange={(e) => update({ invalid_message: e.target.value })} />
              </Field>
            </>
          );
        })()}

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
          <div className="text-xs text-ink-2 bg-surface-2 border border-line p-4 rounded-lg">
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

      <div className="border-t border-line p-3">
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
      <label className="text-xs font-bold uppercase tracking-wider text-ink-2 block mb-1.5">{label}</label>
      {children}
      {hint && <div className="text-[11px] text-ink-3 mt-1">{hint}</div>}
    </div>
  );
}
