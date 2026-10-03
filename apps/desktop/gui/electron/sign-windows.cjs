"use strict";

// Build-time SDK hook only. No certificate export, account login or credential files.
const fs = require("node:fs");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { createHash } = require("node:crypto");

const GUI_DIR = path.resolve(__dirname, "..");
const VERSION = require("../package.json").version;
const VERSION_PATTERN =
  /^\d+\.\d+\.\d+(?:-[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*)?$/;

function ownedTarget(file, stage, version) {
  if (
    typeof file !== "string" ||
    !path.isAbsolute(file) ||
    file.includes("\0") ||
    !VERSION_PATTERN.test(version)
  )
    return false;
  const relative = path.relative(path.resolve(stage), path.resolve(file));
  if (!relative || relative.startsWith("..") || path.isAbsolute(relative))
    return false;
  const parts = relative.split(path.sep);
  // One optional build-output directory; resource subtrees are never artifact roots.
  if (
    parts.length > 1 &&
    ["resources", "vendor", "motor", "worker", "sidecar", "tooling"].includes(
      parts[0].toLowerCase(),
    )
  )
    return false;
  const normalized = parts.join("/");
  if (/^(?:[^/]+\/)?win-unpacked\/Rasathane\.exe$/.test(normalized))
    return true;
  if (/^(?:[^/]+\/)?win-unpacked\/resources\/elevate\.exe$/.test(normalized))
    return true;
  const name = parts.at(-1);
  return (
    parts.length <= 2 &&
    [
      `Rasathane-Setup-${version}-x64.exe`,
      `Rasathane-Setup-${version}-x64.__uninstaller.exe`,
    ].includes(name)
  );
}

function signingConfig(env) {
  const thumbprint = env.RASATHANE_SIGN_THUMBPRINT;
  const tool = env.RASATHANE_SIGNTOOL_PATH;
  if (
    typeof thumbprint !== "string" ||
    !/^[a-fA-F0-9]{40}$/.test(thumbprint) ||
    typeof tool !== "string" ||
    !path.isAbsolute(tool) ||
    path.basename(tool).toLowerCase() !== "signtool.exe" ||
    tool.includes("\0")
  ) {
    throw new Error(
      "SIGN_CONFIG_INVALID: public certificate thumbprint and absolute SDK signtool.exe path required",
    );
  }
  try {
    if (!fs.statSync(tool).isFile()) throw new Error("not a file");
  } catch {
    throw new Error("SIGN_CONFIG_INVALID: SDK signtool.exe not available");
  }
  return { thumbprint: thumbprint.toUpperCase(), tool };
}

function safeOwnedFile(file, stage, guiDir, version) {
  try {
    const realGui = fs.realpathSync(guiDir);
    const realStage = fs.realpathSync(stage);
    const stageRelative = path.relative(realGui, realStage);
    if (
      !stageRelative ||
      stageRelative.startsWith("..") ||
      path.isAbsolute(stageRelative)
    )
      throw new Error("outside GUI");
    const resolved = fs.realpathSync(file);
    const stat = fs.lstatSync(file);
    // Shared hardlinks would modify another copy of an upstream/frozen executable.
    if (
      !stat.isFile() ||
      stat.isSymbolicLink() ||
      stat.nlink !== 1 ||
      !ownedTarget(resolved, realStage, version)
    )
      throw new Error("unsafe target");
    return resolved;
  } catch {
    throw new Error(
      "SIGN_TARGET_UNSAFE: target must be an independent owned file in GUI/dist-electron",
    );
  }
}

function runSDK(tool, args, options) {
  return new Promise((resolve, reject) => {
    execFile(tool, args, options, (error) =>
      error ? reject(error) : resolve(),
    );
  });
}

async function fileSHA256(file) {
  const hash = createHash("sha256");
  for await (const chunk of fs.createReadStream(file, {
    highWaterMark: 1024 * 1024,
  }))
    hash.update(chunk);
  return hash.digest("hex");
}

function createSigner({
  guiDir = GUI_DIR,
  version = VERSION,
  env = process.env,
  execute = runSDK,
  log = console.log,
} = {}) {
  const stage = path.join(path.resolve(guiDir), "dist-electron");
  return async function signWindows(options, packager) {
    const currentVersion = packager?.appInfo?.version || version;
    if (!ownedTarget(options?.path, stage, currentVersion))
      return { signed: false, reason: "not_owned_artifact" };
    if (env.RASATHANE_UNSIGNED_BUILD === "1")
      return { signed: false, reason: "explicit_unsigned_build" };
    // Builder must configure signingHashAlgorithms: ["sha256"]. Never append SHA1/dual signatures.
    if (options.hash !== "sha256" || options.isNest === true)
      throw new Error("SIGN_HASH_INVALID: single SHA256 signing required");
    const config = signingConfig(env);
    const resolved = safeOwnedFile(options.path, stage, guiDir, currentVersion);
    const sdkOptions = {
      shell: false,
      windowsHide: true,
      timeout: 60000,
      maxBuffer: 1024 * 1024,
      encoding: "utf8",
    };
    try {
      await execute(
        config.tool,
        [
          "sign",
          "/sha1",
          config.thumbprint,
          "/fd",
          "sha256",
          "/tr",
          "http://ts.ssl.com",
          "/td",
          "sha256",
          resolved,
        ],
        sdkOptions,
      );
    } catch {
      // Provider stdout/stderr may include account information: never forward it.
      throw new Error("WINDOWS_SIGNATURE_SIGN_FAILED");
    }
    try {
      await execute(
        config.tool,
        ["verify", "/pa", "/all", resolved],
        sdkOptions,
      );
    } catch {
      throw new Error("WINDOWS_SIGNATURE_VERIFY_FAILED");
    }
    safeOwnedFile(resolved, stage, guiDir, currentVersion);
    const sha256 = await fileSHA256(resolved);
    // NSIS deletes its temporary uninstaller after build; this event preserves its proof.
    log(
      "RASATHANE_SIGNATURE " +
        JSON.stringify({
          path: resolved,
          sha256,
          verified: true,
          rfc3161_requested: true,
        }),
    );
    return { signed: true, path: resolved, sha256 };
  };
}

const sign = createSigner();
module.exports = sign;
module.exports.sign = sign;
module.exports.createSigner = createSigner;
module.exports.ownedTarget = ownedTarget;
