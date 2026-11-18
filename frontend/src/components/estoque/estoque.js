import { API } from "@/lib/api";

/**
 * O que as telas do estoque compartilham: rótulos, formatos e a foto.
 *
 * As listas fechadas (câmbio, combustível, categoria...) vêm do backend em
 * `/estoque/opcoes`. As daqui são só o reserva para o primeiro desenho, antes
 * de a resposta chegar, e têm de ser as mesmas de `routes/estoque.py`.
 */
export const OPCOES_PADRAO = {
  cambio: [["manual", "Manual"], ["automatico", "Automático"], ["cvt", "CVT"], ["automatizado", "Automatizado"]],
  combustivel: [["flex", "Flex"], ["gasolina", "Gasolina"], ["etanol", "Etanol"], ["diesel", "Diesel"],
    ["hibrido", "Híbrido"], ["eletrico", "Elétrico"], ["gnv", "GNV"]],
  categoria: [["hatch", "Hatch"], ["sedan", "Sedã"], ["suv", "SUV"], ["picape", "Picape"],
    ["minivan", "Minivan"], ["esportivo", "Esportivo"], ["utilitario", "Utilitário"], ["moto", "Moto"]],
  condicao: [["novo", "Novo"], ["seminovo", "Seminovo"], ["usado", "Usado"]],
  status: [["disponivel", "Disponível"], ["reservado", "Reservado"], ["vendido", "Vendido"]],
};

// O que veio da API, por cima do reserva: uma lista que falte (ou uma resposta
// estranha) não pode deixar um `<select>` sem opções nem derrubar a tela.
export const deApi = (resp) => {
  const saida = { ...OPCOES_PADRAO };
  if (resp && typeof resp === "object" && !Array.isArray(resp)) {
    Object.entries(resp).forEach(([k, lista]) => {
      if (Array.isArray(lista) && lista.length) saida[k] = lista.map((o) => [o.valor, o.rotulo]);
    });
  }
  return saida;
};

export const rotulo = (opcoes, campo, valor) =>
  (opcoes[campo] || []).find(([v]) => v === valor)?.[1] || "";

// As marcas mais vendidas no Brasil, para o campo sugerir enquanto se digita.
// Sugestão, não lista fechada: marca nova entra digitando.
export const MARCAS_SUGERIDAS = [
  "Audi", "BMW", "BYD", "Caoa Chery", "Chevrolet", "Citroën", "Fiat", "Ford", "GWM", "Honda",
  "Hyundai", "Jeep", "Kia", "Land Rover", "Mercedes-Benz", "Mitsubishi", "Nissan", "Peugeot",
  "Porsche", "RAM", "Renault", "Toyota", "Volkswagen", "Volvo",
];

export const fotoUrl = (id) => `${API}/media/${id}`;

export const nomeVeiculo = (v) => [v.marca, v.modelo].filter(Boolean).join(" ");

export const formatPreco = (n) =>
  n || n === 0
    ? Number(n).toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 })
    : "Sob consulta";

export const formatKm = (n) => (n || n === 0 ? `${Number(n).toLocaleString("pt-BR")} km` : null);

export const formatAno = (v) => {
  if (v.ano_fabricacao && v.ano_modelo && v.ano_fabricacao !== v.ano_modelo) return `${v.ano_fabricacao}/${v.ano_modelo}`;
  return String(v.ano_modelo || v.ano_fabricacao || "");
};

export const formatPlaca = (p) => (p && p.length === 7 ? `${p.slice(0, 3)}${/\d/.test(p[4]) ? "-" : ""}${p.slice(3)}` : p);

export const diasNoPatio = (d) => {
  if (d === null || d === undefined) return "";
  if (d === 0) return "Entrou hoje";
  return `${d} ${d === 1 ? "dia" : "dias"} no pátio`;
};

/**
 * Comprime a foto antes de subir: celular tira foto de 4000px e 6MB, e a
 * vitrine não precisa de mais que 1600px. Subir menor é muito mais rápido na
 * loja, que costuma ter internet fraca no pátio. Os parâmetros são os mesmos
 * do servidor (`FOTO_LADO_MAX`, `FOTO_QUALIDADE` em routes/estoque.py), que
 * comprime de novo por garantia: assim a segunda passada quase não mexe.
 * Se o navegador não conseguir ler a imagem (HEIC no Windows, por exemplo),
 * sobe a original e o servidor resolve.
 */
export async function reduzirImagem(arquivo, maximo = 1600, qualidade = 0.85) {
  if (!arquivo.type.startsWith("image/") || arquivo.type === "image/gif") return arquivo;
  try {
    // `imageOrientation: "from-image"` aplica a rotação do EXIF ao desenhar,
    // senão a foto de celular sai deitada.
    const bitmap = await createImageBitmap(arquivo, { imageOrientation: "from-image" });
    const escala = Math.min(1, maximo / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * escala);
    canvas.height = Math.round(bitmap.height * escala);
    const ctx = canvas.getContext("2d");
    // Fundo branco: PNG transparente não vira carro sobre fundo preto.
    ctx.fillStyle = "#FFFFFF";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise((ok) => canvas.toBlob(ok, "image/jpeg", qualidade));
    // Comprimir não pode piorar: se a original já era menor, vai ela.
    if (!blob || (blob.size >= arquivo.size && escala === 1)) return arquivo;
    const nome = arquivo.name.replace(/\.[^.]+$/, "") + ".jpg";
    return new File([blob], nome, { type: "image/jpeg" });
  } catch {
    return arquivo;
  }
}

/** O "de" riscado: só quando é maior que o preço de agora. */
export const temPromocao = (v) => !!(v.preco_anterior && v.preco && v.preco_anterior > v.preco);
