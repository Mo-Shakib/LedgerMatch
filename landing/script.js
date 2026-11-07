(() => {
  const button = document.querySelector(".copy-button");
  const label = button ? button.querySelector(".copy-label") : null;
  const status = document.getElementById("copy-status");
  const target = button
    ? document.querySelector(button.getAttribute("data-copy-target"))
    : null;

  if (!button || !label || !target) {
    return;
  }

  const resetLabel = () => {
    window.setTimeout(() => {
      label.textContent = "Copy";
      button.classList.remove("is-copied");
    }, 1800);
  };

  const fallbackCopy = (text) => {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.className = "copy-fallback";
    document.body.appendChild(textarea);
    textarea.select();
    const copied = document.execCommand("copy");
    document.body.removeChild(textarea);
    if (!copied) {
      throw new Error("Copy command was unavailable.");
    }
  };

  button.addEventListener("click", async () => {
    const text = target.innerText.trim();

    try {
      let copied = false;

      if (navigator.clipboard && window.isSecureContext) {
        try {
          await navigator.clipboard.writeText(text);
          copied = true;
        } catch (error) {
          copied = false;
        }
      }

      if (!copied) {
        fallbackCopy(text);
      }

      label.textContent = "Copied";
      button.classList.add("is-copied");
      if (status) {
        status.textContent = "Setup commands copied to the clipboard.";
      }
      resetLabel();
    } catch (error) {
      const selection = window.getSelection();
      if (selection) {
        const range = document.createRange();
        range.selectNodeContents(target);
        selection.removeAllRanges();
        selection.addRange(range);
      }
      label.textContent = "Select";
      button.classList.remove("is-copied");
      if (status) {
        status.textContent = "Copy unavailable. The commands have been selected for manual copying.";
      }
      resetLabel();
    }
  });
})();
