import { useEffect, useState } from "react";
import { toast } from "sonner";
import { ArrowSquareOut, Copy, WhatsappLogo } from "@phosphor-icons/react";
import api, { formatApiErrorDetail } from "@/lib/api";
import { useAcao } from "@/hooks/useAcao";
import { useAuth } from "@/context/AuthContext";

// Catálogo público: o estoque num link para mandar ao cliente (ver
// backend/catalogo.py). A página pública é montada pelo servidor em /c/<slug>;
// aqui fica a configuração dela.

export async function copiar(texto, aviso = "Link copiado") {
  try {
    await navigator.clipboard.writeText(texto);
    toast.success(aviso);
  } catch {
    toast.error("Não foi possível copiar. Selecione o link e copie à mão.");
  }
}

function Campo({ label, hint, children }) {
  return (
    <label className="block">
      <span className="text-xs font-bold text-ink-2">{label}</span>
      <div className="mt-1.5">{children}</div>
      {hint && <span className="block text-[11px] text-ink-3 mt-1">{hint}</span>}
    </label>
  );
}

export default function CatalogoPage() {
  const { user } = useAuth();
  const admin = user?.role === "tenant_admin";
  const [cfg, setCfg] = useState(null);
  const [form, setForm] = useState(null);

  const aplicar = (data) => {
    setCfg(data);
    setForm({
      ativo: data.ativo, slug: data.slug, nome: data.nome, whatsapp: data.whatsapp,
      endereco: data.endereco, mostrar_preco: data.mostrar_preco, texto_whatsapp: data.texto_whatsapp,
    });
  };

  useEffect(() => {
    api.get("/catalogo").then((r) => aplicar(r.data))
      .catch((ex) => toast.error(formatApiErrorDetail(ex.response?.data?.detail) || ex.message));
  }, []);

  const [salvar, salvando] = useAcao(async (ev) => {
    ev?.preventDefault?.();
    try {
      const { data } = await api.put("/catalogo", form);
      aplicar(data);
      toast.success(data.ativo ? "Catálogo no ar" : "Configuração salva");
    } catch (ex) {
      toast.error(formatApiErrorDetail(ex.response?.data?.detail) || ex.message);
    }
  });

  const set = (campo) => (e) =>
    setForm({ ...form, [campo]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  const noAr = cfg?.ativo && cfg?.link;
  const compartilhar = noAr
    ? `https://wa.me/?text=${encodeURIComponent(`Veja os carros disponíveis na ${cfg.nome}: ${cfg.link}`)}`
    : null;

  return (
    <div className="zz-page-form" data-testid="catalogo-page">
      <div className="mb-7">
        <h1 className="font-heading text-4xl font-semibold tracking-tight">Catálogo</h1>
        <p className="text-ink-3 mt-2 text-sm max-w-xl">
          O estoque num link para mandar ao cliente: fotos, ficha e preço de cada carro, com o botão que
          abre o WhatsApp da loja. Só os carros disponíveis e reservados aparecem; placa e localização no
          pátio nunca saem.
        </p>
      </div>

      {!cfg || !form ? <div className="text-sm text-ink-3">Carregando…</div> : (
        <>
          <section className={`rounded-2xl border p-5 mb-5 ${noAr ? "border-success bg-success-soft" : "border-line bg-surface"}`}
            data-testid="catalogo-status">
            {noAr ? (
              <>
                <div className="text-xs font-bold text-success">No ar</div>
                <div className="flex flex-wrap items-center gap-2 mt-2">
                  <a href={cfg.link} target="_blank" rel="noopener noreferrer"
                    className="font-mono text-sm break-all underline decoration-dotted" data-testid="catalogo-link">{cfg.link}</a>
                </div>
                <div className="flex flex-wrap gap-2 mt-3">
                  <button type="button" className="zz-btn h-9" onClick={() => copiar(cfg.link)} data-testid="catalogo-copiar">
                    <Copy size={14} /> Copiar link
                  </button>
                  <a className="zz-btn zz-btn-secondary h-9" href={compartilhar} target="_blank" rel="noopener noreferrer">
                    <WhatsappLogo size={14} /> Mandar no WhatsApp
                  </a>
                  <a className="zz-btn zz-btn-secondary h-9" href={cfg.link} target="_blank" rel="noopener noreferrer">
                    <ArrowSquareOut size={14} /> Abrir
                  </a>
                </div>
                <p className="text-xs text-ink-3 mt-3">
                  Para mandar um carro só, abra o carro no Estoque e use "Copiar link".
                </p>
              </>
            ) : (
              <div className="text-sm text-ink-2">
                {cfg.configurado ? "O catálogo está desligado: o link não abre." : "O catálogo ainda não foi ligado."}
                {!admin && " Peça ao administrador para ligar."}
              </div>
            )}
          </section>

          {admin && (
            <form onSubmit={salvar} className="rounded-2xl border border-line bg-surface p-5 grid grid-cols-1 sm:grid-cols-2 gap-4"
              data-testid="catalogo-form">
              <div className="sm:col-span-2">
                <Campo label="Endereço do catálogo" hint="Letras minúsculas, números e hífen. Mudar o endereço quebra os links já enviados.">
                  <div className="flex items-stretch">
                    <span className="hidden sm:flex items-center px-3 rounded-l-[10px] border border-r-0 border-line bg-surface-2 text-xs text-ink-3 font-mono">
                      {cfg.prefixo}
                    </span>
                    <input className="zz-input h-9 w-full sm:rounded-l-none font-mono" value={form.slug} onChange={set("slug")}
                      required data-testid="catalogo-slug" />
                  </div>
                </Campo>
              </div>
              <Campo label="Nome da loja" hint="Aparece no topo do catálogo e na prévia do link.">
                <input className="zz-input h-9 w-full" value={form.nome} onChange={set("nome")} required maxLength={80} />
              </Campo>
              <Campo label="WhatsApp da loja" hint="Com DDD. É para onde vai o botão &quot;Tenho interesse&quot;.">
                <input className="zz-input h-9 w-full" value={form.whatsapp} onChange={set("whatsapp")} inputMode="tel"
                  placeholder="(85) 99999-8888" data-testid="catalogo-whatsapp" />
              </Campo>
              <div className="sm:col-span-2">
                <Campo label="Endereço da loja" hint="Opcional. Aparece embaixo do nome.">
                  <input className="zz-input h-9 w-full" value={form.endereco} onChange={set("endereco")} maxLength={160}
                    placeholder="Av. Central, 100 · Fortaleza" />
                </Campo>
              </div>
              <div className="sm:col-span-2">
                <Campo label="Mensagem do botão de interesse"
                  hint="{carro} vira o nome do carro e {link}, o link dele. O cliente pode editar antes de mandar.">
                  <textarea className="zz-input w-full min-h-[70px]" value={form.texto_whatsapp} onChange={set("texto_whatsapp")}
                    maxLength={400} />
                </Campo>
              </div>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={form.mostrar_preco} onChange={set("mostrar_preco")} />
                Mostrar os preços
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={form.ativo} onChange={set("ativo")} data-testid="catalogo-ativo" />
                Catálogo no ar
              </label>
              <div className="sm:col-span-2 flex justify-end">
                <button type="submit" className="zz-btn h-10" disabled={salvando} data-testid="catalogo-salvar">
                  {salvando ? "Salvando…" : "Salvar"}
                </button>
              </div>
            </form>
          )}
        </>
      )}
    </div>
  );
}
