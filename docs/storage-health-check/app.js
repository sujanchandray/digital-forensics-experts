import { createClient } from "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm";

const CATEGORIES = [
  "Windows forensics",
  "Memory forensics",
  "Network forensics",
  "Mobile forensics",
  "E-mail forensics",
  "USB drive forensics",
  "Anti-forensics",
  "Linux forensics",
  "Cloud forensics",
  "Malware analysis",
  "Incident response",
  "Software testing"
];

const DRAFT_KEY = "qshc-profile-draft";
const NOT_CONNECTED = "The board is not connected yet.";

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  }[ch]));
}

function when(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString();
}

function db() {
  const config = window.SITE_CONFIG || {};
  if (!config.supabaseUrl || !config.supabaseKey) return null;
  return createClient(config.supabaseUrl, config.supabaseKey);
}

function categoryFromUrl() {
  const value = new URLSearchParams(location.search).get("category");
  return CATEGORIES.includes(value) ? value : "";
}

function markFilters() {
  const current = categoryFromUrl();
  document.querySelectorAll("[data-category]").forEach((link) => {
    const value = link.getAttribute("data-category");
    if ((value || "") === current) link.setAttribute("aria-current", "true");
  });
}

function jobCard(job) {
  const name = job.profiles?.display_name || "Client";
  return `<a class="tile" href="job.html?id=${encodeURIComponent(job.id)}">
    <p class="eyebrow">${esc(job.category)}</p>
    <h3>${esc(job.title)}</h3>
    <p>${esc(name)} · ${esc(when(job.created_at))}</p>
  </a>`;
}

async function loadJobs(client, list) {
  let query = client
    .from("jobs")
    .select("id, title, category, description, created_at, profiles(display_name)")
    .order("created_at", { ascending: false });
  const category = categoryFromUrl();
  if (category) query = query.eq("category", category);
  const { data, error } = await query;
  if (error) {
    list.innerHTML = `<p class="error">${esc(error.message)}</p>`;
    return;
  }
  const rows = data || [];
  list.innerHTML = rows.length
    ? rows.map(jobCard).join("")
    : `<p class="muted">No jobs in this category yet.</p>`;
}

async function sessionOf(client) {
  const { data } = await client.auth.getSession();
  return data.session;
}

async function profileOf(client, userId) {
  const { data } = await client
    .from("profiles")
    .select("id, display_name, role, expertise")
    .eq("id", userId)
    .maybeSingle();
  return data;
}

function selectedExpertise(form) {
  return [...form.querySelectorAll('input[name="expertise"]:checked')].map((box) => box.value);
}

function watchRole(form) {
  const pick = form.querySelector(".expertise-pick");
  if (!pick) return;
  const sync = () => {
    pick.hidden = form.role.value !== "professional";
  };
  form.querySelectorAll('input[name="role"]').forEach((input) => {
    input.addEventListener("change", sync);
  });
  sync();
}

async function saveProfile(client, user, form) {
  const displayName = form.display_name.value.trim();
  const role = form.role.value;
  const expertise = role === "professional" ? selectedExpertise(form) : [];
  if (!displayName) return "Enter the name people should see.";
  if (role === "professional" && !expertise.length) return "Choose at least one area of practice.";
  const { error } = await client.from("profiles").upsert({
    id: user.id,
    display_name: displayName,
    role,
    expertise
  });
  return error ? error.message : "";
}

function watchJobs(client, list) {
  client
    .channel("public-jobs")
    .on("postgres_changes", { event: "INSERT", schema: "public", table: "jobs" }, () => {
      loadJobs(client, list);
    })
    .subscribe();
}

function watchMessages(client, jobId, reload) {
  client
    .channel(`job-messages-${jobId}`)
    .on("postgres_changes", { event: "INSERT", schema: "public", table: "messages", filter: `job_id=eq.${jobId}` }, reload)
    .subscribe();
}

const PRACTICES = {
  "Windows forensics": {
    summary: "Disk, registry and Windows artifact review.",
    items: [
      "Data Acquisition and Duplication",
      "Deleted File Recovery",
      "Collection of volatile and non-volatile information",
      "Windows memory and registry analysis",
      "Examine web browsers (cache, cookie, and history records)",
      "Examine windows files and metadata",
      "Recovering graphics files",
      "Forensic Image Analysis",
      "Timeline Analysis",
      "Keyword Search",
      "Web Artifact Recovery",
      "Windows Registry Analysis",
      "Analyze User Activity",
      "System Configurations",
      "System TimeZone Information",
      "Analyze Recently Used (Documents, Applications, MountedDevices, etc.)",
      "Analyze Windows SAM Files",
      "Event Log Analysis"
    ]
  },
  "Mobile forensics": {
    summary: "Phones and the records they keep.",
    items: ["ImageAnalysis", "TimelineAnalysis", "KeywordSearch", "WebArtifactAnalysis"]
  },
  "Anti-forensics": {
    summary: "Recognizing attempts to hide and alter evidence during an investigation.",
    items: ["FileCarving", "Degaussing", "Steganography"]
  }
};

function showPractice() {
  const slot = document.querySelector("#practice");
  if (!slot) return;
  const pack = PRACTICES[categoryFromUrl()];
  if (!pack) {
    slot.innerHTML = "";
    return;
  }
  slot.innerHTML = `<p>${esc(pack.summary)}</p><ul class="practices">${pack.items.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>`;
}

async function initJobs() {
  markFilters();
  showPractice();
  const list = document.querySelector("#job-list");
  const client = db();
  if (!client) {
    list.innerHTML = `<p class="notice">${NOT_CONNECTED}</p>`;
    return;
  }
  await loadJobs(client, list);
  watchJobs(client, list);
}

async function initPost() {
  const form = document.querySelector("#post-form");
  const note = document.querySelector("#post-note");
  const client = db();
  if (!client) {
    note.textContent = NOT_CONNECTED;
    return;
  }
  const session = await sessionOf(client);
  if (!session) {
    note.innerHTML = `Sign in as someone hiring before posting. <a href="account.html">Account</a>`;
    return;
  }
  const profile = await profileOf(client, session.user.id);
  if (!profile) {
    note.innerHTML = `Save a profile before posting. <a href="account.html">Account</a>`;
    return;
  }
  if (profile.role !== "client") {
    note.textContent = "This profile is available for work. A hiring profile can post a job.";
    return;
  }
  form.hidden = false;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    note.textContent = "";
    const title = form.title.value.trim();
    const description = form.description.value.trim();
    if (!title || !description) {
      note.textContent = "Enter a title and a description.";
      note.className = "error";
      return;
    }
    const { error } = await client.from("jobs").insert({
      client_id: session.user.id,
      title,
      category: form.category.value,
      description
    });
    if (error) {
      note.textContent = error.message;
      note.className = "error";
      return;
    }
    location.href = `jobs.html?category=${encodeURIComponent(form.category.value)}`;
  });
}

async function initJob() {
  const root = document.querySelector("#job");
  const id = new URLSearchParams(location.search).get("id");
  const client = db();
  if (!id) {
    root.innerHTML = `<p class="error">This job link is missing an id.</p>`;
    return;
  }
  if (!client) {
    root.innerHTML = `<p class="notice">${NOT_CONNECTED}</p>`;
    return;
  }
  const { data: job, error } = await client
    .from("jobs")
    .select("id, title, category, description, created_at, client_id, profiles(display_name)")
    .eq("id", id)
    .maybeSingle();
  if (error || !job) {
    root.innerHTML = `<p class="error">${esc(error?.message || "This job is not on the board.")}</p>`;
    return;
  }
  const session = await sessionOf(client);
  const profile = session ? await profileOf(client, session.user.id) : null;
  const isClient = profile && profile.id === job.client_id;
  let proposal = null;
  if (profile && profile.role === "professional") {
    const found = await client
      .from("proposals")
      .select("id, message, created_at")
      .eq("job_id", job.id)
      .eq("professional_id", profile.id)
      .maybeSingle();
    proposal = found.data;
  }
  const canMessage = Boolean(isClient || proposal);
  root.innerHTML = `
    <p class="eyebrow">${esc(job.category)}</p>
    <h1>${esc(job.title)}</h1>
    <p class="muted">${esc(job.profiles?.display_name || "Client")} · ${esc(when(job.created_at))}</p>
    <p>${esc(job.description)}</p>
    <h2>Proposals</h2>
    <div id="proposals"></div>
    <h2>Messages</h2>
    <div id="messages"></div>
  `;
  const proposals = root.querySelector("#proposals");
  const messages = root.querySelector("#messages");

  async function loadProposals() {
    if (!session) {
      proposals.innerHTML = `<p class="muted"><a href="account.html">Sign in</a> to send a proposal.</p>`;
      return;
    }
    const { data, error: proposalError } = await client
      .from("proposals")
      .select("id, message, created_at, profiles(display_name)")
      .eq("job_id", job.id)
      .order("created_at");
    const rows = proposalError ? "" : (data || []).map((item) => `
      <article class="bubble">
        <p class="eyebrow">${esc(item.profiles?.display_name || "Specialist")} · ${esc(when(item.created_at))}</p>
        <p>${esc(item.message)}</p>
      </article>
    `).join("");
    const form = !isClient && profile?.role === "professional" && !proposal
      ? `<form id="proposal-form" class="stack">
          <label>Proposal<textarea name="message" required></textarea></label>
          <button class="primary" type="submit">Send proposal</button>
        </form>`
      : "";
    const hint = isClient ? "" : (profile?.role === "professional" ? "" : `<p class="muted">A profile that is available for work can send a proposal.</p>`);
    proposals.innerHTML = `${rows}${form}${hint}<p id="proposal-note" class="notice"></p>`;
    const proposalForm = proposals.querySelector("#proposal-form");
    if (proposalForm) {
      proposalForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const message = proposalForm.message.value.trim();
        const note = proposals.querySelector("#proposal-note");
        const inserted = await client.from("proposals").insert({
          job_id: job.id,
          professional_id: profile.id,
          message
        });
        if (inserted.error) {
          note.textContent = inserted.error.message;
          note.className = "error";
          return;
        }
        proposal = { message };
        await loadProposals();
        await loadMessages();
      });
    }
  }

  let loadingMessages = false;
  async function loadMessages() {
    if (loadingMessages) return;
    if (!canMessage && !proposal) {
      messages.innerHTML = `<p class="muted">Messages on this job stay with the client and the people who sent a proposal.</p>`;
      return;
    }
    loadingMessages = true;
    const { data, error: messageError } = await client
      .from("messages")
      .select("id, body, created_at, profiles(display_name)")
      .eq("job_id", job.id)
      .order("created_at");
    if (messageError) {
      messages.innerHTML = `<p class="error">${esc(messageError.message)}</p>`;
      loadingMessages = false;
      return;
    }
    const rows = (data || []).map((item) => `
      <article class="bubble">
        <p class="eyebrow">${esc(item.profiles?.display_name || "Member")} · ${esc(when(item.created_at))}</p>
        <p>${esc(item.body)}</p>
      </article>
    `).join("");
    messages.innerHTML = `${rows || `<p class="muted">No messages yet.</p>`}
      <form id="message-form" class="stack">
        <label>Message<textarea name="body" required></textarea></label>
        <button class="primary" type="submit">Send</button>
      </form>
      <p id="message-note" class="notice"></p>`;
    messages.querySelector("#message-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const note = messages.querySelector("#message-note");
      const body = form.body.value.trim();
      if (!body) return;
      loadingMessages = false;
      const inserted = await client.from("messages").insert({
        job_id: job.id,
        sender_id: profile.id,
        body
      });
      if (inserted.error) {
        note.textContent = inserted.error.message;
        note.className = "error";
        return;
      }
      form.reset();
      await loadMessages();
    });
    loadingMessages = false;
  }

  await loadProposals();
  await loadMessages();
  if (session) watchMessages(client, job.id, loadMessages);
}

function showAccount(root, html) {
  root.innerHTML = html;
}

async function initAccount() {
  const root = document.querySelector("#account");
  const client = db();
  if (!client) {
    showAccount(root, `<p class="notice">${NOT_CONNECTED}</p>`);
    return;
  }
  const session = await sessionOf(client);
  if (!session) {
    showAccount(root, document.querySelector("#signed-out").innerHTML);
    bindSignedOut(client, root);
    return;
  }
  let profile = await profileOf(client, session.user.id);
  const draft = readDraft(session.user.email);
  if (!profile && draft) {
    const error = await saveProfile(client, session.user, fakeForm(draft));
    if (!error) {
      localStorage.removeItem(DRAFT_KEY);
      profile = await profileOf(client, session.user.id);
    }
  }
  if (!profile) {
    showAccount(root, document.querySelector("#profile-form-template").innerHTML);
    const form = root.querySelector("form");
    form.email.value = session.user.email || "";
    bindProfileSave(client, session.user, form, root);
    return;
  }
  const skills = (profile.expertise || []).join(", ") || "None listed";
  showAccount(root, `
    <p class="eyebrow">${profile.role === "client" ? "Hiring" : "Available for work"}</p>
    <h1>${esc(profile.display_name)}</h1>
    <p class="muted">${esc(session.user.email || "")}</p>
    <p>${esc(skills)}</p>
    <p class="actions"><button class="ghost" id="sign-out" type="button">Sign out</button></p>
  `);
  root.querySelector("#sign-out").addEventListener("click", async () => {
    await client.auth.signOut();
    location.reload();
  });
}

function readDraft(email) {
  try {
    const draft = JSON.parse(localStorage.getItem(DRAFT_KEY) || "null");
    if (draft && draft.email === email) return draft;
  } catch (error) {
    return null;
  }
  return null;
}

function fakeForm(draft) {
  return {
    display_name: { value: draft.display_name || "" },
    role: { value: draft.role || "professional" },
    querySelectorAll: () => (draft.expertise || []).map((value) => ({ value, checked: true }))
  };
}

function bindProfileSave(client, user, form, root) {
  watchRole(form);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const note = form.querySelector(".form-note");
    const message = await saveProfile(client, user, form);
    if (message) {
      note.textContent = message;
      note.className = "form-note error";
      return;
    }
    localStorage.removeItem(DRAFT_KEY);
    initAccount();
  });
  root.querySelector("#cancel-session")?.addEventListener("click", async () => {
    await client.auth.signOut();
    location.reload();
  });
}

function bindSignedOut(client, root) {
  const note = root.querySelector(".form-note");
  watchRole(root.querySelector("#sign-up-form"));
  root.querySelector("#show-sign-up").addEventListener("click", () => {
    root.querySelector("#sign-in-panel").hidden = true;
    root.querySelector("#sign-up-panel").hidden = false;
  });
  root.querySelector("#show-sign-in").addEventListener("click", () => {
    root.querySelector("#sign-up-panel").hidden = true;
    root.querySelector("#sign-in-panel").hidden = false;
  });
  root.querySelector("#sign-in-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const result = await client.auth.signInWithPassword({
      email: form.email.value.trim(),
      password: form.password.value
    });
    if (result.error) {
      note.textContent = result.error.message;
      note.className = "form-note error";
      return;
    }
    initAccount();
  });
  root.querySelector("#sign-up-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const email = form.email.value.trim();
    const displayName = form.display_name.value.trim();
    const role = form.role.value;
    const expertise = role === "professional" ? selectedExpertise(form) : [];
    if (!displayName) {
      note.textContent = "Enter the name people should see.";
      note.className = "form-note error";
      return;
    }
    if (role === "professional" && !expertise.length) {
      note.textContent = "Choose at least one area of practice.";
      note.className = "form-note error";
      return;
    }
    const result = await client.auth.signUp({ email, password: form.password.value });
    if (result.error) {
      note.textContent = result.error.message;
      note.className = "form-note error";
      return;
    }
    localStorage.setItem(DRAFT_KEY, JSON.stringify({
      email,
      display_name: displayName,
      role,
      expertise
    }));
    if (result.data.session) {
      const message = await saveProfile(client, result.data.user, form);
      if (message) {
        note.textContent = message;
        note.className = "form-note error";
        return;
      }
      localStorage.removeItem(DRAFT_KEY);
      initAccount();
      return;
    }
    note.textContent = "Confirm the email, then sign in. The profile is saved on that sign-in.";
    note.className = "form-note notice";
  });
}

const page = document.body.dataset.page;
if (page === "jobs") initJobs();
if (page === "post") initPost();
if (page === "job") initJob();
if (page === "account") initAccount();
