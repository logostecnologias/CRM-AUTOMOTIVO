import { useRef, useState } from "react";
import api, { formatApiErrorDetail } from "@/lib/api";
import { toast } from "sonner";
import {
  UploadSimple, DownloadSimple, X, Warning, CheckCircle, ArrowRight,
} from "@phosphor-icons/react";

const ALVOS = [
  ["", "— não importar —"],
  ["nome", "Nome"],
  ["numero_whatsapp", "WhatsApp"],
  ["email", "E-mail"],
  ["empresa", "Empresa"],
  ["cargo", "Cargo"],
  ["origem", "Origem"],
  ["tags", "Etiquetas"],
  ["responsavel_email", "Responsável (e-mail)"],
];

export default function ImportExport({ filtros, onClose, onImportou }) {
  const [arquivo, setArquivo] = useState(null);
  const [previa, setPrevia] = useState(null);
  const [mapa, setMapa] = useState({});
  const [duplicados, setDuplicados] = useState("ignorar");
  const [ocupado, setOcupado] = useState(false);
  const entradaRef = useRef(null);

  const exportar = async () => {
    setOcupado(true);
    try {
      // Baixado por blob e não por link direto: assim o erro do servidor
      // aparece como mensagem, em vez de o navegador abrir uma aba com JSON.
      const r = await api.get("/contacts/export", { params: filtros, responseType: "blob" });
      const url = URL.createObjectURL(r.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = "contatos.csv";
      a.click();
      URL.revokeObjectURL(url);
      toast.success("Exportação baixada");
    } catch {
      toast.error("Não consegui exportar agora");
    } finally {
      setOcupado(false);
    }
  };

  const enviar = async (file, mapeamento, dryRun) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("dry_run", dryRun ? "true" : "false");
    fd.append("duplicados", duplicados);
    if (mapeamento) fd.append("mapeamento", JSON.stringify(mapeamento));
    const r = await api.post("/contacts/import", fd);
    return r.data;
  };

  const escolher = async (file) => {
    if (!file) return;
    setArquivo(file);
    setOcupado(true);
    try {
      const dados = await enviar(file, null, true);
      setPrevia(dados);
      setMapa(dados.mapeamento || {});
    } catch (ex) {
      setPrevia(null);
      setArquivo(null);
      if (entradaRef.current) entradaRef.current.value = "";
      toast.error(formatApiErrorDetail(ex.response?.data?.detail));
    } finally {
      setOcupado(false);
    }
  };

  const revisar = async (novoMapa) => {
    setMapa(novoMapa);
    setOcupado(true);
    try {
      setPrevia(await enviar(arquivo, novoMapa, true));
    } catch (ex) {
      toast.error(formatApiErrorDetail(ex.response?.data?.detail));
    } finally {
      setOcupado(false);
    }
  };

  const confirmar = async () => {
    setOcupado(true);
    try {
      const r = await enviar(arquivo, mapa, false);
      toast.success(
        `${r.criados} criado(s)` +
        (r.atualizados ? `, ${r.atualizados} atualizado(s)` : "") +
        (r.ignorados ? `, ${r.ignorados} já existiam` : "")
      );
      limpar();
      onImportou?.();
    } catch (ex) {
      toast.error(formatApiErrorDetail(ex.response?.data?.detail));
    } finally {
      setOcupado(false);
    }
  };

  const limpar = () => {
    setPrevia(null);
    setArquivo(null);
    if (entradaRef.current) entradaRef.current.value = "";
  };

  const opcoes = [...ALVOS, ...(previa?.campos_disponiveis || [])
    .map((c) => [`campo:${c.id}`, `${c.nome} (personalizado)`])];

  return (
    <div className="border border-slate-900 bg-white p-5 mb-6 zz-panel-hard" data-testid="import-export">
      <div className="flex items-start justify-between mb-4">
        <div>
          <div className="font-heading text-xl font-black tracking-tighter">Importar e exportar</div>
          <p className="text-xs text-slate-600 mt-1">
            CSV separado por ponto e vírgula ou vírgula. A primeira linha precisa ser o cabeçalho
            com o nome das colunas.
          </p>
        </div>
        <div className="flex gap-2">
          <button onClick={exportar} disabled={ocupado} className="zz-btn zz-btn-secondary text-xs py-1 disabled:opacity-40"
            data-testid="exportar-btn">
            <DownloadSimple size={13} weight="bold" /> Exportar {filtros && Object.keys(filtros).length > 0 ? "o filtrado" : "tudo"}
          </button>
          <button onClick={onClose} className="p-1.5 hover:bg-slate-200"><X size={15} weight="bold" /></button>
        </div>
      </div>

      {!previa ? (
        <div className="border border-dashed border-slate-300 bg-slate-50 p-8 text-center">
          <input ref={entradaRef} type="file" accept=".csv,text/csv" className="hidden"
            data-testid="import-file" onChange={(e) => escolher(e.target.files?.[0])} />
          <UploadSimple size={26} weight="bold" className="mx-auto mb-2 text-slate-400" />
          <button onClick={() => entradaRef.current?.click()} disabled={ocupado}
            className="zz-btn disabled:opacity-40" data-testid="escolher-arquivo">
            {ocupado ? "Lendo arquivo…" : "Escolher arquivo CSV"}
          </button>
          <div className="text-[11px] text-slate-500 mt-2">
            Nada é gravado até você conferir a prévia.
          </div>
        </div>
      ) : (
        <div>
          <div className="grid grid-cols-4 gap-2 mb-4">
            {[["Linhas no arquivo", previa.linhas, "border-slate-300 bg-white"],
              ["Novos", previa.novos, "border-green-500 bg-green-50"],
              ["Já existem", previa.duplicados, "border-amber-500 bg-amber-50"],
              ["Com erro", previa.erros, previa.erros ? "border-red-500 bg-red-50" : "border-slate-300 bg-white"],
            ].map(([r, v, cls]) => (
              <div key={r} className={`border px-3 py-2 ${cls}`}>
                <div className="text-[9px] font-bold uppercase tracking-wider text-slate-600">{r}</div>
                <div className="font-heading text-xl font-black tracking-tighter">{v}</div>
              </div>
            ))}
          </div>

          <div className="mb-4">
            <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500 mb-2">
              De qual coluna vem cada campo
            </div>
            <div className="border border-slate-200">
              {previa.colunas.map((coluna) => (
                <div key={coluna} className="flex items-center gap-3 px-3 py-1.5 border-b border-slate-100 last:border-b-0">
                  <span className="text-sm font-semibold w-52 truncate" title={coluna}>{coluna}</span>
                  <ArrowRight size={12} weight="bold" className="text-slate-400 shrink-0" />
                  <select className="zz-input h-7 py-0 text-xs max-w-[240px]"
                    data-testid={`mapa-${coluna}`}
                    value={mapa[coluna] || ""}
                    onChange={(e) => revisar({ ...mapa, [coluna]: e.target.value })}>
                    {opcoes.map(([v, r]) => <option key={v} value={v}>{r}</option>)}
                  </select>
                </div>
              ))}
            </div>
          </div>

          <div className="mb-4">
            <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500 mb-2">
              Quem já está na base
            </div>
            <div className="flex gap-2">
              {[["ignorar", "Não mexer"], ["atualizar", "Atualizar os dados"]].map(([v, r]) => (
                <button key={v} onClick={() => { setDuplicados(v); }}
                  className={`px-3 py-1.5 text-xs font-bold uppercase tracking-wider border ${
                    duplicados === v ? "bg-slate-900 text-white border-slate-900" : "bg-white border-slate-300 text-slate-600"
                  }`}>
                  {r}
                </button>
              ))}
            </div>
            {duplicados === "atualizar" && (
              <div className="text-[11px] text-slate-500 mt-1.5">
                Só sobrescreve o que vem preenchido na planilha. Etiquetas são somadas, não
                substituídas.
              </div>
            )}
          </div>

          {previa.erros > 0 && (
            <div className="border-2 border-red-300 bg-red-50 p-3 mb-4">
              <div className="flex items-center gap-2 mb-2">
                <Warning size={14} weight="bold" className="text-red-700" />
                <span className="text-sm font-bold">
                  {previa.erros} linha(s) não serão importadas
                </span>
              </div>
              <div className="max-h-32 overflow-y-auto space-y-0.5">
                {previa.erros_detalhe.map((e) => (
                  <div key={e.linha} className="text-xs text-slate-700 font-mono">
                    linha {e.linha}: {e.erro}
                  </div>
                ))}
              </div>
              {previa.erros_omitidos > 0 && (
                <div className="text-[11px] text-slate-600 mt-1.5">
                  e outras {previa.erros_omitidos} não listadas aqui.
                </div>
              )}
            </div>
          )}

          {previa.amostra.length > 0 && (
            <div className="mb-4">
              <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500 mb-2">
                Como vão entrar (primeiras linhas)
              </div>
              <div className="border border-slate-200 overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-slate-200 bg-slate-50">
                      {["Nome", "WhatsApp", "E-mail", "Empresa", "Etiquetas"].map((h) => (
                        <th key={h} className="text-left px-2 py-1 font-bold uppercase tracking-wider text-[9px] text-slate-500">
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {previa.amostra.map((a, i) => (
                      <tr key={i} className="border-b border-slate-100 last:border-b-0">
                        <td className="px-2 py-1 font-semibold">{a.nome}</td>
                        <td className="px-2 py-1 font-mono">{a.numero_whatsapp}</td>
                        <td className="px-2 py-1">{a.email || "—"}</td>
                        <td className="px-2 py-1">{a.empresa || "—"}</td>
                        <td className="px-2 py-1">{(a.tags || []).join(", ") || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <div className="flex gap-2 justify-end items-center">
            <span className="text-xs text-slate-500 mr-auto">{arquivo?.name}</span>
            <button onClick={limpar} className="zz-btn zz-btn-secondary">Escolher outro</button>
            <button onClick={confirmar} disabled={ocupado || (previa.novos === 0 && duplicados === "ignorar")}
              className="zz-btn disabled:opacity-40" data-testid="confirmar-import">
              <CheckCircle size={14} weight="bold" />
              {ocupado ? "Importando…" : `Importar ${
                duplicados === "atualizar"
                  ? previa.novos + previa.duplicados
                  : previa.novos
              } contato(s)`}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
