/* Hiriq — admin console: a tiny PDF writer, so every section can be downloaded without any outside library.
   window.HiriqPDF.download(filename, { title, subtitle, blocks: [...] }) builds an A4 PDF in the browser and saves it.
   Blocks:
     { type: "kpis",  items: [[label, value, note?], ...] }          a row of figures
     { type: "heading", text }                                        a sub-heading
     { type: "text",  text }                                          a paragraph
     { type: "table", head: [...], rows: [[...], ...], widths: [...], align: ["l"|"r", ...] }
   Text uses the built-in Helvetica fonts, so characters outside Latin-1 are swapped for plain look-alikes (₹ becomes Rs). */
window.HiriqPDF = (function () {
  var W = 595.28, H = 841.89, M = 42, FOOT = 34;
  var CONTENT_W = W - M * 2;

  // Helvetica widths for characters 32..126 (per 1000 units of font size)
  var HW = [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556,
    1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556,
    333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584];

  var SWAP = { "—": "-", "–": "-", "−": "-", "‘": "'", "’": "'", "“": '"', "”": '"', "…": "...", "₹": "Rs ",
    "→": "->", "▲": "+", "▼": "-", "✓": "", " ": " ", "•": "-", "·": "·" };

  function clean(s) {
    s = String(s == null ? "" : s);
    var out = "";
    for (var i = 0; i < s.length; i++) {
      var ch = s.charAt(i), c = s.charCodeAt(i);
      if (SWAP.hasOwnProperty(ch)) out += SWAP[ch];
      else if (c === 10 || c === 13 || c === 9) out += " ";
      else if (c >= 32 && c < 127) out += ch;
      else if (c >= 160 && c <= 255) out += ch;
      else out += "?";
    }
    return out;
  }
  function esc(s) { return s.replace(/\\/g, "\\\\").replace(/\(/g, "\\(").replace(/\)/g, "\\)"); }
  function width(s, size, bold) {
    var w = 0;
    for (var i = 0; i < s.length; i++) {
      var c = s.charCodeAt(i);
      w += c >= 32 && c <= 126 ? HW[c - 32] : 556;
    }
    return (w / 1000) * size * (bold ? 1.06 : 1);
  }
  /** Break text into lines no wider than max. Long unbroken words are cut. */
  function wrap(text, max, size, bold) {
    text = clean(text);
    if (!text) return [""];
    var lines = [], line = "";
    text.split(" ").forEach(function (word) {
      while (width(word, size, bold) > max && word.length > 1) {   // a word wider than the cell
        var cut = word.length;
        while (cut > 1 && width(word.slice(0, cut), size, bold) > max) cut--;
        if (line) { lines.push(line); line = ""; }
        lines.push(word.slice(0, cut));
        word = word.slice(cut);
      }
      var test = line ? line + " " + word : word;
      if (width(test, size, bold) <= max) line = test;
      else { if (line) lines.push(line); line = word; }
    });
    if (line) lines.push(line);
    return lines;
  }
  function rgb(hex) {
    return [parseInt(hex.slice(0, 2), 16) / 255, parseInt(hex.slice(2, 4), 16) / 255, parseInt(hex.slice(4, 6), 16) / 255].map(function (n) { return n.toFixed(3); }).join(" ");
  }

  function Doc() {
    this.pages = [];
    this.y = 0;
    this.newPage();
  }
  Doc.prototype.newPage = function () {
    this.ops = [];
    this.pages.push(this.ops);
    this.y = H - M;
  };
  Doc.prototype.need = function (h) {
    if (this.y - h < M + FOOT) { this.newPage(); return true; }
    return false;
  };
  Doc.prototype.text = function (x, y, s, size, bold, color, align, boxW) {
    s = clean(s);
    if (align === "r") x = x + boxW - width(s, size, bold);
    this.ops.push("BT /" + (bold ? "F2" : "F1") + " " + size + " Tf " + rgb(color || "1B2233") + " rg " + x.toFixed(2) + " " + y.toFixed(2) + " Td (" + esc(s) + ") Tj ET");
  };
  Doc.prototype.rect = function (x, y, w, h, fill) {
    this.ops.push(rgb(fill) + " rg " + x.toFixed(2) + " " + y.toFixed(2) + " " + w.toFixed(2) + " " + h.toFixed(2) + " re f");
  };
  Doc.prototype.line = function (x1, y1, x2, y2, color) {
    this.ops.push(rgb(color || "D9DEE8") + " RG 0.5 w " + x1.toFixed(2) + " " + y1.toFixed(2) + " m " + x2.toFixed(2) + " " + y2.toFixed(2) + " l S");
  };

  Doc.prototype.cover = function (title, subtitle, stamp) {
    this.rect(0, H - 92, W, 92, "0B1020");
    this.rect(0, H - 94, W, 2, "22D3EE");
    this.text(M, H - 40, "HIRIQ  |  ADMIN CONSOLE", 9, true, "7DD3FC");
    this.text(M, H - 66, title, 22, true, "FFFFFF");
    this.y = H - 92 - 26;
    if (subtitle) { this.text(M, this.y, subtitle, 10.5, false, "4A5368"); this.y -= 14; }
    this.text(M, this.y, stamp, 9, false, "7A8397");
    this.y -= 26;
  };
  Doc.prototype.heading = function (t) {
    this.need(40);
    this.y -= 6;
    this.text(M, this.y, t, 13, true, "0B1020");
    this.y -= 6;
    this.line(M, this.y, W - M, this.y, "22D3EE");
    this.y -= 16;
  };
  Doc.prototype.paragraph = function (t) {
    var lines = wrap(t, CONTENT_W, 10, false);
    for (var i = 0; i < lines.length; i++) {
      this.need(15);
      this.text(M, this.y, lines[i], 10, false, "2B3448");
      this.y -= 14;
    }
    this.y -= 6;
  };
  Doc.prototype.kpis = function (items) {
    var per = Math.min(4, items.length) || 1, gap = 10, cw = (CONTENT_W - gap * (per - 1)) / per;
    for (var start = 0; start < items.length; start += per) {
      var row = items.slice(start, start + per);
      this.need(64);
      var top = this.y;
      row.forEach(function (it, i) {
        var x = M + i * (cw + gap);
        this.rect(x, top - 52, cw, 52, "F1F4F9");
        this.rect(x, top - 52, 3, 52, "22D3EE");
        this.text(x + 12, top - 16, it[0], 8.5, false, "5A6479");
        this.text(x + 12, top - 36, it[1], 17, true, "0B1020");
        if (it[2]) this.text(x + 12, top - 47, it[2], 7.5, false, "7A8397");
      }, this);
      this.y = top - 52 - 12;
    }
    this.y -= 4;
  };
  Doc.prototype.table = function (head, rows, widths, align) {
    var n = head.length, total = widths.reduce(function (a, b) { return a + b; }, 0);
    var cols = widths.map(function (w) { return (w / total) * CONTENT_W; });
    var size = 8.5, lead = 11, pad = 5;
    var self = this;
    function drawHead() {
      self.need(26);
      self.rect(M, self.y - 18, CONTENT_W, 18, "0B1020");
      var x = M;
      head.forEach(function (h, i) {
        self.text(x + pad, self.y - 12, h, 8, true, "FFFFFF", align && align[i], cols[i] - pad * 2);
        x += cols[i];
      });
      self.y -= 18;
    }
    drawHead();
    if (!rows.length) {
      this.need(24);
      this.text(M + pad, this.y - 15, "Nothing to show.", 9, false, "7A8397");
      this.y -= 24;
      return;
    }
    rows.forEach(function (r, ri) {
      var cells = r.map(function (c, i) { return wrap(c, cols[i] - pad * 2, size, false); });
      var lines = Math.max.apply(null, cells.map(function (c) { return c.length; }));
      var h = lines * lead + 8;
      if (self.y - h < M + FOOT) { self.newPage(); drawHead(); }
      if (ri % 2 === 1) self.rect(M, self.y - h, CONTENT_W, h, "F6F8FB");
      var x = M;
      cells.forEach(function (c, i) {
        c.forEach(function (ln, li) {
          self.text(x + pad, self.y - 11 - li * lead, ln, size, false, "1B2233", align && align[i], cols[i] - pad * 2);
        });
        x += cols[i];
      });
      self.line(M, self.y - h, W - M, self.y - h, "E3E7EF");
      self.y -= h;
    });
    this.y -= 14;
  };

  /** Assemble the file: catalog, page tree, two fonts, one content stream per page. */
  Doc.prototype.finish = function (footerLeft) {
    var total = this.pages.length, self = this;
    this.pages.forEach(function (ops, i) {
      self.ops = ops;
      self.line(M, M + FOOT - 8, W - M, M + FOOT - 8, "D9DEE8");
      self.text(M, M + FOOT - 22, footerLeft, 8, false, "7A8397");
      self.text(M, M + FOOT - 22, "Page " + (i + 1) + " of " + total, 8, false, "7A8397", "r", CONTENT_W);
    });
    var objs = [];
    function add(body) { objs.push(body); return objs.length; }
    var catalog = add(""), tree = add(""), f1 = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"),
      f2 = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>");
    var kids = [];
    this.pages.forEach(function (ops) {
      var stream = ops.join("\n");
      var content = add("<< /Length " + stream.length + " >>\nstream\n" + stream + "\nendstream");
      var page = add("<< /Type /Page /Parent " + tree + " 0 R /MediaBox [0 0 " + W.toFixed(2) + " " + H.toFixed(2) + "] /Resources << /Font << /F1 " + f1 + " 0 R /F2 " + f2 + " 0 R >> >> /Contents " + content + " 0 R >>");
      kids.push(page + " 0 R");
    });
    objs[catalog - 1] = "<< /Type /Catalog /Pages " + tree + " 0 R >>";
    objs[tree - 1] = "<< /Type /Pages /Kids [" + kids.join(" ") + "] /Count " + kids.length + " >>";
    var out = "%PDF-1.4\n", offsets = [];
    objs.forEach(function (body, i) {
      offsets.push(out.length);
      out += (i + 1) + " 0 obj\n" + body + "\nendobj\n";
    });
    var xref = out.length;
    out += "xref\n0 " + (objs.length + 1) + "\n0000000000 65535 f \n";
    offsets.forEach(function (o) { out += ("0000000000" + o).slice(-10) + " 00000 n \n"; });
    out += "trailer\n<< /Size " + (objs.length + 1) + " /Root " + catalog + " 0 R >>\nstartxref\n" + xref + "\n%%EOF";
    var bytes = new Uint8Array(out.length);       // every character is Latin-1, so one char is one byte
    for (var i = 0; i < out.length; i++) bytes[i] = out.charCodeAt(i) & 255;
    return new Blob([bytes], { type: "application/pdf" });
  };

  function stampNow() {
    return "Generated " + new Date().toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });
  }

  function build(spec) {
    var doc = new Doc();
    doc.cover(spec.title, spec.subtitle, stampNow());
    (spec.blocks || []).forEach(function (b) {
      if (b.type === "kpis") doc.kpis(b.items);
      else if (b.type === "heading") doc.heading(b.text);
      else if (b.type === "text") doc.paragraph(b.text);
      else if (b.type === "table") doc.table(b.head, b.rows, b.widths || b.head.map(function () { return 1; }), b.align);
    });
    return doc.finish("Hiriq admin  |  " + clean(spec.title) + "  |  Confidential");
  }

  function download(filename, spec) {
    var blob = build(spec);
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 4000);
    return blob;
  }

  return { build: build, download: download };
})();
