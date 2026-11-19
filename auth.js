// The page talks to the Flask backend for accounts and shelter data.
// Shorthand for finding the first element that matches a CSS selector.
const $ = (selector) => document.querySelector(selector);
const authDialog = $("#auth-dialog");
let user = null;
let animals = [];
let savedAnimalIds = new Set();
let animalPage = 1;
let signupMode = false;

// Escape database text before placing it in HTML templates.
const escapeHtml = (value = "") => String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
// Convert named form controls into a plain object for JSON requests.
const formData = (form) => Object.fromEntries(new FormData(form).entries());

// Use one request helper for all API calls. JSON requests send the normal
// application/json header, while image forms keep the browser's multipart
// boundary so Flask can read the uploaded file.
async function api(path, options = {}) {
  // Send requests and normalize JSON, form uploads, and error responses.
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
  // Update a status element and mark whether its message is an error.
  element.textContent = text;
  element.dataset.error = String(error);
}

function resetAnimalForm() {
  // Return the staff editor to a clean create-animal state.
  const form = $("#animal-form");
  form.reset();
  form.elements.id.value = "";
  $("#animal-form-title").textContent = "Add an animal";
  showMessage($("#animal-message"), "");
}

function refreshRoleControls() {
  // Show account and management controls that match the current user's role.
  $("#login-button").textContent = user ? `${user.role[0].toUpperCase()}${user.role.slice(1)} · Log Out` : "Log In";
  $("#account-panel").hidden = !user;
  $("#account-link").hidden = !user;
  const canManage = user && ["staff", "administrator"].includes(user.role);
  $("#admin-panel").hidden = !canManage;
  $("#admin-link").hidden = !canManage;
  $("#animal-form").hidden = !user || !["staff", "administrator"].includes(user.role);
}

function animalCard(animal) {
  // Build one safe animal card with actions permitted for this user.
  // The saved ID set controls both the button text and its accessible state.
  const saved = savedAnimalIds.has(Number(animal.id));
  return `<article class="animal-card">
    <img src="${escapeHtml(animal.photo || "https://images.unsplash.com/photo-1548199973-03cce0bbc87b?w=800")}" alt="${escapeHtml(animal.name)}" loading="lazy">
    <div class="animal-info"><div><h3>${escapeHtml(animal.name)}</h3><p>${escapeHtml(animal.breed)} · ${escapeHtml(animal.gender)}</p></div><span class="age">${escapeHtml(animal.age)}</span></div>
    <p class="animal-summary">${escapeHtml(animal.description)}</p><span class="status-badge status-${escapeHtml(animal.status.toLowerCase())}">${escapeHtml(animal.status)}</span>
    <div class="animal-actions"><button class="secondary-button" data-detail="${animal.id}">View profile</button><button class="secondary-button favorite-button" data-favorite="${animal.id}" aria-pressed="${saved}">${saved ? "♥ Saved" : "♡ Save"}</button>${animal.status === "Available" ? `<button class="primary-button" data-adopt="${animal.id}">Apply to adopt</button>` : ""}</div>
    ${user && ["staff", "administrator"].includes(user.role) ? `<div class="admin-animal-actions"><button data-edit="${animal.id}">Edit</button><button data-delete="${animal.id}">Remove</button></div>` : ""}</article>`;
}

async function loadAnimals(page = animalPage) {
  // Fetch the filtered page and render its cards and page controls.
  // Send search filters and the requested page to the backend. The backend
  // returns at most 12 matching animals plus the total page count.
  const filters = new URLSearchParams(new FormData($("#animal-filters")));
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
  // Populate the contact form's optional animal selector.
  const { animals: allAnimals } = await api("animals/options", { method: "GET" });
  $("#contact-animal").innerHTML = `<option value="">General question</option>` + allAnimals.map((animal) => `<option value="${animal.id}">${escapeHtml(animal.name)}</option>`).join("");
}

async function loadOpportunities() {
  // Render volunteer roles and schedules from the backend.
  const { opportunities } = await api("opportunities", { method: "GET" });
  $("#opportunity-grid").innerHTML = opportunities.map((item) => `<article class="help-card"><div>🤝</div><h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(item.description)}</p><p><strong>Schedule:</strong> ${escapeHtml(item.schedule)}</p></article>`).join("");
}

async function loadAccount() {
  // Fill the profile, saved-animal, and adoption-application panels.
  if (!user) return;
  const profileForm = $("#profile-form");
  for (const key of ["name", "phone", "address", "experience", "pets"]) profileForm.elements[key].value = user[key] || "";
  const [favorites, applications] = await Promise.all([api("favorites", { method: "GET" }), api("applications", { method: "GET" })]);
  // Keep this set in sync with Supabase-backed records so listing buttons
  // immediately show which animals the current account has saved.
  savedAnimalIds = new Set(favorites.animals.map((animal) => Number(animal.id)));
  $("#favorite-list").innerHTML = favorites.animals.length ? favorites.animals.map((animal) => `<p><a href="#animals">${escapeHtml(animal.name)}</a> · ${escapeHtml(animal.status)} <button data-unfavorite="${animal.id}">Remove</button></p>`).join("") : `<p class="empty-state">Save an animal from the listings to see it here.</p>`;
  $("#application-list").innerHTML = applications.applications.length ? applications.applications.map((item) => `<article class="application-item"><strong>${escapeHtml(item.animal_name)}</strong><span>${escapeHtml(item.status)}</span><small>Submitted ${escapeHtml(item.created_at)}</small></article>`).join("") : `<p class="empty-state">Your adoption applications will appear here.</p>`;
}

async function loadAdminApplications() {
  // Load application queues for staff and administrator accounts.
  if (!user || !["staff", "administrator"].includes(user.role)) return;
  const result = await api("admin/applications", { method: "GET" });
  const all = [
    ...result.adoptions.map((item) => ({ ...item, kind: "adoption", label: `Adoption · ${item.animal_name}`, applicant: item.name })),
    ...result.volunteers.map((item) => ({ ...item, kind: "volunteer", label: "Volunteer application", applicant: item.name }))
  ];
  $("#admin-application-list").innerHTML = all.length ? all.map((item) => `<article class="application-item"><strong>${escapeHtml(item.label)}</strong><span>${escapeHtml(item.applicant)} · ${escapeHtml(item.email)}</span><select data-status-kind="${item.kind}" data-status-id="${item.id}">${["Submitted", "In Review", "Approved", "Declined"].map((status) => `<option ${status === item.status ? "selected" : ""}>${status}</option>`).join("")}</select><small>${escapeHtml(item.created_at)}</small></article>`).join("") : `<p class="empty-state">No applications have been submitted yet.</p>`;
}

async function loadUser() {
  // Restore the login session and load the relevant account data.
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
// Sign out the active user, or open the login dialog for a visitor.
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
    $("#role-field").hidden = true;
    $("#register-name").hidden = true;
    $("#auth-submit").textContent = "Log In";
    $("#auth-switch").textContent = "Create an account";
    authDialog.showModal();
  }
};
// Close the login/register dialog without changing the current session.
$("#auth-close").onclick = () => authDialog.close();

// Open account tools as dialogs instead of scrolling down the landing page.
// Open profile and saved activity in a dialog.
$("#account-link").onclick = (event) => {
  event.preventDefault();
  $("#account-panel").showModal();
};
// Reset the staff editor before opening the management dialog.
$("#admin-link").onclick = (event) => {
  event.preventDefault();
  resetAnimalForm();
  $("#admin-panel").showModal();
};
$("#admin-panel").addEventListener("close", resetAnimalForm);
// Connect each dialog close button to the dialog named in its data attribute.
document.querySelectorAll("[data-close-dialog]").forEach((button) => {
  button.onclick = () => $(`#${button.dataset.closeDialog}`).close();
});

// Switch between login and account-registration form modes.
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

// Submit credentials, update role controls, and reload account data.
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
// Apply search filters from the beginning of the result list.
$("#animal-filters").onsubmit = (event) => {
  event.preventDefault();
  // A new search starts at page one because the previous page may not exist
  // in the smaller filtered result set.
  loadAnimals(1).catch((error) => showMessage($("#animal-feedback"), error.message, true));
};
// Refresh the first results page whenever a select filter changes.
$("#animal-filters").onchange = () => loadAnimals(1).catch((error) => showMessage($("#animal-feedback"), error.message, true));
// Load the page number attached to the clicked pagination button.
$("#animal-pagination").onclick = (event) => {
  const pageButton = event.target.closest("[data-page]");
  if (pageButton && !pageButton.disabled) loadAnimals(Number(pageButton.dataset.page)).catch((error) => showMessage($("#animal-feedback"), error.message, true));
};

// Animal cards open profiles, save favorites, and begin adoption applications.
// Handle profile, favorite, and adoption actions from animal cards.
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
      // The same control adds or removes a favorite. Refresh the account list
      // and current animal page after the backend confirms the change.
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
    $("#application-dialog").showModal();
  }
};
// Close the detailed animal profile dialog.
$("#detail-close").onclick = () => $("#detail-dialog").close();
// Close the adoption application dialog.
$("#application-close").onclick = () => $("#application-dialog").close();
// Remove a saved animal from the account's favorites.
$("#favorite-list").onclick = async (event) => {
  const id = event.target.dataset.unfavorite;
  if (id) {
    await api(`favorites/${id}`, { method: "DELETE" });
    await loadAccount();
    await loadAnimals(animalPage);
  }
};

// Submit an adoption application and refresh the account tracking list.
$("#application-form").onsubmit = async (event) => {
  event.preventDefault();
  try {
    await api("applications", { body: formData(event.currentTarget) });
    showMessage($("#application-message"), "Application submitted. You can track it in My Account.");
    await loadAccount();
    setTimeout(() => $("#application-dialog").close(), 900);
  } catch (error) { showMessage($("#application-message"), error.message, true); }
};

// Save profile fields and update the current in-memory user record.
$("#profile-form").onsubmit = async (event) => {
  event.preventDefault();
  try {
    const result = await api("profile", { method: "PATCH", body: formData(event.currentTarget) });
    user = result.user;
    showMessage($("#profile-message"), "Profile saved.");
  } catch (error) { showMessage($("#profile-message"), error.message, true); }
};

// Submit a volunteer application, then clear the form on success.
$("#volunteer-form").onsubmit = async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    await api("volunteers", { body: formData(form) });
    form.reset();
    showMessage($("#volunteer-message"), "Volunteer application submitted. Thank you!");
  } catch (error) { showMessage($("#volunteer-message"), error.message, true); }
};

// Send the visitor's message and clear the form after a successful send.
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
// Staff-only card actions edit or remove the selected animal.
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
// Create or update an animal, including an optional uploaded image.
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
// Clear the editor and restore its create-animal heading.
$("#animal-cancel").onclick = () => { $("#animal-form").reset(); $("#animal-form-title").textContent = "Add an animal"; };
// Persist a staff member's changed application status.
$("#admin-application-list").onchange = async (event) => {
  const select = event.target.closest("[data-status-kind]");
  if (!select) return;
  await api(`admin/applications/${select.dataset.statusKind}/${select.dataset.statusId}`, { method: "PATCH", body: { status: select.value } });
};

// Load the public listings and restore any existing account session.
Promise.all([loadUser(), loadOpportunities(), loadAnimalOptions()]).catch((error) => console.error(error));
