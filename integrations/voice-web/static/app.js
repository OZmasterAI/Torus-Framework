// Torus Voice — compact Slide Over UI: toggle mic, editable transcript, send

(function () {
  "use strict";

  // --- DOM refs ---
  var authScreen = document.getElementById("auth-screen");
  var voiceScreen = document.getElementById("voice-screen");
  var tokenInput = document.getElementById("token-input");
  var authBtn = document.getElementById("auth-btn");
  var authError = document.getElementById("auth-error");
  var transcript = document.getElementById("transcript");
  var sendBtn = document.getElementById("send-btn");
  var micBtn = document.getElementById("mic-btn");
  var micLabel = document.getElementById("mic-label");
  var statusDot = document.getElementById("status-dot");
  var flash = document.getElementById("flash");

  // --- State ---
  var ws = null;
  var recognition = null;
  var isListening = false;
  var flashTimer = null;

  var TOKEN_KEY = "torus_voice_token";
  var hasSpeechAPI = "webkitSpeechRecognition" in window || "SpeechRecognition" in window;

  // --- Auth ---

  function getStoredToken() {
    return localStorage.getItem(TOKEN_KEY);
  }

  function showAuth() {
    authScreen.hidden = false;
    voiceScreen.hidden = true;
    tokenInput.focus();
  }

  function showVoice() {
    authScreen.hidden = true;
    voiceScreen.hidden = false;
    if (!hasSpeechAPI) {
      micBtn.disabled = true;
      micLabel.textContent = "No speech API";
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
            showVoice();
          }
          break;

        case "sent":
          showFlash("Sent!");
          break;

        case "error":
          if (data.text === "Invalid token" || data.text === "Auth timeout") {
            localStorage.removeItem(TOKEN_KEY);
            authError.textContent = data.text;
            authError.hidden = false;
            showAuth();
          } else {
            showFlash(data.text, true);
          }
          break;
      }
    };

    ws.onclose = function (evt) {
      setStatus("error");
      if (evt.code === 1008) {
        localStorage.removeItem(TOKEN_KEY);
        authError.textContent = "Invalid token";
        authError.hidden = false;
        showAuth();
        return;
      }
      var storedToken = getStoredToken();
      if (storedToken && !voiceScreen.hidden) {
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

  // --- Flash notification ---

  function showFlash(text, isError) {
    if (flashTimer) clearTimeout(flashTimer);
    flash.textContent = text;
    flash.style.background = isError ? "var(--error)" : "var(--success)";
    flash.hidden = false;
    // Force reflow for transition
    void flash.offsetWidth;
    flash.classList.add("visible");
    flashTimer = setTimeout(function () {
      flash.classList.remove("visible");
      setTimeout(function () { flash.hidden = true; }, 300);
    }, 2000);
  }

  // --- Send message ---

  function sendMessage() {
    var text = transcript.value.trim();
    if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({ type: "message", text: text }));
    transcript.value = "";
  }

  sendBtn.addEventListener("click", sendMessage);

  transcript.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  // --- Web Speech API (toggle mode) ---

  function initSpeech() {
    if (!hasSpeechAPI) return;

    var SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    recognition = new SpeechRecognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = "en-US";

    recognition.onresult = function (event) {
      var final_ = "";
      var interim = "";
      for (var i = 0; i < event.results.length; i++) {
        var t = event.results[i][0].transcript;
        if (event.results[i].isFinal) {
          final_ += t;
        } else {
          interim += t;
        }
      }
      transcript.value = final_ + interim;
    };

    recognition.onerror = function (event) {
      console.error("Speech error:", event.error);
      if (event.error === "not-allowed") {
        micBtn.disabled = true;
        micLabel.textContent = "Mic denied";
        isListening = false;
        micBtn.classList.remove("listening");
      } else if (event.error !== "aborted") {
        stopListening();
      }
    };

    recognition.onend = function () {
      if (isListening) {
        // Continuous mode — restart if still toggled on
        try { recognition.start(); } catch (e) { /* ignore */ }
      }
    };
  }

  function startListening() {
    if (!recognition || isListening) return;
    transcript.value = "";
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
    micLabel.textContent = "Tap to speak";
    try {
      recognition.stop();
    } catch (e) {
      // Already stopped
    }
  }

  // Toggle mic on tap
  micBtn.addEventListener("click", function (e) {
    e.preventDefault();
    if (isListening) {
      stopListening();
    } else {
      startListening();
    }
  });

  // Prevent context menu on long press
  micBtn.addEventListener("contextmenu", function (e) { e.preventDefault(); });

  // Control key toggle (press to start, press again to stop)
  document.addEventListener("keydown", function (e) {
    if (e.key === "Control" && !e.repeat) {
      e.preventDefault();
      if (isListening) {
        stopListening();
      } else {
        startListening();
      }
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
