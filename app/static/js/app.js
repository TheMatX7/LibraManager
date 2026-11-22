document.addEventListener("click", (event) => {
  const trigger = event.target.closest("[data-confirm]");
  if (trigger && !window.confirm(trigger.dataset.confirm)) {
    event.preventDefault();
  }
});

document.querySelectorAll(".alert").forEach((alert) => {
  window.setTimeout(() => alert.classList.add("fade"), 5200);
});
