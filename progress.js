const byId = id => document.getElementById(id);
const picker = byId("name");
const workPicker = byId("work");
const statusPicker = byId("work-status");
const status = byId("summary-status");
const body = byId("summary-rows");
const labels = {passed: "Пройдена", started: "В работе", new: "Не начата"};
let summary;

function element(parent, tag, value) {
  const child = document.createElement(tag);
  child.textContent = value;
  parent.append(child);
  return child;
}

function render() {
  if (!summary) return;
  const profiles = summary.profiles.filter(profile => !picker.value || profile.name === picker.value);
  const lessons = summary.lessons.filter(lesson => !workPicker.value || lesson.id === workPicker.value);
  body.replaceChildren();
  const counts = {new: 0, started: 0, passed: 0};
  for (const profile of profiles) {
    for (const lesson of lessons) {
      const result = profile.work[lesson.id];
      const state = result?.status ?? "new";
      counts[state]++;
      if (statusPicker.value && state !== statusPicker.value) continue;
      const row = body.insertRow();
      element(row, "td", profile.name);
      element(row, "td", lesson.title);
      element(row, "td", labels[state]).classList.toggle("passed", state === "passed");
      element(row, "td", result?.total ? `${result.passed} / ${result.total}` : "—");
      element(row, "td", result?.attempts ?? 0);
    }
  }
  byId("progress-table").hidden = body.rows.length === 0;
  const breakdown = `Не начато: ${counts.new} · В работе: ${counts.started} · Пройдено: ${counts.passed}`;
  status.textContent = profiles.length ? `${breakdown}${body.rows.length ? "" : " · Нет записей с выбранным статусом"}` :
    "Результаты появятся после первого действия в учебной машине или сохранения черновика.";
}

function fillPicker(select, choices) {
  const selected = select.value;
  select.length = 1;
  for (const [value, label] of choices) element(select, "option", label).value = value;
  if (choices.some(([value]) => value === selected)) select.value = selected;
}

async function load() {
  byId("refresh").disabled = true;
  try {
    const response = await fetch("/api/summary");
    if (response.status === 403) {
      summary = undefined;
      picker.length = 1;
      workPicker.length = 1;
      body.replaceChildren();
      byId("progress-table").hidden = true;
      status.textContent = "Войдите как преподаватель, чтобы открыть сводку.";
      return;
    }
    if (!response.ok) throw Error();
    summary = await response.json();
    fillPicker(picker, summary.profiles.map(({name}) => [name, name]));
    fillPicker(workPicker, summary.lessons.map(({id, title}) => [id, title]));
    render();
  } catch {
    status.textContent = "Не удалось загрузить результаты. Нажмите «Обновить».";
  } finally {
    byId("refresh").disabled = false;
  }
}

picker.onchange = render;
workPicker.onchange = render;
statusPicker.onchange = render;
byId("refresh").onclick = load;
addEventListener("pageshow", event => { if (event.persisted) load(); });
load();
