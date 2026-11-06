/* MIT Blog Crawler 前端逻辑：
 * - 开始采集：一次启动两套任务
 * - SSE：两套框架各自独立的实时进度流
 * - 采集未停止前禁止下载 CSV
 * - 无结果预览区域，结果通过 CSV 下载查看
 */

const FRAMEWORKS = ["playwright", "drissionpage"];
const sources = {};        // framework -> EventSource
const elapsedTimers = {};  // framework -> interval id

const btnStart = document.getElementById("btnStart");
const btnStop = document.getElementById("btnStop");
const btnReset = document.getElementById("btnReset");
const globalMsg = document.getElementById("globalMsg");

/* ---------- 启动 / 停止 ---------- */

btnStart.onclick = async () => {
  const mode = document.querySelector('input[name="mode"]:checked').value;
  const maxPages = mode === "all" ? 0 : Math.max(1, parseInt(document.getElementById("maxPages").value, 10) || 1);
  globalMsg.textContent = "";
  try {
    const res = await fetch("/api/crawl/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ max_pages: maxPages }),
    });
    const data = await res.json();
    if (!res.ok) {
      globalMsg.textContent = data.detail || "启动失败";
      return;
    }
    setRunningUI(true);
    FRAMEWORKS.forEach(connectStream);
  } catch (err) {
    globalMsg.textContent = "启动失败：" + err.message;
  }
};

btnStop.onclick = async () => {
  await fetch("/api/crawl/stop", { method: "POST" });
  globalMsg.textContent = "已发送停止信号，任务正在收尾…";
};

btnReset.onclick = async () => {
  if (!confirm("确定要清空两套爬虫已采集的全部数据吗？\n此操作会删除两个 CSV 和断点记录，不可恢复。")) {
    return;
  }
  try {
    const res = await fetch("/api/crawl/reset", { method: "POST" });
    const data = await res.json();
    if (!res.ok) {
      globalMsg.textContent = data.detail || "重置失败";
      return;
    }
    // 重置成功后刷新状态展示
    const statusRes = await fetch("/api/crawl/status");
    const statuses = await statusRes.json();
    FRAMEWORKS.forEach((fw) => renderState(fw, statuses[fw]));
    globalMsg.textContent = "已重置：" + (data.deleted.length ? data.deleted.join("、") : "无数据文件");
  } catch (err) {
    globalMsg.textContent = "重置失败：" + err.message;
  }
};

function setRunningUI(running) {
  btnStart.disabled = running;
  btnStop.disabled = !running;
  btnReset.disabled = running;
  updateDownloads();
}

/* ---------- SSE 实时进度 ---------- */

function connectStream(framework) {
  if (sources[framework]) sources[framework].close();
  const source = new EventSource(`/api/crawl/stream/${framework}`);
  sources[framework] = source;
  source.onmessage = (event) => {
    const snap = JSON.parse(event.data);
    renderState(framework, snap);
    if (["finished", "stopped", "error"].includes(snap.status)) {
      source.close();
      delete sources[framework];
      stopElapsedTimer(framework);
      if (!Object.keys(sources).length) {
        setRunningUI(false);
        globalMsg.textContent = "任务结束：" + snap.status;
      }
      updateDownloads();
    }
  };
  source.onerror = () => {
    source.close();
    delete sources[framework];
  };
}

/* ---------- 状态渲染 ---------- */

function renderState(framework, snap) {
  const card = document.getElementById(`card-${framework}`);
  const statusEl = card.querySelector(".status");
  statusEl.textContent = snap.status;
  statusEl.className = "status " + snap.status;
  card.querySelector(".current-page").textContent = snap.current_page;
  card.querySelector(".total-pages").textContent = snap.total_pages ?? "?";
  card.querySelector(".discovered").textContent = snap.discovered_count;
  card.querySelector(".success").textContent = snap.success_count;
  card.querySelector(".failed").textContent = snap.failed_count;
  card.querySelector(".article").textContent = snap.current_article || "-";
  card.querySelector(".start-time").textContent = snap.start_time || "-";

  const bar = card.querySelector(".progress-bar");
  const text = card.querySelector(".progress-text");
  if (snap.progress.mode === "percent") {
    bar.style.width = snap.progress.percent + "%";
    text.textContent = `已采集 ${snap.progress.processed} / 总 ${snap.progress.total} 篇（${snap.progress.percent}%）`;
  } else {
    bar.style.width = "0%";
    text.textContent = `已处理 ${snap.progress.processed} 篇（文章总数未知，不伪造百分比）`;
  }

  if (snap.status === "running" && snap.start_time && !elapsedTimers[framework]) {
    const startedAt = Date.now() - snap.elapsed_time * 1000;
    elapsedTimers[framework] = setInterval(() => {
      const sec = Math.round((Date.now() - startedAt) / 1000);
      card.querySelector(".elapsed").textContent = sec >= 60 ? `${Math.floor(sec / 60)}m${sec % 60}s` : `${sec}s`;
    }, 1000);
  }
}

function stopElapsedTimer(framework) {
  if (elapsedTimers[framework]) {
    clearInterval(elapsedTimers[framework]);
    delete elapsedTimers[framework];
  }
}

/* ---------- 下载控制：采集未停止前禁止下载 ---------- */

const downloadLinks = document.querySelectorAll("a.download");

function updateDownloads() {
  fetch("/api/crawl/status")
    .then((r) => r.json())
    .then((statuses) => {
      const busy = FRAMEWORKS.some((fw) => ["running", "stopping"].includes(statuses[fw].status));
      downloadLinks.forEach((link) => {
        link.classList.toggle("disabled", busy);
        link.title = busy ? "采集进行中，停止后才能下载" : "";
      });
    })
    .catch(() => {});
}

downloadLinks.forEach((link) => {
  link.addEventListener("click", (e) => {
    if (link.classList.contains("disabled")) {
      e.preventDefault();
      globalMsg.textContent = "采集进行中，停止后才能下载";
    }
  });
});

/* 页面加载时刷新一次状态 */
(async () => {
  try {
    const res = await fetch("/api/crawl/status");
    const statuses = await res.json();
    FRAMEWORKS.forEach((fw) => renderState(fw, statuses[fw]));
    const anyRunning = FRAMEWORKS.some((fw) => ["running", "stopping"].includes(statuses[fw].status));
    if (anyRunning) {
      setRunningUI(true);
      FRAMEWORKS.forEach(connectStream);
    }
    updateDownloads();
  } catch (err) {
    globalMsg.textContent = "后端未启动？请先运行 uvicorn backend.main:app";
  }
})();
