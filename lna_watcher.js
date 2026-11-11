// lna-watcher.js
(() => {
  const STYLE_ID = "__lna_style__";
  const DIALOG_ID = "__lna_dialog__";
  const START_DELAY = 2500; // 2.5초 지연

  let lastState = null;
  let started = false;

  /* =========================
   *  UI & Style Injection
   * ========================= */

  function injectStyle() {
    if (document.getElementById(STYLE_ID)) return;

    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
      body.__lna_blocked__ {
        overflow: hidden;
      }

      body.__lna_blocked__ > *:not(#${DIALOG_ID}) {
        filter: blur(14px);
        transition: filter .25s ease;
        pointer-events: none;
        user-select: none;
      }

      #${DIALOG_ID} {
        position: fixed;
        inset: 0;
        display: none;
        z-index: 2147483647;
        align-items: center;
        justify-content: center;
        font-family: system-ui, -apple-system, BlinkMacSystemFont, sans-serif;

        /* 배경 레이어 */
        background: rgba(20, 30, 45, 0.55);
        backdrop-filter: blur(10px);
      }

      #${DIALOG_ID}.show {
        display: flex;
      }

      #${DIALOG_ID} .box {
        background: linear-gradient(
          180deg,
          #2b3a4a 0%,
          #1f2a36 100%
        );
        padding: 34px 44px;
        border-radius: 16px;
        max-width: 460px;
        text-align: center;
        color: #e9eef3;

        box-shadow:
          0 30px 80px rgba(0,0,0,0.45),
          inset 0 1px 0 rgba(255,255,255,0.06);
      }

      #${DIALOG_ID} h2 {
        margin: 0 0 16px;
        font-size: 22px;
        font-weight: 600;
        letter-spacing: -0.2px;
      }

      #${DIALOG_ID} p {
        margin: 10px 0;
        line-height: 1.6;
        font-size: 15px;
        color: #d5dde6;
      }

      #${DIALOG_ID} strong {
        color: #9ecbff;
        font-weight: 600;
      }

      #${DIALOG_ID} .hint {
        margin-top: 20px;
        font-size: 13px;
        opacity: .65;
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
        <h2>로컬 네트워크 접근 권한 요청</h2>
        <p>
          이 콘텐츠는 내부 네트워크 자원과 통신합니다.<br />
          계속하려면 <strong>Local Network Access</strong> 권한이 필요합니다.
        </p>
        <p class="hint">
          잠시 후 브라우저 권한 요청이 표시됩니다.
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
      await fetch("http://127.0.0.1", { mode: "cors" });
    } catch (_) {
      // 실패해도 prompt는 발생
    }
  }

  async function watchPermission() {
    if (!started) return;

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

    setTimeout(() => {
      started = true;
      watchPermission();
      setInterval(watchPermission, 500);
    }, START_DELAY);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
