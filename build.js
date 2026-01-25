import { execSync } from "node:child_process";
import fs from "node:fs";
import { pathToFileURL } from "node:url";

export const startMarker = "### START-OF-ICON-MAP";
export const endMarker = "### END-OF-ICON-MAP";

export function build() {
  // For mac/Linux: temporarily rename SVG and mapping files from -name- to :name: for font generation
  const isMacOrLinux = process.platform !== 'win32';
  const renamedSvgFiles = [];
  const renamedMappingFiles = [];
  
  if (isMacOrLinux) {
    // Rename SVG files
    const svgFiles = fs.readdirSync("./svgs").filter(f => f.endsWith(".svg"));
    for (const file of svgFiles) {
      const oldPath = `./svgs/${file}`;
      const newPath = `./svgs/${file.replace(/^-|-(?=\.svg$)/g, ':')}`;
      if (oldPath !== newPath) {
        fs.renameSync(oldPath, newPath);
        renamedSvgFiles.push({ oldPath, newPath });
      }
    }
    
    // Rename mapping files
    const mappingFiles = fs.readdirSync("./mappings").filter(f => !f.startsWith('.'));
    for (const file of mappingFiles) {
      const oldPath = `./mappings/${file}`;
      const newPath = `./mappings/${file.replace(/^-|-$/g, ':')}`;
      if (oldPath !== newPath) {
        fs.renameSync(oldPath, newPath);
        renamedMappingFiles.push({ oldPath, newPath });
      }
    }
  }
  
  try {
    execSync("./node_modules/.bin/svgtofont -s svgs/ -o public/dist/", {
      stdio: "inherit",
    });

    const iconMap = fs.readdirSync("./mappings").filter(f => !f.startsWith('.')).map((file) => {
      const iconName = file;
      const appNames = fs.readFileSync(`./mappings/${file}`, "utf8").trim();
      return {
        iconName,
        appNames,
      };
    });

    const result = generateIconMapFiles(iconMap);
    return result;
  } finally {
    // Restore original file names
    if (isMacOrLinux) {
      for (const { oldPath, newPath } of renamedSvgFiles.reverse()) {
        fs.renameSync(newPath, oldPath);
      }
      for (const { oldPath, newPath } of renamedMappingFiles.reverse()) {
        fs.renameSync(newPath, oldPath);
      }
    }
  }
}

function generateIconMapFiles(iconMap) {
  const iconMapBashFn = `
${startMarker}
function __icon_map() {
    case "$1" in
${iconMap
      .map(
        ({ appNames, iconName }) =>
          `   ${appNames})
        icon_result="${iconName}"
        ;;`,
      )
      .join("\n")}
    *)
        icon_result=":default:"
        ;;
    esac
}
${endMarker}`;

  fs.writeFileSync(
    "./public/dist/icon_map.sh",
    `#!/usr/bin/env bash
${iconMapBashFn}
`,
    "utf8",
  );

  const iconMapLua = `return {
${iconMap
      .map(({ appNames, iconName }) =>
        appNames
          .split("|")
          // remove all * in mappings
          .map((app) => app.replace("*", ""))
          .map((app) => `\t[${app.trim()}] = "${iconName}",`)
          .join("\n"),
      )
      .join("\n")}
}`;

  fs.writeFileSync("./public/dist/icon_map.lua", iconMapLua, "utf8");

  // chmod +x ./public/dist/icon_map.sh
  fs.chmodSync("./public/dist/icon_map.sh", 0o755);

  const iconMapJson = JSON.stringify(iconMap.map(a => {
    return {
      iconName: a.iconName,
      appNames: a.appNames.replaceAll("\"", "").split(" | "),
    }
  }), null, 4)

  fs.writeFileSync("./public/dist/icon_map.json", iconMapJson, "utf-8");

  return { iconMapBashFn };
}

// only execute if run directly (ESM)
// use url instead of __filename to support pnpm
if (import.meta.url === pathToFileURL(process.argv[1]).toString()) {
  build();
}
