import {
  parseMindmapHTML,
  validatePDFBytes,
  mapLayout,
  ARTIFACT_LIMIT,
} from "./artifact-data.js";

const views = new Map();
function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function button(text, action) {
  const node = element("button", text, "btn btn-ikincil mini");
  node.type = "button";
  node.addEventListener("click", action);
  return node;
}
function svgElement(tag, attributes = {}, text) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attributes))
    node.setAttribute(key, String(value));
  if (text !== undefined) node.textContent = text;
  return node;
}
function download(bytes, type, name) {
  const url = URL.createObjectURL(new Blob([bytes], { type }));
  const link = element("a", "Dosyayı indir", "btn btn-ikincil mini");
  link.href = url;
  link.download = name.split(/[\\/]/).pop();
  return { link, release: () => URL.revokeObjectURL(url) };
}
export function clearArtifact(host) {
  views.get(host)?.();
  views.delete(host);
  host.replaceChildren();
  host.dataset.ready = "false";
}
export function clearAllArtifacts() {
  for (const host of [...views.keys()]) clearArtifact(host);
}
export async function renderArtifact(
  host,
  bytes,
  name,
  isCurrent = () => true,
) {
  if (bytes.length > ARTIFACT_LIMIT)
    throw new Error("Çıktı boyut sınırını aşıyor.");
  if (/\.html$/i.test(name)) {
    const tree = parseMindmapHTML(new TextDecoder().decode(bytes));
    if (isCurrent()) renderMap(host, tree, bytes, name);
  } else if (/\.pdf$/i.test(name)) {
    validatePDFBytes(bytes);
    await renderPDF(host, bytes, name, isCurrent);
  } else throw new Error("Bu dosya türü önizlenemiyor.");
}

function renderMap(host, tree, bytes, name) {
  clearArtifact(host);
  const toolbar = element("div", undefined, "artifact-toolbar");
  const status = element("span", undefined, "artifact-status");
  const viewport = element("div", undefined, "artifact-map-viewport");
  const outline = element("div", undefined, "artifact-map-outline");
  const collapse = new Set();
  let scale = 0.85;
  let textMode = window.matchMedia("(max-width: 620px)").matches;
  const file = download(bytes, "text/html;charset=utf-8", name);
  const modes = button("Metin görünümü", () => {
    textMode = !textMode;
    draw();
  });
  const zoomOut = button("−", () => {
    scale = Math.max(0.2, scale / 1.25);
    draw();
  });
  zoomOut.setAttribute("aria-label", "Haritayı uzaklaştır");
  const zoomIn = button("+", () => {
    scale = Math.min(2, scale * 1.25);
    draw();
  });
  zoomIn.setAttribute("aria-label", "Haritayı yakınlaştır");
  const fit = button("Sığdır", () => {
    const layout = mapLayout(tree, collapse);
    scale = Math.max(0.15, Math.min(1, (host.clientWidth - 24) / layout.width));
    textMode = false;
    draw();
  });
  toolbar.append(status, zoomOut, zoomIn, fit, modes, file.link);
  host.replaceChildren(toolbar, viewport, outline);
  function draw() {
    const layout = mapLayout(tree, collapse);
    status.textContent = `${layout.rows.length} düğüm`;
    modes.textContent = textMode ? "Harita görünümü" : "Metin görünümü";
    modes.setAttribute("aria-pressed", String(textMode));
    viewport.hidden = textMode;
    outline.hidden = !textMode;
    const svg = svgElement("svg", {
      viewBox: `0 0 ${layout.width} ${layout.height}`,
      width: layout.width * scale,
      height: layout.height * scale,
      role: "img",
      "aria-label": `Zihin haritası, ${layout.rows.length} görünür düğüm`,
    });
    for (const row of layout.rows) {
      if (row.parent)
        svg.append(
          svgElement("path", {
            d: `M${row.parent.x + 220},${row.parent.y} C${row.parent.x + 244},${row.parent.y} ${row.x - 24},${row.y} ${row.x},${row.y}`,
            class: "map-branch",
            "data-depth": row.depth,
          }),
        );
      const group = svgElement("g", {
        class: "map-node",
        transform: `translate(${row.x},${row.y})`,
      });
      group.append(svgElement("title", {}, row.node.content));
      group.append(
        svgElement("rect", { x: 0, y: -36, width: 220, height: 72, rx: 9 }),
      );
      const text = svgElement("text", {
        x: 12,
        y: -(row.lines.length - 1) * 8 + 5,
      });
      for (let index = 0; index < row.lines.length; index++)
        text.append(
          svgElement("tspan", { x: 12, dy: index ? 16 : 0 }, row.lines[index]),
        );
      group.append(text);
      svg.append(group);
    }
    viewport.replaceChildren(svg);
    const list = element("ul", undefined, "map-text-tree");
    for (const row of layout.rows) {
      const item = element("li");
      item.style.paddingInlineStart = `${Math.min(row.depth, 5) * 12}px`;
      if (row.node.children.length) {
        const toggle = button(
          `${collapse.has(row.path) ? "+" : "−"} ${row.node.content}`,
          () => {
            collapse.has(row.path)
              ? collapse.delete(row.path)
              : collapse.add(row.path);
            draw();
          },
        );
        toggle.setAttribute("aria-expanded", String(!collapse.has(row.path)));
        item.append(toggle);
      } else item.append(element("span", row.node.content));
      list.append(item);
    }
    outline.replaceChildren(list);
    host.dataset.ready = "true";
    host.dataset.nodes = String(layout.rows.length);
  }
  views.set(host, file.release);
  draw();
}

let pdfModule;
async function renderPDF(host, bytes, name, isCurrent) {
  const pdfjs = await (pdfModule ||= import("../lib/pdfjs/build/pdf.mjs"));
  if (!isCurrent()) return;
  clearArtifact(host);
  const file = download(bytes, "application/pdf", name);
  const toolbar = element("div", undefined, "artifact-toolbar");
  const status = element("span", "PDF açılıyor…", "artifact-status");
  status.setAttribute("role", "status");
  const surface = element("div", undefined, "artifact-pdf-surface");
  const canvas = element("canvas", undefined, "artifact-pdf-canvas");
  canvas.setAttribute("role", "img");
  const accessible = element("details", undefined, "artifact-pdf-text");
  accessible.append(element("summary", "Sayfa metni"));
  const text = element("p");
  accessible.append(text);
  let pageNumber = 1,
    documentPDF,
    task,
    renderTask,
    worker,
    pdfWorker,
    closed = false,
    timer,
    resizeTimer;
  const previous = button("Önceki sayfa", () => showPage(pageNumber - 1));
  const next = button("Sonraki sayfa", () => showPage(pageNumber + 1));
  previous.disabled = next.disabled = true;
  toolbar.append(previous, status, next, file.link);
  surface.append(canvas, accessible);
  host.replaceChildren(toolbar, surface);
  function release() {
    closed = true;
    clearTimeout(timer);
    clearTimeout(resizeTimer);
    observer.disconnect();
    renderTask?.cancel();
    task?.destroy().catch(() => {});
    pdfWorker?.destroy();
    worker?.terminate();
    canvas.width = canvas.height = 0;
    file.release();
  }
  const observer = new ResizeObserver(() => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      if (documentPDF && !closed) showPage(pageNumber);
    }, 180);
  });
  observer.observe(host);
  views.set(host, release);
  async function showPage(number) {
    if (
      closed ||
      !isCurrent() ||
      !documentPDF ||
      number < 1 ||
      number > documentPDF.numPages
    )
      return;
    pageNumber = number;
    previous.disabled = next.disabled = true;
    renderTask?.cancel();
    try {
      await renderTask?.promise;
    } catch {
      /* Eski çizim iptal edildi. */
    }
    if (closed || !isCurrent()) return;
    status.textContent = `${number} / ${documentPDF.numPages} · çiziliyor…`;
    text.textContent = "";
    host.dataset.ready = "false";
    try {
      const page = await documentPDF.getPage(number);
      if (closed || number !== pageNumber || !isCurrent()) return;
      const original = page.getViewport({ scale: 1 });
      const width = Math.max(200, Math.min(1400, host.clientWidth - 32));
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      const scale = Math.min(
        (width / original.width) * ratio,
        Math.sqrt(6_000_000 / (original.width * original.height)),
        4096 / Math.max(original.width, original.height),
      );
      const viewport = page.getViewport({ scale });
      canvas.width = Math.ceil(viewport.width);
      canvas.height = Math.ceil(viewport.height);
      canvas.style.width = `${Math.round(viewport.width / ratio)}px`;
      canvas.style.height = `${Math.round(viewport.height / ratio)}px`;
      canvas.setAttribute(
        "aria-label",
        `PDF sayfası ${number} / ${documentPDF.numPages}`,
      );
      renderTask = page.render({
        canvas,
        canvasContext: canvas.getContext("2d"),
        viewport,
        annotationMode: pdfjs.AnnotationMode.DISABLE,
      });
      await renderTask.promise;
      const content = await page.getTextContent();
      if (closed || number !== pageNumber || !isCurrent()) return;
      text.textContent = content.items
        .map((item) => item.str || "")
        .join(" ")
        .slice(0, 100000);
      status.textContent = `${number} / ${documentPDF.numPages}`;
      previous.disabled = number === 1;
      next.disabled = number === documentPDF.numPages;
      host.dataset.ready = "true";
      host.dataset.pages = String(documentPDF.numPages);
      host.dataset.page = String(number);
      page.cleanup();
    } catch (error) {
      if (!closed && error.name !== "RenderingCancelledException") {
        status.textContent =
          "PDF sayfası çizilemedi. Dosyayı indirerek açabilirsiniz.";
        status.classList.add("record-error");
      }
    }
  }
  try {
    worker = new Worker(
      new URL("../lib/pdfjs/build/pdf.worker.mjs", import.meta.url),
      { type: "module", name: "rasathane-pdf" },
    );
    pdfWorker = new pdfjs.PDFWorker({ port: worker });
    const workerReady = new Promise((resolve, reject) => {
      timer = setTimeout(
        () => reject(new Error("PDF worker zaman aşımı.")),
        20000,
      );
      pdfWorker.promise.then(resolve, reject);
      worker.addEventListener(
        "error",
        () => reject(new Error("PDF worker açılamadı.")),
        { once: true },
      );
    });
    await workerReady;
    clearTimeout(timer);
    if (closed || !isCurrent()) return;
    host.dataset.worker = "loading";
    const root = new URL("../lib/pdfjs/", import.meta.url);
    task = pdfjs.getDocument({
      data: bytes.slice(),
      worker: pdfWorker,
      cMapUrl: new URL("cmaps/", root).href,
      cMapPacked: true,
      standardFontDataUrl: new URL("standard_fonts/", root).href,
      wasmUrl: new URL("wasm/", root).href,
      iccUrl: new URL("iccs/", root).href,
      useWorkerFetch: false,
      useWasm: false,
      isEvalSupported: false,
      disableFontFace: true,
      useSystemFonts: false,
      maxImageSize: 16_000_000,
      canvasMaxAreaInBytes: 32 * 1024 * 1024,
      stopAtErrors: true,
      enableHWA: false,
    });
    documentPDF = await Promise.race([
      task.promise,
      new Promise((_, reject) => {
        timer = setTimeout(
          () => reject(new Error("PDF açılışı zaman aşımı.")),
          20000,
        );
        worker.addEventListener(
          "error",
          () => reject(new Error("PDF worker yanıt vermedi.")),
          { once: true },
        );
      }),
    ]);
    clearTimeout(timer);
    host.dataset.worker = "ready";
    if (closed || !isCurrent()) return;
    if (documentPDF.numPages > 1000)
      throw new Error("PDF sayfa sınırını aşıyor.");
    await showPage(1);
  } catch (error) {
    if (!closed && isCurrent()) {
      status.textContent =
        "PDF önizlemesi açılamadı. Dosyayı indirerek açabilirsiniz.";
      status.classList.add("record-error");
      host.dataset.ready = "false";
      task?.destroy().catch(() => {});
      worker?.terminate();
      pdfWorker?.destroy();
    }
  }
}
