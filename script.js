
"use strict";

const API = "/api";

async function apiRequest(path, options = {}) {
  const response = await fetch(API + path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options.headers
    }
  });

  const result = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new Error(result.error || "Something went wrong.");
  }

  return result;
}

function showStatus(elementId, message, type = "") {
  const element = document.getElementById(elementId);
  element.textContent = message;
  element.className = "status " + type;
}

function formDataObject(form) {
  return Object.fromEntries(new FormData(form).entries());
}

// Search donors
document.getElementById("search-form").addEventListener(
  "submit",
  async function (event) {
    event.preventDefault();

    const group = document.getElementById("search-group").value;
    const city = document.getElementById("search-city").value.trim();
    const results = document.getElementById("donor-results");

    results.replaceChildren();
    showStatus("search-status", "Searching donors...");

    try {
      const params = new URLSearchParams({ group, city });
      const data = await apiRequest("/blood?" + params.toString());

      if (!data.donors || data.donors.length === 0) {
        showStatus("search-status", "No matching donors found.");
        return;
      }

      showStatus(
        "search-status",
        data.donors.length + " donor(s) found.",
        "success"
      );

      data.donors.forEach(function (donor) {
        const card = document.createElement("article");
        card.className = "donor-card";

        const badge = document.createElement("div");
        badge.className = "blood-badge";
        badge.textContent = donor.blood_group;

        const name = document.createElement("h3");
        name.textContent = donor.name;

        const location = document.createElement("p");
        location.textContent = "📍 " + donor.city;

        card.append(badge, name, location);
        results.appendChild(card);
      });
    } catch (error) {
      showStatus("search-status", error.message, "error");
    }
  }
);

// Register donor
document.getElementById("donor-form").addEventListener(
  "submit",
  async function (event) {
    event.preventDefault();

    const form = event.currentTarget;
    const button = form.querySelector("button[type='submit']");
    const payload = formDataObject(form);

    button.disabled = true;
    showStatus("donor-status", "Registering donor...");

    try {
      const result = await apiRequest("/donors", {
        method: "POST",
        body: JSON.stringify(payload)
      });

      showStatus("donor-status", result.message, "success");
      form.reset();

      document.getElementById("search-form").requestSubmit();
    } catch (error) {
      showStatus("donor-status", error.message, "error");
    } finally {
      button.disabled = false;
    }
  }
);

// Submit blood request
document.getElementById("request-form").addEventListener(
  "submit",
  async function (event) {
    event.preventDefault();

    const form = event.currentTarget;
    const button = form.querySelector("button[type='submit']");
    const payload = formDataObject(form);
    payload.units = Number(payload.units);

    button.disabled = true;
    showStatus("request-status", "Submitting request...");

    try {
      const result = await apiRequest("/requests", {
        method: "POST",
        body: JSON.stringify(payload)
      });

      showStatus("request-status", result.message, "success");
      form.reset();
    } catch (error) {
      showStatus("request-status", error.message, "error");
    } finally {
      button.disabled = false;
    }
  }
);
