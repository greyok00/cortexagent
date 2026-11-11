/* Lite markdown → HTML, the one sanctioned markup renderer (GS-01).
   Escapes & and < up front, so no raw tag from engine or model output can
   reach innerHTML. Links and images are scheme-checked (http(s) or the
   run's own /imgcand store) and the URL may not carry quote or angle
   characters, so neither the attribute nor the tag can be broken out of.
   Structural tags only - the page CSS owns the look. Consumers: refine
   output, curation panes, research-set drafts, and the run-ledger reader. */
(function () {
  "use strict";
  var HTTP_URL = /^https?:\/\//i;
  var SAFE_URL = /^(?!["'<>\\])[^"'<>\s]+$/;

  window.liteMd = window.liteMd || function (md) {
    var h = String(md).replace(/&/g, "&amp;").replace(/</g, "&lt;");
    /* every line-level block below consumes its own newline so the final
       \n -> <br> pass never drops a <br> against a block edge; spacing
       between blocks is then exactly one boundary, owned by the CSS */
    /* horizontal rule (whole line only) */
    h = h.replace(/^(?:-{3,}|\*{3,})[^\n]*\n?/gm, "<hr>");
    /* headings: level preserved so reader styles map cleanly */
    h = h.replace(/^#### ([^\n]+)\n?/gm, "<h4>$1</h4>");
    h = h.replace(/^### ([^\n]+)\n?/gm, "<h3>$1</h3>");
    h = h.replace(/^## ([^\n]+)\n?/gm, "<h2>$1</h2>");
    h = h.replace(/^# ([^\n]+)\n?/gm, "<h1>$1</h1>");
    /* blockquote lines (the > character needs no escaping) */
    h = h.replace(/^> ([^\n]+)\n?/gm, "<blockquote>$1</blockquote>");
    /* images first (superset of link syntax); a refused image stays as
       literal text - mangle-free and honest */
    h = h.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g,
      function (m0, alt, src) {
        var ok = HTTP_URL.test(src) &&
          SAFE_URL.test(src) ||
          (src.indexOf("/imgcand/") === 0 && src.indexOf("..") < 0 &&
           SAFE_URL.test(src));
        if (!ok) return m0;
        return '<img src="' + src + '" alt="' +
          String(alt).replace(/"/g, "&quot;") + '" loading="lazy">';
      });
    /* links: http(s) hrefs only; refused schemes stay as literal text */
    h = h.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g,
      function (m0, text, src) {
        return (HTTP_URL.test(src) && SAFE_URL.test(src)) ?
          '<a href="' + src + '" target="_blank" ' +
          'rel="noopener noreferrer">' + text + "</a>" : m0;
      });
    /* whole-line italic emphasis, underscore and asterisk forms */
    h = h.replace(/^_([\s\S]*?)_$/gm, "<i>$1</i>");
    h = h.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
    h = h.replace(/\\\*\\\*(.+?)\\\*\\\*/g, "<b>$1</b>");
    h = h.replace(/(^|\n)\*([^*\n]+)\*(?=\n|$)/g, "$1<i>$2</i>");
    /* markdown tables: a contiguous pipe-line block is a table ONLY when
       it carries a delimiter row (| --- | --- |, right under the header).
       Prose that merely contains a pipe - engine copy does that constantly
       - must stay prose; rendering it as cells mangled the paragraph. */
    h = h.replace(/^([^\n]*\|[^\n]*)$/gm, "<tr-split>$1</tr-split>");
    h = h.replace(/(<tr-split>[^\n]*<\/tr-split>\n?)+\n?/g, function (block) {
      var lines = block.split("\n").filter(function (l) {
        return l.indexOf("tr-split") >= 0;
      }).map(function (l) {
        return l.replace(/<\/?tr-split>/g, "").trim();
      });
      var isDelim = function (l) {
        return l.indexOf("|") >= 0 &&
          /^\|?[-\s|:]+\|?[-\s|:]*$/.test(l);
      };
      if (!lines.some(isDelim)) return block;
      var rows = lines.filter(function (l) {
        return l.replace(/[^|]/g, "").length >= 1 && !isDelim(l);
      });
      if (!rows.length) return block;
      var cells = function (r) {
        return r.replace(/^\|/, "").replace(/\|$/, "").split("|").map(
          function (x) { return "<td>" + x.trim() + "</td>"; }).join("");
      };
      return "<table><tr>" + rows[0].replace(/^\|/, "")
        .replace(/\|$/, "").split("|").map(function (x) {
          return "<th>" + x.trim() + "</th>";
        }).join("") + "</tr>" + rows.slice(1).map(function (r) {
          return "<tr>" + cells(r) + "</tr>";
        }).join("") + "</table>";
    });
    h = h.replace(/<\/?tr-split>/g, "");
    /* list lines first, then consecutive items wrap into one <ul> */
    h = h.replace(/^\s*[-*]\s+([^\n]+)\n?/gm, "<li>$1</li>");
    h = h.replace(/(<li>[\s\S]*?<\/li>)(?!\s*<li>)/g, "<ul>$1</ul>");
    /* newlines hugging block edges carry no content - drop them so the
       <br> pass never doubles a block boundary's own line break */
    h = h.replace(/(<\/(?:h[1-4]|blockquote|table|ul|hr)>)\n+/g, "$1");
    h = h.replace(/\n+(?=<(?:h[1-4]|blockquote|table|ul|hr)[ >])/g, "");
    return h.replace(/\n/g, "<br>");
  };
})();