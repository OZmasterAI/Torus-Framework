// Torus Voice — Web Speech API + WebSocket client + chat UI

(function () {
  "use strict";

  // --- DOM refs ---
  var authScreen = document.getElementById("auth-screen");
  var chatScreen = document.getElementById("chat-screen");
  var tokenInput = document.getElementById("token-input");
  var authBtn = document.getElementById("auth-btn");
  var authError = document.getElementById("auth-error");
  var messages = document.getElementById("messages");
  var textInput = document.getElementById("text-input");
  var sendBtn = document.getElementById("send-btn");
  var micBtn = document.getElementById("mic-btn");
  var micLabel = document.getElementById("mic-label");
  var statusDot = document.getElementById("status-dot");

  // --- State ---
  var ws = null;
  var recognition = null;
  var isListening = false;
  var transcript = "";
  var interimText = "";
  var thinkingEl = null;

  var TOKEN_KEY = "torus_voice_token";
  var hasSpeechAPI = "webkitSpeechRecognition" in window || "SpeechRecognition" in window;

  // --- Auth ---

  function getStoredToken() {
    return localStorage.getItem(TOKEN_KEY);
  }

  function showAuth() {
    authScreen.hidden = false;
    chatScreen.hidden = true;
    tokenInput.focus();
  }

  function showChat() {
    authScreen.hidden = true;
    chatScreen.hidden = false;
    textInput.focus();
    if (!hasSpeechAPI) {
      micBtn.disabled = true;
      micLabel.textContent = "Speech not available";
    }
  }

  authBtn.addEventListener("click", function () {
    var token = tokenInput.value.trim();
    if (!token) return;
    localStorage.setItem(TOKEN_KEY, token);
    connectWS(token);
  });

  tokenInput.addEventListener("keydown", function (e) {
    if (e.key === "Enter") authBtn.click();
  });

  // --- WebSocket ---

  function connectWS(token) {
    var proto = location.protocol === "https:" ? "wss:" : "ws:";
    var url = proto + "//" + location.host + "/ws?token=" + encodeURIComponent(token);

    ws = new WebSocket(url);

    ws.onopen = function () {
      setStatus("connecting");
    };

    ws.onmessage = function (evt) {
      var data;
      try {
        data = JSON.parse(evt.data);
      } catch (e) {
        return;
      }

      switch (data.type) {
        case "status":
          if (data.text === "authenticated") {
            setStatus("connected");
            showChat();
          } else if (data.text === "thinking") {
            showThinking();
          }
          break;

        case "response":
          hideThinking();
          addMessage(data.text, "claude");
          break;

        case "error":
          hideThinking();
          if (data.text === "Invalid token" || data.text === "Auth timeout") {
            localStorage.removeItem(TOKEN_KEY);
            authError.textContent = data.text;
            authError.hidden = false;
            showAuth();
          } else {
            addMessage(data.text, "error");
          }
          break;
      }
    };

    ws.onclose = function (evt) {
      setStatus("error");
      // 1008 = policy violation (auth failed) — don't reconnect
      if (evt.code === 1008) {
        localStorage.removeItem(TOKEN_KEY);
        authError.textContent = "Invalid token";
        authError.hidden = false;
        showAuth();
        return;
      }
      var storedToken = getStoredToken();
      if (storedToken && !chatScreen.hidden) {
        setTimeout(function () { connectWS(storedToken); }, 3000);
      }
    };

    ws.onerror = function () {
      setStatus("error");
    };
  }

  function setStatus(state) {
    statusDot.className = "dot dot-" + state;
  }

  // --- Messages UI ---

  function addMessage(text, type) {
    var div = document.createElement("div");
    div.className = "msg msg-" + type;
    div.textContent = text;
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
  }

  function showThinking() {
    hideThinking();
    thinkingEl = document.createElement("div");
    thinkingEl.className = "msg msg-status thinking";
    thinkingEl.textContent = "Claude is thinking";
    messages.appendChild(thinkingEl);
    messages.scrollTop = messages.scrollHeight;
  }

  function hideThinking() {
    if (thinkingEl) {
      thinkingEl.remove();
      thinkingEl = null;
    }
  }

  // --- Send message ---

  function sendMessage(text) {
    text = text.trim();
    if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;
    addMessage(text, "user");
    ws.send(JSON.stringify({ type: "message", text: text }));
    textInput.value = "";
  }

  sendBtn.addEventListener("click", function () { sendMessage(textInput.value); });

  textInput.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(textInput.value);
    }
  });

  // --- Web Speech API (push-to-talk) ---

  function initSpeech() {
    if (!hasSpeechAPI) return;

    var SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    recognition = new SpeechRecognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = "en-US";

    recognition.onresult = function (event) {
      var interim = "";
      var final_ = "";
      for (var i = event.resultIndex; i < event.results.length; i++) {
        var t = event.results[i][0].transcript;
        if (event.results[i].isFinal) {
          final_ += t;
        } else {
          interim += t;
        }
      }
      transcript += final_;
      interimText = interim;
      micLabel.textContent = transcript + interim || "Listening...";
    };

    recognition.onerror = function (event) {
      console.error("Speech error:", event.error);
      stopListening();
      if (event.error === "not-allowed") {
        micBtn.disabled = true;
        micLabel.textContent = "Mic permission denied";
      }
    };

    recognition.onend = function () {
      if (isListening) {
        try { recognition.start(); } catch (e) { /* ignore */ }
      }
    };
  }

  function startListening() {
    if (!recognition || isListening) return;
    transcript = "";
    isListening = true;
    micBtn.classList.add("listening");
    micLabel.textContent = "Listening...";
    try {
      recognition.start();
    } catch (e) {
      // Already started
    }
  }

  function stopListening() {
    if (!isListening) return;
    isListening = false;
    micBtn.classList.remove("listening");
    try {
      recognition.stop();
    } catch (e) {
      // Already stopped
    }
    // Safari often hasn't finalized results by stop() — use interim as fallback
    var fullText = (transcript + interimText).trim();
    if (fullText) {
      sendMessage(fullText);
    }
    transcript = "";
    interimText = "";
    micLabel.textContent = "Hold to speak";
  }

  // Push-to-talk: pointer events for cross-platform touch/mouse
  micBtn.addEventListener("pointerdown", function (e) {
    e.preventDefault();
    startListening();
  });

  micBtn.addEventListener("pointerup", function (e) {
    e.preventDefault();
    stopListening();
  });

  micBtn.addEventListener("pointerleave", function () {
    if (isListening) stopListening();
  });

  micBtn.addEventListener("pointercancel", function () {
    if (isListening) stopListening();
  });

  // Prevent context menu on long press
  micBtn.addEventListener("contextmenu", function (e) { e.preventDefault(); });

  // Control key push-to-talk
  document.addEventListener("keydown", function (e) {
    if (e.key === "Control" && !e.repeat && !isListening) {
      e.preventDefault();
      startListening();
    }
  });

  document.addEventListener("keyup", function (e) {
    if (e.key === "Control" && isListening) {
      e.preventDefault();
      stopListening();
    }
  });

  // --- Init ---

  initSpeech();

  var storedToken = getStoredToken();
  if (storedToken) {
    connectWS(storedToken);
  } else {
    showAuth();
  }

  // Register service worker
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(function () {});
  }
})();
