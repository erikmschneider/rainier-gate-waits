const copyButton = document.querySelector("#copy-methodology-link");
const copyStatus = document.querySelector("#copy-methodology-status");
copyButton.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(window.location.href);
    copyStatus.textContent = "Methodology link copied.";
  } catch {
    const temporary = document.createElement("textarea");
    temporary.value = window.location.href;
    temporary.setAttribute("readonly", "");
    temporary.style.position = "fixed";
    temporary.style.opacity = "0";
    document.body.appendChild(temporary);
    temporary.select();
    document.execCommand("copy");
    temporary.remove();
    copyStatus.textContent = "Methodology link copied.";
  }
});
