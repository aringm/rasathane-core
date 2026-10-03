"use strict";
// Tek SVG'den PNG ve Windows ICO üretir; raster asset elle değiştirilmez.
const fs = require("node:fs/promises");
const path = require("node:path");
const sharp = require("sharp");

async function main() {
  const root = path.resolve(__dirname, "..");
  const svg = await fs.readFile(path.join(root, "ui/brand/rasathane-mark.svg"));
  const icons = path.join(root, "src-tauri/icons");
  await fs.mkdir(icons, { recursive: true });
  await fs.writeFile(path.join(icons, "rasathane-logo.svg"), svg);
  async function refreshPNG(directory) {
    for (const item of await fs.readdir(directory, { withFileTypes: true })) {
      const file = path.join(directory, item.name);
      if (item.isDirectory()) await refreshPNG(file);
      else if (item.name.endsWith(".png")) { const { width, height } = await sharp(file).metadata(); await sharp(svg).resize(width, height).png().toFile(`${file}.new`); await fs.rename(`${file}.new`, file); }
    }
  }
  await refreshPNG(icons);
  for (const [name, size] of [["32x32.png", 32], ["128x128.png", 128], ["128x128@2x.png", 256], ["icon.png", 512]]) {
    await sharp(svg).resize(size, size).png().toFile(path.join(icons, name));
  }
  const sizes = [16, 24, 32, 48, 64, 128, 256];
  const images = await Promise.all(sizes.map(size => sharp(svg).resize(size, size).png().toBuffer()));
  const header = Buffer.alloc(6 + 16 * sizes.length);
  header.writeUInt16LE(1, 2); header.writeUInt16LE(sizes.length, 4);
  let offset = header.length;
  for (let index = 0; index < sizes.length; index++) {
    const position = 6 + index * 16;
    header[position] = sizes[index] === 256 ? 0 : sizes[index];
    header[position + 1] = header[position];
    header.writeUInt16LE(1, position + 4); header.writeUInt16LE(32, position + 6);
    header.writeUInt32LE(images[index].length, position + 8); header.writeUInt32LE(offset, position + 12);
    offset += images[index].length;
  }
  await fs.writeFile(path.join(icons, "icon.ico"), Buffer.concat([header, ...images]));
  await sharp(svg).resize(512, 512).png().toFile(path.join(icons, "rasathane-logo.png"));
  const icnsChunks = await Promise.all([["ic07", 128], ["ic08", 256], ["ic09", 512], ["ic10", 1024]].map(async ([type, size]) => {
    const payload = await sharp(svg).resize(size, size).png().toBuffer(); const block = Buffer.alloc(8); block.write(type); block.writeUInt32BE(payload.length + 8, 4); return Buffer.concat([block, payload]);
  }));
  const icnsHeader = Buffer.alloc(8); icnsHeader.write("icns"); icnsHeader.writeUInt32BE(8 + icnsChunks.reduce((total, value) => total + value.length, 0), 4);
  await fs.writeFile(path.join(icons, "icon.icns"), Buffer.concat([icnsHeader, ...icnsChunks]));
  await fs.writeFile(path.resolve(root, "../../web/src/app/icon.svg"), svg);
  await fs.writeFile(path.resolve(root, "../../web/public/brand/rasathane-mark.svg"), svg);
  console.log("Rasathane PNG, ICO ve web ikonları üretildi.");
}
main().catch(error => { console.error(error.message); process.exitCode = 1; });
