const $ = (selector) => document.querySelector(selector);
const authDialog = $("#auth-dialog");
let user = null;
let animals = [];
let savedAnimalIds = new Set();
let animalPage = 1;
let signupMode = false;
const escapeHtml = (value = "") => String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
const formData = (form) => Object.fromEntries(
  Array.from(form.elements)
    .filter((field) => field.name && !field.disabled && field.type !== "file")
    .map((field) => [field.name, field.value])
);
async function api(path, options = {}) {
  const method = options.method || (options.body ? "POST" : "GET");
  const isFormData = options.body instanceof FormData;
  const response = await fetch(`/api/${path}`, {
    ...options,
    method,
    headers: isFormData ? { ...(options.headers || {}) } : { "Content-Type": "application/json", ...(options.headers || {}) },
    body: options.body ? (isFormData ? options.body : JSON.stringify(options.body)) : undefined
  });
  const responseText = await response.text();
  let data;
  try {
    data = JSON.parse(responseText);
  } catch {
    throw new Error(`Server returned HTTP ${response.status} instead of JSON. Check that Vercel deployed app.py and requirements.txt. ${responseText.slice(0, 160)}`);
  }
  if (!response.ok) throw new Error(data.error || "The request could not be completed.");
  return data;
}

function showMessage(element, text, error = false) {
  element.textContent = text;
  element.dataset.error = String(error);
}

function resetAnimalForm() {
  const form = $("#animal-form");
  form.reset();
  form.elements.id.value = "";
  $("#animal-form-title").textContent = "Add an animal";
  showMessage($("#animal-message"), "");
}

function refreshRoleControls() {
  $("#login-button").textContent = user ? `${user.role[0].toUpperCase()}${user.role.slice(1)} · Log Out` : "Log In";
  $("#account-panel").hidden = !user;
  $("#account-link").hidden = !user;
  const canManage = user && ["staff", "administrator"].includes(user.role);
  $("#admin-panel").hidden = !canManage;
  $("#admin-link").hidden = !canManage;
  $("#animal-form").hidden = !user || !["staff", "administrator"].includes(user.role);
  $("#volunteer-form").hidden = !user;
  $("#volunteer-signin").hidden = !!user;
  $("#contact-message-form").hidden = !user;
  $("#contact-signin").hidden = !!user;
  if (user) {
    $("#volunteer-form").elements.name.value = user.name || "";
    $("#volunteer-form").elements.email.value = user.email || "";
    $("#volunteer-form").elements.phone.value = user.phone || "";
    $("#contact-message-form").elements.name.value = user.name || "";
    $("#contact-message-form").elements.email.value = user.email || "";
  }
}

function animalCard(animal) {
  const saved = savedAnimalIds.has(Number(animal.id));
  return `<article class="animal-card">
    <img src="${escapeHtml(animal.photo || "https://images.unsplash.com/photo-1548199973-03cce0bbc87b?w=800")}" alt="${escapeHtml(animal.name)}" loading="lazy">
    <div class="animal-info"><div><h3>${escapeHtml(animal.name)}</h3><p>${escapeHtml(animal.breed)} · ${escapeHtml(animal.gender)}</p></div><span class="age">${escapeHtml(animal.age)}</span></div>
    <p class="animal-summary">${escapeHtml(animal.description)}</p><span class="status-badge status-${escapeHtml(animal.status.toLowerCase())}">${escapeHtml(animal.status)}</span>
    <div class="animal-actions"><button class="secondary-button" data-detail="${animal.id}">View profile</button><button class="secondary-button favorite-button" data-favorite="${animal.id}" aria-pressed="${saved}">${saved ? "♥ Saved" : "♡ Save"}</button>${animal.status === "Available" && !animal.adoption_on_hold ? `<button class="primary-button" data-adopt="${animal.id}">Apply to adopt</button>` : ""}</div>
    ${user && ["staff", "administrator"].includes(user.role) ? `<div class="admin-animal-actions"><button data-edit="${animal.id}">Edit</button><button data-delete="${animal.id}">Remove</button></div>` : ""}</article>`;
}

async function loadAnimals(page = animalPage) {
  const filters = new URLSearchParams(formData($("#animal-filters")));
  filters.set("page", page);
  const data = await api(`animals?${filters.toString()}`, { method: "GET" });
  animals = data.animals;
  $("#animal-grid").innerHTML = animals.length ? animals.map(animalCard).join("") : `<p class="empty-state">No animals match those filters yet. Try changing your search.</p>`;
  animalPage = data.page;
  $("#animal-pagination").innerHTML = data.pages > 1
    ? `<button type="button" data-page="${data.page - 1}" ${data.page === 1 ? "disabled" : ""}>← Previous</button><span>Page ${data.page} of ${data.pages} · ${data.total} animals</span><button type="button" data-page="${data.page + 1}" ${data.page === data.pages ? "disabled" : ""}>Next →</button>`
    : `<span>${data.total} ${data.total === 1 ? "animal" : "animals"}</span>`;
}

async function loadAnimalOptions() {
  const { animals: allAnimals } = await api("animals/options", { method: "GET" });
  $("#contact-animal").innerHTML = `<option value="">General question</option>` + allAnimals.map((animal) => `<option value="${animal.id}">${escapeHtml(animal.name)}</option>`).join("");
}

async function loadOpportunities() {
  const { opportunities } = await api("opportunities", { method: "GET" });
  $("#opportunity-grid").innerHTML = opportunities.map((item) => `<article class="help-card"><div>🤝</div><h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(item.description)}</p><p><strong>Schedule:</strong> ${escapeHtml(item.schedule)}</p></article>`).join("");
}

async function loadAccount() {
  if (!user) return;
  const profileForm = $("#profile-form");
  for (const key of ["name", "phone", "address", "experience", "pets"]) profileForm.elements[key].value = user[key] || "";
  try {
    const result = await api("applications", { method: "GET" });
    const tracked = [
      ...(result.applications || []).map((item) => ({ ...item, kind: "Adoption", subject: item.animal_name || "Animal" })),
      ...(result.volunteer_applications || []).map((item) => ({ ...item, kind: "Volunteer", subject: "Volunteer application" }))
    ];
    $("#application-list").innerHTML = tracked.length ? tracked.map((item) => `<article class="application-item"><strong>${item.kind === "Volunteer" ? "Volunteer application" : `Adoption application · ${escapeHtml(item.subject)}`}</strong><span>Review status: ${escapeHtml(item.status)}</span>${item.adoption_status ? `<span>Animal status: ${escapeHtml(item.adoption_status)}</span>` : ""}<small>Submitted ${escapeHtml(item.created_at)}</small></article>`).join("") : `<p class="empty-state">Your adoption and volunteer applications will appear here.</p>`;
  } catch (error) {
    $("#application-list").textContent = `Could not load your applications: ${error.message}`;
  }
  let favorites = null;
  try { favorites = await api("favorites", { method: "GET" }); }
  catch (error) { $("#favorite-list").textContent = `Could not load saved animals: ${error.message}`; }
  let messages = null;
  try { messages = await api("messages", { method: "GET" }); }
  catch (error) { $("#message-list").textContent = `Could not load questions: ${error.message}`; }
  if (favorites) {
    savedAnimalIds = new Set(favorites.animals.map((animal) => Number(animal.id)));
    $("#favorite-list").innerHTML = favorites.animals.length ? favorites.animals.map((animal) => `<article class="saved-animal"><img src="${escapeHtml(animal.photo || "https://images.unsplash.com/photo-1548199973-03cce0bbc87b?w=800")}" alt="${escapeHtml(animal.name)}"><div><strong>${escapeHtml(animal.name)}</strong><small>${escapeHtml(animal.breed)} · ${escapeHtml(animal.status)}</small><button data-unfavorite="${animal.id}">Remove</button></div></article>`).join("") : `<p class="empty-state">Save an animal from the listings to see it here.</p>`;
  }
  if (messages) $("#message-list").innerHTML = messages.messages.length ? messages.messages.map((item) => `<article class="application-item"><strong>${escapeHtml(item.animal_name || "General question")}</strong><p>${escapeHtml(item.message)}</p><span>${item.reply ? `Shelter reply: ${escapeHtml(item.reply)}` : "Waiting for a shelter response"}</span><small>${escapeHtml(item.created_at)}</small></article>`).join("") : `<p class="empty-state">Questions you send while signed in and shelter replies will appear here.</p>`;
}

async function loadAdminApplications() {
  if (!user || !["staff", "administrator"].includes(user.role)) return;
  const result = await api("admin/applications", { method: "GET" });
  const all = [
    ...result.adoptions.map((item) => ({ ...item, kind: "adoption", label: `Adoption · ${item.animal_name}`, applicant: item.name })),
    ...result.volunteers.map((item) => ({ ...item, kind: "volunteer", label: "Volunteer application", applicant: item.name }))
  ];
  $("#admin-application-list").innerHTML = all.length ? all.map((item) => {
    const statuses = item.kind === "adoption" ? ["In Review", "Approved", "Declined"] : ["Submitted", "In Review", "Approved", "Declined"];
    const selectedStatus = item.kind === "adoption" && item.status === "Submitted" ? "In Review" : item.status;
    return `<article class="application-item"><strong>#${item.id} · ${escapeHtml(item.label)}</strong><span>${escapeHtml(item.applicant)} · ${escapeHtml(item.email)}</span><select data-status-kind="${item.kind}" data-status-id="${item.id}">${statuses.map((status) => `<option ${status === selectedStatus ? "selected" : ""}>${status}</option>`).join("")}</select><small>Submitted ${escapeHtml(item.created_at)}</small></article>`;
  }).join("") : `<p class="empty-state">No applications have been submitted yet.</p>`;
  const { messages } = await api("admin/messages", { method: "GET" });
  $("#admin-message-list").innerHTML = messages.length ? messages.map((item) => `<article class="application-item"><strong>${escapeHtml(item.name)} · ${escapeHtml(item.email)}${item.animal_name ? ` · ${escapeHtml(item.animal_name)}` : ""}</strong><p>${escapeHtml(item.message)}</p><label>Reply<textarea data-message-reply="${item.id}" rows="2">${escapeHtml(item.reply || "")}</textarea></label><button type="button" data-send-reply="${item.id}">Save reply</button><small>${escapeHtml(item.created_at)}</small></article>`).join("") : `<p class="empty-state">No customer questions yet.</p>`;
}

async function refreshAdminApplications() {
  try {
    await loadAdminApplications();
  } catch (error) {
    $("#admin-application-list").textContent = `Could not load applications: ${error.message}`;
    $("#admin-message-list").textContent = "";
  }
}

async function loadUser() {
  const data = await api("me", { method: "GET" });
  user = data.user;
  refreshRoleControls();
  if (user) {
    $("#contact-message-form").elements.name.value = user.name || "";
    $("#contact-message-form").elements.email.value = user.email || "";
    await loadAccount();
    await loadAdminApplications();
  }
  await loadAnimals();
}
$("#login-button").onclick = async () => {
  if (user) {
    await api("logout", { body: {} });
    user = null;
    savedAnimalIds.clear();
    refreshRoleControls();
    await loadAnimals();
  } else {
    signupMode = false;
    $("#auth-title").textContent = "Welcome back";
    $("#auth-intro").textContent = "Log in to continue.";
    $("#register-name").hidden = true;
    $("#auth-submit").textContent = "Log In";
    $("#auth-switch").textContent = "Create an account";
    authDialog.showModal();
  }
};
$("#auth-close").onclick = () => authDialog.close();
$("#account-link").onclick = async (event) => {
  event.preventDefault();
  await loadAccount();
  $("#account-panel").showModal();
};
$("#admin-link").onclick = async (event) => {
  event.preventDefault();
  resetAnimalForm();
  await refreshAdminApplications();
  $("#admin-panel").showModal();
};
$("#admin-panel").addEventListener("close", resetAnimalForm);
document.querySelectorAll("[data-close-dialog]").forEach((button) => {
  button.onclick = () => $(`#${button.dataset.closeDialog}`).close();
});
$("#auth-switch").onclick = (event) => {
  signupMode = !signupMode;
  $("#auth-title").textContent = signupMode ? "Create your account" : "Welcome back";
  $("#auth-intro").textContent = signupMode ? "Create an account to save favorites and track applications." : "Log in to continue.";
  $("#register-name").hidden = !signupMode;
  $("#register-name input").required = signupMode;
  $("#auth-submit").textContent = signupMode ? "Create Account" : "Log In";
  event.currentTarget.textContent = signupMode ? "Already have an account? Log in" : "Create an account";
  $("#auth-message").textContent = "";
};
$("#auth-form").onsubmit = async (event) => {
  event.preventDefault();
  const data = formData(event.currentTarget);
  try {
    const result = await api(signupMode ? "register" : "login", { body: { email: data.email, password: data.password, name: data.name } });
    user = result.user;
    refreshRoleControls();
    authDialog.close();
    await loadUser();
  } catch (error) { showMessage($("#auth-message"), error.message, true); }
};
$("#animal-filters").onsubmit = (event) => {
  event.preventDefault();
  loadAnimals(1).catch((error) => showMessage($("#animal-feedback"), error.message, true));
};
$("#animal-filters").onchange = () => loadAnimals(1).catch((error) => showMessage($("#animal-feedback"), error.message, true));
$("#animal-pagination").onclick = (event) => {
  const pageButton = event.target.closest("[data-page]");
  if (pageButton && !pageButton.disabled) loadAnimals(Number(pageButton.dataset.page)).catch((error) => showMessage($("#animal-feedback"), error.message, true));
};
$("#animal-grid").onclick = async (event) => {
  const detailId = event.target.dataset.detail;
  const favoriteId = event.target.dataset.favorite;
  const adoptId = event.target.dataset.adopt;
  if (detailId) {
    const { animal } = await api(`animals/${detailId}`, { method: "GET" });
    $("#animal-detail").innerHTML = `<img class="detail-photo" src="${escapeHtml(animal.photo)}" alt="${escapeHtml(animal.name)}"><span class="status-badge">${escapeHtml(animal.status)}</span><h2>${escapeHtml(animal.name)}</h2><p>${escapeHtml(animal.species)} · ${escapeHtml(animal.breed)} · ${escapeHtml(animal.age)} · ${escapeHtml(animal.gender)} · ${escapeHtml(animal.size)}</p><p>${escapeHtml(animal.description)}</p><h3>Health and care</h3><p><strong>Vaccinations:</strong> ${escapeHtml(animal.vaccinated || "Ask shelter staff")}</p><p><strong>Spayed/neutered:</strong> ${escapeHtml(animal.spayed_neutered || "Ask shelter staff")}</p><p><strong>Diet:</strong> ${escapeHtml(animal.dietary_needs || "No special needs listed")}</p><p><strong>Behavior:</strong> ${escapeHtml(animal.behavior || "Ask shelter staff")}</p><p><strong>Special care:</strong> ${escapeHtml(animal.special_care || "No special care listed")}</p><a class="primary-button" href="#contact-form" onclick="document.querySelector('#contact-animal').value='${animal.id}';document.querySelector('#detail-dialog').close()">Ask about ${escapeHtml(animal.name)}</a>`;
    $("#detail-dialog").showModal();
  }
  if (favoriteId) {
    if (!user) {
      showMessage($("#animal-feedback"), "Log in to save animals to your account.", true);
      $("#login-button").click();
      return;
    }
    try {
      const isSaved = savedAnimalIds.has(Number(favoriteId));
      await api(`favorites/${favoriteId}`, { method: isSaved ? "DELETE" : "POST", body: isSaved ? undefined : {} });
      await loadAccount();
      await loadAnimals(animalPage);
      showMessage($("#animal-feedback"), isSaved ? "Animal removed from saved animals." : "Animal saved to your account.");
    } catch (error) {
      showMessage($("#animal-feedback"), error.message, true);
    }
  }
  if (adoptId) {
    if (!user) { alert("Please log in before applying to adopt."); $("#login-button").click(); return; }
    const animal = animals.find((item) => item.id === Number(adoptId));
    $("#application-form").elements.animal_id.value = adoptId;
    $("#application-animal").textContent = `Applying to adopt ${animal?.name || "this animal"}`;
    const applicationForm = $("#application-form");
    applicationForm.elements.name.value = user.name || "";
    applicationForm.elements.email.value = user.email;
    applicationForm.elements.phone.value = user.phone || "";
    applicationForm.elements.other_pets.value = user.pets || "";
    applicationForm.elements.experience.value = user.experience || "";
    $("#application-dialog").showModal();
  }
};
$("#detail-close").onclick = () => $("#detail-dialog").close();
$("#application-close").onclick = () => $("#application-dialog").close();
$("#favorite-list").onclick = async (event) => {
  const id = event.target.dataset.unfavorite;
  if (id) {
    await api(`favorites/${id}`, { method: "DELETE" });
    await loadAccount();
    await loadAnimals(animalPage);
  }
};
$("#application-form").onsubmit = async (event) => {
  event.preventDefault();
  try {
    const result = await api("applications", { body: formData(event.currentTarget) });
    showMessage($("#application-message"), "Application submitted. You can track it in My Account.");
    await loadAccount();
    setTimeout(() => $("#application-dialog").close(), 900);
  } catch (error) { showMessage($("#application-message"), error.message, true); }
};
$("#profile-form").onsubmit = async (event) => {
  event.preventDefault();
  try {
    const result = await api("profile", { method: "PATCH", body: formData(event.currentTarget) });
    user = result.user;
    showMessage($("#profile-message"), "Profile saved.");
  } catch (error) { showMessage($("#profile-message"), error.message, true); }
};
$("#volunteer-form").onsubmit = async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  if (!user) { $("#login-button").click(); return; }
  try {
    const result = await api("volunteers", { body: formData(form) });
    showMessage($("#volunteer-message"), "Volunteer application submitted.");
    await loadAccount();
  } catch (error) { showMessage($("#volunteer-message"), error.message, true); }
};

$("#volunteer-login").onclick = () => $("#login-button").click();
$("#contact-login").onclick = () => $("#login-button").click();
$("#contact-message-form").onsubmit = async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  if (!user) { $("#login-button").click(); return; }
  try {
    const payload = {
      name: form.elements.name.value,
      email: form.elements.email.value,
      animal_id: form.elements.animal_id.value,
      message: form.elements.message.value
    };
    await api("contact", { body: payload });
    form.reset();
    form.elements.name.value = user.name || "";
    form.elements.email.value = user.email || "";
    await loadAccount();
    showMessage($("#contact-message"), "Your message has been sent. Thank you!");
  } catch (error) { showMessage($("#contact-message"), error.message, true); }
};
$("#animal-grid").addEventListener("click", async (event) => {
  const editId = event.target.dataset.edit;
  const deleteId = event.target.dataset.delete;
  if (editId) {
    const item = animals.find((animal) => animal.id === Number(editId));
    const form = $("#animal-form");
    for (const [key, value] of Object.entries(item)) if (form.elements[key]) form.elements[key].value = value || "";
    $("#animal-form-title").textContent = `Edit ${item.name}`;
    $("#admin-panel").showModal();
    $("#animal-form").scrollIntoView({ behavior: "smooth", block: "start" });
  }
  if (deleteId && confirm("Remove this animal profile?")) {
    await api(`admin/animals/${deleteId}`, { method: "DELETE" });
    await loadAnimals();
  }
});
$("#animal-form").onsubmit = async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  if (!(form instanceof HTMLFormElement)) throw new TypeError("Animal editor form was not found.");
  const data = new FormData(form);
  const id = data.get("id");
  data.delete("id");
  try {
    await api(id ? `admin/animals/${id}` : "admin/animals", { method: id ? "PUT" : "POST", body: data });
    form.reset();
    $("#animal-form-title").textContent = "Add an animal";
    showMessage($("#animal-message"), id ? "Animal updated successfully." : "Animal added successfully.");
    await loadAnimals();
  } catch (error) { showMessage($("#animal-message"), error.message, true); }
};
$("#animal-cancel").onclick = () => { $("#animal-form").reset(); $("#animal-form-title").textContent = "Add an animal"; };
$("#admin-application-list").onchange = async (event) => {
  const select = event.target.closest("[data-status-kind]");
  if (!select) return;
  await api(`admin/applications/${select.dataset.statusKind}/${select.dataset.statusId}`, { method: "PATCH", body: { status: select.value } });
};

$("#admin-message-list").onclick = async (event) => {
  const button = event.target.closest("[data-send-reply]");
  if (!button) return;
  const id = button.dataset.sendReply;
  const reply = $("#admin-message-list").querySelector(`[data-message-reply="${id}"]`).value;
  await api(`admin/messages/${id}`, { method: "PATCH", body: { reply } });
  await loadAdminApplications();
};
Promise.all([loadUser(), loadOpportunities(), loadAnimalOptions()]).catch((error) => console.error(error));
