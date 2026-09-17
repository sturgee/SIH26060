// Waits for the HTML layout to load, then activates the browser redirection path
document.addEventListener("DOMContentLoaded", () => {
  const backBtn = document.getElementById("btnPrevPage");
  if (backBtn) {
    backBtn.addEventListener("click", () => {
      window.location.href = "/"; // Instantly drops back to your root dashboard view path
    });
  }
});
