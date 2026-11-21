const byId = id => document.getElementById(id);
const picker = byId("name");
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
  body.replaceChildren();
  let passed = 0;
  for (const profile of profiles) {
    for (const lesson of summary.lessons) {
      const result = profile.work[lesson.id];
      const row = body.insertRow();
      element(row, "td", profile.name);
      element(row, "td", lesson.title);
      element(row, "td", labels[result?.status ?? "new"]).classList.toggle("passed", result?.status === "passed");
      element(row, "td", result?.total ? `${result.passed} / ${result.total}` : "—");
      element(row, "td", result?.attempts ?? 0);
      if (result?.status === "passed") passed++;
    }
  }
  byId("progress-table").hidden = profiles.length === 0;
  status.textContent = profiles.length ? `Профилей: ${profiles.length} · Пройдено работ: ${passed}` :
    "Результаты появятся после первого действия в учебной машине или сохранения черновика.";
}

async function load() {
  byId("refresh").disabled = true;
  try {
    const response = await fetch("/api/summary");
    if (response.status === 403) {
      summary = undefined;
      picker.length = 1;
      body.replaceChildren();
      byId("progress-table").hidden = true;
      status.textContent = "Войдите как преподаватель, чтобы открыть сводку.";
      return;
    }
    if (!response.ok) throw Error();
    summary = await response.json();
    const selected = picker.value;
    picker.length = 1;
    for (const profile of summary.profiles) element(picker, "option", profile.name).value = profile.name;
    picker.value = summary.profiles.some(item => item.name === selected) ? selected : "";
    render();
  } catch {
    status.textContent = "Не удалось загрузить результаты. Нажмите «Обновить».";
  } finally {
    byId("refresh").disabled = false;
  }
}

picker.onchange = render;
byId("refresh").onclick = load;
addEventListener("pageshow", event => { if (event.persisted) load(); });
load();
