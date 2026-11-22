const byId = id => document.getElementById(id);
const form = byId("task-form");
const templatePicker = byId("task-template");
const checks = byId("task-checks");
const questions = byId("task-questions");
const status = byId("task-status");
const saveStatus = byId("task-save-status");
const openTask = byId("open-task");
const exportTask = byId("export-task");
let catalogue, active;
let dirty = false;
let busy = false;

function create(parent, tag, text = "") {
  const node = document.createElement(tag);
  node.textContent = text;
  parent.append(node);
  return node;
}

async function request(path, payload) {
  const options = payload ? {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)} : {};
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw Error(data.error);
  return data;
}

function message(text, {target = status, error = false, duration = 0, opacity = 0.5} = {}) {
  target.textContent = text;
  target.classList.toggle("failed", error);
  if (text && duration) {
    const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
    target.animate([{opacity: reduced ? 0.9 : opacity}, {opacity: 1}], {
      duration: reduced ? 90 : duration, easing: "cubic-bezier(0.23, 1, 0.32, 1)",
    });
  }
}

function unsaved(event) {
  event.preventDefault();
  event.returnValue = "";
}

function setDirty(value) {
  dirty = value;
  if (dirty) addEventListener("beforeunload", unsaved);
  else removeEventListener("beforeunload", unsaved);
  const saved = active.revision > 0 && !dirty;
  exportTask.hidden = openTask.hidden = !saved;
}

function setBusy(value) {
  busy = value;
  byId("task-fields").disabled = value;
  byId("new-task").disabled = byId("import-task").disabled = value || !catalogue;
}

function showList() {
  const list = byId("saved-tasks");
  list.replaceChildren();
  byId("tasks-empty").hidden = catalogue.tasks.length > 0;
  byId("tasks-empty").textContent = "Создайте первую работу или откройте файл задания.";
  for (const entry of catalogue.tasks) {
    const button = create(create(list, "li"), "button", entry.task.title);
    button.type = "button";
    if (entry.task.id === active?.task.id) button.setAttribute("aria-current", "true");
    button.onclick = () => { if (mayLeave()) showTask(entry); };
  }
}

function mayLeave() {
  return !busy && (!dirty || confirm("Выйти из текущей работы без сохранения изменений?"));
}

function showChecks(selected) {
  checks.replaceChildren();
  const template = catalogue.templates.find(item => item.id === templatePicker.value);
  for (const [key, label] of Object.entries(template.checks)) {
    const row = create(checks, "label");
    const input = create(row, "input");
    input.type = "checkbox";
    input.value = key;
    input.checked = selected.includes(key);
    row.append(document.createTextNode(label));
  }
}

function questionRow(question) {
  const row = create(questions, "div");
  row.className = "task-question";
  row.dataset.question = question.id;
  for (const [key, title] of [["label", "Вопрос"], ["answer", "Эталонный ответ"]]) {
    const input = create(create(row, "label", title), "input");
    input.required = true;
    input.maxLength = 150;
    input.name = key;
    input.value = question[key];
  }
  const remove = create(row, "button", "Удалить вопрос");
  remove.type = "button";
  remove.onclick = () => {
    row.remove();
    byId("add-question").disabled = false;
    setDirty(true);
    byId("add-question").focus();
  };
  return row;
}

function showTask(entry, changed = false) {
  active = entry;
  const {task, revision} = active;
  byId("task-title").value = task.title;
  byId("task-hours").value = task.hours;
  templatePicker.value = task.template;
  templatePicker.disabled = revision > 0;
  byId("task-steps").value = task.steps.join("\n");
  showChecks(task.checks);
  questions.replaceChildren();
  task.questions.forEach(questionRow);
  byId("add-question").disabled = task.questions.length >= 10;
  byId("copy-task").hidden = revision === 0;
  openTask.href = `/#${task.id}`;
  openTask.target = "_blank";
  openTask.rel = "noopener";
  setDirty(changed);
  showList();
  form.hidden = false;
  message("");
  message("", {target: saveStatus});
}

function draftTask() {
  return {
    version: 1,
    id: active.task.id,
    title: byId("task-title").value,
    hours: byId("task-hours").valueAsNumber,
    template: templatePicker.value,
    steps: byId("task-steps").value.split(/\r?\n/).map(step => step.trim()).filter(Boolean),
    checks: [...checks.querySelectorAll(":checked")].map(item => item.value),
    questions: [...questions.children].map(row => ({
      id: row.dataset.question,
      label: row.querySelector('[name="label"]').value,
      answer: row.querySelector('[name="answer"]').value,
    })),
  };
}

form.oninput = () => {
  setDirty(true);
  message("", {target: saveStatus});
};
templatePicker.onchange = () => showChecks(Object.keys(catalogue.templates.find(item => item.id === templatePicker.value).checks));
byId("new-task").onclick = () => {
  if (!mayLeave()) return;
  const template = catalogue.templates[0];
  showTask({revision: 0, task: {version: 1, id: `custom-${crypto.randomUUID()}`, title: "", hours: 2,
    template: template.id, steps: [], checks: Object.keys(template.checks), questions: []}});
  byId("task-title").focus();
};
byId("copy-task").onclick = () => {
  if (busy) return;
  showTask({revision: 0, task: {...draftTask(), id: `custom-${crypto.randomUUID()}`}}, true);
  message("Копия появится в оглавлении после сохранения.");
  byId("task-title").focus();
};
byId("add-question").onclick = () => {
  questionRow({id: `q-${crypto.randomUUID().slice(0, 24)}`, label: "", answer: ""}).querySelector("input").focus();
  byId("add-question").disabled = questions.children.length >= 10;
  setDirty(true);
};

byId("import-task").onclick = () => { if (mayLeave()) byId("task-file").click(); };
byId("task-file").onchange = async event => {
  const file = event.target.files[0];
  event.target.value = "";
  if (!file || busy) return;
  setBusy(true);
  try {
    if (file.size > 65_536) throw Error("Файл задания должен быть меньше 64 КБ.");
    let input;
    try { input = JSON.parse((await file.text()).replace(/^\uFEFF/, "")); }
    catch { throw Error("Файл не удалось прочитать. Выберите JSON с заданием ОП.01."); }
    const {task} = await request("/api/tasks/preview", {task: input});
    const existing = catalogue.tasks.find(entry => entry.task.id === task.id);
    showTask({task, revision: existing?.revision ?? 0}, true);
    message(existing ? "Файл относится к существующей работе. Сохраните изменения или создайте копию." :
      "Проверьте условие и сохраните работу, чтобы добавить её в оглавление.", {duration: 160, opacity: 0.6});
    byId("task-title").focus();
  } catch (error) {
    message(error.message, {error: true});
  } finally {
    setBusy(false);
  }
};

form.onsubmit = async event => {
  event.preventDefault();
  if (busy) return;
  const task = draftTask();
  setBusy(true);
  try {
    const saved = await request("/api/tasks", {task, revision: active.revision});
    catalogue.tasks = catalogue.tasks.filter(entry => entry.task.id !== task.id).concat(saved)
      .sort((left, right) => left.task.title.localeCompare(right.task.title, "ru"));
    showTask(saved);
    message("Работа сохранена и доступна ученикам в оглавлении.", {target: saveStatus, duration: 140});
  } catch (error) {
    message(error.message, {target: saveStatus, error: true});
  } finally {
    setBusy(false);
  }
};

exportTask.onclick = () => {
  const blob = new Blob([JSON.stringify(active.task, null, 2) + "\n"], {type: "application/json"});
  const asset = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = asset;
  link.download = `${active.task.id}.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(asset), 1000);
};

try {
  catalogue = await request("/api/tasks");
  catalogue.tasks.sort((left, right) => left.task.title.localeCompare(right.task.title, "ru"));
  for (const template of catalogue.templates) create(templatePicker, "option", template.title).value = template.id;
  if (catalogue.tasks.length) showTask(catalogue.tasks[0]);
  else showList();
  setBusy(false);
} catch (error) {
  byId("tasks-empty").hidden = true;
  message(error.message, {error: true});
}
