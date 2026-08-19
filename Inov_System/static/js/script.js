/* ==========================================================================
   INOV System — comportamentos de tela
   ========================================================================== */

/* --------------------------------------------------------------------------
   Diálogos
   -------------------------------------------------------------------------- */

function openModal(id) {
    const modal = document.getElementById(id);
    if (!modal) return;

    modal.classList.add("show");
    document.body.style.overflow = "hidden";

    const primeiro = modal.querySelector("input:not([type=hidden]), select, textarea");
    if (primeiro) primeiro.focus();
}

function closeModal(id) {
    const modal = document.getElementById(id);
    if (!modal) return;

    modal.classList.remove("show");
    document.body.style.overflow = "";
}

function fecharTodosModais() {
    document.querySelectorAll(".modal.show").forEach((m) => m.classList.remove("show"));
    document.body.style.overflow = "";
}

// Clique no fundo escuro fecha
document.addEventListener("click", (evento) => {
    if (evento.target.classList.contains("modal")) fecharTodosModais();
});

document.addEventListener("keydown", (evento) => {
    if (evento.key === "Escape") fecharTodosModais();
});

/* --------------------------------------------------------------------------
   Filtro de tabela no navegador

   A tabela declara data-filter-table; cada linha traz data-busca com o texto
   pesquisável e um data-<campo> por filtro de select. Os controles ficam em
   qualquer lugar do mesmo .card.
   -------------------------------------------------------------------------- */

// "Serviços" e "servicos" precisam casar — tira acento e caixa antes de comparar.
// O normalize("NFD") separa a letra do acento; o \p{Diacritic} descarta o acento.
function normalizar(texto) {
    return (texto || "")
        .toString()
        .normalize("NFD")
        .replace(/\p{Diacritic}/gu, "")
        .toLowerCase()
        .trim();
}

function montarFiltro(tabela) {
    const escopo = tabela.closest(".card") || document;
    const campoBusca = escopo.querySelector("[data-filter-input]");
    const seletores = Array.from(escopo.querySelectorAll("[data-filter-select]"));
    const contador = escopo.querySelector("[data-filter-count]");
    const linhaVazia = tabela.querySelector("[data-filter-empty]");

    const linhas = Array.from(tabela.querySelectorAll("tbody tr")).filter(
        (linha) => !linha.hasAttribute("data-filter-empty")
    );

    if (!campoBusca && !seletores.length) return;

    // Texto normalizado só uma vez por linha, não a cada tecla.
    const indice = linhas.map((linha) => normalizar(linha.dataset.busca));

    function aplicar() {
        const termo = normalizar(campoBusca ? campoBusca.value : "");
        let visiveis = 0;

        linhas.forEach((linha, i) => {
            let combina = !termo || indice[i].includes(termo);

            if (combina) {
                for (const seletor of seletores) {
                    const campo = seletor.dataset.filterSelect;
                    const alvo = seletor.value;
                    if (alvo && linha.dataset[campo] !== alvo) {
                        combina = false;
                        break;
                    }
                }
            }

            linha.classList.toggle("is-hidden", !combina);
            if (combina) visiveis++;
        });

        if (contador) contador.textContent = visiveis;
        if (linhaVazia) linhaVazia.hidden = visiveis > 0;
    }

    if (campoBusca) campoBusca.addEventListener("input", aplicar);
    seletores.forEach((seletor) => seletor.addEventListener("change", aplicar));
}

/* --------------------------------------------------------------------------
   Abas

   Cada botão traz data-tab-target com o id do painel que deve aparecer.
   Botões e painéis do mesmo grupo ficam dentro do mesmo .card.
   -------------------------------------------------------------------------- */

function montarAbas(botao) {
    botao.addEventListener("click", () => {
        const escopo = botao.closest(".card") || document;

        escopo.querySelectorAll("[data-tab-target]").forEach((outro) => {
            const painel = document.getElementById(outro.dataset.tabTarget);
            const selecionado = outro === botao;

            outro.classList.toggle("active", selecionado);
            if (painel) painel.hidden = !selecionado;
        });
    });
}

/* --------------------------------------------------------------------------
   Máscaras
   -------------------------------------------------------------------------- */

function mascararCnpj(valor) {
    let digitos = valor.replace(/\D/g, "").slice(0, 14);

    return digitos
        .replace(/^(\d{2})(\d)/, "$1.$2")
        .replace(/^(\d{2})\.(\d{3})(\d)/, "$1.$2.$3")
        .replace(/\.(\d{3})(\d)/, ".$1/$2")
        .replace(/(\d{4})(\d)/, "$1-$2");
}

/* --------------------------------------------------------------------------
   Inicialização
   -------------------------------------------------------------------------- */

document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-filter-table]").forEach(montarFiltro);
    document.querySelectorAll("[data-tab-target]").forEach(montarAbas);

    const campoCnpj = document.getElementById("cnpj");
    if (campoCnpj) {
        campoCnpj.addEventListener("input", (evento) => {
            evento.target.value = mascararCnpj(evento.target.value);
        });
    }

    // Campo de dinheiro: seleciona tudo ao focar, para trocar o valor sem apagar
    // dígito por dígito. A conversão de vírgula/ponto é feita no servidor.
    document.querySelectorAll(".money-input").forEach((campo) => {
        campo.addEventListener("focus", () => campo.select());
    });
});
