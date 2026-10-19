const form = document.querySelector("#generatorForm");
const modeInput = document.querySelector("#mode");
const promptInput = document.querySelector("#prompt");
const promptCount = document.querySelector("#promptCount");
const imageInput = document.querySelector("#image");
const imageField = document.querySelector("#imageField");
const imagePreview = document.querySelector("#imagePreview");
const errorBox = document.querySelector("#formError");
const generateButton = document.querySelector("#generateButton");
const grid = document.querySelector("#creationGrid");
const emptyState = document.querySelector("#emptyState");
const template = document.querySelector("#creationTemplate");
const activeJobs = new Set();
let pollingTimer;

document.querySelectorAll(".mode-tab").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".mode-tab").forEach((tab) => tab.classList.remove("active"));
    button.classList.add("active");
    modeInput.value = button.dataset.mode;
    imageField.classList.toggle("hidden", modeInput.value !== "image-to-video");
    imageInput.required = modeInput.value === "image-to-video";
  });
});

promptInput.addEventListener("input", () => {
  promptCount.textContent = promptInput.value.length;
});

imageInput.addEventListener("change", () => {
  const file = imageInput.files[0];
  if (!file) return;
  imagePreview.style.backgroundImage = `linear-gradient(#0004, #0004), url("${URL.createObjectURL(file)}")`;
  imagePreview.classList.remove("hidden");
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  errorBox.classList.add("hidden");
  generateButton.disabled = true;
  try {
    const data = new FormData(form);
    if (!data.get("seed")) data.delete("seed");
    if (modeInput.value === "text-to-video") data.delete("image");
    const response = await fetch("/api/generations", { method: "POST", body: data });
    const payload = await response.json();
    if (!response.ok) {
      const detail = Array.isArray(payload.detail)
        ? payload.detail.map((item) => item.msg).join(", ")
        : payload.detail;
      throw new Error(detail || "Could not create this video.");
    }
    promptInput.value = "";
    promptCount.textContent = "0";
    await loadGenerations();
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.classList.remove("hidden");
  } finally {
    generateButton.disabled = false;
  }
});

document.querySelector("#refreshButton").addEventListener("click", loadGenerations);

async function loadGenerations() {
  try {
    const response = await fetch("/api/generations");
    if (!response.ok) throw new Error("Could not load creations.");
    const jobs = await response.json();
    render(jobs);
    const shouldPoll = jobs.some((job) => ["queued", "generating"].includes(job.status));
    clearTimeout(pollingTimer);
    if (shouldPoll) pollingTimer = setTimeout(loadGenerations, 1400);
  } catch (error) {
    console.error(error);
  }
}

function render(jobs) {
  grid.replaceChildren();
  emptyState.classList.toggle("hidden", jobs.length > 0);
  activeJobs.clear();
  jobs.forEach((job) => {
    const card = template.content.firstElementChild.cloneNode(true);
    const media = card.querySelector(".media");
    const video = card.querySelector("video");
    const pending = card.querySelector(".pending");
    const status = card.querySelector(".pending-status");
    const progress = card.querySelector(".progress-track span");
    const eta = card.querySelector(".eta");
    const error = card.querySelector(".card-error");
    const download = card.querySelector(".download");
    const deleteButton = card.querySelector(".delete");

    media.style.aspectRatio = job.aspect_ratio.replace(":", " / ");
    card.querySelector(".ratio-pill").textContent = `${job.aspect_ratio} · ${job.duration}s`;
    card.querySelector(".card-prompt").textContent = job.prompt;
    card.querySelector(".mode-label").textContent = job.mode.replaceAll("-", " ");
    card.querySelector(".timestamp").textContent = relativeTime(job.created_at);

    if (job.status === "succeeded") {
      pending.classList.add("hidden");
      video.src = job.video_url;
      download.href = job.video_url;
      download.setAttribute("download", `motion-${job.id.slice(0, 8)}.mp4`);
    } else {
      video.classList.add("hidden");
      download.classList.add("hidden");
      status.textContent = job.status === "failed" ? "Generation failed" : capitalize(job.status);
      progress.style.width = `${job.progress}%`;
      eta.textContent = job.eta_seconds ? `About ${job.eta_seconds}s remaining` : `${job.progress}%`;
      if (job.status === "failed") {
        card.querySelector(".orb").style.filter = "grayscale(1)";
        error.textContent = job.error || "The provider could not finish this generation.";
        error.classList.remove("hidden");
      } else {
        activeJobs.add(job.id);
      }
    }

    deleteButton.disabled = ["queued", "generating"].includes(job.status);
    deleteButton.addEventListener("click", async () => {
      if (!window.confirm("Delete this creation?")) return;
      const response = await fetch(`/api/generations/${job.id}`, { method: "DELETE" });
      if (response.ok) loadGenerations();
    });
    grid.append(card);
  });
}

function relativeTime(value) {
  const seconds = Math.round((new Date(value).getTime() - Date.now()) / 1000);
  const formatter = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  if (Math.abs(seconds) < 60) return formatter.format(seconds, "second");
  const minutes = Math.round(seconds / 60);
  if (Math.abs(minutes) < 60) return formatter.format(minutes, "minute");
  return formatter.format(Math.round(minutes / 60), "hour");
}

function capitalize(value) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

fetch("/health")
  .then((response) => response.json())
  .then((health) => {
    const providerLabels = { replicate: "Replicate connected", prompt: "Prompt video" };
    document.querySelector("#providerLabel").textContent =
      providerLabels[health.provider] || "Prompt video";
  })
  .catch(() => {});

loadGenerations();
