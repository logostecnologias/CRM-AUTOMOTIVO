import { useEffect, useState } from "react";
import api, { formatApiErrorDetail } from "@/lib/api";

// Os modelos aprovados da conta da Meta, para quem escreve primeiro (telefone,
// formulário de site). Na conexão não oficial não existe modelo, e a mensagem
// sai sempre como texto livre.
//
// `primeiraVariavel` é o valor sugerido para {{1}} ao escolher o modelo, e
// `dica` diz quais marcadores a tela aceita: cada tela tem os seus.
export default function EscolhaDeModelo({ conexao, template, onChange, primeiraVariavel = "", dica, testId }) {
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
      variaveis: Array.from({ length: m.variaveis }, (_, i) => (i === 0 ? primeiraVariavel : "")),
    });
  };
  const escolhido = (modelos || []).find((m) => m.nome === template.nome && m.idioma === template.idioma);

  return (
    <div className="space-y-3">
      <div>
        <label className="text-xs font-bold uppercase tracking-wider text-ink-2 block mb-1.5">Modelo aprovado</label>
        <select className="zz-input" data-testid={testId}
          value={template.nome ? `${template.nome}|${template.idioma}` : ""}
          onChange={(e) => escolher(e.target.value)}>
          <option value="">{modelos === null && !erro ? "Carregando…" : "Nenhum (só texto livre)"}</option>
          {(modelos || []).map((m) => (
            <option key={`${m.nome}|${m.idioma}`} value={`${m.nome}|${m.idioma}`}>
              {m.nome} ({m.idioma}) · {String(m.categoria || "").toLowerCase()}
            </option>
          ))}
        </select>
        <p className="text-[11px] text-ink-3 mt-1">
          {erro || "Cadastrado no painel da Meta. Prefira a categoria Utilidade: Marketing custa cerca de 8 vezes mais."}
        </p>
      </div>
      {escolhido?.corpo && (
        <div className="text-xs text-ink-2 bg-surface-2 rounded-lg p-3 whitespace-pre-wrap">{escolhido.corpo}</div>
      )}
      {(template.variaveis || []).map((v, i) => (
        <div key={i}>
          <label className="text-xs font-bold uppercase tracking-wider text-ink-2 block mb-1.5">{`Variável {{${i + 1}}}`}</label>
          <input className="zz-input font-mono text-xs" value={v}
            onChange={(e) => onChange({
              ...template,
              variaveis: template.variaveis.map((x, k) => (k === i ? e.target.value : x)),
            })} />
          {i === 0 && dica && <p className="text-[11px] text-ink-3 mt-1">{dica}</p>}
        </div>
      ))}
    </div>
  );
}
