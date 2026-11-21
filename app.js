const byId = id => document.getElementById(id);
const answers = byId("answers");
const wizardForm = byId("wizard-form");
const editor = byId("editor-text");
const profileInput = byId("profile");
const errorLine = byId("error");
let model, current, profile, progress = {};
let busy = false;
let classroomMode = false;
const transcripts = new Map();
const drafts = new Map();
const documentDrafts = new Map();
const lessonLinks = new Map();
let documentLoad;
const initialOutput = "Введите help, чтобы увидеть команды.";

async function request(path, body) {
  const options = body ? {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)} : {};
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) {
    if (classroomMode && response.status === 401 && path !== "/api/login") signedOut();
    throw Error(data.error);
  }
  return data;
}

function add(parent, name, text) {
  const node = document.createElement(name);
  node.textContent = text;
  parent.append(node);
  return node;
}

function state(lesson) {
  if (model.later.includes(lesson.id)) return "Позже";
  if (!Object.hasOwn(model.labs, lesson.id)) return "В разработке";
  const record = progress[lesson.id];
  if (record?.results?.every(item => item.passed)) return "Пройдена";
  return record ? "В работе" : "Не начата";
}

function catalog() {
  const nav = byId("catalog");
  if (!lessonLinks.size) {
    let number = 0;
    for (const section of model.course.sections) {
      add(nav, "h3", section.title);
      for (const lesson of section.lessons) {
        const link = add(nav, "a", "");
        link.href = `#${lesson.id}`;
        add(link, "span", `${++number}. ${lesson.title}`);
        lessonLinks.set(lesson, {link, status: add(link, "small", "")});
      }
    }
  }
  const active = [...lessonLinks.keys()].filter(lesson => Object.hasOwn(model.labs, lesson.id));
  const done = active.filter(lesson => state(lesson) === "Пройдена").length;
  byId("total").textContent = `${done} из ${active.length} доступных работ пройдено`;
  for (const [lesson, {link, status}] of lessonLinks) {
    link.setAttribute("aria-current", String(lesson.id === current.id));
    status.textContent = state(lesson);
  }
}

function report(record) {
  const list = byId("results");
  list.replaceChildren();
  for (const item of record?.results ?? []) {
    const row = add(list, "li", `${item.passed ? "✓" : "×"} ${item.label}${item.hint ? " — " + item.hint : ""}`);
    row.className = item.passed ? "passed" : "failed";
  }
  if (record?.attempts) add(list, "li", `Попыток: ${record.attempts}`);
}

function answerFields(lab, saved) {
  byId("answer-title").textContent = lab.title;
  byId("answer-prompt").textContent = lab.prompt;
  const container = byId("answer-fields");
  container.replaceChildren();
  for (const spec of lab.fields) {
    const label = add(container, "label", spec.label);
    const input = add(label, spec.options ? "select" : "input", "");
    input.name = spec.name;
    if (spec.options) {
      add(input, "option", "Выберите ответ").value = "";
      for (const [value, name] of Object.entries(spec.options)) add(input, "option", name).value = value;
    } else {
      input.maxLength = 150;
    }
    input.value = saved?.[spec.name] ?? "";
  }
}

function render() {
  catalog();
  byId("meta").textContent = `${current.hours} ак. ч.  /  ${state(current)}`;
  byId("lesson-title").textContent = current.title;
  const lab = model.labs[current.id];
  byId("workspace").hidden = !lab;
  byId("editor-form").hidden = !lab?.editor;
  wizardForm.hidden = !lab?.wizard;
  byId("availability").textContent = lab ? (lab.wizard ? "Linux · Симулятор установки" : "Linux · Симуляция команд") :
    model.later.includes(current.id) ? "Работа с Windows запланирована на следующий этап." :
    "Шаги работы доступны. Учебная среда и самопроверка готовятся.";
  const steps = byId("steps");
  steps.replaceChildren();
  current.steps.forEach(step => add(steps, "li", step));
  if (lab) {
    const record = progress[current.id];
    answerFields(lab, drafts.get(current.id) ?? record?.answers);
    const output = byId("output");
    output.textContent = transcripts.get(current.id) ?? initialOutput;
    output.scrollTop = output.scrollHeight;
    byId("command").value = "";
    byId("save-status").textContent = "";
    report(record);
    if (lab.editor) loadDocument(lab.editor);
    if (lab.wizard) loadWizard();
  }
}

function showWizard(data) {
  const button = byId("wizard-apply");
  const fields = byId("wizard-fields");
  const selected = wizardForm.dataset.stage === data.id ? [...new FormData(wizardForm).values()] : [];
  delete wizardForm.dataset.stage;
  byId("wizard-title").textContent = data.title;
  byId("wizard-step").textContent = data.id ? `Шаг ${data.stage + 1} из ${data.total}` : "";
  byId("wizard-status").textContent = data.message;
  fields.replaceChildren();
  button.hidden = !data.id;
  button.disabled = !data.id;
  if (!data.id) return;
  wizardForm.dataset.stage = data.id;
  for (const [index, field] of data.fields.entries()) {
    const label = add(fields, "label", field.label);
    const select = add(label, "select", "");
    select.name = String(index);
    select.required = true;
    add(select, "option", "Выберите вариант").value = "";
    for (const [value, text] of Object.entries(field.options)) add(select, "option", text).value = value;
    select.value = selected[index] ?? "";
  }
  button.textContent = data.action;
}

async function loadWizard() {
  const name = profile;
  const lesson = current.id;
  showWizard({title: "Учебный установщик Debian", message: "Загружаем состояние…"});
  try {
    const reply = await request("/api/terminal", {profile: name, lesson, command: "installer status"});
    if (profile === name && current.id === lesson) showWizard(reply.wizard);
  } catch (error) {
    if (profile === name && current.id === lesson) errorLine.textContent = error.message;
  }
}

async function loadDocument(path) {
  const name = profile;
  const lesson = current.id;
  const load = documentLoad = Symbol();
  const save = byId("editor-save");
  byId("editor-path").textContent = path;
  if (documentDrafts.has(lesson)) {
    editor.value = documentDrafts.get(lesson);
    editor.disabled = save.disabled = false;
    byId("editor-status").textContent = "Есть несохранённые изменения";
    return;
  }
  byId("editor-status").textContent = "";
  editor.value = "";
  editor.disabled = save.disabled = true;
  try {
    const reply = await request("/api/document", {lesson, profile: name});
    if (load !== documentLoad || current.id !== lesson || profile !== name) return;
    editor.value = reply.text;
    editor.disabled = save.disabled = false;
  } catch (error) {
    if (load === documentLoad && current.id === lesson && profile === name) errorLine.textContent = error.message;
  }
}

function lessonFromHash() {
  const lessons = model.course.sections.flatMap(section => section.lessons);
  return lessons.find(lesson => "#" + lesson.id === location.hash) ?? lessons[0];
}

addEventListener("hashchange", () => {
  if (profile && !busy) syncLesson();
});

async function openProfile(name) {
  progress = await request("/api/progress?profile=" + encodeURIComponent(name));
  if (profile !== name) {
    transcripts.clear();
    drafts.clear();
    documentDrafts.clear();
  }
  profile = name;
  current = lessonFromHash();
  profileInput.value = name;
  if (!classroomMode) localStorage.setItem("op01-profile", name);
  render();
}

async function save(mode) {
  if (busy || !profile) return;
  busy = true;
  const fields = Object.fromEntries(new FormData(answers));
  try {
    const old = progress[current.id];
    const reply = await request("/api/" + mode, {lesson: current.id, profile, answers: fields});
    progress[current.id] = {answers: fields, ...reply, results: reply.results ?? old?.results};
    byId("save-status").textContent = mode === "draft" ? "Черновик сохранён" : "Проверка сохранена";
    byId("meta").textContent = `${current.hours} ак. ч.  /  ${state(current)}`;
    errorLine.textContent = "";
    report(progress[current.id]);
    catalog();
  } catch (error) {
    errorLine.textContent = error.message;
  } finally {
    busy = false;
    syncLesson();
  }
}

function syncLesson() {
  const next = lessonFromHash();
  if (next.id !== current.id) {
    current = next;
    render();
  }
}

function signedOut() {
  profile = undefined;
  progress = {};
  drafts.clear();
  transcripts.clear();
  documentDrafts.clear();
  byId("session-controls").hidden = true;
  byId("teacher-link").hidden = true;
  byId("practice").hidden = true;
  byId("sign-in").hidden = false;
}

async function signedIn(identity) {
  await openProfile(identity.profile);
  byId("sign-in").hidden = true;
  byId("session-controls").hidden = false;
  byId("session-name").textContent = identity.profile;
  byId("teacher-link").hidden = !identity.teacher;
  byId("practice").hidden = false;
}

byId("login-form").onsubmit = async event => {
  event.preventDefault();
  if (busy) return;
  busy = true;
  try {
    const identity = await request("/api/login", {login: byId("login").value.trim(), password: byId("password").value});
    byId("password").value = "";
    await signedIn(identity);
    errorLine.textContent = "";
  } catch (error) {
    errorLine.textContent = error.message;
  } finally {
    busy = false;
    if (profile) syncLesson();
  }
};

byId("logout").onclick = async () => {
  if (busy) return;
  busy = true;
  try {
    await request("/api/logout", {});
    signedOut();
    errorLine.textContent = "";
  } catch (error) {
    errorLine.textContent = error.message;
  } finally {
    busy = false;
  }
};

function markActivity(started) {
  const previous = progress[current.id];
  if (started && !previous) {
    progress[current.id] = {answers: {}, attempts: 0, activity_only: true};
  } else if (!started && previous?.activity_only) {
    delete progress[current.id];
  } else {
    return;
  }
  byId("meta").textContent = `${current.hours} ак. ч.  /  ${state(current)}`;
  catalog();
}

byId("profile-form").onsubmit = async event => {
  event.preventDefault();
  if (busy || !model || !current) return;
  busy = true;
  try {
    await openProfile(profileInput.value.trim());
    errorLine.textContent = "";
  } catch (error) {
    errorLine.textContent = error.message;
  } finally {
    busy = false;
    syncLesson();
  }
};
answers.oninput = () => drafts.set(current.id, Object.fromEntries(new FormData(answers)));
answers.onsubmit = event => { event.preventDefault(); save("check"); };
byId("draft").onclick = () => save("draft");
editor.oninput = () => {
  documentDrafts.set(current.id, editor.value);
  byId("editor-status").textContent = "Есть несохранённые изменения";
};
byId("editor-form").onsubmit = async event => {
  event.preventDefault();
  if (busy || editor.disabled) return;
  busy = true;
  const lesson = current.id;
  const text = editor.value;
  try {
    await request("/api/document", {lesson, profile, text});
    markActivity(true);
    if (editor.value === text) {
      documentDrafts.delete(lesson);
      byId("editor-status").textContent = "Файл сохранён";
    }
    errorLine.textContent = "";
  } catch (error) {
    errorLine.textContent = error.message;
  } finally {
    busy = false;
    syncLesson();
  }
};
async function sendCommand(command, echo) {
  busy = true;
  const output = byId("output");
  try {
    const reply = await request("/api/terminal", {lesson: current.id, profile, command});
    markActivity(reply.started);
    if (reply.wizard) showWizard(reply.wizard);
    if (echo) {
      output.textContent = (output.textContent + `\n\nstudent@lab$ ${command}\n${reply.output}`).slice(-18000);
      transcripts.set(current.id, output.textContent);
      output.scrollTop = output.scrollHeight;
    }
    errorLine.textContent = "";
    if (command === "lab-reset" && model.labs[current.id].editor) {
      documentDrafts.delete(current.id);
      loadDocument(model.labs[current.id].editor);
    }
  } catch (error) {
    errorLine.textContent = error.message;
  } finally {
    busy = false;
    syncLesson();
  }
}

wizardForm.onsubmit = event => {
  event.preventDefault();
  if (busy || !profile || !wizardForm.dataset.stage) return;
  const values = [...new FormData(wizardForm).values()];
  sendCommand(["installer", wizardForm.dataset.stage, ...values].join(" "), false);
};

byId("command-form").onsubmit = event => {
  event.preventDefault();
  if (busy || !profile) return;
  const input = byId("command");
  const command = input.value.trim();
  if (!command) return;
  input.value = "";
  sendCommand(command, true);
};

try {
  const [catalogue, session] = await Promise.all([request("/api/course"), request("/api/session")]);
  model = catalogue;
  current = lessonFromHash();
  classroomMode = session.classroom;
  if (classroomMode) {
    if (session.identity) await signedIn(session.identity);
    else signedOut();
  } else {
    await openProfile(localStorage.getItem("op01-profile") || "Ученик");
    byId("profile-form").hidden = false;
    byId("teacher-link").hidden = false;
    byId("practice").hidden = false;
  }
} catch (error) {
  errorLine.textContent = error.message;
}
