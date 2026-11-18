import { t } from "./textos";

const comMarca = (marca) => { document.documentElement.dataset.marca = marca; };

describe("vocabulário do AUTO", () => {
  afterEach(() => { delete document.documentElement.dataset.marca; });

  test("contato vira cliente, e a maiúscula é derivada", () => {
    expect(t("contato")).toBe("cliente");
    expect(t("Contatos")).toBe("Clientes");
    expect(t("Contato")).toBe("Cliente");
  });

  test("o vocabulário é o mesmo nas duas marcas", () => {
    comMarca("logos");
    const logos = [t("Contatos"), t("Funil")];
    comMarca("r3");
    expect([t("Contatos"), t("Funil")]).toEqual(logos);
  });

  test("chave fora do dicionário passa intacta", () => {
    expect(t("Funil")).toBe("Funil");
    expect(t("qualquer frase")).toBe("qualquer frase");
  });
});
