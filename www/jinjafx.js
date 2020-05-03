var loaded = false;
var dirty = false;
var sobj = undefined;
var fe = undefined;
var tid = 0;
var dt = {};
var qs = {};

function jinjafx(method) {
  sobj.innerHTML = "";

  if (window.cmData.getValue().length !== 0) {
    if (!window.cmData.getValue().match(/\w.*[\r\n]+.*\w/i)) {
      window.cmData.focus();
      set_status("darkred", "ERROR", "Not Enough Rows in Data");
      return false;
    }
  }

  if (window.cmTemplate.getValue().length === 0) {
    window.cmTemplate.focus();
    set_status("darkred", "ERROR", "No Template");
    return false;
  }

  fe.focus();

  dt.data = window.cmData.getValue().replace(/^[ \t]+/gm, function(m) {
    var ns = ((m.match(/\t/g) || []).length * 2) + (m.match(/ /g) || []).length;
    return Array(ns + 1).join(" ");
  });
  dt.template = window.cmTemplate.getValue().replace(/\t/g, "  ");
  dt.vars = window.cmVars.getValue().replace(/\t/g, "  ");

  if (method === "generate") {
    try {
      dt.data = window.btoa(dt.data);
      dt.template = window.btoa(dt.template);
      dt.vars = window.btoa(dt.vars);
      window.open("output.html", "_blank");
    }
    catch (ex) {
      set_status("darkred", "ERROR", "Invalid Character Encoding in DataTemplate");
    }
  }
  else if (method === "export") {
    window.open("dt.html", "_blank");
  }
}

window.onload = function() {
  if (typeof window.btoa == 'function') {
    sobj = document.getElementById("status");

    window.onresize = function() {
      document.getElementById("content").style.height = (window.innerHeight - 155) + "px";
    };

    window.onresize();

    document.body.style.display = "block";
    
    var gExtraKeys = {
      "Alt-F": "findPersistent",
      "Ctrl-F": "findPersistent",
      "Cmd-F": "findPersistent",
      "Ctrl-D": false
    };

    CodeMirror.defineMode("data", cmDataMode);    
    window.cmData = CodeMirror.fromTextArea(data, {
      tabSize: 2,
      autofocus: true,
      scrollbarStyle: "null",
      styleSelectedText: true,
      extraKeys: gExtraKeys,
      mode: "data",
      smartIndent: false
    });

    window.cmVars = CodeMirror.fromTextArea(vars, {
      tabSize: 2,
      scrollbarStyle: "null",
      styleSelectedText: true,
      extraKeys: gExtraKeys,
      mode: "yaml",
      smartIndent: false
    });

    window.cmTemplate = CodeMirror.fromTextArea(template, {
      lineNumbers: true,
      tabSize: 2,
      scrollbarStyle: "null",
      styleSelectedText: true,
      extraKeys: gExtraKeys,
      mode: "jinja2",
      smartIndent: false
    });

    fe = window.cmData;
    window.cmData.on("focus", function() { fe = window.cmData });
    window.cmVars.on("focus", function() { fe = window.cmVars });
    window.cmTemplate.on("focus", function() { fe = window.cmTemplate });

    window.cmData.on("beforeChange", onPaste);
    window.cmTemplate.on("beforeChange", onPaste);
    window.cmVars.on("beforeChange", onPaste);

    window.cmData.on("change", onChange);
    window.cmVars.on("change", onChange);
    window.cmTemplate.on("change", onChange);

    Split(["#cdata", "#cvars"], {
      direction: "horizontal",
      cursor: "col-resize",
      sizes: [75, 25],
      snapOffset: 0,
      minSize: 100
    });

    Split(["#top", "#ctemplate"], {
      direction: "vertical",
      cursor: "row-resize",
      sizes: [30, 70],
      snapOffset: 0,
      minSize: 100
    });

    document.getElementById("import").onchange = function() {
      var r = new FileReader();
      r.onload = function (e) {
        var _dt = parse_datatemplate(e.target.result, true);
        if (_dt != null) {
          load_datatemplate(_dt, null);
          lfn = e.target.filename;
        }
        document.getElementById("import").value = '';
        fe.focus();
      };
      r.filename = this.files[0].name;
      r.readAsText(this.files[0]);
    };

    if (window.location.href.indexOf('?') > -1) {
      var v = window.location.href.substr(window.location.href.indexOf('?') + 1).split('&');

      for (var i = 0; i < v.length; i++) {
        var p = v[i].split('=');
        qs[p[0].toLowerCase()] = decodeURIComponent(p.length > 1 ? p[1] : '');
      }

      try {
        update_from_qs();
        loaded = true;
      }
      catch (ex) {
        set_status("darkred", "ERROR", ex);
        loaded = true; onChange(true);
      }
    }
    else {
      loaded = true;
    }
  }
  else {
    document.body.innerHTML = "<p style=\"padding: 15px;\">Sorry, a Modern Browser is Required (Chrome, Firefox, Safari or IE >= 10)</p>";
    document.body.style.display = "block";
  }
};

function quote(str) {
  str = str.replace(/&/g, "&amp;");
  str = str.replace(/>/g, "&gt;");
  str = str.replace(/</g, "&lt;");
  str = str.replace(/"/g, "&quot;");
  str = str.replace(/'/g, "&apos;");
  return str;
}

function escapeRegExp(s) {
  return s.replace(/[\\^$.*+?()[\]{}|]/g, '\\$&');
}

function reset_dt() {
  dt = {};
}

function onPaste(cm, change) {
  if (change.origin === "paste") {
    var _dt = parse_datatemplate(change.text.join('\n'), false);
    if (_dt != null) {
      load_datatemplate(_dt, null);
      change.cancel();
    }
  }
}

function onChange(errflag) {
  if (loaded) {
    if (!dirty && (errflag !== true)) {
      window.addEventListener('beforeunload', function (e) {
        e.returnValue = 'Are you sure?';
      });
      dirty = true;
    }
    if (window.location.href.indexOf('?') > -1) {
      window.history.replaceState({}, document.title, window.location.pathname);
    }
  }
}

function load_datatemplate(_dt, _qs) {
  try {
    if (_qs != null) {
      if (_qs.hasOwnProperty("data")) {
        _dt.data = window.atob(_qs.data);
      }
      if (_qs.hasOwnProperty("template")) {
        _dt.template = window.atob(_qs.template);
      }
      if (_qs.hasOwnProperty("vars")) {
        _dt.vars = window.atob(_qs.vars);
      }
    }

    window.cmData.setValue(_dt.hasOwnProperty("data") ? _dt.data : "");
    window.cmTemplate.setValue(_dt.hasOwnProperty("template") ? _dt.template : "");
    window.cmVars.setValue(_dt.hasOwnProperty("vars") ? _dt.vars : "");
    loaded = true;
  }
  catch (ex) {
    set_status("darkred", "ERROR", ex);
    loaded = true; onChange(true);
  }
}

function parse_datatemplate(request, us) {
  var _dt = {};

  if (request.match(/<(?:data\.csv|template\.j2|vars\.yml)>/i)) {
    var m = request.match(/<data\.csv>([\s\S]*?)<\/data\.csv>/i);
    if (m != null) {
      _dt.data = m[1].trim();
    }
    m = request.match(/<template\.j2>([\s\S]*?)<\/template\.j2>/i);
    if (m != null) {
      _dt.template = m[1].trim();
    }
    m = request.match(/<vars\.yml>([\s\S]*?)<\/vars\.yml>/i);
    if (m != null) {
      _dt.vars = m[1].trim();
    }
    return _dt;
  }
  else if (us) {
    set_status("darkred", "ERROR", "Invalid DataTemplate Format");
  }
  return null;
}

function update_from_qs() {
  try {
    var _data = qs.hasOwnProperty('data') ? window.atob(qs.data) : null;
    var _template = qs.hasOwnProperty('template') ? window.atob(qs.template) : null;
    var _vars = qs.hasOwnProperty('vars') ? window.atob(qs.vars) : null;

    if (_data != null) {
      window.cmData.setValue(_data);
    }
    if (_template != null) {
      window.cmTemplate.setValue(_template);
    }
    if (_vars != null) {
      window.cmVars.setValue(_vars);
    }
  }
  catch (ex) {
    set_status("darkred", "ERROR", ex);
  }
}

function set_status(color, title, message) {
  clearTimeout(tid);
  tid = setTimeout(function() { sobj.innerHTML = "" }, 5000);
  sobj.style.color = color;
  sobj.innerHTML = "<strong>" + title + "</strong> " + message;
}

function cmDataMode() {
  return {
    startState: function() {
      return { n: 0 };
    },
    token: function(stream, state) {
      if (!state.n && stream.match(/.+/)) {
        state.n = 1;
        return "jfx-header";
      }
      stream.next();
    }
  };
}