function openModal(id) {
    const modal = document.getElementById(id);
    if (modal) {
        modal.classList.add("show");
    }
}

function closeModal(id) {
    const modal = document.getElementById(id);
    if (modal) {
        modal.classList.remove("show");
    }
}

window.onclick = function(event) {
    document.querySelectorAll(".modal").forEach((modal) => {
        if (event.target === modal) {
            modal.classList.remove("show");
        }
    });
};

document.addEventListener("DOMContentLoaded", function() {
    const cnpjInput = document.getElementById("cnpj");

    if (cnpjInput) {
        cnpjInput.addEventListener("input", function(e) {
            let value = e.target.value.replace(/\D/g, "");

            if (value.length > 14) value = value.slice(0, 14);

            value = value.replace(/^(\d{2})(\d)/, "$1.$2");
            value = value.replace(/^(\d{2})\.(\d{3})(\d)/, "$1.$2.$3");
            value = value.replace(/\.(\d{3})(\d)/, ".$1/$2");
            value = value.replace(/(\d{4})(\d)/, "$1-$2");

            e.target.value = value;
        });
    }

    const moneyInputs = document.querySelectorAll(".money-input");
    moneyInputs.forEach((input) => {
        input.addEventListener("input", function() {
            this.value = this.value.replace(",", ".");
        });
    });
});