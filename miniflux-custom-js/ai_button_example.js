;(function () {
  "use strict";

  function getEntryIdFromUrl() {
    var match = window.location.pathname.match(/\/entry\/(\d+)/);
    if (match && match[1]) {
      return match[1];
    }
    return null;
  }

  function addAiButtonToEntryView() {
    var container = document.querySelector(".entry header .entry-actions");
    if (!container) {
      return;
    }

    if (container.querySelector(".ai-process-button")) {
      return;
    }

    var button = document.createElement("button");
    button.type = "button";
    button.textContent = "AI";
    button.className = "ai-process-button page-link";

    button.addEventListener("click", function () {
      var entryId =
        container.getAttribute("data-entry-id") || getEntryIdFromUrl();
      if (!entryId) {
        alert("无法获取条目 ID");
        return;
      }

      fetch("/miniflux-ai/manual-process", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ entry_id: entryId }),
      })
        .then(function (response) {
          if (!response.ok) {
            throw new Error("HTTP " + response.status);
          }
          return response
            .json()
            .catch(function () {
              return {};
            });
        })
        .then(function () {
          alert("AI 处理已触发");
        })
        .catch(function (error) {
          alert("AI 处理失败: " + error.message);
        });
    });

    container.appendChild(button);
  }

  function init() {
    addAiButtonToEntryView();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

