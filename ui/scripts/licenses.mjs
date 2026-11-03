// Lists the libraries the GUI ships (package.json "dependencies") with version and licence for the About
// screen. Runs before every build, so the list follows the installed packages.
import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const pkg = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));

const components = Object.keys(pkg.dependencies).sort().map((name) => {
  const dep = JSON.parse(readFileSync(join(root, "node_modules", name, "package.json"), "utf8"));
  const repo = typeof dep.repository === "string" ? dep.repository : dep.repository?.url ?? "";
  const url = dep.homepage || repo.replace(/^git\+/, "").replace(/\.git$/, "").replace(/^git:/, "https:");
  return { name, version: dep.version, licence: dep.license ?? "see package", url, kind: "ui" };
});

writeFileSync(join(root, "src", "about", "ui-components.json"), JSON.stringify(components, null, 1) + "\n");

// Licence texts travel with the program (MIT, ISC and OFL require it); served next to the GUI.
const notices = components.map((c) => {
  const dir = join(root, "node_modules", c.name);
  const files = existsSync(dir) ? readdirSync(dir).filter((f) => /^(licen[cs]e|copying|notice)/i.test(f)) : [];
  const texts = files.map((f) => `--- ${f} ---\n${readFileSync(join(dir, f), "utf8")}`).join("\n");
  return `==== ${c.name} ${c.version} ====\nLicence: ${c.licence}\n${texts}\n`;
});
writeFileSync(join(root, "public", "ui-licenses.txt"),
  "The Clipcura interface bundles the following libraries.\n\n" + notices.join("\n"));
console.log(`about: ${components.length} UI libraries listed`);
