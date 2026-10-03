"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { createHash } = require("node:crypto");
const sign = require("./sign-windows.cjs");

const VERSION = "0.5.0";
const THUMBPRINT = "a".repeat(40); // Public synthetic certificate identifier, not a credential.
const setupName = `Rasathane-Setup-${VERSION}-x64.exe`;
const uninstallerName = `Rasathane-Setup-${VERSION}-x64.__uninstaller.exe`;

function fixture() {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), "rasathane-sign-test-"));
  const guiDir = path.join(base, "gui");
  const stage = path.join(guiDir, "dist-electron");
  const sdk = path.join(base, "SDK", "signtool.exe");
  fs.mkdirSync(stage, { recursive: true });
  fs.mkdirSync(path.dirname(sdk));
  fs.writeFileSync(sdk, "synthetic SDK; never executed");
  const write = (relative) => {
    const target = path.join(stage, relative);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, "unsigned fixture");
    return target;
  };
  return {
    base,
    guiDir,
    stage,
    sdk,
    write,
    env: {
      RASATHANE_SIGN_THUMBPRINT: THUMBPRINT,
      RASATHANE_SIGNTOOL_PATH: sdk,
    },
    close() {
      const rel = path.relative(os.tmpdir(), path.resolve(base));
      assert.ok(rel && !rel.startsWith("..") && !path.isAbsolute(rel));
      fs.rmSync(base, { recursive: true, force: true });
    },
  };
}

test("CommonJS default and named sign resolve to the same builder hook", () => {
  assert.equal(typeof sign, "function");
  assert.equal(sign.sign, sign);
});

test("only exact current app, elevation helper and NSIS artifact paths are owned", () => {
  const stage = path.resolve("dist-electron");
  for (const relative of [
    "win-unpacked/Rasathane.exe",
    "0.5.0/win-unpacked/resources/elevate.exe",
    setupName,
    `0.5.0/${uninstallerName}`,
  ]) {
    assert.equal(
      sign.ownedTarget(path.join(stage, relative), stage, VERSION),
      true,
    );
  }
  for (const relative of [
    "Rasathane.exe",
    "win-unpacked/resources/sidecar/ytanaliz-sidecar.exe",
    "win-unpacked/resources/worker/rasathane-worker.exe",
    "win-unpacked/resources/motor/bin/llama-server.exe",
    "win-unpacked/resources/tooling/typst/typst.exe",
    "win-unpacked/resources/motor/Rasathane.exe",
    "resources/elevate.exe",
    "Rasathane-Setup-0.4.1-x64.exe",
    `${setupName}.__uninstaller.exe`,
    "anything.exe",
  ]) {
    assert.equal(
      sign.ownedTarget(path.join(stage, relative), stage, VERSION),
      false,
      relative,
    );
  }
  assert.equal(
    sign.ownedTarget(path.join(stage, "..", setupName), stage, VERSION),
    false,
  );
  assert.equal(
    sign.ownedTarget(path.join(stage + "-other", setupName), stage, VERSION),
    false,
  );
  assert.equal(sign.ownedTarget("relative.exe", stage, VERSION), false);
});

test("vendor and escaped files skip before env access or any SDK call", async () => {
  const f = fixture();
  let calls = 0;
  try {
    const env = new Proxy(
      {},
      {
        get() {
          throw new Error("ENV_MUST_NOT_BE_READ");
        },
      },
    );
    const signer = sign.createSigner({
      guiDir: f.guiDir,
      version: VERSION,
      env,
      execute: async () => {
        calls++;
      },
    });
    for (const target of [
      f.write("win-unpacked/resources/worker/rasathane-worker.exe"),
      path.join(f.base, setupName),
    ]) {
      assert.equal(
        (await signer({ path: target, hash: "sha256" })).signed,
        false,
      );
    }
    assert.equal(calls, 0);
  } finally {
    f.close();
  }
});

test("missing/invalid public config fails before SDK, without reading account secrets", async () => {
  const f = fixture();
  let calls = 0;
  try {
    const target = f.write("win-unpacked/Rasathane.exe");
    for (const env of [
      {},
      { ...f.env, RASATHANE_SIGN_THUMBPRINT: "not-a-thumbprint" },
      { ...f.env, RASATHANE_SIGNTOOL_PATH: "signtool.exe" },
      { ...f.env, RASATHANE_SIGNTOOL_PATH: path.join(f.base, "other.exe") },
    ]) {
      const signer = sign.createSigner({
        guiDir: f.guiDir,
        version: VERSION,
        env,
        execute: async () => {
          calls++;
        },
      });
      await assert.rejects(
        signer({ path: target, hash: "sha256" }),
        /SIGN_CONFIG_INVALID/,
      );
    }
    assert.equal(calls, 0);
    assert.equal(fs.readFileSync(target, "utf8"), "unsigned fixture");
  } finally {
    f.close();
  }
});

test("one SHA256 certificate-store signature and verification use no shell or credentials", async () => {
  const f = fixture();
  const calls = [];
  try {
    const target = f.write("win-unpacked/Rasathane.exe");
    const env = new Proxy(f.env, {
      get(obj, key) {
        assert.ok(
          [
            "RASATHANE_UNSIGNED_BUILD",
            "RASATHANE_SIGN_THUMBPRINT",
            "RASATHANE_SIGNTOOL_PATH",
          ].includes(key),
        );
        return obj[key];
      },
    });
    const signer = sign.createSigner({
      guiDir: f.guiDir,
      version: VERSION,
      env,
      log: () => {}, // Synthetic signatures must not enter production build-event receipts.
      execute: async (...args) => calls.push(args),
    });
    assert.equal(
      (
        await signer({
          path: target,
          hash: "sha256",
          isNest: false,
          cscInfo: { password: "MUST_NOT_READ" },
        })
      ).signed,
      true,
    );
    assert.equal(calls.length, 2);
    assert.deepEqual(calls[0][1], [
      "sign",
      "/sha1",
      THUMBPRINT.toUpperCase(),
      "/fd",
      "sha256",
      "/tr",
      "http://ts.ssl.com",
      "/td",
      "sha256",
      target,
    ]);
    assert.deepEqual(calls[1][1], ["verify", "/pa", "/all", target]);
    for (const [tool, args, options] of calls) {
      assert.equal(tool, f.sdk);
      assert.equal(options.shell, false);
      assert.equal(options.windowsHide, true);
      assert.ok(options.timeout > 0 && options.timeout <= 60000);
      assert.equal(args.includes("/p"), false);
      assert.equal(args.includes("/f"), false);
      assert.equal(args.includes("/as"), false);
      assert.equal(JSON.stringify(args).includes("MUST_NOT_READ"), false);
    }
  } finally {
    f.close();
  }
});

test("SHA1 or nested signing fails; unsigned build needs exact explicit opt-in", async () => {
  const f = fixture();
  let calls = 0;
  try {
    const target = f.write(setupName);
    const signer = sign.createSigner({
      guiDir: f.guiDir,
      version: VERSION,
      env: f.env,
      execute: async () => {
        calls++;
      },
    });
    await assert.rejects(
      signer({ path: target, hash: "sha1" }),
      /SIGN_HASH_INVALID/,
    );
    await assert.rejects(
      signer({ path: target, hash: "sha256", isNest: true }),
      /SIGN_HASH_INVALID/,
    );
    const unsigned = sign.createSigner({
      guiDir: f.guiDir,
      version: VERSION,
      env: { RASATHANE_UNSIGNED_BUILD: "1" },
      execute: async () => {
        calls++;
      },
    });
    assert.deepEqual(await unsigned({ path: target, hash: "sha256" }), {
      signed: false,
      reason: "explicit_unsigned_build",
    });
    assert.equal(calls, 0);
  } finally {
    f.close();
  }
});

test("junction escape and shared hardlink are rejected before signing another file", async () => {
  const f = fixture();
  let calls = 0;
  try {
    const outside = path.join(f.base, "outside");
    fs.mkdirSync(outside);
    const outsideExe = path.join(outside, "Rasathane.exe");
    fs.writeFileSync(outsideExe, "protected outside fixture");
    const unpacked = path.join(f.stage, "win-unpacked");
    fs.symlinkSync(
      outside,
      unpacked,
      process.platform === "win32" ? "junction" : "dir",
    );
    const signer = sign.createSigner({
      guiDir: f.guiDir,
      version: VERSION,
      env: f.env,
      execute: async () => {
        calls++;
      },
    });
    await assert.rejects(
      signer({ path: path.join(unpacked, "Rasathane.exe"), hash: "sha256" }),
      /SIGN_TARGET_UNSAFE/,
    );
    fs.unlinkSync(unpacked);
    fs.mkdirSync(unpacked);
    const target = path.join(unpacked, "Rasathane.exe");
    fs.linkSync(outsideExe, target);
    await assert.rejects(
      signer({ path: target, hash: "sha256" }),
      /SIGN_TARGET_UNSAFE/,
    );
    assert.equal(calls, 0);
    assert.equal(
      fs.readFileSync(outsideExe, "utf8"),
      "protected outside fixture",
    );
  } finally {
    f.close();
  }
});

test("only four owned stage files change; frozen worker and pinned upstream remain exact", async () => {
  const f = fixture();
  const signed = [];
  const events = [];
  try {
    const owned = [
      "win-unpacked/Rasathane.exe",
      "win-unpacked/resources/elevate.exe",
      setupName,
      uninstallerName,
    ].map(f.write);
    const protectedFiles = [
      "win-unpacked/resources/worker/rasathane-worker.exe",
      "win-unpacked/resources/sidecar/ytanaliz-sidecar.exe",
      "win-unpacked/resources/motor/bin/llama-server.exe",
      "win-unpacked/resources/tooling/typst.exe",
    ].map(f.write);
    const signer = sign.createSigner({
      guiDir: f.guiDir,
      version: VERSION,
      env: f.env,
      log: (event) => events.push(event),
      execute: async (_sdk, args) => {
        const target = args.at(-1);
        assert.ok(owned.includes(target));
        if (args[0] === "sign") {
          signed.push(target);
          fs.appendFileSync(target, " synthetic signature");
        }
      },
    });
    for (const target of [...owned, ...protectedFiles])
      await signer({ path: target, hash: "sha256" });
    assert.deepEqual(signed, owned);
    assert.equal(events.length, 4);
    for (let i = 0; i < events.length; i++) {
      assert.ok(events[i].startsWith("RASATHANE_SIGNATURE "));
      assert.deepEqual(
        JSON.parse(events[i].slice("RASATHANE_SIGNATURE ".length)),
        {
          path: owned[i],
          sha256: createHash("sha256")
            .update(fs.readFileSync(owned[i]))
            .digest("hex"),
          verified: true,
          rfc3161_requested: true,
        },
      );
    }
    for (const target of protectedFiles)
      assert.equal(fs.readFileSync(target, "utf8"), "unsigned fixture");
  } finally {
    f.close();
  }
});

test("SDK sign/verification failure aborts release and does not expose provider error output", async () => {
  const f = fixture();
  try {
    const target = f.write(setupName);
    for (const failedOperation of ["sign", "verify"]) {
      const calls = [];
      const signer = sign.createSigner({
        guiDir: f.guiDir,
        version: VERSION,
        env: f.env,
        execute: async (_sdk, args) => {
          calls.push(args[0]);
          if (args[0] === failedOperation)
            throw new Error("PRIVATE_PROVIDER_ACCOUNT_OUTPUT");
        },
      });
      await assert.rejects(
        signer({ path: target, hash: "sha256" }),
        (error) => {
          assert.match(error.message, /WINDOWS_SIGNATURE_(SIGN|VERIFY)_FAILED/);
          assert.equal(
            String(error).includes("PRIVATE_PROVIDER_ACCOUNT_OUTPUT"),
            false,
          );
          return true;
        },
      );
      assert.deepEqual(
        calls,
        failedOperation === "sign" ? ["sign"] : ["sign", "verify"],
      );
    }
  } finally {
    f.close();
  }
});
