document.addEventListener("DOMContentLoaded", () => {
  const alerts = document.querySelectorAll(".flash-message");
  alerts.forEach((alert) => {
    window.setTimeout(() => {
      alert.classList.add("is-hidden");
    }, 5000);
  });

  document.querySelectorAll("[data-phone]").forEach((phone) => {
    phone.addEventListener("click", () => {
      phone.classList.add("phone-revealed");
    });
  });

  document.querySelectorAll("[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });
});
