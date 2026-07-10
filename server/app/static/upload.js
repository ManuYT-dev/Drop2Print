(function () {
  "use strict";

// 1. Get the form FIRST using the exact correct ID
  var form = document.getElementById("uploadForm");

  // 2. Read the dynamic limits from the HTML data attributes
  var ALLOWED_EXTENSIONS = JSON.parse(form.dataset.allowedExtensions);
  var MAX_FILES = parseInt(form.dataset.maxFiles, 10);
  var MAX_FILE_SIZE_BYTES = parseInt(form.dataset.maxFileSize, 10);
  var MAX_TOTAL_SIZE_BYTES = parseInt(form.dataset.maxTotalSize, 10);

  // 3. Get the rest of the elements
  var nameInput = document.getElementById("name");
  var fileInput = document.getElementById("uploads");
  var fileListEl = document.getElementById("fileList");
  var rejectedListEl = document.getElementById("rejectedList");
  var submitBtn = document.getElementById("submitBtn");
  var formErrorsEl = document.getElementById("formErrors");
  var nameErrorEl = document.getElementById("nameError");
  var filesErrorEl = document.getElementById("filesError");
  var modal = document.getElementById("successModal");
  var modalReturnBtn = document.getElementById("modalReturnBtn");

  // Source of truth for what's queued up. The browser resets the native
  // input's FileList to just the newest pick every time the dialog closes
  // (it doesn't append), so we keep our own running list here and rebuild
  // the input's FileList from it after every change or removal.
  var selectedFiles = [];

  function extensionOf(filename) {
    var parts = filename.split(".");
    return parts.length > 1 ? parts.pop().toLowerCase() : "";
  }

  function formatSize(bytes) {
    if (bytes >= 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + " MB";
    return Math.ceil(bytes / 1024) + " KB";
  }

  function totalSelectedSize() {
    return selectedFiles.reduce(function (sum, f) { return sum + f.size; }, 0);
  }

  function isSameFile(a, b) {
    return a.name === b.name && a.size === b.size && a.lastModified === b.lastModified;
  }

  function syncInputFiles() {
    var dataTransfer = new DataTransfer();
    selectedFiles.forEach(function (file) { dataTransfer.items.add(file); });
    fileInput.files = dataTransfer.files;
  }

  function renderFileList(rejected) {
    fileListEl.innerHTML = "";
    selectedFiles.forEach(function (file, index) {
      var li = document.createElement("li");
      li.className = "file-item";

      var nameSpan = document.createElement("span");
      nameSpan.className = "file-item-name";
      nameSpan.textContent = file.name + " (" + formatSize(file.size) + ")";

      var removeBtn = document.createElement("button");
      removeBtn.type = "button";
      removeBtn.className = "file-remove-btn";
      removeBtn.setAttribute("aria-label", "Entfernen: " + file.name);
      removeBtn.textContent = "\u2715";
      removeBtn.addEventListener("click", function () { removeFile(index); });

      li.appendChild(nameSpan);
      li.appendChild(removeBtn);
      fileListEl.appendChild(li);
    });

    rejectedListEl.innerHTML = "";
    (rejected || []).forEach(function (item) {
      var li = document.createElement("li");
      li.className = "file-item file-item-rejected";
      li.textContent = item.name + " \u2013 " + item.reason;
      rejectedListEl.appendChild(li);
    });
  }

  function removeFile(index) {
    selectedFiles.splice(index, 1);
    syncInputFiles();
    renderFileList([]);
  }

  // Runs every time the file dialog closes with a selection. Newly picked
  // files are merged into selectedFiles (after validation); anything that
  // fails a check is rejected right here, with the reason shown inline -
  // no popup, no alert().
  function addFiles(incomingFileList) {
    var incoming = Array.prototype.slice.call(incomingFileList);
    var rejected = [];

    incoming.forEach(function (file) {
      if (selectedFiles.some(function (f) { return isSameFile(f, file); })) {
        rejected.push({ name: file.name, reason: "bereits hinzugefügt" });
        return;
      }

      var ext = extensionOf(file.name);
      if (ALLOWED_EXTENSIONS.indexOf(ext) === -1) {
        rejected.push({ name: file.name, reason: "Dateityp nicht erlaubt" });
        return;
      }
      if (file.size > MAX_FILE_SIZE_BYTES) {
        rejected.push({ name: file.name, reason: "zu groß (max. " + formatSize(MAX_FILE_SIZE_BYTES) + ")" });
        return;
      }
      if (selectedFiles.length >= MAX_FILES) {
        rejected.push({ name: file.name, reason: "Limit von " + MAX_FILES + " Dateien erreicht" });
        return;
      }
      if (totalSelectedSize() + file.size > MAX_TOTAL_SIZE_BYTES) {
        rejected.push({ name: file.name, reason: "Gesamtgröße überschritten (max. " + formatSize(MAX_TOTAL_SIZE_BYTES) + ")" });
        return;
      }

      selectedFiles.push(file);
    });

    syncInputFiles();
    renderFileList(rejected);
    clearFieldError(filesErrorEl);
  }

  function showFieldError(el) {
    el.hidden = false;
  }

  function clearFieldError(el) {
    el.hidden = true;
  }

  function showGlobalErrors(messages) {
    formErrorsEl.innerHTML = "";
    if (!messages || !messages.length) {
      formErrorsEl.hidden = true;
      return;
    }
    messages.forEach(function (msg) {
      var li = document.createElement("li");
      li.className = "flash flash-error";
      li.textContent = msg;
      formErrorsEl.appendChild(li);
    });
    formErrorsEl.hidden = false;
  }

  // Checks required fields inline and returns whether the form may be
  // submitted. Nothing the user typed is ever cleared here - this only
  // toggles small error hints under the relevant fields.
  function validateRequiredFields() {
    var ok = true;

    if (nameInput.value.trim().length === 0) {
      showFieldError(nameErrorEl);
      ok = false;
    } else {
      clearFieldError(nameErrorEl);
    }

    if (fileInput.files.length === 0) {
      showFieldError(filesErrorEl);
      ok = false;
    } else {
      clearFieldError(filesErrorEl);
    }

    return ok;
  }

  function resetForm() {
    form.reset();
    selectedFiles = [];
    syncInputFiles();
    renderFileList([]);
    showGlobalErrors([]);
    clearFieldError(nameErrorEl);
    clearFieldError(filesErrorEl);
  }

  function openModal() {
    modal.hidden = false;
  }

  function closeModalAndReset() {
    modal.hidden = true;
    resetForm();
    nameInput.focus();
  }

  fileInput.addEventListener("change", function () {
    addFiles(fileInput.files);
  });
  nameInput.addEventListener("input", function () {
    if (nameInput.value.trim().length > 0) clearFieldError(nameErrorEl);
  });

  form.addEventListener("submit", function (event) {
    event.preventDefault();

    if (!validateRequiredFields()) {
      // Focus the first thing that still needs attention - a clear,
      // in-page nudge instead of any popup.
      if (nameInput.value.trim().length === 0) {
        nameInput.focus();
      } else {
        fileInput.focus();
      }
      return;
    }

    submitBtn.disabled = true;
    var originalLabel = submitBtn.textContent;
    submitBtn.textContent = "Wird gesendet …";
    showGlobalErrors([]);

    var formData = new FormData(form);

    fetch(form.action || window.location.href, {
      method: "POST",
      body: formData,
      headers: { "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
    })
      .then(function (response) {
        return response.json().then(function (data) {
          return { ok: response.ok, data: data };
        });
      })
      .then(function (result) {
        submitBtn.disabled = false;
        submitBtn.textContent = originalLabel;
        if (result.ok && result.data.success) {
          openModal();
        } else {
          // Server-side rejection (e.g. a check the client-side filter
          // doesn't cover) - shown inline, form contents stay untouched.
          showGlobalErrors(result.data.errors || ["Unbekannter Fehler beim Senden."]);
        }
      })
      .catch(function () {
        submitBtn.disabled = false;
        submitBtn.textContent = originalLabel;
        showGlobalErrors(["Verbindung fehlgeschlagen. Bitte erneut versuchen."]);
      });
  });

  modalReturnBtn.addEventListener("click", closeModalAndReset);
})();