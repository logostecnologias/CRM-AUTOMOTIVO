import { createContext, Fragment, useContext, useEffect, useState } from "react";
import api from "@/lib/api";
import { aplicar as aplicarMarca, guardada as marcaGuardada } from "@/lib/marca";

const AuthContext = createContext(null);

function readCookie(name) {
  const m = document.cookie.match(new RegExp("(^| )" + name + "=([^;]+)"));
  return m ? decodeURIComponent(m[2]) : null;
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [impersonatedFrom, setImpersonatedFrom] = useState(null); // "super_admin" if active
  // Começa na marca guardada no navegador (já pintada em `index.js`) e é
  // corrigida pela que o servidor devolve. No logout ela fica: a próxima tela
  // é o login, e quem usa este navegador é cliente da mesma marca.
  const [marca, setMarca] = useState(marcaGuardada);
  const trocarMarca = (m) => setMarca(aplicarMarca(m).id);

  const refresh = () => {
    return api
      .get("/auth/me")
      .then((r) => {
        setUser(r.data);
        trocarMarca(r.data.marca);
        setImpersonatedFrom(readCookie("impersonated_role"));
      })
      .catch(() => setUser(false));
  };

  useEffect(() => {
    refresh().finally(() => setLoading(false));
  }, []);

  const login = async (email, password) => {
    const { data } = await api.post("/auth/login", { email, password });
    setUser(data);
    trocarMarca(data.marca);
    setImpersonatedFrom(null);
    return data;
  };

  const logout = async () => {
    try { await api.post("/auth/logout"); } catch {}
    setUser(false);
    setImpersonatedFrom(null);
  };

  const exitImpersonation = async () => {
    await api.post("/auth/exit-impersonation");
    setImpersonatedFrom(null);
    await refresh();
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, refresh, exitImpersonation, impersonatedFrom, marca }}>
      {/* A chave remonta a árvore quando a marca muda (login, modo suporte):
          é o que faz o texto de `lib/textos.js`, lido da marca pintada no
          `<html>`, valer em toda tela já aberta. A troca só acontece nessas
          fronteiras, onde a tela muda de qualquer jeito. */}
      <Fragment key={marca}>{children}</Fragment>
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
