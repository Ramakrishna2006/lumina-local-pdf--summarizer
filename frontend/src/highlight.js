// Tiny, dependency-free syntax highlighter.
// Returns an array of [className | null, text] tokens; the React code renders
// them as <span>s (never innerHTML), so model output cannot inject markup.

const KW = {
  py: "and as assert async await break class continue def del elif else except False finally for from global if import in is lambda None nonlocal not or pass raise return True try while with yield match case self",
  js: "async await break case catch class const continue debugger default delete do else export extends false finally for from function if import in instanceof let new null of return static super switch this throw true try typeof undefined var void while with yield interface type enum implements public private protected readonly as",
  java: "abstract assert boolean break byte case catch char class const continue default do double else enum extends final finally float for if implements import instanceof int interface long native new null package private protected public return short static super switch synchronized this throw throws try void volatile while true false var record",
  c: "auto break case char const continue default do double else enum extern float for goto if inline int long register return short signed sizeof static struct switch typedef union unsigned void volatile while bool true false nullptr class public private protected namespace using template typename new delete virtual override std include define",
  sql: "select from where and or not insert into values update set delete create table drop alter add primary key foreign references join left right inner outer on group by order having limit offset as distinct count sum avg min max null is in like between union all case when then else end index view",
  sh: "if then else elif fi for in do done while case esac function return export local echo cd ls set unset sudo",
  go: "break case chan const continue default defer else fallthrough for func go goto if import interface map package range return select struct switch type var true false nil",
  rs: "as async await break const continue crate else enum extern false fn for if impl in let loop match mod move mut pub ref return self Self static struct super trait true type unsafe use where while",
};

const ALIASES = {
  python: "py", py: "py", python3: "py",
  javascript: "js", js: "js", jsx: "js", ts: "js", tsx: "js", typescript: "js", node: "js", json: "js", react: "js",
  java: "java", kotlin: "java", kt: "java", csharp: "java", cs: "java", "c#": "java", swift: "java", scala: "java",
  c: "c", cpp: "c", "c++": "c", h: "c", hpp: "c", cc: "c",
  sql: "sql", mysql: "sql", postgres: "sql", postgresql: "sql", sqlite: "sql",
  sh: "sh", bash: "sh", shell: "sh", zsh: "sh", powershell: "sh", ps1: "sh", ps: "sh", cmd: "sh", bat: "sh",
  go: "go", golang: "go", rust: "rs", rs: "rs", php: "js", ruby: "py", rb: "py",
};

const KW_SETS = Object.fromEntries(Object.entries(KW).map(([k, v]) => [k, new Set(v.split(" "))]));

export function langFamily(lang) {
  const l = String(lang || "").toLowerCase().split(/[\s:]/)[0];
  if (["html", "xml", "svg", "vue", "jsx-html"].includes(l)) return "html";
  if (["css", "scss", "less"].includes(l)) return "css";
  return ALIASES[l] || null;
}

function lineCommentFor(fam) {
  if (fam === "py" || fam === "sh") return "#";
  if (fam === "sql") return "--";
  return "//";
}

export function tokenize(code, lang) {
  const fam = langFamily(lang);
  if (!fam || code.length > 60000) return [[null, code]];
  if (fam === "html") return tokenizeHtml(code);
  const out = [];
  const kw = KW_SETS[fam] || new Set();
  const lc = lineCommentFor(fam);
  const caseless = fam === "sql";
  let i = 0;
  let buf = "";
  const flush = () => {
    if (buf) out.push([null, buf]);
    buf = "";
  };
  while (i < code.length) {
    const ch = code[i];
    const rest = code.slice(i, i + 3);
    // comments
    if (code.startsWith(lc, i) || (fam === "css" && code.startsWith("/*", i))) {
      if (fam !== "css" || code.startsWith("/*", i)) {
        flush();
        const end = fam === "css" ? code.indexOf("*/", i + 2) : code.indexOf("\n", i);
        const stop = end === -1 ? code.length : fam === "css" ? end + 2 : end;
        out.push(["c", code.slice(i, stop)]);
        i = stop;
        continue;
      }
    }
    if (code.startsWith("/*", i) && fam !== "py" && fam !== "sh") {
      flush();
      const end = code.indexOf("*/", i + 2);
      const stop = end === -1 ? code.length : end + 2;
      out.push(["c", code.slice(i, stop)]);
      i = stop;
      continue;
    }
    // strings (incl. Python triple quotes and JS templates)
    if (ch === '"' || ch === "'" || ch === "`") {
      flush();
      const triple = fam === "py" && (rest === '"""' || rest === "'''");
      const q = triple ? rest : ch;
      let j = i + q.length;
      while (j < code.length && !code.startsWith(q, j)) {
        if (code[j] === "\\") j++;
        if (!triple && q !== "`" && code[j] === "\n") break;
        j++;
      }
      j = Math.min(code.length, j + q.length);
      out.push(["s", code.slice(i, j)]);
      i = j;
      continue;
    }
    // numbers
    if (/[0-9]/.test(ch) && !/[A-Za-z_]/.test(code[i - 1] || "")) {
      flush();
      const m = /^(0x[0-9a-f]+|\d[\d_]*(\.\d+)?(e[+-]?\d+)?)/i.exec(code.slice(i));
      out.push(["n", m[0]]);
      i += m[0].length;
      continue;
    }
    // words
    if (/[A-Za-z_$@#]/.test(ch)) {
      const m = /^[A-Za-z_$@#][\w$]*/.exec(code.slice(i));
      const word = m[0];
      const key = caseless ? word.toLowerCase() : word.replace(/^#/, "");
      flush();
      if (kw.has(key)) out.push(["k", word]);
      else if (word.startsWith("@")) out.push(["a", word]);
      else if (code[i + word.length] === "(") out.push(["f", word]);
      else if (/^[A-Z][a-z]/.test(word) && fam !== "sql") out.push(["t", word]);
      else out.push([null, word]);
      i += word.length;
      continue;
    }
    buf += ch;
    i++;
  }
  flush();
  return out;
}

function tokenizeHtml(code) {
  const out = [];
  const re = /(<!--[\s\S]*?-->)|(<\/?[\w-]+)|("[^"]*"|'[^']*')|(\/?>)|([\w-]+)(?==)/g;
  let last = 0;
  let m;
  while ((m = re.exec(code))) {
    if (m.index > last) out.push([null, code.slice(last, m.index)]);
    if (m[1]) out.push(["c", m[1]]);
    else if (m[2] || m[4]) out.push(["k", m[0]]);
    else if (m[3]) out.push(["s", m[3]]);
    else if (m[5]) out.push(["a", m[5]]);
    last = m.index + m[0].length;
  }
  if (last < code.length) out.push([null, code.slice(last)]);
  return out;
}

const EXT = {
  python: "py", py: "py", javascript: "js", js: "js", jsx: "jsx", typescript: "ts", ts: "ts", tsx: "tsx",
  java: "java", c: "c", cpp: "cpp", "c++": "cpp", csharp: "cs", cs: "cs", go: "go", rust: "rs", rs: "rs",
  html: "html", css: "css", scss: "scss", sql: "sql", bash: "sh", sh: "sh", shell: "sh", powershell: "ps1",
  ps1: "ps1", json: "json", yaml: "yml", yml: "yml", xml: "xml", markdown: "md", md: "md", php: "php",
  ruby: "rb", kotlin: "kt", swift: "swift", dockerfile: "Dockerfile", toml: "toml", ini: "ini", text: "txt",
};

export function extensionFor(lang) {
  return EXT[String(lang || "").toLowerCase().split(/[\s:]/)[0]] || "txt";
}

const FILE_LINE = /^\s*(?:#{1,4}\s*)?(?:\*\*|__)?`?((?:[\w.-]+\/)*[\w.-]+\.[A-Za-z0-9]{1,10}|Dockerfile|Makefile|\.env\.example|\.gitignore)`?(?:\*\*|__)?:?\s*$/;

export function fileNameFromLine(line) {
  const m = FILE_LINE.exec(line || "");
  return m ? m[1] : null;
}

/** Find "**`path/file.py`**" + code block pairs in an answer (multi-file projects). */
export function extractFiles(markdown) {
  const lines = String(markdown || "").replace(/\r\n/g, "\n").split("\n");
  const files = [];
  let pending = null;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const fence = /^```\s*([\w+#.-]*)(?:[\s:]+(?:title=)?["']?([\w./-]+\.[\w]+)["']?)?/.exec(line);
    if (fence && line.startsWith("```")) {
      const code = [];
      i++;
      while (i < lines.length && !/^```/.test(lines[i])) code.push(lines[i++]);
      const path = fence[2] || pending;
      if (path) files.push({ path, lang: fence[1], content: code.join("\n") + "\n" });
      pending = null;
      continue;
    }
    const m = FILE_LINE.exec(line);
    if (m) pending = m[1];
    else if (line.trim()) pending = null;
  }
  const seen = new Set();
  return files.filter((f) => (seen.has(f.path) ? false : seen.add(f.path)));
}

/** Folder tree text ("app/ … main.py") for a list of paths. */
export function fileTree(paths) {
  const root = {};
  for (const p of paths) {
    let node = root;
    for (const part of p.split("/")) node = node[part] = node[part] || {};
  }
  const lines = [];
  const walk = (node, prefix) => {
    const keys = Object.keys(node).sort((a, b) => (Object.keys(node[b]).length > 0) - (Object.keys(node[a]).length > 0) || a.localeCompare(b));
    keys.forEach((k, idx) => {
      const last = idx === keys.length - 1;
      const isDir = Object.keys(node[k]).length > 0;
      lines.push(`${prefix}${last ? "└── " : "├── "}${k}${isDir ? "/" : ""}`);
      if (isDir) walk(node[k], prefix + (last ? "    " : "│   "));
    });
  };
  walk(root, "");
  return lines.join("\n");
}
