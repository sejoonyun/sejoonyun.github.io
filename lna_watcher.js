// lna-watcher.js
(() => {
  const STYLE_ID = "__lna_style__";
  const DIALOG_ID = "__lna_dialog__";

  let lastState = null;

  /* =========================
   *  UI & Style Injection
   * ========================= */

  function injectStyle() {
    if (document.getElementById(STYLE_ID)) return;

    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
      body.__lna_blocked__ > *:not(#${DIALOG_ID}) {
        display: none !important;
      }

      #${DIALOG_ID} {
        position: fixed;
        inset: 0;
        background: rgba(0,0,0,0.85);
        color: #fff;
        display: none;
        z-index: 2147483647;
        align-items: center;
        justify-content: center;
        font-family: system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
      }

      #${DIALOG_ID}.show {
        display: flex;
      }

      #${DIALOG_ID} .box {
        background: #1e1e1e;
        padding: 32px 40px;
        border-radius: 14px;
        max-width: 440px;
        text-align: center;
        box-shadow: 0 20px 60px rgba(0,0,0,0.5);
      }

      #${DIALOG_ID} h2 {
        margin: 0 0 16px;
        font-size: 22px;
      }

      #${DIALOG_ID} p {
        margin: 8px 0;
        line-height: 1.5;
        opacity: .9;
      }

      #${DIALOG_ID} .hint {
        margin-top: 18px;
        font-size: 14px;
        opacity: .6;
      }
    `;
    document.head.appendChild(style);
  }

  function injectDialog() {
    if (document.getElementById(DIALOG_ID)) return;

    const dialog = document.createElement("div");
    dialog.id = DIALOG_ID;
    dialog.innerHTML = `
      <div class="box">
        <h2>로컬 네트워크 접근 권한 필요</h2>
        <p>
          이 기능을 사용하려면<br />
          <strong>Local Network Access</strong> 권한이 필요합니다.
        </p>
        <p class="hint">
          브라우저 권한 요청이 곧 표시됩니다.
        </p>
      </div>
    `;
    document.body.appendChild(dialog);
  }

  function showDialog() {
    document.body.classList.add("__lna_blocked__");
    document.getElementById(DIALOG_ID)?.classList.add("show");
  }

  function hideDialog() {
    document.body.classList.remove("__lna_blocked__");
    document.getElementById(DIALOG_ID)?.classList.remove("show");
  }

  /* =========================
   *  Permission Handling
   * ========================= */

  async function queryLNA() {
    try {
      return await navigator.permissions.query({
        name: "local-network-access"
      });
    } catch (e) {
      console.warn("[LNA] Permissions API not supported", e);
      return null;
    }
  }

  async function triggerPrompt() {
    try {
      // 실제 LNA prompt를 발생시키기 위한 localhost 호출
      await fetch("http://127.0.0.1", { mode: "cors" });
    } catch (_) {
      // 실패해도 prompt는 발생함
    }
  }

  async function watchPermission() {
    const perm = await queryLNA();
    if (!perm) return;

    if (perm.state === lastState) return;
    lastState = perm.state;

    if (perm.state === "prompt") {
      console.log("[LNA] state = prompt");
      showDialog();
      triggerPrompt();
    }

    if (perm.state === "granted") {
      console.log("[LNA] state = allow");
      hideDialog();
    }

    if (perm.state === "denied") {
      console.log("[LNA] state = block");
      hideDialog();
    }
  }

  /* =========================
   *  Bootstrap
   * ========================= */

  function start() {
    injectStyle();
    injectDialog();
    watchPermission();
    setInterval(watchPermission, 500);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
