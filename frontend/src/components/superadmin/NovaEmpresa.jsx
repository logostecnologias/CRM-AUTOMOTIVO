import { useEffect, useRef, useState } from "react";
import api from "@/lib/api";
import { useAcao } from "@/hooks/useAcao";
import { SENHA_MIN, copiar, gerarSenha } from "@/components/superadmin/comum";
import { MARCAS, PADRAO as MARCA_PADRAO, valida as validaMarca } from "@/lib/marca";
import { toast } from "sonner";
import {
  ArrowsClockwise, Buildings, CheckCircle, Copy, Eye, EyeSlash,
  SignIn, Warning, WhatsappLogo, X,
} from "@phosphor-icons/react";

/**
 * Criação de empresa em duas partes: o formulário e a entrega do acesso.
 *
 * A segunda parte é o motivo de isto ser um modal e não o formulário inline de
 * antes. A senha inicial não volta do servidor nunca mais (`users` guarda só o
 * hash), então o único momento em que ela existe para ser passada ao cliente é
 * agora. Fechar direto no toast, como era, empurrava esse repasse para a
 * memória de quem criou.
 */
export default function NovaEmpresa({ onFechar, onCriada, onEntrar }) {
  const [form, setForm] = useState({
    name: "", admin_name: "", admin_email: "", admin_password: "",
    marca: MARCA_PADRAO,
  });
  const [verSenha, setVerSenha] = useState(false);
  const [erroEmail, setErroEmail] = useState("");
  const [criada, setCriada] = useState(null);
  const emailRef = useRef(null);

  // Esc fecha só enquanto é formulário. Na tela de acesso ele fica desligado de
  // propósito: um Esc distraído ali leva embora a única cópia da senha.
  useEffect(() => {
    if (criada) return undefined;
    const aoTeclar = (e) => { if (e.key === "Escape") onFechar(); };
    window.addEventListener("keydown", aoTeclar);
    return () => window.removeEventListener("keydown", aoTeclar);
  }, [criada, onFechar]);

  const [criar, criando] = useAcao(async (e) => {
    e.preventDefault();
    setErroEmail("");
    try {
      const { data } = await api.post("/admin/tenants", form);
      setCriada({ tenant: data, ...form });
      onCriada();
    } catch (ex) {
      const detalhe = ex.response?.data?.detail;
      const msg = typeof detalhe === "string" ? detalhe : "Erro ao criar empresa";
      // E-mail repetido é o erro que aparece aqui na prática, e ele tem um
      // campo para apontar. Mensagem no rodapé obrigava a procurar qual dos
      // cinco campos estava errado.
      if (/email/i.test(msg)) {
        setErroEmail(msg);
        emailRef.current?.focus();
      }
      toast.error(msg);
    }
  });

  if (criada) {
    return (
      <Moldura titulo="Empresa criada" icone={CheckCircle} onFechar={onFechar} travado>
        <Acesso dados={criada} onFechar={onFechar} onEntrar={onEntrar} />
      </Moldura>
    );
  }

  return (
    <Moldura titulo="Nova empresa" icone={Buildings} onFechar={onFechar}>
      <form onSubmit={criar} className="flex flex-col min-h-0 flex-1" data-testid="tenant-form">
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-6">
          <Campo label="Nome da empresa">
            <input required autoFocus data-testid="tenant-name" className="zz-input"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </Campo>

          <div>
            <Titulo>Marca do painel</Titulo>
            <p className="text-xs text-ink-3 mb-3">
              É o que o cliente vê ao entrar: cores, logo e nome na aba do navegador. Dá para
              trocar depois, na ficha da empresa.
            </p>
            <SeletorMarca valor={form.marca} onChange={(marca) => setForm({ ...form, marca })} />
          </div>

          <div>
            <Titulo>Admin da empresa</Titulo>
            <p className="text-xs text-ink-3 mb-3">
              É esta pessoa que entra no painel e configura o resto. Ela pode criar os outros
              usuários (vendedores, atendentes) depois.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <Campo label="Nome">
                <input required data-testid="admin-name" className="zz-input" autoComplete="off"
                  value={form.admin_name}
                  onChange={(e) => setForm({ ...form, admin_name: e.target.value })} />
              </Campo>
              <Campo label="E-mail" erro={erroEmail}>
                <input required type="email" data-testid="admin-email" className="zz-input"
                  ref={emailRef} autoComplete="off" placeholder="admin@empresa.com.br"
                  value={form.admin_email}
                  onChange={(e) => { setErroEmail(""); setForm({ ...form, admin_email: e.target.value }); }} />
              </Campo>
            </div>

            <div className="mt-4">
              <Campo label="Senha inicial">
                <div className="flex gap-2">
                  <div className="relative flex-1">
                    <input required data-testid="admin-password" className="zz-input pr-10"
                      // `new-password` impede o gerenciador do navegador de
                      // oferecer a credencial do próprio super admin neste
                      // campo, que é o que acontecia com o autocomplete solto.
                      type={verSenha ? "text" : "password"} autoComplete="new-password"
                      minLength={SENHA_MIN} value={form.admin_password}
                      onChange={(e) => setForm({ ...form, admin_password: e.target.value })} />
                    <button type="button" onClick={() => setVerSenha(!verSenha)}
                      title={verSenha ? "Esconder" : "Mostrar"}
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-ink-3 hover:text-ink p-1">
                      {verSenha ? <EyeSlash size={16} weight="bold" /> : <Eye size={16} weight="bold" />}
                    </button>
                  </div>
                  <button type="button" data-testid="gerar-senha" className="zz-btn zz-btn-secondary"
                    onClick={() => { setForm({ ...form, admin_password: gerarSenha() }); setVerSenha(true); }}>
                    <ArrowsClockwise size={14} weight="bold" /> Gerar
                  </button>
                </div>
                <div className="text-[11px] text-ink-3 mt-1.5">
                  Mínimo de {SENHA_MIN} caracteres. Ninguém é obrigado a trocá-la no primeiro
                  acesso, então é ela que o cliente vai usar: prefira a gerada.
                </div>
              </Campo>
            </div>
          </div>
        </div>

        <div className="border-t border-line px-6 py-4 flex justify-end gap-2">
          <button type="button" onClick={onFechar} className="zz-btn zz-btn-secondary">Cancelar</button>
          <button type="submit" data-testid="tenant-submit" className="zz-btn" disabled={criando}>
            {criando ? "Criando…" : "Criar empresa"}
          </button>
        </div>
      </form>
    </Moldura>
  );
}

// Um cartão por marca, com a amostra das cores: o nome sozinho ("r3") não diz
// ao super admin o que o cliente vai ver.
function SeletorMarca({ valor, onChange }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3" role="radiogroup" data-testid="tenant-marca">
      {Object.values(MARCAS).map((m) => {
        const ativo = valor === m.id;
        return (
          <button key={m.id} type="button" role="radio" aria-checked={ativo}
            data-testid={`tenant-marca-${m.id}`} onClick={() => onChange(m.id)}
            className={`text-left rounded-lg border px-4 py-3 transition-colors ${
              ativo ? "border-info ring-1 ring-info bg-info-soft" : "border-line hover:border-line-strong"}`}>
            <div className="flex items-center justify-between gap-3">
              <span className="font-semibold text-sm">{m.nome}</span>
              <span className="flex gap-1">
                {m.amostra.map((cor) => (
                  // A amostra é a cor da marca em si, e é o único lugar em que
                  // um hex no `style` é o dado, não decoração do tema.
                  <span key={cor} className="w-4 h-4 rounded-md border border-line" style={{ background: cor }} />
                ))}
              </span>
            </div>
            <div className="text-xs text-ink-3 mt-1">{m.descricao}</div>
          </button>
        );
      })}
    </div>
  );
}

/**
 * O acesso do cliente, uma vez só. Daqui não se volta para o formulário: a
 * empresa já existe, e o que resta é entregar a credencial e abrir o caminho do
 * próximo passo real (conectar o WhatsApp), que é o que ficava esquecido.
 */
function Acesso({ dados, onFechar, onEntrar }) {
  const { tenant } = dados;
  const endereco = `${window.location.origin}/login`;
  const bloco = [
    `Acesso ao painel ${tenant.name}`,
    `Endereço: ${endereco}`,
    `E-mail: ${dados.admin_email}`,
    `Senha: ${dados.admin_password}`,
  ].join("\n");

  return (
    <>
      <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
        <div className="flex items-start gap-3 rounded-lg border border-warning bg-warning-soft px-4 py-3">
          <Warning size={18} weight="fill" className="text-warning shrink-0 mt-0.5" />
          <div className="text-sm text-ink-2">
            <b className="text-ink">Copie a senha agora.</b> O sistema guarda só o hash dela, então
            esta é a última vez que ela aparece. Se sair sem copiar, dá para definir outra na
            ficha da empresa, aba Equipe.
          </div>
        </div>

        <div className="border border-line rounded-lg divide-y divide-line" data-testid="acesso-criado">
          <Linha rotulo="Empresa" valor={tenant.name} />
          <Linha rotulo="Marca" valor={MARCAS[validaMarca(tenant.marca)].nome} />
          <Linha rotulo="Endereço" valor={endereco} />
          <Linha rotulo="E-mail" valor={dados.admin_email} mono />
          <Linha rotulo="Senha" valor={dados.admin_password} mono destaque />
        </div>

        <button type="button" className="zz-btn zz-btn-secondary w-full justify-center"
          data-testid="copiar-acesso"
          onClick={() => copiar(bloco, "Acesso copiado. Já pode colar para o cliente.")}>
          <Copy size={14} weight="bold" /> Copiar acesso completo
        </button>

        <div>
          <Titulo>Próximo passo</Titulo>
          <p className="text-xs text-ink-3 mb-3">
            A empresa nasce vazia: sem conexão de WhatsApp ela não recebe mensagem nenhuma, e
            nenhum robô roda.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <Atalho icone={WhatsappLogo} titulo="Conectar o WhatsApp"
              nota="Entra na empresa e abre a tela de conexões, para ler o QR agora."
              onClick={() => onEntrar(tenant, "/app/whatsapp")} />
            <Atalho icone={SignIn} titulo="Entrar na empresa"
              nota="Modo suporte, no painel do cliente, para configurar o resto."
              onClick={() => onEntrar(tenant, "/app")} />
          </div>
        </div>
      </div>

      <div className="border-t border-line px-6 py-4 flex justify-end">
        <button type="button" className="zz-btn" onClick={onFechar} data-testid="acesso-concluir">
          Concluir
        </button>
      </div>
    </>
  );
}

function Linha({ rotulo, valor, mono, destaque }) {
  return (
    <div className="flex items-center gap-3 px-4 py-2.5">
      <span className="text-[10px] font-bold uppercase tracking-wider text-ink-3 w-24 shrink-0">{rotulo}</span>
      <span className={`text-sm flex-1 break-all ${mono ? "font-mono" : ""} ${destaque ? "font-bold" : ""}`}>
        {valor}
      </span>
      <button type="button" title="Copiar" className="zz-btn-icon shrink-0"
        onClick={() => copiar(valor, `${rotulo} copiado`)}>
        <Copy size={14} weight="bold" />
      </button>
    </div>
  );
}

function Atalho({ icone: Icone, titulo, nota, onClick }) {
  return (
    <button type="button" onClick={onClick}
      className="text-left border border-line rounded-lg px-4 py-3 hover:border-info hover:bg-info-soft transition-colors">
      <div className="flex items-center gap-2 font-semibold text-sm">
        <Icone size={16} weight="bold" /> {titulo}
      </div>
      <div className="text-xs text-ink-3 mt-1">{nota}</div>
    </button>
  );
}

// A moldura do modal. `travado` esconde o X: na entrega do acesso a saída é
// pelo "Concluir", pelo mesmo motivo que o Esc fica desligado ali.
function Moldura({ titulo, icone: Icone, children, onFechar, travado }) {
  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
      <div className="bg-surface border border-line rounded-2xl w-full max-w-2xl max-h-[92vh] flex flex-col shadow-pop"
        data-testid="nova-empresa-modal">
        <div className="flex items-center justify-between px-6 py-4 border-b border-line">
          <h2 className="font-heading text-xl font-black tracking-tighter flex items-center gap-2">
            <Icone size={20} weight="bold" /> {titulo}
          </h2>
          {!travado && (
            <button type="button" onClick={onFechar} className="zz-btn-icon" title="Fechar">
              <X size={18} weight="bold" />
            </button>
          )}
        </div>
        {children}
      </div>
    </div>
  );
}

function Campo({ label, erro, children }) {
  return (
    <div>
      <label className="text-xs font-bold uppercase tracking-wider text-ink-2 block mb-1.5">{label}</label>
      {children}
      {erro && <div className="text-xs text-danger mt-1.5">{erro}</div>}
    </div>
  );
}

function Titulo({ children }) {
  return (
    <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-ink-3 mb-2">{children}</div>
  );
}
