const levelSelect = document.getElementById("level");
const backendUrlInput = document.getElementById("backendUrl");
const status = document.getElementById("status");

chrome.storage.local.get(["level", "backendUrl"], ({ level, backendUrl }) => {
  if (level) levelSelect.value = level;
  if (backendUrl) backendUrlInput.value = backendUrl;
});

document.getElementById("save").addEventListener("click", () => {
  const level = levelSelect.value;
  const backendUrl = backendUrlInput.value.trim();
  chrome.storage.local.set({ level, backendUrl }, () => {
    status.textContent = "Saved.";
    setTimeout(() => (status.textContent = ""), 1500);
  });
});
