// The page talks to the Flask backend for accounts and shelter data.
const $ = (selector) => document.querySelector(selector);
const authDialog = $("#auth-dialog");
let user = null;
let animals = [];
let signupMode = false;

const escapeHtml = (value = "") => String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
const formData = (form) => Object.fromEntries(new FormData(form).entries());

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
}

function animalCard(animal) {
  return `<article class="animal-card">
    <img src="${escapeHtml(animal.photo || "https://images.unsplash.com/photo-1548199973-03cce0bbc87b?w=800")}" alt="${escapeHtml(animal.name)}" loading="lazy">
    <div class="animal-info"><div><h3>${escapeHtml(animal.name)}</h3><p>${escapeHtml(animal.breed)} · ${escapeHtml(animal.gender)}</p></div><span class="age">${escapeHtml(animal.age)}</span></div>
    <p class="animal-summary">${escapeHtml(animal.description)}</p><span class="status-badge status-${escapeHtml(animal.status.toLowerCase())}">${escapeHtml(animal.status)}</span>
    <div class="animal-actions"><button class="secondary-button" data-detail="${animal.id}">View profile</button><button class="secondary-button" data-favorite="${animal.id}" aria-label="Save ${escapeHtml(animal.name)}">♡ Save</button>${animal.status === "Available" ? `<button class="primary-button" data-adopt="${animal.id}">Apply to adopt</button>` : ""}</div>
    ${user && ["staff", "administrator"].includes(user.role) ? `<div class="admin-animal-actions"><button data-edit="${animal.id}">Edit</button><button data-delete="${animal.id}">Remove</button></div>` : ""}</article>`;
}

async function loadAnimals() {
  const filters = new URLSearchParams(new FormData($("#animal-filters")));
  const data = await api(`animals?${filters.toString()}`, { method: "GET" });
  animals = data.animals;
  $("#animal-grid").innerHTML = animals.length ? animals.map(animalCard).join("") : `<p class="empty-state">No animals match those filters yet. Try changing your search.</p>`;
  $("#contact-animal").innerHTML = `<option value="">General question</option>` + animals.map((animal) => `<option value="${animal.id}">${escapeHtml(animal.name)}</option>`).join("");
}

async function loadOpportunities() {
  const { opportunities } = await api("opportunities", { method: "GET" });
  $("#opportunity-grid").innerHTML = opportunities.map((item) => `<article class="help-card"><div>🤝</div><h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(item.description)}</p><p><strong>Schedule:</strong> ${escapeHtml(item.schedule)}</p></article>`).join("");
}

async function loadAccount() {
  if (!user) return;
  const profileForm = $("#profile-form");
  for (const key of ["name", "phone", "address", "experience", "pets"]) profileForm.elements[key].value = user[key] || "";
  const [favorites, applications] = await Promise.all([api("favorites", { method: "GET" }), api("applications", { method: "GET" })]);
  $("#favorite-list").innerHTML = favorites.animals.length ? favorites.animals.map((animal) => `<p><a href="#animals">${escapeHtml(animal.name)}</a> · ${escapeHtml(animal.status)} <button data-unfavorite="${animal.id}">Remove</button></p>`).join("") : `<p class="empty-state">Save an animal from the listings to see it here.</p>`;
  $("#application-list").innerHTML = applications.applications.length ? applications.applications.map((item) => `<article class="application-item"><strong>${escapeHtml(item.animal_name)}</strong><span>${escapeHtml(item.status)}</span><small>Submitted ${escapeHtml(item.created_at)}</small></article>`).join("") : `<p class="empty-state">Your adoption applications will appear here.</p>`;
}

async function loadAdminApplications() {
  if (!user || !["staff", "administrator"].includes(user.role)) return;
  const result = await api("admin/applications", { method: "GET" });
  const all = [
    ...result.adoptions.map((item) => ({ ...item, kind: "adoption", label: `Adoption · ${item.animal_name}`, applicant: item.name })),
    ...result.volunteers.map((item) => ({ ...item, kind: "volunteer", label: "Volunteer application", applicant: item.name }))
  ];
  $("#admin-application-list").innerHTML = all.length ? all.map((item) => `<article class="application-item"><strong>${escapeHtml(item.label)}</strong><span>${escapeHtml(item.applicant)} · ${escapeHtml(item.email)}</span><select data-status-kind="${item.kind}" data-status-id="${item.id}">${["Submitted", "In Review", "Approved", "Declined"].map((status) => `<option ${status === item.status ? "selected" : ""}>${status}</option>`).join("")}</select><small>${escapeHtml(item.created_at)}</small></article>`).join("") : `<p class="empty-state">No applications have been submitted yet.</p>`;
}

async function loadUser() {
  const data = await api("me", { method: "GET" });
  user = data.user;
  refreshRoleControls();
  if (user) {
    await loadAccount();
    await loadAdminApplications();
  }
  await loadAnimals();
}

// Toggle the header between opening login and signing out.
$("#login-button").onclick = async () => {
  if (user) {
    await api("logout", { body: {} });
    user = null;
    refreshRoleControls();
    await loadAnimals();
  } else {
    signupMode = false;
    $("#auth-title").textContent = "Welcome back";
    $("#auth-intro").textContent = "Log in to continue.";
    $("#role-field").hidden = true;
    $("#register-name").hidden = true;
    $("#auth-submit").textContent = "Log In";
    $("#auth-switch").textContent = "Create an account";
    authDialog.showModal();
  }
};
$("#auth-close").onclick = () => authDialog.close();

// Open account tools as dialogs instead of scrolling down the landing page.
$("#account-link").onclick = (event) => {
  event.preventDefault();
  $("#account-panel").showModal();
};
$("#admin-link").onclick = (event) => {
  event.preventDefault();
  resetAnimalForm();
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
  $("#role-field").hidden = !signupMode;
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
    const result = await api(signupMode ? "register" : "login", { body: { email: data.email, password: data.password, name: data.name, role: data.role } });
    user = result.user;
    refreshRoleControls();
    authDialog.close();
    await loadUser();
  } catch (error) { showMessage($("#auth-message"), error.message, true); }
};

// Search and filter animals from the shelter database.
$("#animal-filters").onsubmit = (event) => { event.preventDefault(); loadAnimals().catch((error) => alert(error.message)); };
$("#animal-filters").onchange = () => loadAnimals().catch((error) => alert(error.message));

// Animal cards open profiles, save favorites, and begin adoption applications.
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
    if (!user) { alert("Please log in to save favorites."); return; }
    await api(`favorites/${favoriteId}`, { method: "POST", body: {} });
    await loadAccount();
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
    $("#application-dialog").showModal();
  }
};
$("#animal-grid").ondblclick = () => {};
$("#detail-close").onclick = () => $("#detail-dialog").close();
$("#application-close").onclick = () => $("#application-dialog").close();
$("#favorite-list").onclick = async (event) => {
  const id = event.target.dataset.unfavorite;
  if (id) { await api(`favorites/${id}`, { method: "DELETE" }); await loadAccount(); }
};

$("#application-form").onsubmit = async (event) => {
  event.preventDefault();
  try {
    await api("applications", { body: formData(event.currentTarget) });
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
  try {
    await api("volunteers", { body: formData(form) });
    form.reset();
    showMessage($("#volunteer-message"), "Volunteer application submitted. Thank you!");
  } catch (error) { showMessage($("#volunteer-message"), error.message, true); }
};

$("#contact-form").onsubmit = async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    await api("contact", { body: formData(form) });
    form.reset();
    showMessage($("#contact-message"), "Your message has been sent. Thank you!");
  } catch (error) { showMessage($("#contact-message"), error.message, true); }
};

// Staff and administrators can edit animal details and remove profiles.
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

// Load the public listings and restore any existing account session.
Promise.all([loadUser(), loadOpportunities()]).catch((error) => console.error(error));
